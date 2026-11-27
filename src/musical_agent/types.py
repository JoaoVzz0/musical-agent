from __future__ import annotations

from typing import TypedDict


class ProductSummary(TypedDict):
    id: int
    name: str
    category: str
    original_price: float
    final_price: float
    discount_percent: float | None
    promotion: str | None
    stock: int
    available: bool


class ProductDetail(ProductSummary):
    description: str
    specs: dict[str, str]
    catalog_status: str
    pix_price: float | None
    max_installments: int
    installment_value: float


class OrderItem(TypedDict):
    name: str
    quantity: int


class OrderDetail(TypedDict):
    number: int
    date: str
    status: str
    status_label: str
    items: list[OrderItem]
    total: float
    payment_method: str
    tracking_code: str | None
    estimated_delivery: str | None
    note: str | None
    days_since_delivery: int | None
    withdrawal_eligible: bool | None
    defect_exchange_eligible: bool | None
    legal_warranty_until: str | None
    customer_first_name: str


class PolicyPassage(TypedDict):
    section: str
    title: str
    text: str
    score: float
