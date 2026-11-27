"""Semantic ranking of the store manual chunks (production retriever, ADR-003).

Chosen over BM25 by the retrieval eval: customers paraphrase ("cadê meu pedido?") without
the manual's words, and embeddings reached 91.7% recall@2 against 79.2% for BM25.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np

from musical_agent.config import get_settings
from musical_agent.data.policies import PolicyChunk, load_policy_index
from musical_agent.types import PolicyPassage

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
QUERY_TASK = "RETRIEVAL_QUERY"
CACHE_SUBDIR = "embeddings"

Embedder = Callable[[list[str]], list[list[float]]]


def chunk_text(chunk: PolicyChunk) -> str:
    return f"{chunk.title}\n{chunk.text}"


def cache_key(chunks: Sequence[PolicyChunk], model: str) -> str:
    digest = hashlib.sha256(model.encode("utf-8"))
    for chunk in chunks:
        digest.update(f"{chunk.section}\x00{chunk_text(chunk)}\x00".encode())
    return digest.hexdigest()


def gemini_embedder(
    task_type: str, model: str = EMBEDDING_MODEL, api_key: str | None = None
) -> Embedder:
    """Build an embed function backed by one long-lived google-genai client.

    The client must outlive every call: a client created inline is garbage-collected and
    closes its HTTP connection while the request is still in flight.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    config = types.EmbedContentConfig(task_type=task_type)

    def embed(texts: list[str]) -> list[list[float]]:
        response = client.models.embed_content(model=model, contents=texts, config=config)
        return [list(embedding.values or []) for embedding in response.embeddings or []]

    return embed


def normalize_rows(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class EmbeddingIndex:
    def __init__(
        self,
        chunks: Sequence[PolicyChunk],
        embed_documents: Embedder,
        embed_query: Embedder,
        cache_dir: Path,
        model: str = EMBEDDING_MODEL,
    ) -> None:
        self._chunks = list(chunks)
        self._embed_query = embed_query
        cache_path = cache_dir / f"{cache_key(self._chunks, model)}.json"
        self._matrix = normalize_rows(self._load_or_embed(embed_documents, cache_path))

    def _load_or_embed(self, embed: Embedder, cache_path: Path) -> list[list[float]]:
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        vectors = embed([chunk_text(chunk) for chunk in self._chunks])
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(vectors), encoding="utf-8")
        logger.info("Cached %d chunk embeddings at %s", len(vectors), cache_path)
        return vectors

    def similarities(self, question: str) -> np.ndarray:
        query = normalize_rows(self._embed_query([question]))[0]
        return self._matrix @ query

    def rank_sections(self, question: str) -> list[str]:
        order = np.argsort(-self.similarities(question), kind="stable")
        return [self._chunks[position].section for position in order]

    def search(self, question: str, k: int) -> list[PolicyPassage]:
        scores = self.similarities(question)
        order = np.argsort(-scores, kind="stable")[:k]
        return [
            PolicyPassage(
                section=self._chunks[position].section,
                title=self._chunks[position].title,
                text=self._chunks[position].text,
                score=float(scores[position]),
            )
            for position in order
        ]


@lru_cache(maxsize=1)
def load_embedding_index() -> EmbeddingIndex | None:
    """Return the production embedding index, or None when no API key is configured.

    Chunk embeddings are computed once and cached under `SUPPORT_DIR/embeddings`.
    """
    settings = get_settings()
    api_key = settings.google_api_key.get_secret_value() if settings.google_api_key else ""
    if not api_key.strip():
        return None
    return EmbeddingIndex(
        load_policy_index().chunks(),
        embed_documents=gemini_embedder(DOCUMENT_TASK, api_key=api_key),
        embed_query=gemini_embedder(QUERY_TASK, api_key=api_key),
        cache_dir=settings.support_dir / CACHE_SUBDIR,
    )
