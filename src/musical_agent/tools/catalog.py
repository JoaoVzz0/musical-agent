from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from google.adk.tools import ToolContext
from rapidfuzz import fuzz, process

from musical_agent.data.loader import Dataset, active_promotion, load_dataset, normalize_text
from musical_agent.domain.rules import (
    MAX_ALTERNATIVES,
    CatalogItem,
    final_price,
    installment_value,
    is_available,
    max_installments,
    pick_alternatives,
    pix_price,
)
from musical_agent.types import ProductDetail, ProductSummary

logger = logging.getLogger(__name__)

SEARCH_LIMIT_CAP = 8
MIN_SEARCH_LIMIT = 1
CATEGORY_FUZZY_CUTOFF = 80
QUERY_FUZZY_CUTOFF = 80
NAME_MATCH_CUTOFF = 70
MIN_FUZZY_TOKEN_LENGTH = 4
MAX_SUGGESTIONS = 3
LAST_VIEWED_KEY = "last_viewed_product_id"
ERROR_MESSAGE = "Catálogo indisponível no momento."
DATA_ERRORS = (OSError, ValueError, KeyError, pd.errors.ParserError, pd.errors.EmptyDataError)

GUITARRAS = "Guitarras"
BAIXOS = "Baixos"
PERCUSSAO = "Baterias e Percussão"
TECLADOS = "Teclados e Pianos"
VIOLOES = "Violões"
MADEIRAS = "Instrumentos de Sopro (Madeiras)"
METAIS = "Instrumentos de Sopro (Metais)"
CORDAS = "Cordas Orquestrais"
UKULELES = "Ukuleles"

CATEGORY_SYNONYMS: dict[str, str] = {
    "violao": VIOLOES,
    "violoes": VIOLOES,
    "guitarra": GUITARRAS,
    "guitarras": GUITARRAS,
    "baixo": BAIXOS,
    "baixos": BAIXOS,
    "bateria": PERCUSSAO,
    "baterias": PERCUSSAO,
    "percussao": PERCUSSAO,
    "teclado": TECLADOS,
    "teclados": TECLADOS,
    "piano": TECLADOS,
    "pianos": TECLADOS,
    "sintetizador": TECLADOS,
    "flauta": MADEIRAS,
    "flautas": MADEIRAS,
    "sax": MADEIRAS,
    "saxofone": MADEIRAS,
    "clarinete": MADEIRAS,
    "madeiras": MADEIRAS,
    "trompete": METAIS,
    "trombone": METAIS,
    "metais": METAIS,
    "violino": CORDAS,
    "violinos": CORDAS,
    "violoncelo": CORDAS,
    "cello": CORDAS,
    "ukulele": UKULELES,
    "ukuleles": UKULELES,
}

QUERY_STOPWORDS = frozenset(
    {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "para", "com", "um", "uma"}
)


def _error() -> dict[str, Any]:
    return {"status": "error", "message": ERROR_MESSAGE}


def _fuzzy_synonym(token: str) -> str | None:
    match = process.extractOne(
        token, CATEGORY_SYNONYMS.keys(), scorer=fuzz.ratio, score_cutoff=CATEGORY_FUZZY_CUTOFF
    )
    return CATEGORY_SYNONYMS[match[0]] if match else None


def resolve_category(raw: str, categories: list[str]) -> str | None:
    """Map a free-form category (synonym, plural, typo) to a catalog category name."""
    normalized = normalize_text(raw)
    by_normalized = {normalize_text(name): name for name in categories}
    if normalized in by_normalized:
        return by_normalized[normalized]
    tokens = normalized.split()
    for token in tokens:
        if token in CATEGORY_SYNONYMS:
            return CATEGORY_SYNONYMS[token]
    for token in tokens:
        fuzzy = _fuzzy_synonym(token)
        if fuzzy:
            return fuzzy
    return None


