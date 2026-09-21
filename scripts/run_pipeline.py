#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.companies import collect_all
from collector.results import is_access_blocked
from collector.types import STATUS_DEGRADED, STATUS_FAILED, SourceResult
from config.settings import seen_gate_enabled
from storage.vacancy_feed import append_feed, load_feed, prune_feed, save_feed
from storage.seen import (
    default_seen_path,
    load_seen,
    mark_seen,
    purge_dead_seen,
    save_seen,
    seen_key,
    seen_roles,
    utc_now,
)
from storage.source_health import (
    classify_degraded,
    default_baseline_path,
    load_baseline,
    save_baseline,
    update_baseline,
)
from storage.telegram_cursors import (
    apply_cursor_updates,
    default_telegram_cursors_path,
    load_telegram_cursors,
    save_telegram_cursors,
)
from integrations.notify import CollectReportStats, SourceFailure
from parser.deduplicate import deduplicate_with_report
from parser.normalize import Vacancy, is_inbox_candidate, normalize_many, role_family_key
from reporter.hourly import notify_hourly_inbox
from reporter.collector_health import label_counts, rejection_counts, safe_error, write_collect_diagnostics


def _is_telegram_source(source: SourceResult) -> bool:
    return source.source_id.startswith("telegram:") or source.source_name.startswith("Telegram @")


def _telegram_channel_label(source: SourceResult) -> str:
    if source.source_id.startswith("telegram:"):
        return source.source_id.split(":", 1)[1]
    if source.source_name.startswith("Telegram @"):
        return source.source_name.removeprefix("Telegram @").strip()
    return source.source_name


def summarize_source_checks(
    source_results: list[SourceResult],
) -> tuple[tuple[str, ...], dict[str, object]]:
    failed_names: list[str] = []
    degraded_names: list[str] = []
    sites_ok = 0
    sites_total = 0
    telegram_ok = 0
    telegram_total = 0
    telegram_skipped = 0
    telegram_skipped_names: list[str] = []
    telegram_ok_names: list[str] = []
    failed_sources: list[SourceFailure] = []
    telegram_cursor_updates: dict[str, int] = {}
    manual_check_sources: list[SourceFailure] = []
    manual_review_roles: list[SourceFailure] = []

    for source in source_results:
        if _is_telegram_source(source):
            telegram_total += 1
            skipped = bool(source.error and "not set" in source.error.lower())
            if source.status == STATUS_FAILED:
                failed_names.append(source.source_name)
                failed_sources.append(
                    SourceFailure(
                        name=source.source_name,
                        url=source.source_url or "",
                        reason=source.error or "unknown error",
                    )
                )
            elif skipped:
                telegram_skipped += 1
                telegram_skipped_names.append(_telegram_channel_label(source))
            elif source.status == STATUS_DEGRADED:
                degraded_names.append(source.source_name)
            else:
                telegram_ok += 1
                telegram_ok_names.append(_telegram_channel_label(source))
                if source.checkpoint is not None:
                    telegram_cursor_updates[_telegram_channel_label(source)] = source.checkpoint
            continue

        sites_total += 1
        manual_review_roles.extend(
            SourceFailure(name=source.source_name, url=role["url"], reason=role["title"])
            for role in source.manual_review
        )
        if source.status == STATUS_FAILED and is_access_blocked(source.error):
            manual_check_sources.append(
                SourceFailure(name=source.source_name, url=source.source_url or "", reason=source.error or "")
            )
        elif source.status == STATUS_FAILED:
            failed_names.append(source.source_name)
            failed_sources.append(
                SourceFailure(
                    name=source.source_name,
                    url=source.source_url or "",
                    reason=source.error or "unknown error",
                )
            )
        elif source.status == STATUS_DEGRADED:
            degraded_names.append(source.source_name)
        else:
            sites_ok += 1

    health = {
        "sites_ok": sites_ok,
        "sites_total": sites_total,
        "telegram_ok": telegram_ok,
        "telegram_total": telegram_total,
        "telegram_skipped": telegram_skipped,
        "telegram_skipped_names": tuple(telegram_skipped_names),
        "telegram_ok_names": tuple(telegram_ok_names),
        "degraded_source_names": tuple(degraded_names),
        "failed_sources": tuple(failed_sources),
        "telegram_cursor_updates": telegram_cursor_updates,
        "manual_check_sources": tuple(manual_check_sources),
        "manual_review_roles": tuple(manual_review_roles),
    }
    return tuple(failed_names), health


