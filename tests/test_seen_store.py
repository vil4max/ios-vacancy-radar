from __future__ import annotations

from pathlib import Path

from storage.seen import (
    load_seen,
    mark_seen,
    purge_dead_seen,
    save_seen,
    seen_key,
)
from tests.conftest import make_vacancy


def test_seen_key_prefers_canonical_url() -> None:
    vacancy = make_vacancy(url="https://Example.com/jobs/1/?utm_source=x")
    assert seen_key(vacancy) == "https://example.com/jobs/1"


def test_mark_seen_persists_and_skips_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    vacancy = make_vacancy()
    seen: dict = {}

    assert mark_seen(seen, vacancy, first_seen="2026-07-10T10:00:00+00:00") is True
    assert mark_seen(seen, vacancy) is False
    save_seen(path, seen)

    reloaded = load_seen(path)
    assert seen_key(vacancy) in reloaded
    assert reloaded[seen_key(vacancy)]["title"] == vacancy.title
    assert reloaded[seen_key(vacancy)]["company"] == vacancy.company


def test_seen_store_never_persists_application_decisions(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text(
        '{"https://example.com/jobs/drop": {"title": "iOS", "company": "Acme", '
        '"first_seen": "2026-07-01T00:00:00+00:00", "disposition": "dropped", "applied_at": "2026-07-02"}}',
        encoding="utf-8",
    )
    seen = load_seen(path)
    assert seen == {"https://example.com/jobs/drop": {
        "title": "iOS", "company": "Acme", "first_seen": "2026-07-01T00:00:00+00:00"}}
    seen["https://example.com/jobs/drop"]["disposition"] = "applied"
    save_seen(path, seen)
    text = path.read_text(encoding="utf-8")
    assert "disposition" not in text and "applied_at" not in text
    assert mark_seen(seen, make_vacancy(url="https://example.com/jobs/drop")) is False


def test_purge_dead_seen_removes_only_missing_for_purgeable_companies() -> None:
    seen = {
        "https://example.com/epam/live": {
            "title": "Senior iOS",
            "company": "EPAM",
            "first_seen": "2026-07-01T00:00:00+00:00",
        },
        "https://example.com/epam/dead": {
            "title": "Middle iOS",
            "company": "EPAM",
            "first_seen": "2026-07-01T00:00:00+00:00",
        },
        "https://example.com/softserve/old": {
            "title": "iOS Engineer",
            "company": "SoftServe",
            "first_seen": "2026-07-01T00:00:00+00:00",
        },
    }
    removed = purge_dead_seen(
        seen,
        live_urls={"https://example.com/epam/live"},
        purgeable_companies={"EPAM"},
        confirmed_closed_urls={"https://example.com/epam/dead"},
    )
    assert removed == ["https://example.com/epam/dead"]
    assert "https://example.com/epam/live" in seen
    assert "https://example.com/softserve/old" in seen
    assert "https://example.com/epam/dead" not in seen


def test_partial_listing_never_erases_history() -> None:
    seen = {}
    for name in ("closed", "live"):
        mark_seen(seen, make_vacancy(url=f"https://example.com/{name}"))
    assert purge_dead_seen(seen, live_urls=set(), purgeable_companies={"Acme"}) == []
    assert len(seen) == 2
    removed = purge_dead_seen(seen, live_urls={"https://example.com/live"}, purgeable_companies={"Acme"},
                              confirmed_closed_urls={"https://example.com/closed"})
    assert removed == ["https://example.com/closed"]
    assert list(seen) == ["https://example.com/live"]
