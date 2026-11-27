from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace

import pytest

from musical_agent.config import get_settings
from musical_agent.data.loader import load_dataset
from musical_agent.tools.orders import get_order_status

PEDRO_ORDER = 1
PEDRO_EMAIL = "pedro.oliveira@jmail.com"
PEDRO_PHONE_MASKED = "(67) 98432-1098"
PEDRO_PHONE_DIGITS = "67984321098"
LETICIA_ORDER = 7
LETICIA_EMAIL = "leticia.rocha@jmail.com"
SHIPPED_ORDER = 8
SHIPPED_EMAIL = "anacarol.ferreira@coldmail.com"
CANCELLED_ORDER = 17
MISSING_ORDER = 99
WINDOW_FIELDS = (
    "days_since_delivery",
    "withdrawal_eligible",
    "defect_exchange_eligible",
    "legal_warranty_until",
)


@pytest.fixture
def pin_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def pin(moment: str) -> None:
        monkeypatch.setenv("AGENT_NOW", moment)
        get_settings.cache_clear()

    yield pin
    get_settings.cache_clear()


def tool_context() -> SimpleNamespace:
    return SimpleNamespace(state={})


def cancelled_order_email() -> str:
    dataset = load_dataset()
    orders = dataset.orders
    customer_id = orders.loc[orders["order_id"] == CANCELLED_ORDER, "customer_id"].item()
    customers = dataset.customers
    return customers.loc[customers["customer_id"] == customer_id, "email"].item()


@pytest.mark.dod("03.B1")
def test_valid_email_returns_ok_with_order_details() -> None:
    result = get_order_status(PEDRO_ORDER, PEDRO_EMAIL)

    assert result["status"] == "ok"
    assert result["order"]["number"] == PEDRO_ORDER
    assert result["order"]["customer_first_name"] == "Pedro"


@pytest.mark.dod("03.B1")
def test_payload_exposes_no_contact_or_address_data() -> None:
    result = get_order_status(PEDRO_ORDER, PEDRO_EMAIL)

    serialized = repr(result).lower()
    assert PEDRO_EMAIL not in serialized
    assert PEDRO_PHONE_DIGITS not in serialized
    assert "98432" not in serialized
    assert "campo grande" not in serialized
    assert "oliveira" not in serialized
    assert not {"email", "phone", "address", "city", "customer_id"} & set(result["order"])


@pytest.mark.dod("03.B1")
def test_total_comes_from_order_total_and_labels_are_readable() -> None:
    order = get_order_status(PEDRO_ORDER, PEDRO_EMAIL)["order"]

    assert order["total"] == 11499.0
    assert order["status_label"] == "entregue"
    assert order["payment_method"] == "PIX"
    assert order["date"] == "2025-10-15"
    assert order["estimated_delivery"] == "2025-10-25"
    assert order["items"]
    assert all(set(item) == {"name", "quantity"} for item in order["items"])


@pytest.mark.dod("03.B1")
def test_email_is_matched_case_insensitive_and_trimmed() -> None:
    result = get_order_status(PEDRO_ORDER, f"  {PEDRO_EMAIL.upper()} ")

    assert result["status"] == "ok"


@pytest.mark.dod("03.B2")
def test_wrong_email_fails_verification() -> None:
    result = get_order_status(PEDRO_ORDER, "someone.else@jmail.com")

    assert result == {"status": "verification_failed"}


@pytest.mark.dod("03.B2")
def test_other_customers_email_fails_verification() -> None:
    result = get_order_status(PEDRO_ORDER, LETICIA_EMAIL)

    assert result == {"status": "verification_failed"}


@pytest.mark.dod("03.B2")
def test_masked_phone_matches() -> None:
    result = get_order_status(PEDRO_ORDER, PEDRO_PHONE_MASKED)

    assert result["status"] == "ok"


@pytest.mark.dod("03.B2")
def test_phone_with_country_code_matches() -> None:
    result = get_order_status(PEDRO_ORDER, "+55 67 98432-1098")

    assert result["status"] == "ok"


@pytest.mark.dod("03.B2")
def test_empty_contact_fails_verification() -> None:
    result = get_order_status(PEDRO_ORDER, "   ")

    assert result == {"status": "verification_failed"}


@pytest.mark.dod("03.B3")
def test_unknown_order_gets_the_same_answer_as_a_failed_verification() -> None:
    result = get_order_status(MISSING_ORDER, PEDRO_EMAIL)

    assert result == {"status": "verification_failed"}


@pytest.mark.dod("03.B3")
def test_cancelled_order_includes_note() -> None:
    order = get_order_status(CANCELLED_ORDER, cancelled_order_email())["order"]

    assert order["status_label"] == "cancelado"
    assert order["note"] == "Pedido cancelado pelo cliente antes do processamento"


@pytest.mark.dod("03.B3")
def test_order_without_notes_has_no_note() -> None:
    order = get_order_status(PEDRO_ORDER, PEDRO_EMAIL)["order"]

    assert order["note"] is None


@pytest.mark.dod("03.B4")
def test_delivered_order_within_seven_days_allows_withdrawal(
    pin_today: Callable[[str], None],
) -> None:
    pin_today("2026-02-20T10:00:00")

    order = get_order_status(LETICIA_ORDER, LETICIA_EMAIL)["order"]

    assert order["days_since_delivery"] == 3
    assert order["withdrawal_eligible"] is True


@pytest.mark.dod("03.B5")
def test_delivered_order_after_thirty_days_keeps_only_legal_warranty(
    pin_today: Callable[[str], None],
) -> None:
    pin_today("2026-03-25T10:00:00")

    order = get_order_status(LETICIA_ORDER, LETICIA_EMAIL)["order"]

    assert order["withdrawal_eligible"] is False
    assert order["defect_exchange_eligible"] is False
    assert order["legal_warranty_until"] == "2026-05-18"
    assert order["legal_warranty_until"] > "2026-03-25"


@pytest.mark.dod("03.B6")
def test_shipped_order_has_no_after_sales_windows(pin_today: Callable[[str], None]) -> None:
    pin_today("2026-03-25T10:00:00")

    order = get_order_status(SHIPPED_ORDER, SHIPPED_EMAIL)["order"]

    assert order["status_label"] == "a caminho"
    assert order["payment_method"] == "cartão de débito"
    assert all(order[field] is None for field in WINDOW_FIELDS)


@pytest.mark.dod("03.B7")
def test_success_stores_verified_order_and_first_name_in_state() -> None:
    context = tool_context()

    get_order_status(PEDRO_ORDER, PEDRO_EMAIL, context)

    assert context.state == {"verified_order_id": PEDRO_ORDER, "first_name": "Pedro"}
    assert not any(key.startswith("user:") for key in context.state)


@pytest.mark.dod("03.B7")
def test_state_never_holds_email_or_phone() -> None:
    context = tool_context()

    get_order_status(PEDRO_ORDER, PEDRO_PHONE_MASKED, context)

    serialized = repr(context.state)
    assert PEDRO_EMAIL not in serialized
    assert PEDRO_PHONE_DIGITS not in serialized
    assert "98432" not in serialized


@pytest.mark.dod("03.B7")
def test_failed_verification_leaves_state_untouched() -> None:
    context = tool_context()

    get_order_status(PEDRO_ORDER, LETICIA_EMAIL, context)

    assert context.state == {}
