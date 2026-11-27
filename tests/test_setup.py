from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from musical_agent import types
from musical_agent.config import PROJECT_ROOT, Settings, current_time

CAMPO_GRANDE = ZoneInfo("America/Campo_Grande")


def keys_of(typed_dict: type) -> set[str]:
    return set(typed_dict.__required_keys__) | set(typed_dict.__optional_keys__)


@pytest.mark.dod("01.X2")
def test_settings_defaults_without_env_file(monkeypatch):
    for name in ("MODEL", "MAX_LLM_CALLS_PER_TURN", "AGENT_NOW", "SESSION_DB_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.model == "gemini-3.5-flash-lite"
    assert settings.max_llm_calls_per_turn == 6
    assert settings.max_message_chars == 2000
    assert settings.agent_now is None
    assert settings.session_db_url == f"sqlite+aiosqlite:///{PROJECT_ROOT / 'var' / 'sessions.db'}"
    assert settings.data_dir == PROJECT_ROOT / "data"
    assert settings.support_dir == PROJECT_ROOT / "var"


@pytest.mark.dod("01.X2")
def test_settings_read_overrides_from_env(monkeypatch):
    monkeypatch.setenv("MODEL", "gemini-test")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_TURN", "3")
    monkeypatch.setenv("AGENT_NOW", "2026-03-25T10:00:00-04:00")

    settings = Settings(_env_file=None)

    assert settings.model == "gemini-test"
    assert settings.max_llm_calls_per_turn == 3
    assert settings.agent_now == datetime(2026, 3, 25, 10, 0, tzinfo=CAMPO_GRANDE)


def test_current_time_uses_agent_now_when_set():
    settings = Settings(_env_file=None, agent_now="2026-02-20T09:30:00")

    assert current_time(settings) == datetime(2026, 2, 20, 9, 30, tzinfo=CAMPO_GRANDE)


def test_current_time_falls_back_to_clock_in_store_timezone():
    settings = Settings(_env_file=None, agent_now=None)

    now = current_time(settings)

    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now(CAMPO_GRANDE).utcoffset()


@pytest.mark.dod("01.X3")
def test_product_contracts_match_spec():
    summary = {
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
    detail_extra = {
        "description",
        "specs",
        "catalog_status",
        "pix_price",
        "max_installments",
        "installment_value",
    }

    assert keys_of(types.ProductSummary) == summary
    assert keys_of(types.ProductDetail) == summary | detail_extra


@pytest.mark.dod("01.X3")
def test_order_contract_matches_spec():
    expected = {
        "number",
        "date",
        "status",
        "status_label",
        "items",
        "total",
        "payment_method",
        "tracking_code",
        "estimated_delivery",
        "note",
        "days_since_delivery",
        "withdrawal_eligible",
        "defect_exchange_eligible",
        "legal_warranty_until",
        "customer_first_name",
    }

    assert keys_of(types.OrderDetail) == expected
    assert keys_of(types.OrderItem) == {"name", "quantity"}


@pytest.mark.dod("01.X3")
def test_policy_passage_contract_matches_spec():
    assert keys_of(types.PolicyPassage) == {"section", "title", "text", "score"}


@pytest.mark.dod("01.X4")
@pytest.mark.parametrize(
    "file_name",
    [
        "products.csv",
        "categories.csv",
        "customers.csv",
        "orders.csv",
        "order_items.csv",
        "promotions.csv",
        "store_policies.pdf",
    ],
)
def test_challenge_file_is_in_data_dir(file_name):
    assert (PROJECT_ROOT / "data" / file_name).is_file()


def is_git_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.dod("01.X5")
@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "deploy.pem",
        "gcp-credentials.json",
        "my-service-account.json",
        "sessions.db",
        "var/complaints.jsonl",
        ".adk/session.db",
        "evals/.cache/embeddings.npy",
        "challenge/data/products.csv",
        "HOW_TO_USE.md",
    ],
)
def test_sensitive_or_local_path_is_git_ignored(path):
    assert is_git_ignored(path)


@pytest.mark.dod("01.X5")
@pytest.mark.parametrize(
    "path", [".env.example", "data/products.csv", "src/musical_agent/config.py"]
)
def test_deliverable_path_is_not_git_ignored(path):
    assert not is_git_ignored(path)


def test_project_root_points_to_repository():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert isinstance(PROJECT_ROOT, Path)


@pytest.mark.dod("01.X3")
def test_agent_reply_contract_matches_respond_signature():
    record = types.ToolCallRecord(name="search_products", args={"category": "violao"}, response={})
    reply = types.AgentReply(
        text="Oi!",
        tools_called=["search_products"],
        tool_calls=[record],
        tokens=120,
        latency_ms=850,
        blocked=False,
    )

    assert reply.tool_calls[0].name == "search_products"
    assert reply.tools_called == ["search_products"]
    assert not reply.blocked
