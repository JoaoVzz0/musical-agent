"""Store opening hours (manual section 2): Mon-Fri 09:00-18:00, Sat 09:00-13:00, Sun closed.

Holidays are not modeled: the manual gives no list, so only the weekly schedule is applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

OPENING_TIME = time(9, 0)
WEEKDAY_CLOSING_TIME = time(18, 0)
SATURDAY_CLOSING_TIME = time(13, 0)
SATURDAY = 5
SUNDAY = 6
DAYS_IN_WEEK = 7


@dataclass(frozen=True)
class StoreStatus:
    is_open: bool
    closes_at: datetime | None
    reopens_at: datetime | None


def closing_time(weekday: int) -> time | None:
    if weekday == SUNDAY:
        return None
    return SATURDAY_CLOSING_TIME if weekday == SATURDAY else WEEKDAY_CLOSING_TIME


def _at(day: datetime, moment: time) -> datetime:
    return day.replace(hour=moment.hour, minute=moment.minute, second=0, microsecond=0)


def next_opening(now: datetime) -> datetime:
    if closing_time(now.weekday()) is not None and now.time() < OPENING_TIME:
        return _at(now, OPENING_TIME)
    for days_ahead in range(1, DAYS_IN_WEEK + 1):
        day = now + timedelta(days=days_ahead)
        if closing_time(day.weekday()) is not None:
            return _at(day, OPENING_TIME)
    raise ValueError("The weekly schedule has no opening day")


def store_status(now: datetime) -> StoreStatus:
    closes = closing_time(now.weekday())
    if closes is not None and OPENING_TIME <= now.time() < closes:
        return StoreStatus(is_open=True, closes_at=_at(now, closes), reopens_at=None)
    return StoreStatus(is_open=False, closes_at=None, reopens_at=next_opening(now))
