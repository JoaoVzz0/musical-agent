from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from musical_agent.config import get_settings

logger = logging.getLogger(__name__)

CSV_ENCODING = "utf-8"
ACTIVE_FLAG = "1"
DATASET_CACHE_SIZE = 4
COMBINING_MARK_FORM = "NFKD"
NON_DIGITS = re.compile(r"\D")
WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class Dataset:
    products: pd.DataFrame
    categories: pd.DataFrame
    customers: pd.DataFrame
    orders: pd.DataFrame
    order_items: pd.DataFrame
    promotions: pd.DataFrame


@dataclass(frozen=True)
class Promotion:
    discount_percent: float
    description: str


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize(COMBINING_MARK_FORM, text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return WHITESPACE_RUN.sub(" ", without_accents).strip().lower()


def digits_only(text: str) -> str:
    return NON_DIGITS.sub("", text)


def _read_csv(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(
        data_dir / f"{name}.csv",
        dtype=str,
        keep_default_na=False,
        encoding=CSV_ENCODING,
    )


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _optional_date(value: str) -> date | None:
    stripped = value.strip()
    return date.fromisoformat(stripped) if stripped else None


def _parse_specs(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    return {str(key): str(value) for key, value in json.loads(raw).items()}


def _object_column(values: list[object]) -> pd.Series:
    return pd.Series(values, dtype=object)


def _normalize_categories(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category_id": raw["category_id"].astype(int),
            "name": raw["name"].str.strip(),
            "description": raw["description"].str.strip(),
        }
    )


def _normalize_products(raw: pd.DataFrame, categories: pd.DataFrame) -> pd.DataFrame:
    category_names = dict(zip(categories["category_id"], categories["name"], strict=True))
    names = raw["name"].str.strip()
    category_ids = raw["category_id"].astype(int)
    return pd.DataFrame(
        {
            "product_id": raw["product_id"].astype(int),
            "name": names,
            "name_normalized": names.map(normalize_text),
            "price": raw["price_brl"].astype(float),
            "category_id": category_ids,
            "category": category_ids.map(category_names),
            "description": raw["description"].str.strip(),
            "stock": raw["stock_quantity"].astype(int),
            "status": raw["status"].str.strip(),
            "specs": _object_column([_parse_specs(spec) for spec in raw["specs"]]),
        }
    )


def _normalize_customers(raw: pd.DataFrame) -> pd.DataFrame:
    names = raw["name"].str.strip()
    return pd.DataFrame(
        {
            "customer_id": raw["customer_id"].astype(int),
            "name": names,
            "first_name": names.str.split().str[0],
            "phone_digits": raw["phone"].map(digits_only),
            "email": raw["email"].str.strip().str.lower(),
            "city": raw["city"].str.strip(),
        }
    )


def _normalize_orders(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": raw["order_id"].astype(int),
            "customer_id": raw["customer_id"].astype(int),
            "order_date": _object_column([date.fromisoformat(v) for v in raw["order_date"]]),
            "status": raw["status"].str.strip(),
            "total": raw["total_brl"].astype(float),
            "payment_method": raw["payment_method"].str.strip(),
            "tracking_code": _object_column([_optional_text(v) for v in raw["tracking_code"]]),
            "estimated_delivery": _object_column(
                [_optional_date(v) for v in raw["estimated_delivery"]]
            ),
            "notes": _object_column([_optional_text(v) for v in raw["notes"]]),
        }
    )


def _normalize_order_items(raw: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    product_names = dict(zip(products["product_id"], products["name"], strict=True))
    product_ids = raw["product_id"].astype(int)
    return pd.DataFrame(
        {
            "order_id": raw["order_id"].astype(int),
            "product_id": product_ids,
            "quantity": raw["quantity"].astype(int),
            "product_name": product_ids.map(product_names),
        }
    )


def _normalize_promotions(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "promotion_id": raw["promotion_id"].astype(int),
            "product_id": raw["product_id"].astype(int),
            "discount_percent": raw["discount_percent"].astype(float),
            "description": raw["description"].str.strip(),
            "is_active": raw["is_active"].str.strip() == ACTIVE_FLAG,
        }
    )


def _load_from(data_dir: Path) -> Dataset:
    categories = _normalize_categories(_read_csv(data_dir, "categories"))
    products = _normalize_products(_read_csv(data_dir, "products"), categories)
    dataset = Dataset(
        products=products,
        categories=categories,
        customers=_normalize_customers(_read_csv(data_dir, "customers")),
        orders=_normalize_orders(_read_csv(data_dir, "orders")),
        order_items=_normalize_order_items(_read_csv(data_dir, "order_items"), products),
        promotions=_normalize_promotions(_read_csv(data_dir, "promotions")),
    )
    logger.info("Loaded dataset from %s (%d products)", data_dir, len(products))
    return dataset


@lru_cache(maxsize=DATASET_CACHE_SIZE)
def load_dataset(data_dir: Path | None = None) -> Dataset:
    """Load and normalize the store CSVs, cached per `data_dir` argument.

    Args:
        data_dir: Folder holding the CSV files; `None` uses `Settings.data_dir`.

    Returns:
        The normalized `Dataset`; repeated calls with the same argument return the same object.
    """
    return _load_from(data_dir or get_settings().data_dir)


def active_promotion(dataset: Dataset, product_id: int) -> Promotion | None:
    """Return the promotion that applies to a product, if any.

    Only promotions flagged active count; when several are active, the highest discount wins.
    """
    promotions = dataset.promotions
    candidates = promotions.loc[(promotions["product_id"] == product_id) & promotions["is_active"]]
    if candidates.empty:
        return None
    best = candidates.loc[candidates["discount_percent"].idxmax()]
    return Promotion(
        discount_percent=float(best["discount_percent"]),
        description=str(best["description"]),
    )
