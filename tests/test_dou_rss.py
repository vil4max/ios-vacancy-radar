from __future__ import annotations

from pathlib import Path

import pytest

from collector import dou_rss
from collector.dou_rss import (
    collect_dou_ai_rss,
    collect_dou_ios_rss,
    is_mobile_ai_title,
    parse_feed,
    parse_item_title,
    strip_tracking,
)
from parser.normalize import normalize_many

# Synthetic feeds that keep the structure of the recorded jobs.dou.ua RSS 2.0
# responses: double-escaped titles, HTML descriptions and utm-tagged links.
FIXTURES = Path(__file__).parent / "fixtures"
IOS_FEED = (FIXTURES / "dou_rss_ios.xml").read_text(encoding="utf-8")
AI_FEED = (FIXTURES / "dou_rss_ai.xml").read_text(encoding="utf-8")


def test_strip_tracking_removes_only_utm_params() -> None:
    assert (
        strip_tracking("https://jobs.dou.ua/companies/x/vacancies/1/?utm_source=jobsrss&utm_medium=rss&page=2")
        == "https://jobs.dou.ua/companies/x/vacancies/1/?page=2"
    )


def test_parse_item_title_splits_role_company_location() -> None:
    role, company, location, remote = parse_item_title(
        "Sr iOS Developer в Example Bank (Example Holding, Ltd), $1000–2000, за кордоном, віддалено"
    )
    assert role == "Sr iOS Developer"
    assert company == "Example Bank (Example Holding, Ltd)"
    assert location == "за кордоном"
    assert remote is True


def test_parse_item_title_uses_last_preposition() -> None:
    role, company, location, remote = parse_item_title("Розробник в команду iOS в Example Studio, Київ")
    assert role == "Розробник в команду iOS"
    assert company == "Example Studio"
    assert location == "Київ"
    assert remote is False


def test_parse_item_title_without_company() -> None:
    assert parse_item_title("iOS Developer") == ("iOS Developer", None, None, False)


def test_ios_feed_goes_through_topic_gate() -> None:
    jobs, scanned = parse_feed(IOS_FEED)

    assert scanned == 4
    assert [job["title"] for job in jobs] == [
        "Sr iOS Developer",
        "Senior iOS Engineer — R&D Team",
        "Розробник в команду iOS",
    ]
    first = jobs[0]
    assert first["company"] == "Example Bank (Example Holding, Ltd)"
    assert first["url"] == "https://jobs.dou.ua/companies/example-bank/vacancies/100001/"
    assert first["source"] == "dou"
    assert first["source_job_id"] == "dou:100001"
    assert first["location"] == "за кордоном"
    assert first["remote"] == "remote"
    assert first["published_at"] == "2026-09-14T23:44:12+03:00"
    assert "SwiftUI" in first["description"]
    assert "$" not in (first["location"] or "")
    assert jobs[1]["url"] == "https://jobs.dou.ua/companies/example-engineering/vacancies/100002/"
    assert jobs[1]["location"] == "Київ, Львів"
    assert len(normalize_many(jobs)) == 3


def test_ai_feed_keeps_only_mobile_titles() -> None:
    jobs, scanned = parse_feed(AI_FEED, title_filter=is_mobile_ai_title)

    assert scanned == 4
    # The Python role mentions iOS only in its body, the designer not at all.
    assert [job["company"] for job in jobs] == ["Example AI", "Example Labs"]


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("AI Engineer (iOS)", True),
        ("Mobile ML Engineer", True),
        ("SwiftUI + LLM Engineer", True),
        ("Apple Intelligence Researcher", True),
        ("Senior macOS Engineer, AI Security", True),
        ("AI Ops Specialist", False),
        ("Automobile Pricing Analyst", False),
    ],
)
def test_mobile_ai_title_filter(title: str, kept: bool) -> None:
    assert is_mobile_ai_title(title) is kept


def test_collectors_report_scanned_items(monkeypatch: pytest.MonkeyPatch) -> None:
    feeds = {dou_rss.IOS_FEED_URL: IOS_FEED, dou_rss.AI_FEED_URL: AI_FEED}
    monkeypatch.setattr(dou_rss, "fetch_text", lambda url: feeds[url])

    ios = collect_dou_ios_rss()
    ai = collect_dou_ai_rss()

    assert (ios.source_id, ios.status, ios.items_scanned, len(ios.jobs)) == ("dou-ios-rss", "healthy", 4, 3)
    assert (ai.source_id, ai.status, ai.items_scanned, len(ai.jobs)) == ("dou-ai-rss", "healthy", 4, 2)


def test_collector_fails_on_broken_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dou_rss, "fetch_text", lambda url: "<html>maintenance</html")

    result = collect_dou_ios_rss()

    assert result.status == "failed"
    assert result.jobs == []
