from __future__ import annotations

import pytest

from musical_agent.tools import policies
from musical_agent.tools.policies import MAX_PASSAGES, MIN_PASSAGES, search_policies

PASSAGE_KEYS = {"section", "title", "text", "score"}


@pytest.mark.dod("03.C1")
def test_search_policies_returns_passages_with_citation_fields() -> None:
    result = search_policies("horário de funcionamento sábado")

    assert result["status"] == "ok"
    assert result["passages"]
    assert all(set(passage) == PASSAGE_KEYS for passage in result["passages"])


@pytest.mark.dod("03.C1")
@pytest.mark.parametrize(
    ("question", "expected_section"),
    [
        ("horário de funcionamento sábado", "2"),
        ("direito de arrependimento devolução", "4.1"),
        ("prazo de entrega outras cidades", "5.2"),
    ],
)
def test_search_policies_top_passage_is_the_right_section(
    question: str, expected_section: str
) -> None:
    result = search_policies(question)

    assert result["passages"][0]["section"] == expected_section


@pytest.mark.dod("03.C1")
@pytest.mark.parametrize("question", ["", "   "])
def test_search_policies_rejects_blank_question(question: str) -> None:
    result = search_policies(question)

    assert result == {"status": "invalid_question"}


@pytest.mark.dod("03.C1")
def test_search_policies_returns_error_when_index_fails_to_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_loader() -> None:
        raise OSError("manual missing")

    monkeypatch.setattr(policies, "load_policy_index", broken_loader)

    result = search_policies("horário de funcionamento")

    assert result["status"] == "error"
    assert result["message"]


@pytest.mark.parametrize(
    ("k", "expected"), [(0, MIN_PASSAGES), (-3, MIN_PASSAGES), (99, MAX_PASSAGES)]
)
def test_search_policies_clamps_k_to_allowed_range(k: int, expected: int) -> None:
    result = search_policies("garantia", k=k)

    assert len(result["passages"]) == expected


def test_search_policies_respects_k_within_range() -> None:
    result = search_policies("garantia", k=3)

    assert len(result["passages"]) == 3


class FakeEmbeddingIndex:
    def __init__(self, sections, error=None):
        self._sections = sections
        self._error = error

    def search(self, question, k):
        if self._error is not None:
            raise self._error
        return [
            {"section": section, "title": f"Seção {section}", "text": "", "score": 1.0}
            for section in self._sections[:k]
        ]


@pytest.mark.dod("03.C2")
def test_search_policies_uses_embeddings_ranking_when_available(monkeypatch):
    monkeypatch.setattr(
        policies, "load_embedding_index", lambda: FakeEmbeddingIndex(["5.3", "5.2"])
    )

    result = policies.search_policies("cadê meu pedido? como acompanho")

    assert [p["section"] for p in result["passages"]] == ["5.3", "5.2"]


@pytest.mark.dod("03.C2")
def test_search_policies_falls_back_to_bm25_without_api_key(monkeypatch):
    monkeypatch.setattr(policies, "load_embedding_index", lambda: None)

    result = policies.search_policies("horário de funcionamento sábado")

    assert result["status"] == "ok"
    assert result["passages"][0]["section"] == "2"


@pytest.mark.dod("03.C2")
def test_search_policies_falls_back_to_bm25_when_embeddings_fail(monkeypatch):
    broken = FakeEmbeddingIndex([], error=OSError("network down"))
    monkeypatch.setattr(policies, "load_embedding_index", lambda: broken)

    result = policies.search_policies("horário de funcionamento sábado")

    assert result["status"] == "ok"
    assert result["passages"][0]["section"] == "2"
