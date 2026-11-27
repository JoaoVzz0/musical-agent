from __future__ import annotations

from datetime import date, timedelta

import pytest

from musical_agent.domain.rules import (
    AfterSalesWindows,
    CatalogItem,
    after_sales_windows,
    final_price,
    installment_value,
    is_available,
    max_installments,
    pick_alternatives,
    pix_price,
    to_cents,
)

DELIVERY_DATE = date(2026, 1, 10)


def _days_after_delivery(days: int) -> date:
    return DELIVERY_DATE + timedelta(days=days)


@pytest.mark.dod("02.C1")
def test_max_installments_for_mid_price_item_is_five():
    assert max_installments(429.90) == 5


@pytest.mark.dod("02.C1")
def test_max_installments_for_high_price_item_is_twelve():
    assert max_installments(2199) == 12


@pytest.mark.dod("02.C1")
def test_installment_value_of_twelve_payments_rounds_to_cents():
    assert installment_value(2199, 12) == 183.25


@pytest.mark.dod("02.C2")
def test_three_installments_allowed_at_exactly_fifty():
    assert max_installments(150.00) == 3


@pytest.mark.dod("02.C2")
def test_three_installments_refused_just_below_fifty():
    assert max_installments(149.97) == 2


@pytest.mark.dod("02.C2")
def test_six_installments_allowed_at_exactly_eighty():
    assert max_installments(480.00) == 6


@pytest.mark.dod("02.C2")
def test_six_installments_refused_just_below_eighty():
    assert max_installments(479.94) == 5


@pytest.mark.dod("02.C2")
def test_twelve_installments_allowed_at_exactly_one_hundred():
    assert max_installments(1200.00) == 12


@pytest.mark.dod("02.C2")
def test_twelve_installments_refused_just_below_one_hundred():
    assert max_installments(1199.88) == 11


@pytest.mark.dod("02.C2")
def test_seven_installments_need_one_hundred_even_when_six_qualify():
    assert max_installments(600.00) == 6


@pytest.mark.dod("02.C2")
def test_total_below_fifty_allows_only_single_payment():
    assert max_installments(40.00) == 1


@pytest.mark.dod("02.C2")
def test_total_of_one_hundred_allows_two_installments():
    assert max_installments(100.00) == 2


@pytest.mark.dod("02.C3")
def test_pix_price_applies_five_percent_discount():
    assert pix_price(2199) == 2089.05


@pytest.mark.dod("02.C3")
def test_pix_price_with_explicit_no_promotion_applies_discount():
    assert pix_price(2199, has_promotion=False) == 2089.05


@pytest.mark.dod("02.C3")
def test_pix_not_applied_on_promotional_price():
    assert pix_price(2199, has_promotion=True) is None


@pytest.mark.dod("02.C4")
def test_final_price_applies_discount_percent():
    assert final_price(1000.00, 15) == 850.00


@pytest.mark.dod("02.C4")
def test_final_price_rounds_half_up_to_cents():
    assert final_price(99.99, 15) == 84.99


@pytest.mark.dod("02.C4")
def test_final_price_rounds_half_cent_up():
    assert final_price(0.10, 25) == 0.08


@pytest.mark.dod("02.C4")
def test_final_price_without_discount_keeps_price():
    assert final_price(429.90, None) == 429.90


def test_to_cents_rounds_half_up():
    assert to_cents(2.675) == 2.68


@pytest.mark.dod("02.C5")
def test_item_with_zero_stock_is_unavailable():
    assert is_available(0, "active") is False


@pytest.mark.dod("02.C5")
def test_discontinued_item_is_unavailable():
    assert is_available(5, "discontinued") is False


@pytest.mark.dod("02.C5")
def test_coming_soon_item_is_unavailable():
    assert is_available(5, "coming_soon") is False


@pytest.mark.dod("02.C5")
def test_active_item_in_stock_is_available():
    assert is_available(5, "active") is True


def _item(item_id: int, price: float, category: str = "guitar", available: bool = True):
    return CatalogItem(id=item_id, category=category, price=price, available=available)


@pytest.mark.dod("02.C6")
def test_alternatives_keep_only_same_category():
    target = _item(1, 1000.00)
    candidates = [_item(2, 1000.00, category="drums"), _item(3, 1000.00)]

    result = pick_alternatives(target, candidates)

    assert [item.id for item in result] == [3]


@pytest.mark.dod("02.C6")
def test_alternatives_exclude_unavailable_items():
    target = _item(1, 1000.00)
    candidates = [_item(2, 1000.00, available=False), _item(3, 1000.00)]

    result = pick_alternatives(target, candidates)

    assert [item.id for item in result] == [3]


@pytest.mark.dod("02.C6")
def test_alternatives_include_thirty_percent_price_band_edges():
    target = _item(1, 1000.00)
    candidates = [_item(2, 699.99), _item(3, 700.00), _item(4, 1300.00), _item(5, 1300.01)]

    result = pick_alternatives(target, candidates)

    assert sorted(item.id for item in result) == [3, 4]


@pytest.mark.dod("02.C6")
def test_alternatives_sorted_by_closest_price_first():
    target = _item(1, 1000.00)
    candidates = [_item(2, 1250.00), _item(3, 980.00), _item(4, 900.00)]

    result = pick_alternatives(target, candidates)

    assert [item.id for item in result] == [3, 4, 2]


@pytest.mark.dod("02.C6")
def test_alternatives_capped_at_three():
    target = _item(1, 1000.00)
    candidates = [_item(item_id, 1000.00 + item_id) for item_id in range(2, 8)]

    result = pick_alternatives(target, candidates)

    assert [item.id for item in result] == [2, 3, 4]


@pytest.mark.dod("02.C6")
def test_alternatives_never_include_target():
    target = _item(1, 1000.00)
    candidates = [target, _item(2, 1010.00)]

    result = pick_alternatives(target, candidates)

    assert [item.id for item in result] == [2]


@pytest.mark.dod("02.C7")
def test_withdrawal_eligible_on_day_seven():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(7))

    assert windows.withdrawal_eligible is True


@pytest.mark.dod("02.C7")
def test_withdrawal_not_eligible_on_day_eight():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(8))

    assert windows.withdrawal_eligible is False


@pytest.mark.dod("02.C7")
def test_defect_exchange_eligible_on_day_thirty():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(30))

    assert windows.defect_exchange_eligible is True


@pytest.mark.dod("02.C7")
def test_defect_exchange_not_eligible_on_day_thirty_one():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(31))

    assert windows.defect_exchange_eligible is False


@pytest.mark.dod("02.C7")
def test_legal_warranty_valid_on_day_ninety():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(90))

    assert windows.legal_warranty_valid is True


@pytest.mark.dod("02.C7")
def test_legal_warranty_not_valid_on_day_ninety_one():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(91))

    assert windows.legal_warranty_valid is False


@pytest.mark.dod("02.C7")
def test_legal_warranty_ends_ninety_days_after_delivery():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(10))

    assert windows.legal_warranty_until == date(2026, 4, 10)


@pytest.mark.dod("02.C7")
def test_days_since_delivery_counts_calendar_days():
    windows = after_sales_windows(DELIVERY_DATE, _days_after_delivery(12))

    assert windows.days_since_delivery == 12


@pytest.mark.dod("02.C8")
def test_not_delivered_order_has_no_after_sales_windows():
    windows = after_sales_windows(None, DELIVERY_DATE)

    assert windows == AfterSalesWindows(
        days_since_delivery=None,
        withdrawal_eligible=None,
        defect_exchange_eligible=None,
        legal_warranty_until=None,
        legal_warranty_valid=None,
    )
