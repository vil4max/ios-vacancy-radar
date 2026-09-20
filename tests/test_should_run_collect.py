from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from storage.collect_slots import mark_slot_completed
from scripts import should_run_collect

KYIV = ZoneInfo("Europe/Kyiv")


def test_should_run_collect_skips_when_slot_already_done(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    slots = tmp_path / "collect_slots.json"
    mark_slot_completed(slots, "2026-08-04", 15)
    monkeypatch.setenv("COLLECT_SLOTS_PATH", str(slots))
    monkeypatch.setattr(
        should_run_collect,
        "_as_kyiv",
        lambda now=None: datetime(2026, 8, 4, 15, 30, tzinfo=KYIV),
    )
    monkeypatch.setattr(should_run_collect, "due_collect_slot", lambda now=None: 15)

    assert should_run_collect.main() == 1
    assert "already completed" in capsys.readouterr().out


def test_should_run_collect_runs_when_slot_is_due(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    slots = tmp_path / "collect_slots.json"
    monkeypatch.setenv("COLLECT_SLOTS_PATH", str(slots))
    monkeypatch.setattr(
        should_run_collect,
        "_as_kyiv",
        lambda now=None: datetime(2026, 8, 4, 15, 30, tzinfo=KYIV),
    )
    monkeypatch.setattr(should_run_collect, "due_collect_slot", lambda now=None: 15)

    assert should_run_collect.main() == 0
    out = capsys.readouterr().out
    assert "due_slot=15" in out
    assert "run due slot 15" in out


def test_should_run_collect_skips_before_first_slot(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        should_run_collect,
        "_as_kyiv",
        lambda: datetime(2026, 8, 4, 8, 30, tzinfo=KYIV),
    )

    assert should_run_collect.main() == 1
    assert "before Kyiv 11:00" in capsys.readouterr().out


def test_should_run_collect_reports_read_failure_as_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        should_run_collect,
        "_as_kyiv",
        lambda: datetime(2026, 8, 4, 12, 30, tzinfo=KYIV),
    )

    def unreadable_slots(*args):
        raise PermissionError("cannot read collect slots")

    monkeypatch.setattr(should_run_collect, "slot_completed", unreadable_slots)

    assert should_run_collect.main() == 2
    assert "cannot read collect slots" in capsys.readouterr().err
