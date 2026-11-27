from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import yaml

from musical_agent.data.policies import PolicyChunk, PolicyIndex, load_policy_index

logger = logging.getLogger(__name__)

EVALS_DIR = Path(__file__).resolve().parent
CASES_PATH = EVALS_DIR / "retrieval_cases.yaml"
REPORT_PATH = EVALS_DIR / "retrieval_report.md"
CACHE_DIR = EVALS_DIR / ".cache"
EMBEDDING_MODEL = "gemini-embedding-001"
DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
QUERY_TASK = "RETRIEVAL_QUERY"
API_KEY_ENV = "GOOGLE_API_KEY"
DEFAULT_K = 2
RRF_K_CONST = 60
BM25_MIN_RECALL_POINTS = 90.0
MIN_GAIN_POINTS = 10.0
PERCENT = 100
POINTS_PRECISION = 6
MISS_PREVIEW = 3
STRATEGIES = ("bm25", "embeddings", "hybrid")

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    question: str
    expected_sections: list[str]


@dataclass(frozen=True)
class Miss:
    case_id: str
    question: str
    expected_sections: list[str]
    top_sections: list[str]


@dataclass(frozen=True)
class StrategyResult:
    recall_at_2: float
    mrr: float
    misses: list[Miss]


class Retriever(Protocol):
    def rank(self, question: str) -> list[str]: ...


def load_cases(path: Path = CASES_PATH) -> list[RetrievalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [
        RetrievalCase(
            id=str(item["id"]),
            question=str(item["question"]),
            expected_sections=[str(section) for section in item["expected_sections"]],
        )
        for item in raw["cases"]
    ]
    invalid = [case.id for case in cases if not case.question or not case.expected_sections]
    if invalid:
        raise ValueError(f"Cases without question or expected sections: {invalid}")
    return cases


def _check_lengths(rankings: Sequence[list[str]], expected: Sequence[list[str]]) -> None:
    if len(rankings) != len(expected):
        raise ValueError(f"{len(rankings)} rankings for {len(expected)} expectations")
    if not rankings:
        raise ValueError("Metrics need at least one ranking")


def _first_hit_rank(ranking: list[str], expected: list[str]) -> int | None:
    for position, section in enumerate(ranking, start=1):
        if section in expected:
            return position
    return None


def recall_at_k(rankings: Sequence[list[str]], expected: Sequence[list[str]], k: int) -> float:
    """Share of queries with at least one expected section in the top `k` results."""
    _check_lengths(rankings, expected)
    hits = [
        _first_hit_rank(ranking[:k], wanted) is not None
        for ranking, wanted in zip(rankings, expected, strict=True)
    ]
    return sum(hits) / len(hits)


def mrr(rankings: Sequence[list[str]], expected: Sequence[list[str]]) -> float:
    """Mean reciprocal rank of the first expected section; a query with no hit scores 0."""
    _check_lengths(rankings, expected)
    ranks = [
        _first_hit_rank(ranking, wanted) for ranking, wanted in zip(rankings, expected, strict=True)
    ]
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)


def rrf_fuse(rankings_a: list[str], rankings_b: list[str], k_const: int = RRF_K_CONST) -> list[str]:
    """Fuse two rankings of section ids with Reciprocal Rank Fusion.

    Each id scores the sum of `1 / (k_const + rank)` over the rankings it appears in.
    Ties keep the order of first appearance in `rankings_a`, then `rankings_b`.

    Args:
        rankings_a: Section ids, best first.
        rankings_b: Section ids, best first.
        k_const: RRF smoothing constant.

    Returns:
        Every id from both rankings, best fused score first.
    """
    scores: dict[str, float] = {}
    for ranking in (rankings_a, rankings_b):
        for rank, section in enumerate(ranking, start=1):
            scores[section] = scores.get(section, 0.0) + 1 / (k_const + rank)
    first_seen = {section: order for order, section in enumerate(scores)}
    return sorted(scores, key=lambda section: (-scores[section], first_seen[section]))


class Bm25Retriever:
    def __init__(self, index: PolicyIndex) -> None:
        self._index = index
        self._size = len(index.chunks())

    def rank(self, question: str) -> list[str]:
        return [passage["section"] for passage in self._index.search(question, k=self._size)]


def _chunk_text(chunk: PolicyChunk) -> str:
    return f"{chunk.title}\n{chunk.text}"


def _cache_key(chunks: Sequence[PolicyChunk], model: str) -> str:
    digest = hashlib.sha256(model.encode("utf-8"))
    for chunk in chunks:
        digest.update(f"\x00{chunk.section}\x00{_chunk_text(chunk)}".encode())
    return digest.hexdigest()


def gemini_embedder(task_type: str, model: str = EMBEDDING_MODEL) -> Embedder:
    def embed(texts: list[str]) -> list[list[float]]:
        from google import genai
        from google.genai import types

        response = genai.Client().models.embed_content(
            model=model, contents=texts, config=types.EmbedContentConfig(task_type=task_type)
        )
        return [list(embedding.values or []) for embedding in response.embeddings or []]

    return embed


