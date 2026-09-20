from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from integrations.notify import CollectReportStats, SourceFailure
from integrations.telegram import TELEGRAM_MAX_LENGTH
from reporter.hourly import (
    _pack_vacancy_batches,
    format_hourly_heartbeat,
    format_hourly_new_vacancies,
    notify_hourly_inbox,
)
from tests.conftest import make_vacancy

_KYIV = ZoneInfo("Europe/Kyiv")
MORNING = datetime(2026, 7, 28, 11, 2, tzinfo=_KYIV)
EVENING = datetime(2026, 7, 27, 23, 0, tzinfo=_KYIV)


def _stats(**overrides) -> CollectReportStats:
    defaults = dict(found=3, seen_total=3, new_count=0, duplicates_removed=0)
    defaults.update(overrides)
    return CollectReportStats(**defaults)


def test_healthy_heartbeat_is_one_line() -> None:
    assert format_hourly_heartbeat(stats=_stats(), now=EVENING) == "📭 Новых нет · 🟢 23:00 · ⏭ завтра 11:00"


def test_new_vacancies_notice_lists_titles_links_and_one_status_line() -> None:
    vacancies = [
        make_vacancy(company="Acme", title="Senior iOS Engineer", url="https://example.com/jobs/1"),
        make_vacancy(company="Beta", title="iOS Developer", url="https://example.com/jobs/2",
                     location="Limassol, Cyprus", remote="remote"),
    ]

    assert format_hourly_new_vacancies(vacancies, stats=_stats(new_count=2), now=MORNING) == (
        "📬 +2 новые вакансии\n"
        "1. Acme — Senior iOS Engineer\n"
        "   https://example.com/jobs/1\n"
        "2. Beta — ⚠️ iOS Developer\n"
        "   https://example.com/jobs/2\n"
        "🟢 11:02 · ⏭ 15:00"
    )


def test_digest_carries_no_counters_reasons_or_source_urls() -> None:
    # Those belong to the diagnostics artifact; the notice only names what failed.
    stats = _stats(
        failed_source_names=("Acme", "Beta", "Gamma", "Delta", "Telegram @mobile_jobs"),
        failed_sources=(SourceFailure("Acme", "https://acme.example/careers", "HTTP 403"),),
        manual_check_sources=(SourceFailure("Epsilon", "https://epsilon.example", "bot wall"),),
        degraded_source_names=("Zeta",),
        sites_ok=110, sites_total=114,
    )

    message = format_hourly_heartbeat(stats=stats, now=MORNING)

    assert message == (
        "📭 Новых нет\n"
        "⚠️ Не ответили: Acme, Beta, Gamma (+1)\n"
        "🔒 Блокируют автосбор: Epsilon\n"
        "⚠️ Без результата: Zeta\n"
        "⚠️ Telegram: mobile_jobs\n"
        "🕐 11:02 · ⏭ 15:00"
    )
    assert "http" not in message and "403" not in message and "110" not in message


@pytest.mark.parametrize("count,header", [
    (1, "📬 +1 новая вакансия"), (3, "📬 +3 новые вакансии"),
    (5, "📬 +5 новых вакансий"), (11, "📬 +11 новых вакансий"), (21, "📬 +21 новая вакансия"),
])
def test_header_uses_the_russian_noun_form(count: int, header: str) -> None:
    message = format_hourly_new_vacancies([], stats=_stats(), now=MORNING, total_count=count)
    assert message.splitlines()[0] == header


def test_telegram_channel_name_is_not_shown_as_a_company() -> None:
    vacancy = make_vacancy(company="mobile_jobs", source="telegram", title="Senior iOS Engineer")
    message = format_hourly_new_vacancies([vacancy], stats=_stats(), now=MORNING)
    assert "1. Senior iOS Engineer" in message
    assert "mobile_jobs" not in message


def test_pack_vacancy_batches_splits_long_lists() -> None:
    vacancies = [
        make_vacancy(title=f"Senior iOS Engineer {index}", company=f"Company {index}",
                     url=f"https://example.com/jobs/{index}", source="company")
        for index in range(1, 25)
    ]
    messages = _pack_vacancy_batches(vacancies, stats=_stats(new_count=24), limit=400)

    assert len(messages) >= 2
    assert all(len(message) <= TELEGRAM_MAX_LENGTH for message in messages)
    assert messages[0].startswith("📬 +24 новые вакансии (1/")
    assert "1. Company 1 — Senior iOS Engineer 1" in messages[0]
    assert any("24. Company 24 — Senior iOS Engineer 24" in message for message in messages)


def test_notify_sends_packed_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr("reporter.hourly.send_message", sent.append)
    monkeypatch.setattr("reporter.hourly.TELEGRAM_MAX_LENGTH", 350)
    vacancies = [
        make_vacancy(title=f"Role {index}", company=f"Co {index}", url=f"https://example.com/{index}")
        for index in range(1, 21)
    ]

    assert notify_hourly_inbox(vacancies, stats=_stats(new_count=20)) is True
    assert len(sent) >= 2
    assert all(len(message) <= 350 for message in sent)


def test_notify_without_new_vacancies_sends_the_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr("reporter.hourly.send_message", sent.append)

    assert notify_hourly_inbox([], stats=_stats(), now=EVENING)
    assert sent == ["📭 Новых нет · 🟢 23:00 · ⏭ завтра 11:00"]
