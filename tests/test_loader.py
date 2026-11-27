from __future__ import annotations

import dataclasses
import math
from datetime import date

import pandas as pd
import pytest

from musical_agent.config import get_settings
from musical_agent.data.loader import (
    Dataset,
    Promotion,
    active_promotion,
    digits_only,
    load_dataset,
    normalize_text,
)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return load_dataset()


def _row(frame: pd.DataFrame, column: str, value: int) -> pd.Series:
    return frame.loc[frame[column] == value].iloc[0]


@pytest.mark.dod("02.A1")
def test_dataset_has_expected_row_counts(dataset: Dataset) -> None:
    counts = (
        len(dataset.products),
        len(dataset.orders),
        len(dataset.promotions),
        len(dataset.customers),
    )

    assert counts == (65, 20, 25, 50)


def test_load_dataset_is_cached() -> None:
    first = load_dataset()

    second = load_dataset()

    assert first is second


def test_load_dataset_without_argument_uses_settings_data_dir() -> None:
    default = load_dataset()

    explicit = load_dataset(get_settings().data_dir)

    assert len(default.products) == len(explicit.products)


@pytest.mark.dod("02.A2")
def test_product_127_has_active_ten_percent_promotion(dataset: Dataset) -> None:
    promotion = active_promotion(dataset, 127)

    assert promotion == Promotion(discount_percent=10.0, description="Oferta Especial")


@pytest.mark.dod("02.A3")
def test_product_95_inactive_promotion_is_ignored(dataset: Dataset) -> None:
    promotion = active_promotion(dataset, 95)

    assert promotion is None


@pytest.mark.dod("02.A3")
def test_product_96_has_no_active_promotion(dataset: Dataset) -> None:
    promotion = active_promotion(dataset, 96)

    assert promotion is None


@pytest.mark.dod("02.A4")
def test_highest_active_discount_wins(dataset: Dataset) -> None:
    synthetic = pd.DataFrame(
        {
            "promotion_id": [1, 2, 3, 4],
            "product_id": [500, 500, 500, 501],
            "discount_percent": [5.0, 20.0, 50.0, 30.0],
            "description": ["Pequena", "Maior ativa", "Inativa", "Outro produto"],
            "is_active": [True, True, False, True],
        }
    )
    scenario = dataclasses.replace(dataset, promotions=synthetic)

    promotion = active_promotion(scenario, 500)

    assert promotion == Promotion(discount_percent=20.0, description="Maior ativa")


@pytest.mark.dod("02.A5")
def test_customer_phone_is_digits_only(dataset: Dataset) -> None:
    customer = _row(dataset.customers, "customer_id", 1)

    assert customer["phone_digits"] == "67998123456"


@pytest.mark.dod("02.A5")
def test_product_specs_parsed_to_dict(dataset: Dataset) -> None:
    product = _row(dataset.products, "product_id", 81)

    assert product["specs"]["back_sides"] == "Meranti"


@pytest.mark.dod("02.A5")
def test_product_name_normalized_has_no_accents(dataset: Dataset) -> None:
    normalized_names = dataset.products["name_normalized"]

    assert all(name.isascii() and name == name.lower() for name in normalized_names)


@pytest.mark.dod("02.A5")
def test_normalize_text_removes_accents_case_and_extra_spaces() -> None:
    normalized = normalize_text("  Violão   ELÉTRICO  Açaí ")

    assert normalized == "violao eletrico acai"


@pytest.mark.dod("02.A5")
def test_digits_only_strips_formatting() -> None:
    digits = digits_only("(67) 99812-3456")

    assert digits == "67998123456"


def test_product_has_category_name_and_numeric_price(dataset: Dataset) -> None:
    product = _row(dataset.products, "product_id", 81)

    assert (product["category"], product["price"]) == ("Violões", 599.9)


def test_product_price_column_is_float(dataset: Dataset) -> None:
    assert dataset.products["price"].dtype == float


def test_order_dates_are_date_objects(dataset: Dataset) -> None:
    order = _row(dataset.orders, "order_id", 1)

    assert (order["order_date"], order["estimated_delivery"]) == (
        date(2025, 10, 15),
        date(2025, 10, 25),
    )


def test_order_empty_cells_become_none(dataset: Dataset) -> None:
    order = _row(dataset.orders, "order_id", 9)

    assert (order["tracking_code"], order["estimated_delivery"], order["notes"]) == (
        None,
        None,
        None,
    )


def test_order_notes_kept_when_present(dataset: Dataset) -> None:
    order = _row(dataset.orders, "order_id", 17)

    assert order["notes"] == "Pedido cancelado pelo cliente antes do processamento"


def test_order_total_is_float(dataset: Dataset) -> None:
    order = _row(dataset.orders, "order_id", 4)

    assert isinstance(order["total"], float) and math.isclose(order["total"], 799.9)


def test_order_items_carry_product_name(dataset: Dataset) -> None:
    item = _row(dataset.order_items, "order_id", 1)

    assert item["product_name"] == _row(dataset.products, "product_id", 93)["name"]


def test_customer_first_name_and_lowercase_email(dataset: Dataset) -> None:
    customer = _row(dataset.customers, "customer_id", 1)

    assert (customer["first_name"], customer["email"]) == ("Lucas", "lucas.mendes@jmail.com")


def test_promotion_is_active_column_is_bool(dataset: Dataset) -> None:
    assert dataset.promotions["is_active"].dtype == bool
