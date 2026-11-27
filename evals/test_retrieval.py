from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from evals.retrieval_eval import (
    CASES_PATH,
    REPORT_PATH,
    Bm25Retriever,
    EmbeddingRetriever,
    HybridRetriever,
    RetrievalCase,
    StrategyResult,
    decide,
    evaluate,
    gemini_embedder,
    load_cases,
    mrr,
    recall_at_k,
    rrf_fuse,
    run_comparison,
    write_report,
)
from musical_agent.data.policies import PolicyChunk, load_policy_index

MIN_CASES = 15
REQUIRED_TOP_SECTIONS = {"2", "3", "4", "5", "6", "7", "8"}
RECALL_GATE = 0.9
BM25_BASELINE_FLOOR = 0.75
TOY_CHUNKS = [
    PolicyChunk(section="2", title="Horario", text="segunda a sexta"),
    PolicyChunk(section="3", title="Pagamento", text="pix cartao boleto"),
    PolicyChunk(section="5.1", title="Entrega", text="frete gratis"),
]
TOY_VECTORS = {
    "Horario\nsegunda a sexta": [1.0, 0.0, 0.0],
    "Pagamento\npix cartao boleto": [0.0, 1.0, 0.0],
    "Entrega\nfrete gratis": [0.0, 0.0, 1.0],
    "vcs abrem domingo?": [0.9, 0.1, 0.0],
    "chega quando?": [0.1, 0.2, 0.9],
}


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [TOY_VECTORS[text] for text in texts]


class FixedRetriever:
    def __init__(self, ranking: list[str]) -> None:
        self._ranking = ranking

    def rank(self, question: str) -> list[str]:
        return list(self._ranking)


def _result(recall: float) -> StrategyResult:
    return StrategyResult(recall_at_2=recall, mrr=recall, misses=[])


@pytest.mark.dod("05.D1")
def test_cases_file_is_schema_valid() -> None:
    raw = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))

    cases = load_cases(CASES_PATH)

    assert len(cases) == len(raw["cases"])
    assert all(case.id and case.question and case.expected_sections for case in cases)
    assert len({case.id for case in cases}) == len(cases)


@pytest.mark.dod("05.D1")
def test_cases_file_has_at_least_fifteen_cases() -> None:
    cases = load_cases(CASES_PATH)

    assert len(cases) >= MIN_CASES


@pytest.mark.dod("05.D1")
def test_cases_cover_sections_two_to_eight() -> None:
    known = {chunk.section for chunk in load_policy_index().chunks()}

    cases = load_cases(CASES_PATH)

    labeled = {section for case in cases for section in case.expected_sections}
    assert labeled <= known
    assert {section.split(".")[0] for section in labeled} >= REQUIRED_TOP_SECTIONS