def collect_vacancies(
    *,
    baseline_path: Path | None = None,
) -> tuple[list[Vacancy], int, tuple[str, ...], dict[str, object], frozenset[str]]:
    collect_result = collect_all()
    results = collect_result.source_results

    path = baseline_path or default_baseline_path(ROOT)
    baseline = load_baseline(path)
    classify_degraded(results, baseline)
    save_baseline(path, update_baseline(baseline, results))

    raw_jobs: list[dict] = []
    purgeable_companies: set[str] = set()
    for source in results:
        if source.status == STATUS_FAILED:
            print(f"Source failed: {source.source_name}: {source.error}", file=sys.stderr)
            continue
        raw_jobs.extend(source.jobs)
        if _is_telegram_source(source):
            continue
        # A source that parsed nothing cannot prove a vacancy is gone, so its
        # history must survive until the source is healthy again.
        if source.items_scanned <= 0 or source.status == STATUS_DEGRADED:
            continue
        if source.source_id.startswith("company:") or source.source_id.startswith("dou"):
            purgeable_companies.add(source.source_name)

    for source in results:
        if source.status == STATUS_DEGRADED:
            print(f"Source degraded: {source.source_name}: {source.error or 'unspecified'}", file=sys.stderr)

    failed_source_names, health = summarize_source_checks(results)
    vacancies = normalize_many(raw_jobs)
    unique, removed, _ = deduplicate_with_report(vacancies)
    company_sources = [source for source in results if not _is_telegram_source(source)]
    health["company_outage"] = not any(
        source.status != STATUS_FAILED and (source.status != STATUS_DEGRADED or source.items_scanned > 0)
        for source in company_sources
    )
    sources = []
    for source in sorted(results, key=lambda item: item.source_id):
        normalized = normalize_many(source.jobs) if source.status != STATUS_FAILED else []
        sources.append({
            "id": source.source_id, "name": source.source_name, "status": source.status,
            "reason": safe_error(source.error or ""), "scanned": source.items_scanned,
            "skipped": source.items_skipped,
            "raw": len(source.jobs), "normalized": len(normalized),
            "normalization_rejected": len(source.jobs) - len(normalized),
            "inbox_eligible": sum(is_inbox_candidate(item) for item in normalized),
            "rejections": rejection_counts(normalized), "response_ms": source.response_ms,
            "manual_review": list(source.manual_review),
        })
    health["diagnostics"] = {
        "schema_version": 1, "collected_at": utc_now(), "status": "collected",
        "sources": sources,
        "counts": {
            "raw": len(raw_jobs), "normalized": len(vacancies), "unique_roles": len(unique),
            "duplicates_collapsed": removed,
            "inbox_eligible": sum(is_inbox_candidate(item) for item in unique),
        },
        "rejections": rejection_counts(unique),
        "labels": label_counts(unique),
    }
    write_collect_diagnostics(health["diagnostics"])
    return unique, removed, failed_source_names, health, frozenset(purgeable_companies)


def select_fresh(vacancies: list[Vacancy], seen: dict, *, seen_gate: bool) -> list[Vacancy]:
    if not seen_gate:
        return list(vacancies)
    fresh: list[Vacancy] = []
    known_roles = seen_roles(seen)
    for vacancy in vacancies:
        key = seen_key(vacancy)
        # An unknown employer cannot match a role reported under another post.
        role = role_family_key(vacancy.company, vacancy.title) if vacancy.company.strip() else None
        if not key or key in seen or (role is not None and role in known_roles):
            continue
        fresh.append(vacancy)
        if role is not None:
            known_roles.add(role)
    return fresh


def hand_over(fresh: list[Vacancy], *, first_seen: str) -> bool:
    """Append the new vacancies to the downstream feed. The feed is a search
    result, so it exists only when FEED_PATH points into the private store."""
    raw = os.environ.get("FEED_PATH", "").strip()
    if not raw or not fresh:
        return True
    try:
        path = Path(raw)
        feed = load_feed(path)
        append_feed(feed, fresh, first_seen=first_seen)
        prune_feed(feed)
        save_feed(path, feed)
    except (OSError, ValueError) as error:
        print(f"Feed hand-over failed: {type(error).__name__}", file=sys.stderr)
        return False
    return True


