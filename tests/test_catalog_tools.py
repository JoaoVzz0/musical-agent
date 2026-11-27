from __future__ import annotations

from types import SimpleNamespace

import pytest

from musical_agent.data.loader import load_dataset
from musical_agent.tools.catalog import get_product_details, resolve_category, search_products

VIOLOES = "Violões"
GUITARRAS = "Guitarras"
BUDGET = 1000.0
UNAVAILABLE_VIOLAO_IDS = {96, 113}
AVAILABLE_VIOLOES_UP_TO_BUDGET = 12
ALL_VIOLOES_UP_TO_BUDGET = 14
SEARCH_CAP = 8
MAX_ALTERNATIVES = 3
SUMMARY_KEYS = {
    "id",
    "name",
    "category",
    "original_price",
    "final_price",
    "discount_percent",
    "promotion",
    "stock",
    "available",
}


def make_context() -> SimpleNamespace:
    return SimpleNamespace(state={})


def result_ids(result: dict) -> set[int]:
    return {item["id"] for item in result["products"]}


@pytest.mark.dod("03.A1")
def test_available_violoes_under_budget_exclude_unavailable_ids():
    result = search_products(category=VIOLOES, max_price=BUDGET, limit=50)

    assert result["status"] == "ok"
    assert result["total"] == AVAILABLE_VIOLOES_UP_TO_BUDGET
    assert result_ids(result).isdisjoint(UNAVAILABLE_VIOLAO_IDS)


@pytest.mark.dod("03.A1")
def test_violoes_under_budget_respect_max_final_price():
    result = search_products(category=VIOLOES, max_price=BUDGET)

    assert all(item["final_price"] <= BUDGET for item in result["products"])
    assert all(item["category"] == VIOLOES for item in result["products"])


@pytest.mark.dod("03.A1")
def test_including_unavailable_counts_ids_96_and_113():
    result = search_products(category=VIOLOES, max_price=BUDGET, only_available=False)

    assert result["total"] == ALL_VIOLOES_UP_TO_BUDGET


def test_search_results_sorted_by_final_price_ascending():
    result = search_products(category=VIOLOES)

    prices = [item["final_price"] for item in result["products"]]
    assert prices == sorted(prices)


@pytest.mark.dod("03.A2")
def test_takamine_gd20_resolves_product_95():
    result = get_product_details("takamine gd20")

    assert result["status"] == "ok"
    assert result["product"]["id"] == 95


@pytest.mark.dod("03.A2")
def test_takamine_gd20_prices_without_promotion():
    product = get_product_details("takamine gd20")["product"]

    assert product["original_price"] == 2199.00
    assert product["final_price"] == 2199.00
    assert product["discount_percent"] is None
    assert product["promotion"] is None
    assert product["pix_price"] == 2089.05
    assert product["max_installments"] == 12
    assert product["installment_value"] == 183.25


def test_product_resolves_by_numeric_id():
    result = get_product_details("95")

    assert result["product"]["name"].startswith("Takamine GD20")


def test_available_product_has_no_alternatives():
    result = get_product_details("95")

    assert result["alternatives"] == []


@pytest.mark.dod("03.A3")
def test_promotional_product_shows_original_final_and_percent():
    product = get_product_details("127")["product"]

    assert product["original_price"] == 359.00
    assert product["final_price"] == 323.10
    assert product["discount_percent"] == 10
    assert product["promotion"] == "Oferta Especial"


@pytest.mark.dod("03.A3")
def test_promotional_product_has_no_pix_discount():
    product = get_product_details("127")["product"]

    assert product["pix_price"] is None


@pytest.mark.dod("03.A4")
def test_out_of_stock_product_is_unavailable():
    product = get_product_details("96")["product"]

    assert product["available"] is False


@pytest.mark.dod("03.A4")
def test_unavailable_product_returns_up_to_three_valid_alternatives():
    result = get_product_details("96")
    target_price = result["product"]["final_price"]

    alternatives = result["alternatives"]
    assert 0 < len(alternatives) <= MAX_ALTERNATIVES
    for item in alternatives:
        assert item["available"] is True
        assert item["category"] == VIOLOES
        assert abs(item["final_price"] - target_price) <= target_price * 0.30


