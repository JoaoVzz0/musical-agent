from __future__ import annotations

import pytest

from musical_agent.data.embeddings import EmbeddingIndex
from musical_agent.data.policies import PolicyChunk

CHUNKS = [
    PolicyChunk(section="2", title="Horário de Funcionamento", text="Segunda a sexta 9h às 18h"),
    PolicyChunk(section="5.3", title="Código de Rastreamento", text="Enviado por e-mail"),
    PolicyChunk(section="4.1", title="Direito de Arrependimento", text="Até 7 dias corridos"),
]

VECTORS_BY_SECTION = {"2": [1.0, 0.0, 0.0], "5.3": [0.0, 1.0, 0.0], "4.1": [0.0, 0.0, 1.0]}


class CountingEmbedder:
    def __init__(self, vector_for):
        self.calls: list[list[str]] = []
        self._vector_for = vector_for

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self._vector_for(text) for text in texts]


def document_vector(text: str) -> list[float]:
    section = next(chunk.section for chunk in CHUNKS if chunk.title in text)
    return VECTORS_BY_SECTION[section]


def tracking_query_vector(text: str) -> list[float]:
    return [0.1, 0.9, 0.2]


def build_index(tmp_path, documents=None, model="test-model") -> EmbeddingIndex:
    return EmbeddingIndex(
        CHUNKS,
        embed_documents=documents or CountingEmbedder(document_vector),
        embed_query=CountingEmbedder(tracking_query_vector),
        cache_dir=tmp_path,
        model=model,
    )


@pytest.mark.dod("03.C2")
def test_embedding_index_ranks_by_cosine_similarity(tmp_path):
    index = build_index(tmp_path)

    passages = index.search("cadê meu pedido?", k=2)

    assert [passage["section"] for passage in passages] == ["5.3", "4.1"]
    assert passages[0]["title"] == "Código de Rastreamento"
    assert passages[0]["score"] > passages[1]["score"]


@pytest.mark.dod("03.C3")
def test_second_load_reuses_cached_document_embeddings(tmp_path):
    first_embedder = CountingEmbedder(document_vector)
    build_index(tmp_path, documents=first_embedder)
    second_embedder = CountingEmbedder(document_vector)

    build_index(tmp_path, documents=second_embedder)

    assert len(first_embedder.calls) == 1
    assert second_embedder.calls == []


@pytest.mark.dod("03.C3")
def test_cache_is_keyed_by_model(tmp_path):
    build_index(tmp_path, model="model-a")
    other_model_embedder = CountingEmbedder(document_vector)

    build_index(tmp_path, documents=other_model_embedder, model="model-b")

    assert len(other_model_embedder.calls) == 1


@pytest.mark.dod("03.C3")
def test_cache_is_keyed_by_chunk_content(tmp_path):
    build_index(tmp_path)
    changed = [*CHUNKS[:2], PolicyChunk(section="4.1", title="Direito de Arrependimento", text="X")]
    embedder = CountingEmbedder(document_vector)

    EmbeddingIndex(
        changed,
        embed_documents=embedder,
        embed_query=CountingEmbedder(tracking_query_vector),
        cache_dir=tmp_path,
        model="test-model",
    )

    assert len(embedder.calls) == 1