def process_new_vacancies(
    vacancies: list[Vacancy],
    seen: dict,
    *,
    seed_only: bool,
    duplicates_removed: int = 0,
    failed_source_names: list[str] | tuple[str, ...] | None = None,
    source_health: dict[str, object] | None = None,
) -> tuple[int, int, bool]:
    now = utc_now()
    failed = tuple(failed_source_names or ())
    health = source_health or {}

    active = [vacancy for vacancy in vacancies if is_inbox_candidate(vacancy)]
    fresh = select_fresh(active, seen, seen_gate=seen_gate_enabled())

    stats = CollectReportStats(
        found=len(active),
        seen_total=len(seen),
        new_count=len(fresh),
        duplicates_removed=duplicates_removed,
        failed_source_names=failed,
        sites_ok=int(health.get("sites_ok", 0) or 0),
        sites_total=int(health.get("sites_total", 0) or 0),
        telegram_ok=int(health.get("telegram_ok", 0) or 0),
        telegram_total=int(health.get("telegram_total", 0) or 0),
        telegram_skipped=int(health.get("telegram_skipped", 0) or 0),
        telegram_skipped_names=tuple(
            str(name) for name in (health.get("telegram_skipped_names") or ())
        ),
        telegram_ok_names=tuple(
            str(name) for name in (health.get("telegram_ok_names") or ())
        ),
        degraded_source_names=tuple(
            str(name) for name in (health.get("degraded_source_names") or ())
        ),
        failed_sources=tuple(health.get("failed_sources") or ()),
        manual_check_sources=tuple(health.get("manual_check_sources") or ()),
        manual_review_roles=tuple(health.get("manual_review_roles") or ()),
    )

    if seed_only:
        marked = sum(mark_seen(seen, vacancy, first_seen=now) for vacancy in fresh)
        return 0, marked, True

    # Order matters: a vacancy is marked seen only after the owner was told and
    # the hand-over succeeded, so a failure at either step is retried next run.
    try:
        notify_hourly_inbox(fresh, stats=stats)
    except Exception as error:
        print(f"Telegram send failed: {safe_error(str(error))}", file=sys.stderr)
        return 0, 0, False
    if not hand_over(fresh, first_seen=now):
        return 0, 0, False

    marked = sum(mark_seen(seen, vacancy, first_seen=now) for vacancy in fresh)
    return len(fresh), marked, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect iOS vacancies, notify, and hand them over.")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Mark current vacancies as seen without hourly alert.",
    )
    args = parser.parse_args()

    seed_only = args.seed_only or os.environ.get("SEED_SEEN_ONLY", "").strip() in {"1", "true", "yes"}
    if not seed_only and os.environ.get("REQUIRE_TELEGRAM_DELIVERY") == "1":
        if not all(os.environ.get(key, "").strip() for key in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")):
            print("Telegram delivery requires TELEGRAM_TOKEN and TELEGRAM_CHAT_ID", file=sys.stderr)
            write_collect_diagnostics({"schema_version": 1, "status": "failed", "error": "incomplete_telegram_configuration"}, summary=True)
            return 1

    seen_path = Path(os.environ.get("SEEN_PATH", default_seen_path(ROOT)))

    started = time.perf_counter()
    seen = load_seen(seen_path)

    vacancies, duplicates_removed, failed_source_names, source_health, purgeable_companies = (
        collect_vacancies()
    )
    live_urls = {seen_key(vacancy) for vacancy in vacancies if seen_key(vacancy)}
    purged = purge_dead_seen(
        seen,
        live_urls=live_urls,
        purgeable_companies=purgeable_companies,
    )
    sent, marked, notify_ok = process_new_vacancies(
        vacancies,
        seen,
        seed_only=seed_only,
        duplicates_removed=duplicates_removed,
        failed_source_names=failed_source_names,
        source_health=source_health,
    )

    if marked or purged:
        save_seen(seen_path, seen)

    cursor_updates = {
        str(channel): int(message_id)
        for channel, message_id in dict(source_health.get("telegram_cursor_updates") or {}).items()
    }
    if notify_ok and cursor_updates:
        cursor_path = default_telegram_cursors_path(ROOT)
        cursors = load_telegram_cursors(cursor_path)
        if apply_cursor_updates(cursors, cursor_updates):
            save_telegram_cursors(cursor_path, cursors)

    runtime = time.perf_counter() - started
    failed = not notify_ok or bool(source_health.get("company_outage"))
    report = dict(source_health.get("diagnostics") or {})
    partial = bool(
        failed_source_names
        or source_health.get("degraded_source_names")
        or source_health.get("telegram_skipped_names")
        or source_health.get("manual_check_sources")
    )
    report["status"] = "failed" if failed else "degraded" if partial else "healthy"
    report["delivery"] = {"handed_over": sent, "notify_ok": notify_ok, "marked_seen": marked}
    report["runtime_seconds"] = round(runtime, 2)
    write_collect_diagnostics(report, summary=True)
    print(
        f"Vacancies: {len(vacancies)}\n"
        f"Duplicates removed: {duplicates_removed}\n"
        f"Sources failed: {len(failed_source_names)}\n"
        f"Dead purged: {len(purged)}\n"
        f"Handed over: {sent}\n"
        f"Newly marked seen: {marked}\n"
        f"Seed only: {seed_only}\n"
        f"Seen total: {len(seen)}\n"
        f"Notify ok: {notify_ok}\n"
        f"Runtime: {runtime:.1f}s"
    )
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
