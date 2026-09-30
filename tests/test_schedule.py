from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config.schedule import (
    COLLECT_HOURS,
    due_collect_slot,
    due_collect_slot_for_local_kick,
    format_next_check_short,
    is_collect_business_hour,
    next_scheduled_collect,
)

_KYIV = ZoneInfo("Europe/Kyiv")


def test_due_collect_slot_catchup() -> None:
    assert due_collect_slot(datetime(2026, 7, 28, 5, 59, tzinfo=_KYIV)) is None
    assert due_collect_slot(datetime(2026, 7, 28, 6, 0, tzinfo=_KYIV)) == 6
    assert due_collect_slot(datetime(2026, 7, 28, 13, 30, tzinfo=_KYIV)) == 6
    assert due_collect_slot(datetime(2026, 7, 28, 14, 59, tzinfo=_KYIV)) == 6
    assert due_collect_slot(datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)) == 15
    assert due_collect_slot(datetime(2026, 7, 28, 23, 5, tzinfo=_KYIV)) == 15


def test_due_collect_slot_for_local_kick_waits_lag() -> None:
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 6, 0, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 6, 14, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 6, 15, tzinfo=_KYIV)) == 6
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 15, 14, tzinfo=_KYIV)) is None
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 15, 15, tzinfo=_KYIV)) == 15
    assert due_collect_slot_for_local_kick(datetime(2026, 7, 28, 5, 59, tzinfo=_KYIV)) is None


def test_is_collect_business_hour_window() -> None:
    assert is_collect_business_hour(datetime(2026, 7, 28, 2, 0, tzinfo=_KYIV)) is False
    assert is_collect_business_hour(datetime(2026, 7, 28, 6, 0, tzinfo=_KYIV)) is True
    assert is_collect_business_hour(datetime(2026, 7, 28, 13, 30, tzinfo=_KYIV)) is True
    assert is_collect_business_hour(datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)) is True


def test_next_scheduled_collect_before_window() -> None:
    now = datetime(2026, 7, 28, 2, 0, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 28, 6, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ 06:00"


def test_next_scheduled_collect_between_slots() -> None:
    now = datetime(2026, 7, 28, 6, 10, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 28, 15, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ 15:00"


def test_next_scheduled_collect_after_window() -> None:
    now = datetime(2026, 7, 28, 15, 5, tzinfo=_KYIV)
    assert next_scheduled_collect(now) == datetime(2026, 7, 29, 6, 0, tzinfo=_KYIV)
    assert format_next_check_short(now) == "⏭ завтра 06:00"


def test_trigger_cron_band_covers_every_slot_in_summer_and_winter_time() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/hourly-trigger.yml"
    match = re.search(r'cron: "(\d+) (\d+)-(\d+) \* \* \*"', workflow.read_text(encoding="utf-8"))
    assert match, "hourly-trigger.yml must keep a single hourly cron band"
    _, first, last = (int(value) for value in match.groups())
    # July is EEST (UTC+3), January is EET (UTC+2).
    for month in (7, 1):
        for hour in COLLECT_HOURS:
            slot_utc = datetime(2026, month, 15, hour, 0, tzinfo=_KYIV).astimezone(timezone.utc)
            assert first <= slot_utc.hour <= last, (month, hour)
