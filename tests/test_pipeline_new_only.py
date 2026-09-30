from __future__ import annotations

from integrations.notify import CollectReportStats
from parser.normalize import normalize_many
from scripts.run_pipeline import process_new_vacancies
from tests.conftest import make_vacancy


def test_second_identical_run_sends_zero_created(monkeypatch) -> None:
    alerts: list[int] = []

    def fake_hourly(fresh, *, stats, now=None):
        alerts.append(len(fresh))

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    vacancies = normalize_many(
        [
            {
                "company": "Acme",
                "title": "Senior iOS Engineer",
                "url": "https://example.com/jobs/1",
                "source": "test",
            }
        ]
    )
    seen: dict = {}

    sent_count, marked, notify_ok = process_new_vacancies(
        vacancies,
        seen,
        seed_only=False,
        duplicates_removed=2,
        failed_source_names=["DOU Top 50"],
    )
    assert sent_count == 1
    assert marked == 1
    assert notify_ok is True
    assert alerts == [1]

    sent_count_2, marked_2, notify_ok_2 = process_new_vacancies(
        vacancies,
        seen,
        seed_only=False,
        duplicates_removed=2,
        failed_source_names=["DOU Top 50"],
    )
    assert sent_count_2 == 0
    assert marked_2 == 0
    assert notify_ok_2 is True
    assert alerts == [1, 0]


def test_pipeline_excludes_cross_platform_and_foreign_location_from_inbox(monkeypatch) -> None:
    delivered: list[list[str]] = []

    def fake_hourly(fresh, *, stats, now=None):
        delivered.append([vacancy.title for vacancy in fresh])

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)
    vacancies = [
        make_vacancy(title="iOS Developer with Android", location="United States"),
        make_vacancy(title="Senior iOS Engineer", location="Buenos Aires"),
        make_vacancy(title="Senior iOS Engineer", location="Ukraine"),
    ]

    sent, marked, notify_ok = process_new_vacancies(vacancies, {}, seed_only=False)

    assert sent == 1
    assert marked == 1
    assert notify_ok is True
    assert delivered == [["Senior iOS Engineer"]]


def test_seed_only_marks_without_sending(monkeypatch) -> None:
    calls: list[int] = []

    def fake_hourly(fresh, *, stats, now=None):
        calls.append(1)

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    vacancies = [make_vacancy(url="https://example.com/jobs/seed")]
    seen: dict = {}

    sent_count, marked, notify_ok = process_new_vacancies(vacancies, seen, seed_only=True)
    assert sent_count == 0
    assert marked == 1
    assert notify_ok is True
    assert calls == []
    assert "https://example.com/jobs/seed" in seen


def test_same_url_different_description_does_not_recount(monkeypatch) -> None:
    alerts: list[int] = []

    def fake_hourly(fresh, *, stats, now=None):
        alerts.append(len(fresh))

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    first = [make_vacancy(url="https://example.com/jobs/2", description="Old")]
    second = [make_vacancy(url="https://example.com/jobs/2", description="Changed requirements")]
    seen: dict = {}

    process_new_vacancies(first, seen, seed_only=False)
    process_new_vacancies(second, seen, seed_only=False)

    assert alerts == [1, 0]


def test_multiple_new_vacancies_one_hourly_alert(monkeypatch) -> None:
    alerts: list[tuple[int, CollectReportStats]] = []

    def fake_hourly(fresh, *, stats, now=None):
        alerts.append((len(fresh), stats))

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    vacancies = [
        make_vacancy(url="https://example.com/jobs/1", title="Senior iOS Engineer"),
        make_vacancy(url="https://example.com/jobs/2", title="Senior Swift Developer"),
    ]
    seen: dict = {}
    sent, marked, notify_ok = process_new_vacancies(
        vacancies,
        seen,
        seed_only=False,
        duplicates_removed=3,
    )

    assert sent == 2
    assert marked == 2
    assert notify_ok is True
    assert len(alerts) == 1
    assert alerts[0][0] == 2
    assert alerts[0][1] == CollectReportStats(
        found=2,
        seen_total=0,
        new_count=2,
        duplicates_removed=3,
        failed_source_names=(),
    )


def test_no_new_vacancies_still_invokes_notifier(monkeypatch) -> None:
    alerts: list[int] = []

    def fake_hourly(fresh, *, stats, now=None):
        alerts.append(len(fresh))

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    sent, marked, notify_ok = process_new_vacancies([], {}, seed_only=False)
    assert sent == 0
    assert marked == 0
    assert notify_ok is True
    assert alerts == [0]


def test_telegram_notify_failure_returns_notify_ok_false(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", boom)

    sent, marked, notify_ok = process_new_vacancies(
        [make_vacancy(url="https://example.com/jobs/fail")],
        {},
        seed_only=False,
    )
    assert sent == 0
    assert marked == 0
    assert notify_ok is False


def test_degraded_sources_pass_into_hourly_stats(monkeypatch) -> None:
    alerts: list[CollectReportStats] = []

    def fake_hourly(fresh, *, stats, now=None):
        alerts.append(stats)

    monkeypatch.setattr("scripts.run_pipeline.notify_hourly_inbox", fake_hourly)

    process_new_vacancies(
        [],
        {},
        seed_only=False,
        source_health={"degraded_source_names": ("DataArt",), "sites_ok": 11, "sites_total": 12},
    )
    assert alerts[0].degraded_source_names == ("DataArt",)
