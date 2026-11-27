from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from musical_agent.config import current_time
from musical_agent.domain.store_hours import store_status

INSTRUCTION_PATH = Path(__file__).with_name("instruction.md")
INSTRUCTION_MARKER = "LIA-INSTRUCTIONS-V1"
PROTECTED_MARKERS = (
    INSTRUCTION_MARKER,
    "TOOL ROUTING RULES",
    "BUSINESS RULES (SOURCE OF TRUTH)",
)

WEEKDAYS_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

STATIC_INSTRUCTION = INSTRUCTION_PATH.read_text(encoding="utf-8")


class StateContext(Protocol):
    @property
    def state(self) -> Mapping[str, Any]: ...


def format_datetime(moment: datetime) -> str:
    return f"{WEEKDAYS_PT[moment.weekday()]}, {moment:%d/%m/%Y %H:%M}"


def store_status_line(now: datetime) -> str:
    status = store_status(now)
    if status.is_open and status.closes_at is not None:
        return f"The store is OPEN now and closes at {status.closes_at:%H:%M}."
    reopens = status.reopens_at
    weekday = WEEKDAYS_PT[reopens.weekday()] if reopens else ""
    return (
        f"The store is CLOSED now and reopens {weekday}, {reopens:%d/%m} às {reopens:%H:%M}. "
        "If the customer asks for in-store service, say when it reopens."
    )


def known_facts(state: Mapping[str, Any]) -> list[str]:
    facts = []
    if state.get("user:first_name"):
        facts.append(f"The customer's first name is {state['user:first_name']}.")
    if state.get("verified_order_id"):
        facts.append(f"Identity already verified for order {state['verified_order_id']}.")
    if state.get("last_viewed_product_id"):
        facts.append(f"Last product discussed: id {state['last_viewed_product_id']}.")
    return facts


def build_instruction(context: StateContext) -> str:
    """ADK instruction provider: static rules plus per-turn date, store hours and state."""
    now = current_time()
    lines = [
        "## CURRENT CONTEXT",
        f"- Now: {format_datetime(now)} (America/Campo_Grande).",
        f"- {store_status_line(now)}",
        *(f"- {fact}" for fact in known_facts(context.state)),
    ]
    return f"{STATIC_INSTRUCTION}\n" + "\n".join(lines) + "\n"