def _token_matches(token: str, category: str, haystack: str) -> bool:
    if CATEGORY_SYNONYMS.get(token) == category or token in haystack:
        return True
    if len(token) < MIN_FUZZY_TOKEN_LENGTH:
        return False
    return fuzz.partial_ratio(token, haystack) >= QUERY_FUZZY_CUTOFF


def _query_tokens(query: str) -> list[str]:
    return [token for token in normalize_text(query).split() if token not in QUERY_STOPWORDS]


def _matches_query(row: pd.Series, tokens: list[str]) -> bool:
    haystack = " ".join(
        [
            row["name_normalized"],
            normalize_text(row["category"]),
            normalize_text(row["description"]),
        ]
    )
    return all(_token_matches(token, row["category"], haystack) for token in tokens)


def _summary(dataset: Dataset, row: pd.Series) -> ProductSummary:
    product_id = int(row["product_id"])
    promotion = active_promotion(dataset, product_id)
    discount = promotion.discount_percent if promotion else None
    return ProductSummary(
        id=product_id,
        name=str(row["name"]),
        category=str(row["category"]),
        original_price=float(row["price"]),
        final_price=final_price(float(row["price"]), discount),
        discount_percent=discount,
        promotion=promotion.description if promotion else None,
        stock=int(row["stock"]),
        available=is_available(int(row["stock"]), str(row["status"])),
    )


def _detail(row: pd.Series, summary: ProductSummary) -> ProductDetail:
    total = summary["final_price"]
    installments = max_installments(total)
    return ProductDetail(
        **summary,
        description=str(row["description"]),
        specs=dict(row["specs"]),
        catalog_status=str(row["status"]),
        pix_price=pix_price(summary["original_price"], summary["promotion"] is not None),
        max_installments=installments,
        installment_value=installment_value(total, installments),
    )


def _filter_rows(products: pd.DataFrame, category: str | None, query: str) -> pd.DataFrame:
    rows = products if category is None else products.loc[products["category"] == category]
    tokens = _query_tokens(query)
    if not tokens:
        return rows
    return rows.loc[rows.apply(_matches_query, axis=1, tokens=tokens)]


def _keep_summary(item: ProductSummary, max_price: float | None, only_available: bool) -> bool:
    if only_available and not item["available"]:
        return False
    return max_price is None or item["final_price"] <= max_price


def _search(
    dataset: Dataset,
    query: str,
    category: str,
    max_price: float | None,
    only_available: bool,
    limit: int,
) -> dict[str, Any]:
    resolved = resolve_category(category, list(dataset.categories["name"])) if category else None
    if category and resolved is None:
        return {"status": "not_found"}
    rows = _filter_rows(dataset.products, resolved, query)
    summaries = [_summary(dataset, row) for _, row in rows.iterrows()]
    matches = [item for item in summaries if _keep_summary(item, max_price, only_available)]
    if not matches:
        return {"status": "not_found"}
    matches.sort(key=lambda item: (item["final_price"], item["id"]))
    cap = max(MIN_SEARCH_LIMIT, min(limit, SEARCH_LIMIT_CAP))
    return {"status": "ok", "products": matches[:cap], "total": len(matches)}


def search_products(
    query: str = "",
    category: str = "",
    max_price: float | None = None,
    only_available: bool = True,
    limit: int = 8,
    tool_context: ToolContext | None = None,
) -> dict:
    """Search the store catalog for products to recommend or compare.

    Use it when the customer asks what the store has (e.g. "violões até R$ 1.000",
    "tem guitarra Fender?"). Returns compact items without description or specs;
    call `get_product_details` before quoting full details of a specific product.

    Args:
        query: Free text matched against product name, category and description
            (brand, model, style). Empty to list a whole category.
        category: Category name or synonym, typos accepted (e.g. "violao", "guitarra",
            "bateria", "sax", "cello", "ukulele"). Empty for every category.
        max_price: Maximum final price in BRL (after promotions), or None for no limit.
        only_available: True (default) hides out-of-stock, discontinued and coming-soon items.
        limit: Maximum number of items returned (capped at 8).
        tool_context: Injected by ADK.

    Returns:
        {"status": "ok", "products": [summary], "total": matches before the cap}, sorted
        by final price ascending; each summary has id, name, category, original_price,
        final_price, discount_percent, promotion, stock and available.
        {"status": "not_found"} when nothing matches, {"status": "error", "message"} on failure.
    """
    try:
        return _search(load_dataset(), query, category, max_price, only_available, limit)
    except DATA_ERRORS:
        logger.exception("search_products failed")
        return _error()


