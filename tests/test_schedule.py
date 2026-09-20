from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from config.schedule import (
    due_collect_slot,
    due_collect_slot_for_local_kick,
    format_next_check_short,
    is_collect_business_hour,
    next_scheduled_collect,
)

_KYIV = ZoneInfo("Europe/Kyiv")


def test_due_collect_slot_catchup() -> None:
    assert due_collect_slot(datetime(2026, 7, 28, 10, 59, tzinfo=_KYIV)) is None
    assert due_collect_slot(datetime(2026, 7, 28, 11, 0, tzinfo=_KYIV)) == 11
    assert due_collect_slot(datetime(2026, 7, 28, 13, 30, tzinfo=_KYIV)) == 11
    assert due_collect_slot(datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)) == 15
    assert due_collect_slot(datetime(2026, 7, 28, 23, 5, tzinfo=_KYIV)) == 15


def test_due_collect_slot_for_local_kick_waits_lag() -> None:
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 11, 0, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 11, 14, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 11, 15, tzinfo=_KYIV)) == 11
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 15, 14, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 15, 15, tzinfo=_KYIV)) == 15
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 10, 59, tzinfo=_KYIV)) is None


def test_is_collect_business_hour_window() -> None:
    assert is_collect_business_hour(datetime(2026, 7, 28, 2, 0, tzinfo=_KYIV)) is False
    assert is_collect_business_hour(datetime(2026, 7, 28, 11, 0, tzinfo=_KYIV)) is True
    assert is_collect_business_hour(datetime(2026, 7, 28, 13, 30, tzinfo=_KYIV)) is True
    assert is_collect_business_hour(datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)) is True


def test_next_scheduled_collect_before_window() -> None:
    now = datetime(2026, 7, 28, 2, 0, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 28, 11, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ 11:00"


def test_next_scheduled_collect_between_slots() -> None:
    now = datetime(2026, 7, 28, 11, 10, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ 15:00"


def test_next_scheduled_collect_after_window() -> None:
    now = datetime(2026, 7, 28, 15, 5, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 29, 11, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ завтра 11:00"
