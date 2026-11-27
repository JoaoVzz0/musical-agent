from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from musical_agent.tools import support
from musical_agent.tools.support import (
    ComplaintRegistry,
    is_valid_contact,
    mask_contact,
    register_complaint,
)

CAMPO_GRANDE = ZoneInfo("America/Campo_Grande")
FIXED_NOW = datetime(2026, 3, 25, 10, 30, tzinfo=CAMPO_GRANDE)
EMAIL = "pedro.oliveira@jmail.com"
PHONE = "(67) 99812-3456"
SUMMARY = "Violão chegou com o tampo rachado."
PROTOCOL_PATTERN = re.compile(r"^RC-\d{8}-\d{4}$")


def fixed_clock() -> datetime:
    return FIXED_NOW


def complaints_file(directory: Path) -> Path:
    return directory / "complaints.jsonl"


def read_lines(directory: Path) -> list[dict]:
    content = complaints_file(directory).read_text(encoding="utf-8")
    return [json.loads(line) for line in content.splitlines()]


@pytest.fixture
def registry(tmp_path: Path) -> ComplaintRegistry:
    return ComplaintRegistry(tmp_path / "support", fixed_clock)


@pytest.mark.dod("03.D1")
def test_valid_email_returns_protocol_and_deadline(registry):
    result = registry.register(SUMMARY, EMAIL, order_number=1001)

    assert result == {
        "status": "ok",
        "protocol": "RC-20260325-0001",
        "response_deadline": "24 horas úteis",
    }


@pytest.mark.dod("03.D1")
def test_valid_contact_writes_one_json_line_with_all_fields(registry, tmp_path):
    registry.register(SUMMARY, PHONE, order_number=1001)

    lines = read_lines(tmp_path / "support")
    assert lines == [
        {
            "protocol": "RC-20260325-0001",
            "created_at": FIXED_NOW.isoformat(),
            "summary": SUMMARY,
            "contact": PHONE,
            "order_number": 1001,
        }
    ]


@pytest.mark.dod("03.D1")
def test_protocol_sequence_increments_within_the_same_day(registry):
    registry.register(SUMMARY, EMAIL)

    second = registry.register(SUMMARY, PHONE)

    assert second["protocol"] == "RC-20260325-0002"


@pytest.mark.dod("03.D1")
def test_protocol_sequence_restarts_on_a_new_day(tmp_path):
    directory = tmp_path / "support"
    ComplaintRegistry(directory, fixed_clock).register(SUMMARY, EMAIL)
    next_day = ComplaintRegistry(directory, lambda: datetime(2026, 3, 26, 9, tzinfo=CAMPO_GRANDE))

    result = next_day.register(SUMMARY, EMAIL)

    assert result["protocol"] == "RC-20260326-0001"


@pytest.mark.dod("03.D1")
def test_order_number_is_optional_and_stored_as_null(registry, tmp_path):
    registry.register(SUMMARY, EMAIL)

    assert read_lines(tmp_path / "support")[0]["order_number"] is None


@pytest.mark.dod("03.D2")
@pytest.mark.parametrize(
    "contact", ["", "pedro", "pedro@", "@jmail.com", "123456789", "6799812345678"]
)
def test_invalid_contact_returns_invalid_contact(registry, contact):
    result = registry.register(SUMMARY, contact)

    assert result == {"status": "invalid_contact"}


@pytest.mark.dod("03.D2")
def test_invalid_contact_writes_nothing(registry, tmp_path):
    registry.register(SUMMARY, "não tenho")

    assert not complaints_file(tmp_path / "support").exists()


@pytest.mark.parametrize("contact", [EMAIL, PHONE, "6733334444", "67 3333-4444"])
def test_is_valid_contact_accepts_email_and_phone(contact):
    assert is_valid_contact(contact)


def test_mask_contact_hides_email_local_part():
    assert mask_contact(EMAIL) == "p***@jmail.com"


def test_mask_contact_keeps_area_code_and_last_four_digits_of_phone():
    assert mask_contact(PHONE) == "(67) 9****-3456"


@pytest.mark.dod("03.D3")
@pytest.mark.parametrize("contact", [EMAIL, PHONE])
def test_logs_never_contain_full_contact(registry, caplog, contact):
    caplog.set_level(logging.DEBUG)

    registry.register(SUMMARY, contact)

    assert caplog.records
    assert contact not in caplog.text
    assert mask_contact(contact) in caplog.text


@pytest.mark.dod("03.D3")
def test_invalid_contact_is_not_logged_in_full(registry, caplog):
    caplog.set_level(logging.DEBUG)

    registry.register(SUMMARY, "pedro@")

    assert "pedro@" not in caplog.text


def test_write_failure_returns_error_instead_of_raising(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    registry = ComplaintRegistry(blocker / "support", fixed_clock)

    result = registry.register(SUMMARY, EMAIL)

    assert result["status"] == "error"
    assert result["message"]


@pytest.mark.dod("03.D1")
def test_register_complaint_adapter_writes_to_configured_support_dir(monkeypatch, tmp_path):
    settings = SimpleNamespace(support_dir=tmp_path / "var")
    monkeypatch.setattr(support, "get_settings", lambda: settings)
    monkeypatch.setattr(support, "current_time", fixed_clock)

    result = register_complaint(SUMMARY, EMAIL, order_number=1001, tool_context=None)

    assert PROTOCOL_PATTERN.match(result["protocol"])
    assert read_lines(tmp_path / "var")[0]["contact"] == EMAIL


def test_register_complaint_docstring_guides_the_model():
    doc = register_complaint.__doc__ or ""

    assert "contact" in doc.lower()
    assert "protocol" in doc.lower()
    assert "simple questions" in doc.lower()
