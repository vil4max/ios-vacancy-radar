from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import mark_collect_slot

KYIV = ZoneInfo("Europe/Kyiv")


def test_mark_collect_slot_marks_the_due_slot(tmp_path: Path, monkeypatch) -> None:
    slots = tmp_path / "collect_slots.json"
    output = tmp_path / "github_output.txt"
    monkeypatch.setenv("COLLECT_SLOTS_PATH", str(slots))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        mark_collect_slot,
        "_as_kyiv",
        lambda now=None: datetime(2026, 8, 4, 15, 20, tzinfo=KYIV),
    )

    assert mark_collect_slot.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "marked_slot=15" in text
    assert "kyiv_day=2026-08-04" in text


def test_mark_collect_slot_no_due_slot_before_window(tmp_path: Path, monkeypatch) -> None:
    slots = tmp_path / "collect_slots.json"
    output = tmp_path / "github_output.txt"
    monkeypatch.setenv("COLLECT_SLOTS_PATH", str(slots))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        mark_collect_slot,
        "_as_kyiv",
        lambda now=None: datetime(2026, 8, 4, 5, 0, tzinfo=KYIV),
    )

    assert mark_collect_slot.main() == 0
    text = output.read_text(encoding="utf-8")
    assert "marked_slot=" in text
    assert "marked_slot=11" not in text
    assert "marked_slot=15" not in text
