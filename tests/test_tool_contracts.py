from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from musical_agent.config import get_settings
from musical_agent.data.loader import load_dataset
from musical_agent.data.policies import load_policy_index
from musical_agent.tools.catalog import get_product_details, search_products
from musical_agent.tools.orders import get_order_status
from musical_agent.tools.policies import search_policies
from musical_agent.tools.support import register_complaint

ToolCall = Callable[[], Any]

INVALID_INPUT_CALLS: dict[str, ToolCall] = {
    "search_unknown_category": lambda: search_products(category="instrumento xyz inexistente"),
    "search_negative_price": lambda: search_products(max_price=-10),
    "search_zero_limit": lambda: search_products(limit=0),
    "search_huge_limit": lambda: search_products(limit=1000),
    "details_empty": lambda: get_product_details(""),
    "details_unknown_id": lambda: get_product_details("999999"),
    "details_symbols": lambda: get_product_details("!!!"),
    "order_zero": lambda: get_order_status(0, ""),
    "order_negative": lambda: get_order_status(-1, "x"),
    "order_empty_contact": lambda: get_order_status(1, ""),
    "order_text_number": lambda: get_order_status("abc", "pedro.oliveira@jmail.com"),
    "policies_empty": lambda: search_policies(""),
    "policies_zero_k": lambda: search_policies("horário", k=0),
    "policies_huge_k": lambda: search_policies("horário", k=100),
    "complaint_empty": lambda: register_complaint("", ""),
    "complaint_bad_contact": lambda: register_complaint("produto chegou quebrado", "abc"),
}

DATA_DEPENDENT_CALLS: dict[str, ToolCall] = {
    "search": lambda: search_products(category="violao"),
    "details": lambda: get_product_details("95"),
    "order": lambda: get_order_status(1, "pedro.oliveira@jmail.com"),
    "policies": lambda: search_policies("horário de funcionamento"),
    "complaint": lambda: register_complaint("produto chegou quebrado", "(67) 99812-3456"),
}


def assert_tool_contract(result: Any) -> None:
    assert isinstance(result, dict)
    assert isinstance(result.get("status"), str)
    json.dumps(result)


def clear_caches() -> None:
    get_settings.cache_clear()
    load_dataset.cache_clear()
    load_policy_index.cache_clear()


@pytest.fixture
def broken_environment(tmp_path, monkeypatch):
    blocked_dir = tmp_path / "not-a-directory"
    blocked_dir.write_text("a file where a directory is expected")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "missing-data"))
    monkeypatch.setenv("SUPPORT_DIR", str(blocked_dir))
    clear_caches()
    yield
    clear_caches()


@pytest.mark.dod("03.X1")
@pytest.mark.parametrize("call", INVALID_INPUT_CALLS.values(), ids=INVALID_INPUT_CALLS.keys())
def test_tool_returns_status_dict_for_invalid_input(call, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DIR", str(tmp_path))
    get_settings.cache_clear()

    result = call()

    assert_tool_contract(result)
    get_settings.cache_clear()


@pytest.mark.dod("03.X1")
@pytest.mark.parametrize("call", DATA_DEPENDENT_CALLS.values(), ids=DATA_DEPENDENT_CALLS.keys())
def test_tool_returns_error_status_when_environment_is_broken(call, broken_environment):
    result = call()

    assert_tool_contract(result)
    assert result["status"] == "error"
