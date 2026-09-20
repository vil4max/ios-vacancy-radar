from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from storage.vacancy_feed import append_feed, load_feed, prune_feed, save_feed
from scripts import run_pipeline
from scripts import runtime_state as state
from tests.conftest import make_vacancy

NOW = "2026-09-20T09:00:00+00:00"


def test_feed_entry_carries_labels_and_plain_text(tmp_path) -> None:
    vacancy = make_vacancy(
        title="Junior iOS Engineer",
        url="https://acme.example/jobs/1",
        location="Remote, US",
        remote="remote",
        description="<p>Requirements</p><ul><li>Must be authorized to work in the United States</li></ul>",
    )
    feed = load_feed(tmp_path / "missing.json")

    assert append_feed(feed, [vacancy], first_seen=NOW) == 1
    # The same vacancy is handed over once.
    assert append_feed(feed, [vacancy], first_seen=NOW) == 0

    entry = feed["vacancies"]["https://acme.example/jobs/1"]
    assert entry["labels"]["junior"] is True
    assert entry["labels"]["location_needs_check"] is True
    assert entry["labels"]["work_authorization"] == ["local work authorization required"]
    assert entry["labels"]["level"] == "junior"
    assert "<" not in entry["description"]
    assert entry["description_truncated"] is False
    assert entry["language"] == "en"
    assert entry["first_seen"] == NOW


def test_role_key_groups_one_role_across_sources_and_truncation_is_flagged(tmp_path) -> None:
    feed = load_feed(tmp_path / "missing.json")
    long_text = "Swift and SwiftUI experience. " * 400
    append_feed(feed, [
        make_vacancy(title="Senior iOS Engineer", url="https://acme.example/jobs/a", description=long_text),
        make_vacancy(title="Sr. iOS Developer (Payments)", url="https://board.example/acme/b"),
    ], first_seen=NOW)

    first, second = feed["vacancies"].values()
    # Seniority spelling, Developer vs Engineer and a team qualifier are one role.
    assert first["role_key"] == second["role_key"]
    assert first["description_truncated"] is True and len(first["description"]) == 6000


@pytest.mark.parametrize("title,level", [
    ("Senior iOS Engineer", "senior"), ("Sr. iOS Developer", "senior"),
    ("Lead iOS Engineer", "lead"), ("iOS Tech Lead", "lead"), ("iOS Architect", "lead"),
    ("Senior Staff iOS Engineer", "staff"), ("Principal iOS Engineer", "principal"),
    ("Middle iOS Developer", "middle"), ("Trainee iOS Developer", "junior"),
    ("iOS Developer", "unknown"), ("Leading-edge iOS Developer", "unknown"),
])
def test_title_level(title: str, level: str) -> None:
    from parser.normalize import title_level

    assert title_level(title) == level


def test_feed_round_trips_and_prunes_old_entries(tmp_path) -> None:
    path = tmp_path / "feed.json"
    feed = load_feed(path)
    old = (datetime(2026, 9, 20, tzinfo=timezone.utc) - timedelta(days=45)).isoformat()
    append_feed(feed, [make_vacancy(url="https://acme.example/jobs/old")], first_seen=old)
    append_feed(feed, [make_vacancy(url="https://acme.example/jobs/new")], first_seen=NOW)

    assert prune_feed(feed, now=datetime(2026, 9, 20, 12, tzinfo=timezone.utc)) == 1
    save_feed(path, feed)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    assert list(stored["vacancies"]) == ["https://acme.example/jobs/new"]


def test_hand_over_is_a_no_op_without_a_private_feed_path(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FEED_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    assert run_pipeline.hand_over([make_vacancy()], first_seen=NOW)
    assert not list(tmp_path.rglob("*.json")), "no feed may appear outside the private store"


def test_hand_over_writes_the_feed_and_reports_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "state" / "database" / "vacancy_feed.json"
    monkeypatch.setenv("FEED_PATH", str(path))
    assert run_pipeline.hand_over([make_vacancy(url="https://acme.example/jobs/2")], first_seen=NOW)
    assert "https://acme.example/jobs/2" in json.loads(path.read_text(encoding="utf-8"))["vacancies"]

    # An unreadable feed must fail the hand-over so the vacancies are retried.
    path.write_text("not json", encoding="utf-8")
    assert not run_pipeline.hand_over([make_vacancy(url="https://acme.example/jobs/3")], first_seen=NOW)


@pytest.mark.parametrize("path", ["database/vacancy_feed.json", "database/seen.json"])
def test_search_results_cannot_be_published_in_the_public_checkout(tmp_path, path) -> None:
    with pytest.raises(ValueError, match="separate --root store"):
        state.validate_paths([path], root=tmp_path, work=tmp_path)
    state.validate_paths([path], root=tmp_path / "state", work=tmp_path)