def test_load_cases_rejects_case_without_expected_sections(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: x\n    question: oi\n    expected_sections: []\n")

    with pytest.raises(ValueError, match="x"):
        load_cases(path)


@pytest.mark.dod("05.D2")
def test_recall_at_k_counts_hits_within_top_k() -> None:
    rankings = [["a", "b", "c"], ["c", "a", "b"], ["b", "c", "a"]]
    expected = [["a"], ["a"], ["a"]]

    assert recall_at_k(rankings, expected, k=2) == pytest.approx(2 / 3)


@pytest.mark.dod("05.D2")
def test_recall_at_k_accepts_any_of_the_expected_sections() -> None:
    rankings = [["x", "y", "b"]]
    expected = [["a", "y"]]

    assert recall_at_k(rankings, expected, k=2) == 1.0


@pytest.mark.dod("05.D2")
def test_mrr_averages_reciprocal_rank_of_first_hit() -> None:
    rankings = [["a", "b"], ["b", "a"], ["b", "c"]]
    expected = [["a"], ["a"], ["a"]]

    assert mrr(rankings, expected) == pytest.approx((1 + 0.5 + 0) / 3)


@pytest.mark.dod("05.D2")
def test_mrr_uses_best_ranked_expected_section() -> None:
    rankings = [["x", "b", "a"]]
    expected = [["a", "b"]]

    assert mrr(rankings, expected) == pytest.approx(0.5)


@pytest.mark.dod("05.D2")
def test_metrics_reject_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        recall_at_k([["a"]], [], k=2)


@pytest.mark.dod("05.D2")
def test_rrf_fuse_promotes_items_ranked_well_by_both() -> None:
    rankings_a = ["a", "b", "c"]
    rankings_b = ["b", "c", "a"]

    fused = rrf_fuse(rankings_a, rankings_b)

    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c"}


@pytest.mark.dod("05.D2")
def test_rrf_fuse_includes_items_from_only_one_ranking() -> None:
    fused = rrf_fuse(["a", "b"], ["a", "z"])

    assert fused == ["a", "b", "z"] or fused == ["a", "z", "b"]
    assert fused[0] == "a"


@pytest.mark.dod("05.D2")
def test_rrf_fuse_breaks_ties_by_first_ranking() -> None:
    fused = rrf_fuse(["a", "b"], ["b", "a"])

    assert fused == ["a", "b"]


def test_bm25_fallback_baseline_does_not_regress() -> None:
    cases = load_cases(CASES_PATH)

    result = evaluate(Bm25Retriever(load_policy_index()), cases, k=2)

    assert result.recall_at_2 >= BM25_BASELINE_FLOOR, result.misses


@pytest.mark.evals
@pytest.mark.dod("05.D3")
def test_chosen_retriever_meets_recall_gate() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY is not set")
    index = load_policy_index()
    retriever = EmbeddingRetriever(
        index.chunks(),
        embed=gemini_embedder("RETRIEVAL_DOCUMENT"),
        embed_query=gemini_embedder("RETRIEVAL_QUERY"),
    )

    result = evaluate(retriever, load_cases(CASES_PATH), k=2)

    assert result.recall_at_2 >= RECALL_GATE, result.misses


def test_bm25_retriever_ranks_every_chunk() -> None:
    index = load_policy_index()

    ranking = Bm25Retriever(index).rank("dá pra parcelar?")

    assert sorted(ranking) == sorted(chunk.section for chunk in index.chunks())


def test_evaluate_lists_missed_case_ids() -> None:
    cases = [
        RetrievalCase(id="hit", question="q1", expected_sections=["a"]),
        RetrievalCase(id="miss", question="q2", expected_sections=["z"]),
    ]

    result = evaluate(FixedRetriever(["a", "b", "z"]), cases, k=2)

    assert result.recall_at_2 == 0.5
    assert result.mrr == pytest.approx((1 + 1 / 3) / 2)
    assert [miss.case_id for miss in result.misses] == ["miss"]


def test_embedding_retriever_ranks_by_cosine_similarity(tmp_path: Path) -> None:
    retriever = EmbeddingRetriever(TOY_CHUNKS, embed=FakeEmbedder(), cache_dir=tmp_path)

    ranking = retriever.rank("chega quando?")

    assert ranking == ["5.1", "3", "2"]


def test_embedding_retriever_reuses_cached_chunk_embeddings(tmp_path: Path) -> None:
    EmbeddingRetriever(TOY_CHUNKS, embed=FakeEmbedder(), cache_dir=tmp_path).rank("chega quando?")
    second = FakeEmbedder()

    ranking = EmbeddingRetriever(TOY_CHUNKS, embed=second, cache_dir=tmp_path).rank(
        "vcs abrem domingo?"
    )

    assert ranking[0] == "2"
    assert second.calls == [["vcs abrem domingo?"]]


def test_embedding_cache_is_keyed_by_model_name(tmp_path: Path) -> None:
    EmbeddingRetriever(TOY_CHUNKS, embed=FakeEmbedder(), cache_dir=tmp_path, model="m1")
    second = FakeEmbedder()

    EmbeddingRetriever(TOY_CHUNKS, embed=second, cache_dir=tmp_path, model="m2")

    assert len(second.calls) == 1
    assert len(list(tmp_path.iterdir())) == 2


def test_hybrid_retriever_fuses_both_rankings() -> None:
    hybrid = HybridRetriever(FixedRetriever(["a", "b", "c"]), FixedRetriever(["b", "c", "a"]))

    ranking = hybrid.rank("qualquer")

    assert ranking[0] == "b"


def test_decide_keeps_bm25_when_alternatives_do_not_help() -> None:
    outcome = decide(_result(0.92), _result(0.95), _result(0.96))

    assert outcome.startswith("keep BM25")


def test_decide_switches_when_embeddings_gain_ten_points() -> None:
    outcome = decide(_result(0.90), _result(1.0), _result(0.95))

    assert outcome.startswith("switch to embeddings")


def test_decide_prefers_hybrid_when_it_is_the_best_alternative() -> None:
    outcome = decide(_result(0.80), _result(0.85), _result(0.95))

    assert outcome.startswith("switch to hybrid")


def test_decide_flags_low_bm25_without_alternatives() -> None:
    outcome = decide(_result(0.80), None, None)

    assert "below" in outcome


def test_decide_keeps_bm25_when_alternatives_skipped() -> None:
    outcome = decide(_result(0.95), None, None)

    assert outcome.startswith("keep BM25")


def test_write_report_contains_table_misses_and_decision(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    results = {"bm25": _result(0.95), "embeddings": None, "hybrid": None}

    write_report(results, path)

    content = path.read_text(encoding="utf-8")
    assert "| bm25 | 95.0% |" in content
    assert "skipped" in content
    assert "keep BM25" in content


@pytest.mark.evals
@pytest.mark.dod("05.D4")
def test_real_comparison_writes_report() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY is not set")

    results = run_comparison(load_cases(CASES_PATH), with_embeddings=True)
    write_report(results, REPORT_PATH)

    assert results["embeddings"] is not None
    assert REPORT_PATH.exists()
