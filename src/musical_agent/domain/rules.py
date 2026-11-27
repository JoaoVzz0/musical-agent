from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
PERCENT_BASE = Decimal(100)

PIX_DISCOUNT_PERCENT = Decimal(5)

SINGLE_PAYMENT = 1
MAX_INSTALLMENTS = 12
LOW_TIER_MAX_INSTALLMENTS = 3
MID_TIER_MAX_INSTALLMENTS = 6
LOW_TIER_MIN_INSTALLMENT = Decimal(50)
MID_TIER_MIN_INSTALLMENT = Decimal(80)
HIGH_TIER_MIN_INSTALLMENT = Decimal(100)

UNAVAILABLE_STATUSES = frozenset({"discontinued", "coming_soon"})
ALTERNATIVE_PRICE_TOLERANCE = Decimal("0.30")
MAX_ALTERNATIVES = 3

WITHDRAWAL_DAYS = 7
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _round_cents(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def to_cents(value: float) -> float:
    return _round_cents(_decimal(value))


def _apply_discount(price: Decimal, percent: Decimal) -> Decimal:
    return price * (PERCENT_BASE - percent) / PERCENT_BASE


def final_price(price: float, discount_percent: float | None) -> float:
    """Price after a promotional discount, rounded half-up to cents (Rule 2).

    Args:
        price: List price in BRL.
        discount_percent: Promotion discount as a percentage (15 means 15%), or None.

    Returns:
        The discounted price, or the list price when there is no discount.
    """
    if not discount_percent:
        return to_cents(price)
    return _round_cents(_apply_discount(_decimal(price), _decimal(discount_percent)))


def pix_price(price: float, has_promotion: bool = False) -> float | None:
    """PIX price: 5% off the list price (Rule 3).

    Promotions are not cumulative (Manual 6.2), so PIX gives no extra discount
    on an item with an active promotion.

    Args:
        price: List price in BRL.
        has_promotion: Whether a promotion is active for the item.

    Returns:
        The PIX price rounded to cents, or None when a promotion is active.
    """
    if has_promotion:
        return None
    return _round_cents(_apply_discount(_decimal(price), PIX_DISCOUNT_PERCENT))


def _minimum_installment(installments: int) -> Decimal:
    if installments <= LOW_TIER_MAX_INSTALLMENTS:
        return LOW_TIER_MIN_INSTALLMENT
    if installments <= MID_TIER_MAX_INSTALLMENTS:
        return MID_TIER_MIN_INSTALLMENT
    return HIGH_TIER_MIN_INSTALLMENT


def max_installments(total: float) -> int:
    """Largest number of interest-free installments allowed for a total (Manual 3.1).

    Up to 3x needs an installment of at least R$ 50, 4x to 6x at least R$ 80 and
    7x to 12x at least R$ 100. The installment is compared unrounded (total / n).

    Args:
        total: Purchase total in BRL.

    Returns:
        The largest qualifying n in 1..12; 1 when none qualifies.
    """
    amount = _decimal(total)
    for installments in range(MAX_INSTALLMENTS, SINGLE_PAYMENT, -1):
        if amount / installments >= _minimum_installment(installments):
            return installments
    return SINGLE_PAYMENT


def installment_value(total: float, installments: int) -> float:
    if installments < SINGLE_PAYMENT:
        raise ValueError(f"installments must be >= {SINGLE_PAYMENT}, got {installments}")
    return _round_cents(_decimal(total) / installments)


def is_available(stock: int, status: str) -> bool:
    """Whether an item can be sold now (Rule 5).

    Unavailable when out of stock or with status `discontinued` or `coming_soon`.
    """
    return stock > 0 and status.strip().lower() not in UNAVAILABLE_STATUSES


@dataclass(frozen=True)
class CatalogItem:
    id: int
    category: str
    price: float
    available: bool


def _within_price_band(target_price: Decimal, price: Decimal) -> bool:
    return abs(price - target_price) <= target_price * ALTERNATIVE_PRICE_TOLERANCE


def _is_alternative(target: CatalogItem, candidate: CatalogItem) -> bool:
    return (
        candidate.id != target.id
        and candidate.available
        and candidate.category == target.category
        and _within_price_band(_decimal(target.price), _decimal(candidate.price))
    )


def pick_alternatives(
    target: CatalogItem,
    candidates: Iterable[CatalogItem],
    limit: int = MAX_ALTERNATIVES,
) -> list[CatalogItem]:
    """Alternatives for an unavailable item (Rule 5).

    Keeps available items of the same category priced within 30% of the target,
    never the target itself, ordered by closest price (ties by id).

    Args:
        target: The unavailable item.
        candidates: Catalog items to choose from.
        limit: Maximum number of alternatives returned.

    Returns:
        Up to `limit` alternatives, closest price first.
    """
    target_price = _decimal(target.price)
    matches = [item for item in candidates if _is_alternative(target, item)]
    matches.sort(key=lambda item: (abs(_decimal(item.price) - target_price), item.id))
    return matches[:limit]


@dataclass(frozen=True)
class AfterSalesWindows:
    days_since_delivery: int | None
    withdrawal_eligible: bool | None
    defect_exchange_eligible: bool | None
    legal_warranty_until: date | None
    legal_warranty_valid: bool | None


NOT_DELIVERED_WINDOWS = AfterSalesWindows(
    days_since_delivery=None,
    withdrawal_eligible=None,
    defect_exchange_eligible=None,
    legal_warranty_until=None,
    legal_warranty_valid=None,
)


def after_sales_windows(delivery_date: date | None, today: date) -> AfterSalesWindows:
    """After-sales eligibility in calendar days from delivery (Rule 7).

    Right of withdrawal 7 days (Manual 4.1), exchange for defect 30 days
    (Manual 4.2), legal warranty 90 days (Manual 8.1). The last day of each
    window is still eligible.

    Args:
        delivery_date: Date the order was delivered, or None if not delivered.
        today: Reference date for the calculation.

    Returns:
        The windows; every field is None when the order was not delivered.
    """
    if delivery_date is None:
        return NOT_DELIVERED_WINDOWS
    days = (today - delivery_date).days
    return AfterSalesWindows(
        days_since_delivery=days,
        withdrawal_eligible=days <= WITHDRAWAL_DAYS,
        defect_exchange_eligible=days <= DEFECT_EXCHANGE_DAYS,
        legal_warranty_until=delivery_date + timedelta(days=LEGAL_WARRANTY_DAYS),
        legal_warranty_valid=days <= LEGAL_WARRANTY_DAYS,
    )