def _normalize(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class EmbeddingRetriever:
    def __init__(
        self,
        chunks: Sequence[PolicyChunk],
        embed: Embedder | None = None,
        cache_dir: Path = CACHE_DIR,
        model: str = EMBEDDING_MODEL,
        embed_query: Embedder | None = None,
    ) -> None:
        self._sections = [chunk.section for chunk in chunks]
        self._embed_query = embed_query or embed or gemini_embedder(QUERY_TASK, model)
        embed_documents = embed or gemini_embedder(DOCUMENT_TASK, model)
        cache_path = cache_dir / f"{_cache_key(chunks, model)}.json"
        self._matrix = _normalize(self._load_or_embed(chunks, embed_documents, cache_path))

    @staticmethod
    def _load_or_embed(
        chunks: Sequence[PolicyChunk], embed: Embedder, cache_path: Path
    ) -> list[list[float]]:
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        vectors = embed([_chunk_text(chunk) for chunk in chunks])
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(vectors), encoding="utf-8")
        logger.info("Cached %d chunk embeddings at %s", len(vectors), cache_path)
        return vectors

    def rank(self, question: str) -> list[str]:
        query = _normalize(self._embed_query([question]))[0]
        similarities = self._matrix @ query
        order = np.argsort(-similarities, kind="stable")
        return [self._sections[position] for position in order]


class HybridRetriever:
    def __init__(self, bm25: Retriever, embeddings: Retriever) -> None:
        self._bm25 = bm25
        self._embeddings = embeddings

    def rank(self, question: str) -> list[str]:
        return rrf_fuse(self._bm25.rank(question), self._embeddings.rank(question))


def evaluate(
    retriever: Retriever, cases: Sequence[RetrievalCase], k: int = DEFAULT_K
) -> StrategyResult:
    rankings = [retriever.rank(case.question) for case in cases]
    expected = [case.expected_sections for case in cases]
    misses = [
        Miss(case.id, case.question, case.expected_sections, ranking[:MISS_PREVIEW])
        for case, ranking in zip(cases, rankings, strict=True)
        if _first_hit_rank(ranking[:k], case.expected_sections) is None
    ]
    return StrategyResult(
        recall_at_2=recall_at_k(rankings, expected, k), mrr=mrr(rankings, expected), misses=misses
    )


def _points(value: float) -> float:
    return round(value * PERCENT, POINTS_PRECISION)


def decide(
    bm25: StrategyResult, embeddings: StrategyResult | None, hybrid: StrategyResult | None
) -> str:
    """Apply the spec 05 decision rule to the measured results.

    Keep BM25 unless embeddings or hybrid improve recall@2 by at least 10 points, or BM25
    recall@2 is below 90% and an alternative beats it.

    Returns:
        A one-line outcome starting with "keep BM25", "switch to embeddings" or
        "switch to hybrid".
    """
    baseline = _points(bm25.recall_at_2)
    below_gate = baseline < BM25_MIN_RECALL_POINTS
    candidates = {"hybrid": hybrid, "embeddings": embeddings}
    measured = {name: _points(r.recall_at_2) for name, r in candidates.items() if r is not None}
    if not measured:
        status = "below" if below_gate else "meets"
        return f"keep BM25: recall@2 {baseline:.1f}% {status} the 90% gate; alternatives skipped"
    best = max(measured, key=lambda name: measured[name])
    gain = round(measured[best] - baseline, POINTS_PRECISION)
    if gain >= MIN_GAIN_POINTS or (below_gate and gain > 0):
        return f"switch to {best}: recall@2 {measured[best]:.1f}% vs BM25 {baseline:.1f}%"
    status = "below" if below_gate else "meets"
    return (
        f"keep BM25: recall@2 {baseline:.1f}% {status} the 90% gate and the best alternative "
        f"({best}, {measured[best]:.1f}%) gains {gain:.1f} points (< 10)"
    )


def _table(results: dict[str, StrategyResult | None]) -> list[str]:
    lines = ["| Strategy | recall@2 | MRR |", "|---|---|---|"]
    for name, result in results.items():
        if result is None:
            lines.append(f"| {name} | skipped | skipped |")
        else:
            lines.append(f"| {name} | {_points(result.recall_at_2):.1f}% | {result.mrr:.3f} |")
    return lines


def _misses(name: str, result: StrategyResult | None) -> list[str]:
    lines = [f"### {name}", ""]
    if result is None:
        return [*lines, f"skipped ({API_KEY_ENV} not set)", ""]
    if not result.misses:
        return [*lines, "none", ""]
    for miss in result.misses:
        lines.append(
            f'- `{miss.case_id}`: "{miss.question}" expected {miss.expected_sections}, '
            f"top {miss.top_sections}"
        )
    return [*lines, ""]


def write_report(results: dict[str, StrategyResult | None], path: Path = REPORT_PATH) -> None:
    """Write the retrieval comparison as Markdown: metrics table, misses and decision.

    Args:
        results: Result per strategy name (`bm25`, `embeddings`, `hybrid`); None if skipped.
        path: Destination Markdown file.
    """
    decision = decide(results["bm25"], results.get("embeddings"), results.get("hybrid"))
    lines = ["# Policy retrieval eval", "", *_table(results), "", "## Misses (top-2)", ""]
    for name, result in results.items():
        lines.extend(_misses(name, result))
    lines.extend(["## Decision", "", decision, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote retrieval report to %s", path)


def run_comparison(
    cases: Sequence[RetrievalCase], with_embeddings: bool
) -> dict[str, StrategyResult | None]:
    index = load_policy_index()
    bm25 = Bm25Retriever(index)
    results: dict[str, StrategyResult | None] = dict.fromkeys(STRATEGIES)
    results["bm25"] = evaluate(bm25, cases)
    if with_embeddings:
        embeddings = EmbeddingRetriever(index.chunks())
        results["embeddings"] = evaluate(embeddings, cases)
        results["hybrid"] = evaluate(HybridRetriever(bm25, embeddings), cases)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    results = run_comparison(load_cases(), with_embeddings=bool(os.environ.get(API_KEY_ENV)))
    write_report(results)
    print(REPORT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
