from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from google.adk.tools import ToolContext

from musical_agent.config import current_time
from musical_agent.data.loader import Dataset, digits_only, load_dataset
from musical_agent.domain.rules import after_sales_windows
from musical_agent.types import OrderDetail, OrderItem

logger = logging.getLogger(__name__)

DELIVERED_STATUS = "delivered"
COUNTRY_CODE = "55"
NATIONAL_PHONE_DIGITS = range(10, 12)
VERIFIED_ORDER_KEY = "verified_order_id"
FIRST_NAME_KEY = "first_name"
LOOKUP_ERROR_MESSAGE = "Não foi possível consultar o pedido agora."

STATUS_LABELS = {
    "delivered": "entregue",
    "shipped": "a caminho",
    "confirmed": "confirmado, em separação",
    "pending": "aguardando pagamento",
    "cancelled": "cancelado",
}

PAYMENT_LABELS = {
    "pix": "PIX",
    "debit": "cartão de débito",
    "boleto": "boleto",
    "credit_3x": "cartão de crédito em 3x",
    "credit_6x": "cartão de crédito em 6x",
    "credit_12x": "cartão de crédito em 12x",
}


def _national_phone(contact: str) -> str:
    digits = digits_only(contact)
    with_country_code = len(digits) - len(COUNTRY_CODE) in NATIONAL_PHONE_DIGITS
    if digits.startswith(COUNTRY_CODE) and with_country_code:
        return digits[len(COUNTRY_CODE) :]
    return digits


def _contact_matches(customer: pd.Series, contact: str) -> bool:
    cleaned = contact.strip().lower()
    if not cleaned:
        return False
    if "@" in cleaned:
        return cleaned == customer["email"]
    phone = _national_phone(cleaned)
    return bool(phone) and phone == _national_phone(customer["phone_digits"])


def _first_row(frame: pd.DataFrame, column: str, value: int) -> pd.Series | None:
    matches = frame[frame[column] == value]
    return None if matches.empty else matches.iloc[0]


def _items_of(dataset: Dataset, order_id: int) -> list[OrderItem]:
    rows = dataset.order_items[dataset.order_items["order_id"] == order_id]
    return [
        OrderItem(name=str(row.product_name), quantity=int(row.quantity))
        for row in rows.itertuples()
    ]


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _label(labels: dict[str, str], raw: str) -> str:
    return labels.get(raw, raw)


def _build_detail(dataset: Dataset, order: pd.Series, first_name: str) -> OrderDetail:
    delivered = order["status"] == DELIVERED_STATUS
    delivery = order["estimated_delivery"] if delivered else None
    windows = after_sales_windows(delivery, current_time().date())
    return OrderDetail(
        number=int(order["order_id"]),
        date=order["order_date"].isoformat(),
        status=order["status"],
        status_label=_label(STATUS_LABELS, order["status"]),
        items=_items_of(dataset, int(order["order_id"])),
        total=float(order["total"]),
        payment_method=_label(PAYMENT_LABELS, order["payment_method"]),
        tracking_code=order["tracking_code"],
        estimated_delivery=_iso(order["estimated_delivery"]),
        note=order["notes"],
        days_since_delivery=windows.days_since_delivery,
        withdrawal_eligible=windows.withdrawal_eligible,
        defect_exchange_eligible=windows.defect_exchange_eligible,
        legal_warranty_until=_iso(windows.legal_warranty_until),
        customer_first_name=first_name,
    )


def _remember_verification(
    tool_context: ToolContext | None, order_id: int, first_name: str
) -> None:
    if tool_context is None:
        return
    tool_context.state[VERIFIED_ORDER_KEY] = order_id
    tool_context.state[FIRST_NAME_KEY] = first_name


def _lookup(order_number: int, email_or_phone: str) -> dict[str, Any]:
    dataset = load_dataset()
    order = _first_row(dataset.orders, "order_id", int(order_number))
    if order is None:
        logger.info("Order %s not found", order_number)
        return {"status": "not_found"}
    customer = _first_row(dataset.customers, "customer_id", int(order["customer_id"]))
    if customer is None or not _contact_matches(customer, email_or_phone):
        logger.info("Verification failed for order %s", order_number)
        return {"status": "verification_failed"}
    first_name = str(customer["first_name"])
    return {"status": "ok", "order": _build_detail(dataset, order, first_name)}


def get_order_status(
    order_number: int,
    email_or_phone: str,
    tool_context: ToolContext | None = None,
) -> dict:
    """Look up a customer's order after checking their identity.

    Use whenever the customer asks about an order: status, delivery, tracking, items,
    total, or whether it can still be returned, exchanged or covered by warranty. It needs
    BOTH the order number AND the e-mail or phone registered on the order; ask the customer
    for whichever is missing before calling. Never guess either value.

    Args:
        order_number: The order number given by the customer.
        email_or_phone: The customer's e-mail or phone (with area code, any format).
        tool_context: Injected by the framework.

    Returns:
        {"status": "ok", "order": {...}} with number, date, status, status_label, items
        (name, quantity), total in BRL, payment_method, tracking_code, estimated_delivery,
        note (e.g. cancellation reason), after-sales fields (days_since_delivery,
        withdrawal_eligible, defect_exchange_eligible, legal_warranty_until; all None when
        the order was not delivered) and customer_first_name.
        {"status": "verification_failed"} when the e-mail or phone does not match the order
        (do not reveal anything about it); {"status": "not_found"} when the order does not
        exist; {"status": "error", "message": ...} when the lookup failed.
    """
    try:
        result = _lookup(order_number, email_or_phone)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error("Order lookup failed for order %s: %s", order_number, type(error).__name__)
        return {"status": "error", "message": LOOKUP_ERROR_MESSAGE}
    if result["status"] == "ok":
        order = result["order"]
        _remember_verification(tool_context, order["number"], order["customer_first_name"])
    return result
