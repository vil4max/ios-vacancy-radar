from __future__ import annotations

from pathlib import Path

from collector.djinni_rss import parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "djinni_rss_ios.xml"


def test_djinni_feed_keeps_on_topic_items_without_tracking_or_a_guessed_company() -> None:
    jobs, scanned = parse_feed(FIXTURE.read_text(encoding="utf-8"))

    assert scanned == 3
    assert [job["title"] for job in jobs] == ["Senior iOS Engineer", "Senior Mobile Engineer"]
    first = jobs[0]
    assert first["url"] == "https://djinni.co/jobs/100001-senior-ios-engineer/"
    assert first["source"] == "djinni"
    assert first["source_job_id"] == "djinni:100001"
    assert first["company"] == ""
    assert first["published_at"] == "2026-10-09T13:31:13+03:00"
