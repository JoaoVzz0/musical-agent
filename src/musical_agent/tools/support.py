from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from google.adk.tools import ToolContext

from musical_agent.config import current_time, get_settings

logger = logging.getLogger(__name__)

COMPLAINTS_FILENAME = "complaints.jsonl"
PROTOCOL_PREFIX = "RC"
PROTOCOL_DATE_FORMAT = "%Y%m%d"
SEQUENCE_WIDTH = 4
RESPONSE_DEADLINE = "24 horas úteis"
PHONE_DIGIT_RANGE = range(10, 12)
AREA_CODE_LENGTH = 2
VISIBLE_PHONE_SUFFIX = 4
VISIBLE_SUBSCRIBER_PREFIX = 1
MASKABLE_PHONE_MIN_DIGITS = AREA_CODE_LENGTH + VISIBLE_SUBSCRIBER_PREFIX + VISIBLE_PHONE_SUFFIX
MASK_CHAR = "*"
EMAIL_MASK = MASK_CHAR * 3
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NON_DIGITS = re.compile(r"\D")


def _digits_of(contact: str) -> str:
    return NON_DIGITS.sub("", contact)


def _is_email(contact: str) -> bool:
    return bool(EMAIL_PATTERN.match(contact.strip()))


def is_valid_contact(contact: str) -> bool:
    if _is_email(contact):
        return True
    return "@" not in contact and len(_digits_of(contact)) in PHONE_DIGIT_RANGE


def _mask_email(contact: str) -> str:
    local, domain = contact.strip().split("@", 1)
    return f"{local[:1]}{EMAIL_MASK}@{domain}"


def _mask_phone(contact: str) -> str:
    digits = _digits_of(contact)
    area_code = digits[:AREA_CODE_LENGTH]
    subscriber_prefix = digits[AREA_CODE_LENGTH : AREA_CODE_LENGTH + VISIBLE_SUBSCRIBER_PREFIX]
    suffix = digits[-VISIBLE_PHONE_SUFFIX:]
    hidden = MASK_CHAR * (len(digits) - MASKABLE_PHONE_MIN_DIGITS)
    return f"({area_code}) {subscriber_prefix}{hidden}-{suffix}"


def mask_contact(contact: str) -> str:
    if _is_email(contact):
        return _mask_email(contact)
    if len(_digits_of(contact)) >= MASKABLE_PHONE_MIN_DIGITS:
        return _mask_phone(contact)
    return EMAIL_MASK


class ComplaintRegistry:
    def __init__(self, directory: Path, clock: Callable[[], datetime]) -> None:
        self._directory = directory
        self._clock = clock

    @property
    def _file(self) -> Path:
        return self._directory / COMPLAINTS_FILENAME

    def register(self, summary: str, contact: str, order_number: int | None = None) -> dict:
        if not is_valid_contact(contact):
            logger.info("Complaint rejected: invalid contact %s", mask_contact(contact))
            return {"status": "invalid_contact"}
        now = self._clock()
        try:
            protocol = self._next_protocol(now)
            self._append(self._record(protocol, now, summary, contact, order_number))
        except OSError as error:
            logger.error("Complaint storage failed for %s: %s", mask_contact(contact), error)
            return {"status": "error", "message": "Não foi possível registrar a reclamação."}
        logger.info("Complaint %s registered for %s", protocol, mask_contact(contact))
        return {"status": "ok", "protocol": protocol, "response_deadline": RESPONSE_DEADLINE}

    def _next_protocol(self, now: datetime) -> str:
        day_prefix = f"{PROTOCOL_PREFIX}-{now.strftime(PROTOCOL_DATE_FORMAT)}-"
        sequence = self._count_protocols_with_prefix(day_prefix) + 1
        return f"{day_prefix}{sequence:0{SEQUENCE_WIDTH}d}"

    def _count_protocols_with_prefix(self, day_prefix: str) -> int:
        if not self._file.exists():
            return 0
        lines = self._file.read_text(encoding="utf-8").splitlines()
        return sum(1 for line in lines if _protocol_of(line).startswith(day_prefix))

    @staticmethod
    def _record(
        protocol: str, now: datetime, summary: str, contact: str, order_number: int | None
    ) -> dict:
        return {
            "protocol": protocol,
            "created_at": now.isoformat(),
            "summary": summary,
            "contact": contact,
            "order_number": order_number,
        }

    def _append(self, record: dict) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _protocol_of(line: str) -> str:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return ""
    protocol = record.get("protocol") if isinstance(record, dict) else None
    return protocol if isinstance(protocol, str) else ""


def register_complaint(
    summary: str,
    contact: str,
    order_number: int | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Register a customer complaint so the support team can answer it.

    Use only after listening to the complaint with empathy and after the customer has
    given a contact (email or phone with area code). Never use it for simple questions
    about products, orders or policies.

    Args:
        summary: Short description of the complaint in the customer's words.
        contact: Customer email or phone (10 or 11 digits, with area code).
        order_number: Related order number, if the customer mentioned one.
        tool_context: Injected by the framework; not used.

    Returns:
        {"status": "ok", "protocol": "RC-YYYYMMDD-NNNN", "response_deadline": "24 horas úteis"}
        when registered; {"status": "invalid_contact"} when the contact is not a valid email
        or phone (ask the customer again); {"status": "error", "message": ...} when the
        complaint could not be stored.
    """
    registry = ComplaintRegistry(get_settings().support_dir, current_time)
    return registry.register(summary, contact, order_number)
