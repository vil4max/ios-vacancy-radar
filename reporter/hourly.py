"""Telegram digest: a short notice, not a report.

The digest tells the owner that something new was found and whether the run was
healthy. Everything else -- labels in full, descriptions, per-source reasons and
counters -- goes to the hand-over feed and the collection diagnostics, so this
message stays readable on a phone.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from config.schedule import format_next_check_short
from integrations.notify import CollectReportStats
from integrations.telegram import TELEGRAM_MAX_LENGTH, send_message
from parser.normalize import Vacancy, vacancy_title_marks

_KYIV = ZoneInfo("Europe/Kyiv")
_NAMES_SHOWN = 3
_TELEGRAM_CHANNEL_NAMES = frozenset({"telegram", "itrecruit_ua", "remotejobss", "itfreelancers", "mobile_jobs"})


def _clock(now: datetime | None) -> str:
    return (now or datetime.now(_KYIV)).astimezone(_KYIV).strftime("%H:%M")


def _is_telegram_source(name: str) -> bool:
    return name.lower().startswith("telegram")


def _short_list(names: list[str]) -> str:
    shown = ", ".join(names[:_NAMES_SHOWN])
    extra = len(names) - _NAMES_SHOWN
    return f"{shown} (+{extra})" if extra > 0 else shown


def _problem_lines(stats: CollectReportStats) -> list[str]:
    """One line per kind of problem, names only; reasons and URLs are in the
    collection diagnostics artifact."""
    lines: list[str] = []
    sites = [name for name in stats.failed_source_names if not _is_telegram_source(name)]
    if sites:
        lines.append(f"⚠️ Не ответили: {_short_list(sites)}")
    blocked = [source.name for source in stats.manual_check_sources]
    if blocked:
        lines.append(f"🔒 Блокируют автосбор: {_short_list(blocked)}")
    if stats.degraded_source_names:
        lines.append(f"⚠️ Без результата: {_short_list(list(stats.degraded_source_names))}")
    channels = [
        name.removeprefix("Telegram @").removeprefix("Telegram ").strip() or name
        for name in stats.failed_source_names
        if _is_telegram_source(name)
    ]
    if channels:
        lines.append(f"⚠️ Telegram: {_short_list(channels)}")
    return lines


def _status_lines(stats: CollectReportStats, now: datetime | None = None) -> list[str]:
    tail = f"{_clock(now)} · {format_next_check_short(now)}"
    problems = _problem_lines(stats)
    if not problems:
        return [f"🟢 {tail}"]
    return [*problems, f"🕐 {tail}"]


def _new_vacancies_header(total: int) -> str:
    """Title line for new-vacancy alerts: emoji + count + Russian noun form."""
    n = abs(total) % 100
    n1 = n % 10
    if n1 == 1 and n != 11:
        word = "новая вакансия"
    elif 2 <= n1 <= 4 and not (12 <= n <= 14):
        word = "новые вакансии"
    else:
        word = "новых вакансий"
    return f"📬 +{total} {word}"


def _vacancy_label(vacancy: Vacancy) -> str:
    title = vacancy_title_marks(vacancy)
    company = vacancy.company.strip()
    is_telegram = (vacancy.source or "").strip().lower() == "telegram"
    skip_company = is_telegram and (
        company.lower() in _TELEGRAM_CHANNEL_NAMES or company.lower().startswith("telegram @")
    )
    if company and not skip_company:
        return f"{company} — {title}" if title else company
    return title or company or vacancy.url.strip()


def format_hourly_heartbeat(*, stats: CollectReportStats, now: datetime | None = None) -> str:
    status = _status_lines(stats, now)
    if len(status) == 1:
        return f"📭 Новых нет · {status[0]}"
    return "\n".join(["📭 Новых нет", *status])


def format_hourly_new_vacancies(
    vacancies: list[Vacancy],
    *,
    stats: CollectReportStats,
    now: datetime | None = None,
    total_count: int | None = None,
    part: int | None = None,
    parts: int | None = None,
    index_offset: int = 0,
) -> str:
    total = total_count if total_count is not None else len(vacancies)
    header = _new_vacancies_header(total)
    if part is not None and parts is not None and parts > 1:
        header = f"{header} ({part}/{parts})"
    lines = [header]
    for index, vacancy in enumerate(vacancies, start=index_offset + 1):
        lines.append(f"{index}. {_vacancy_label(vacancy)}")
        url = vacancy.url.strip()
        if url:
            lines.append(f"   {url}")
    lines.extend(_status_lines(stats, now))
    return "\n".join(lines)


def _pack_vacancy_batches(
    vacancies: list[Vacancy],
    *,
    stats: CollectReportStats,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[str]:
    if not vacancies:
        return []
    max_len = TELEGRAM_MAX_LENGTH if limit is None else limit
    total = len(vacancies)
    batches: list[list[Vacancy]] = []
    current: list[Vacancy] = []
    offset = 0
    for vacancy in vacancies:
        candidate = current + [vacancy]
        # Size the batch against the widest header it can end up with.
        message = format_hourly_new_vacancies(
            candidate, stats=stats, now=now, total_count=total, part=1, parts=99, index_offset=offset,
        )
        if current and len(message) > max_len:
            batches.append(current)
            offset += len(current)
            current = [vacancy]
        else:
            current = candidate
    if current:
        batches.append(current)

    messages: list[str] = []
    index_offset = 0
    for part_index, batch in enumerate(batches, start=1):
        messages.append(
            format_hourly_new_vacancies(
                batch, stats=stats, now=now, total_count=total,
                part=part_index, parts=len(batches), index_offset=index_offset,
            )
        )
        index_offset += len(batch)
    return messages


def notify_hourly_inbox(
    fresh: list[Vacancy],
    *,
    stats: CollectReportStats,
    now: datetime | None = None,
) -> bool:
    if fresh:
        for message in _pack_vacancy_batches(fresh, stats=stats, now=now):
            send_message(message)
    else:
        send_message(format_hourly_heartbeat(stats=stats, now=now))
    return True
