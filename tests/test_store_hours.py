from __future__ import annotations

from datetime import datetime

import pytest

from musical_agent.config import STORE_TIMEZONE
from musical_agent.domain.store_hours import store_status


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=STORE_TIMEZONE)


WEDNESDAY, SATURDAY, SUNDAY = 25, 28, 29


@pytest.mark.dod("04.A4")
def test_weekday_morning_is_open_until_six_pm():
    status = store_status(at(WEDNESDAY, 10))

    assert status.is_open
    assert status.closes_at == at(WEDNESDAY, 18)
    assert status.reopens_at is None


@pytest.mark.dod("04.A4")
def test_weekday_evening_is_closed_and_reopens_next_morning():
    status = store_status(at(WEDNESDAY, 19))

    assert not status.is_open
    assert status.reopens_at == at(26, 9)


@pytest.mark.dod("04.A4")
def test_weekday_before_opening_reopens_same_day():
    status = store_status(at(WEDNESDAY, 8, 30))

    assert not status.is_open
    assert status.reopens_at == at(WEDNESDAY, 9)


@pytest.mark.dod("04.A4")
def test_saturday_noon_is_open_until_one_pm():
    status = store_status(at(SATURDAY, 12))

    assert status.is_open
    assert status.closes_at == at(SATURDAY, 13)


@pytest.mark.dod("04.A4")
def test_saturday_afternoon_is_closed_and_reopens_monday():
    status = store_status(at(SATURDAY, 14))

    assert not status.is_open
    assert status.reopens_at == at(30, 9)


@pytest.mark.dod("04.A4")
def test_sunday_is_closed_and_reopens_monday():
    status = store_status(at(SUNDAY, 11))

    assert not status.is_open
    assert status.reopens_at == at(30, 9)


@pytest.mark.dod("04.A4")
def test_closing_time_itself_counts_as_closed():
    status = store_status(at(WEDNESDAY, 18))

    assert not status.is_open
