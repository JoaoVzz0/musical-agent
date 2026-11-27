from __future__ import annotations

import re

import pytest

from musical_agent.config import PROJECT_ROOT
from musical_agent.data.policies import (
    PolicyChunk,
    PolicyIndex,
    extract_manual_text,
    load_policy_index,
    split_into_chunks,
    tokenize,
)

MANUAL_PATH = PROJECT_ROOT / "data" / "store_policies.pdf"
EXPECTED_SECTIONS = {
    "1",
    "1.1",
    "1.2",
    "2",
    "3",
    "3.1",
    "4",
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    "5.1",
    "5.2",
    "5.3",
    "6.1",
    "6.2",
    "7",
    "7.1",
    "7.2",
    "7.3",
    "8.1",
    "8.2",
    "8.3",
    "9",
    "10",
}
PAGE_MARKER = re.compile(r"P[áa]gina \d+")
REPEATED_HEADER = "Manual de Políticas e Procedimentos"


@pytest.fixture(scope="module")
def chunks() -> list[PolicyChunk]:
    return split_into_chunks(extract_manual_text(MANUAL_PATH))


@pytest.fixture(scope="module")
def index(chunks: list[PolicyChunk]) -> PolicyIndex:
    return PolicyIndex(chunks)


def top_sections(index: PolicyIndex, question: str, k: int) -> list[str]:
    return [passage["section"] for passage in index.search(question, k=k)]


def belongs_to(section: str, expected: str) -> bool:
    return section == expected or section.startswith(f"{expected}.")


@pytest.mark.dod("02.B1")
def test_chunks_cover_every_section_and_subsection(chunks: list[PolicyChunk]) -> None:
    sections = {chunk.section for chunk in chunks}

    assert sections == EXPECTED_SECTIONS


@pytest.mark.dod("02.B1")
def test_numbered_list_in_section_seven_is_not_split_into_sections(
    chunks: list[PolicyChunk],
) -> None:
    flow = next(chunk for chunk in chunks if chunk.section == "7.2")

    assert "Saudação" in flow.text
    assert "Fechamento" in flow.text


@pytest.mark.dod("02.B1")
def test_subsection_spanning_pages_keeps_text_from_both_pages(
    chunks: list[PolicyChunk],
) -> None:
    other_cities = next(chunk for chunk in chunks if chunk.section == "5.2")

    assert other_cities.title == "Entregas para Outras Cidades"
    assert "Jadlog" in other_cities.text
    assert "frete especial" in other_cities.text


@pytest.mark.dod("02.B1")
def test_no_chunk_contains_page_numbers(chunks: list[PolicyChunk]) -> None:
    offending = [chunk.section for chunk in chunks if PAGE_MARKER.search(chunk.text)]

    assert offending == []


@pytest.mark.dod("02.B1")
def test_no_chunk_contains_repeated_page_header(chunks: list[PolicyChunk]) -> None:
    offending = [chunk.section for chunk in chunks if REPEATED_HEADER in chunk.text]

    assert offending == []


@pytest.mark.dod("02.B1")
def test_cover_page_is_excluded_from_text() -> None:
    text = extract_manual_text(MANUAL_PATH)

    assert "Documento interno" not in text
    assert text.lstrip().startswith("1. Sobre a Empório da Música")


@pytest.mark.dod("02.B1")
def test_chunk_titles_match_manual_headings(chunks: list[PolicyChunk]) -> None:
    titles = {chunk.section: chunk.title for chunk in chunks}

    assert titles["4.1"] == "Direito de Arrependimento (Compras Online)"
    assert titles["10"] == "Disposições Finais"


@pytest.mark.dod("02.B2")
def test_regret_question_finds_withdrawal_right(index: PolicyIndex) -> None:
    sections = top_sections(index, "me arrependi, posso devolver", k=2)

    assert "4.1" in sections


@pytest.mark.dod("02.B2")
def test_pix_question_finds_payment_section(index: PolicyIndex) -> None:
    sections = top_sections(index, "aceita pix", k=2)

    assert any(belongs_to(section, "3") for section in sections)


@pytest.mark.dod("02.B2")
def test_saturday_hours_question_ranks_opening_hours_first(index: PolicyIndex) -> None:
    sections = top_sections(index, "horário sábado", k=1)

    assert belongs_to(sections[0], "2")


@pytest.mark.dod("02.B2")
def test_shipping_to_other_city_finds_intercity_delivery(index: PolicyIndex) -> None:
    sections = top_sections(index, "frete para Dourados", k=2)

    assert "5.2" in sections


@pytest.mark.dod("02.B2")
def test_search_returns_k_passages_best_first(index: PolicyIndex) -> None:
    passages = index.search("garantia legal", k=3)

    scores = [passage["score"] for passage in passages]
    assert len(passages) == 3
    assert scores == sorted(scores, reverse=True)
    assert all(isinstance(score, float) for score in scores)


def test_tokenize_lowercases_strips_accents_stopwords_and_stems() -> None:
    tokens = tokenize("Qual o Horário de funcionamento no Sábado?")

    assert tokens == ["horar", "funci", "sabad"]


def test_index_exposes_the_chunks_it_was_built_from(chunks: list[PolicyChunk]) -> None:
    index = PolicyIndex(chunks)

    assert index.chunks() == chunks


def test_load_policy_index_defaults_to_data_dir_manual_and_is_cached() -> None:
    first = load_policy_index()

    second = load_policy_index()

    assert first is second
    assert {chunk.section for chunk in first.chunks()} == EXPECTED_SECTIONS