def _find_by_id(products: pd.DataFrame, product: str) -> pd.Series | None:
    rows = products.loc[products["product_id"] == int(product)]
    return None if rows.empty else rows.iloc[0]


def _name_score(query: str, name: str) -> tuple[float, float]:
    return fuzz.token_set_ratio(query, name), fuzz.ratio(query, name)


def _find_by_name(products: pd.DataFrame, product: str) -> pd.Series | None:
    query = normalize_text(product)
    scores = products["name_normalized"].map(lambda name: _name_score(query, name))
    best_index = max(scores.index, key=lambda index: scores[index])
    if scores[best_index][0] < NAME_MATCH_CUTOFF:
        return None
    return products.loc[best_index]


def _suggestions(products: pd.DataFrame, product: str) -> list[str]:
    matches = process.extract(
        normalize_text(product),
        list(products["name_normalized"]),
        scorer=fuzz.WRatio,
        limit=MAX_SUGGESTIONS,
    )
    return [str(products["name"].iloc[index]) for _, _, index in matches]


def _alternatives(dataset: Dataset, summary: ProductSummary) -> list[ProductSummary]:
    if summary["available"]:
        return []
    same_category = dataset.products.loc[dataset.products["category"] == summary["category"]]
    candidates = {
        item["id"]: item for item in (_summary(dataset, row) for _, row in same_category.iterrows())
    }
    target = CatalogItem(summary["id"], summary["category"], summary["final_price"], False)
    items = [
        CatalogItem(c["id"], c["category"], c["final_price"], c["available"])
        for c in candidates.values()
    ]
    return [candidates[item.id] for item in pick_alternatives(target, items, MAX_ALTERNATIVES)]


def _details(dataset: Dataset, product: str, tool_context: ToolContext | None) -> dict[str, Any]:
    reference = product.strip()
    products = dataset.products
    row = (
        _find_by_id(products, reference)
        if reference.isdigit()
        else _find_by_name(products, reference)
    )
    if row is None:
        return {"status": "not_found", "suggestions": _suggestions(products, reference)}
    summary = _summary(dataset, row)
    if tool_context is not None:
        tool_context.state[LAST_VIEWED_KEY] = summary["id"]
    return {
        "status": "ok",
        "product": _detail(row, summary),
        "alternatives": _alternatives(dataset, summary),
    }


def get_product_details(product: str, tool_context: ToolContext | None = None) -> dict:
    """Get full details, prices and payment conditions of one product.

    Use it before quoting a price, promotion, PIX price, installments, stock or specs,
    and whenever the customer names a specific product.

    Args:
        product: Product id (e.g. "95") or product name; names are fuzzy-matched
            (e.g. "takamine gd20").
        tool_context: Injected by ADK; the product id is saved as `last_viewed_product_id`.

    Returns:
        {"status": "ok", "product": detail, "alternatives": [summary]} where detail has
        original_price, final_price, discount_percent, promotion, pix_price (None when a
        promotion is active), max_installments, installment_value, available, stock,
        catalog_status, description and specs; alternatives (up to 3, same category,
        similar price) only when the product is unavailable.
        {"status": "not_found", "suggestions": [up to 3 closest names]} when unknown,
        {"status": "error", "message"} on failure.
    """
    try:
        return _details(load_dataset(), product, tool_context)
    except DATA_ERRORS:
        logger.exception("get_product_details failed")
        return _error()
