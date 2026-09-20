from datetime import datetime
from zoneinfo import ZoneInfo

from storage.collect_slots import mark_slot_completed, load_collect_slots
from planner.collect_health import overdue_slots
from scripts import should_kick_collect, mark_collect_slot

KYIV = ZoneInfo('Europe/Kyiv')


def test_overdue_only_after_grace_and_not_completed(tmp_path):
    path = tmp_path / 'slots.json'
    assert overdue_slots(path, datetime(2026, 9, 9, 11, 14, tzinfo=KYIV)) == []
    assert overdue_slots(path, datetime(2026, 9, 9, 11, 15, tzinfo=KYIV)) == [11]
    mark_slot_completed(path, '2026-09-09', 11)
    assert overdue_slots(path, datetime(2026, 9, 9, 15, 30, tzinfo=KYIV)) == [15]


def test_kick_errors_are_not_normal_skips(monkeypatch):
    def broken():
        raise ValueError('corrupt slot history')
    monkeypatch.setattr(should_kick_collect, '_evaluate_gate', broken)
    assert should_kick_collect.main() == 2


def test_kick_does_not_dispatch_overnight(monkeypatch, tmp_path):
    monkeypatch.setenv('COLLECT_SLOTS_PATH', str(tmp_path / 'slots.json'))
    monkeypatch.setattr(should_kick_collect, '_as_kyiv', lambda: datetime(2026, 9, 9, 22, 0, tzinfo=KYIV))
    assert should_kick_collect.main() == 1


def test_slow_collect_marks_start_slot_not_finish_slot(monkeypatch, tmp_path):
    path = tmp_path / 'slots.json'
    monkeypatch.setenv('COLLECT_SLOTS_PATH', str(path))
    monkeypatch.setenv('COLLECT_STARTED_AT', '2026-09-09T08:58:00Z')
    assert mark_collect_slot.main() == 0
    assert load_collect_slots(path)['days']['2026-09-09']['slots'] == [11]


def test_label_counts_describe_handed_over_vacancies_only() -> None:
    from reporter.collector_health import label_counts
    from tests.conftest import make_vacancy

    vacancies = [
        make_vacancy(title="Senior iOS Engineer", location="Bengaluru, India", remote="onsite"),
        make_vacancy(title="Junior iOS Engineer", location="Limassol, Cyprus", remote="remote"),
        make_vacancy(title="Senior Backend Engineer", location=None, remote="unknown"),
    ]

    # An office abroad is not workable and needs no check; the off-topic role is
    # not handed over, so it is not counted at all.
    assert label_counts(vacancies) == {
        "not_workable_from_kyiv": 1,
        "junior": 1,
        "location_needs_check": 1,
    }