@pytest.mark.dod("03.A5")
@pytest.mark.parametrize("category", ["violao", "violões", "violao classico", "Violoes"])
def test_violao_synonyms_resolve_to_violoes(category):
    result = search_products(category=category)

    assert {item["category"] for item in result["products"]} == {VIOLOES}


@pytest.mark.dod("03.A5")
@pytest.mark.parametrize("category", ["guitarra", "guitarras", "Guitarra"])
def test_guitarra_synonyms_resolve_to_guitarras(category):
    result = search_products(category=category)

    assert {item["category"] for item in result["products"]} == {GUITARRAS}


@pytest.mark.dod("03.A5")
@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("guitara", GUITARRAS),
        ("vilao", VIOLOES),
        ("ukelele", "Ukuleles"),
        ("bateria", "Baterias e Percussão"),
        ("piano", "Teclados e Pianos"),
        ("baixo", "Baixos"),
    ],
)
def test_category_typos_and_synonyms_resolve(category, expected):
    result = search_products(category=category)

    assert {item["category"] for item in result["products"]} == {expected}


@pytest.mark.dod("03.A5")
@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("saxofone", "Instrumentos de Sopro (Madeiras)"),
        ("flauta", "Instrumentos de Sopro (Madeiras)"),
        ("clarinete", "Instrumentos de Sopro (Madeiras)"),
        ("trompete", "Instrumentos de Sopro (Metais)"),
        ("trombone", "Instrumentos de Sopro (Metais)"),
        ("violino", "Cordas Orquestrais"),
        ("violoncelo", "Cordas Orquestrais"),
        ("cello", "Cordas Orquestrais"),
        ("percussao", "Baterias e Percussão"),
    ],
)
def test_category_synonyms_without_stock_in_dataset_resolve(category, expected):
    categories = list(load_dataset().categories["name"])

    assert resolve_category(category, categories) == expected


def test_unknown_category_returns_not_found():
    result = search_products(category="xyzwq")

    assert result == {"status": "not_found"}


def test_free_text_query_matches_brand_in_name():
    result = search_products(query="takamine")

    assert result["status"] == "ok"
    assert all("Takamine" in item["name"] for item in result["products"])


def test_free_text_query_without_matches_returns_not_found():
    result = search_products(query="qwertyzxcv")

    assert result == {"status": "not_found"}


@pytest.mark.dod("03.A6")
def test_search_returns_at_most_eight_items_even_with_larger_limit():
    result = search_products(limit=50)

    assert len(result["products"]) == SEARCH_CAP
    assert result["total"] > SEARCH_CAP


@pytest.mark.dod("03.A6")
def test_search_items_are_compact_summaries():
    result = search_products(category=VIOLOES)

    assert all(set(item) == SUMMARY_KEYS for item in result["products"])


@pytest.mark.dod("03.A7")
def test_details_save_last_viewed_product_id_in_state():
    context = make_context()

    get_product_details("takamine gd20", tool_context=context)

    assert context.state["last_viewed_product_id"] == 95
    assert isinstance(context.state["last_viewed_product_id"], int)


def test_unknown_product_returns_up_to_three_suggestions():
    result = get_product_details("zzzz qqqq")

    assert result["status"] == "not_found"
    assert len(result["suggestions"]) <= MAX_ALTERNATIVES


def test_unknown_numeric_id_returns_not_found():
    result = get_product_details("99999")

    assert result["status"] == "not_found"


def test_not_found_does_not_touch_state():
    context = make_context()

    get_product_details("99999", tool_context=context)

    assert "last_viewed_product_id" not in context.state


def test_dataset_failure_returns_error_instead_of_raising(monkeypatch):
    def broken_loader():
        raise OSError("disk unavailable")

    monkeypatch.setattr("musical_agent.tools.catalog.load_dataset", broken_loader)

    result = search_products(category=VIOLOES)

    assert result["status"] == "error"
