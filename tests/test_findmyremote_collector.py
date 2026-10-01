from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from collector import findmyremote
from collector.results import is_access_blocked
from collector.types import STATUS_DEGRADED, STATUS_FAILED, STATUS_HEALTHY
from integrations import http_client
from parser.normalize import is_inbox_candidate, normalize_many, vacancy_labels

# Synthetic page that keeps the card markup of the real listing; every company,
# title, count and link in it is invented.
FIXTURE = (Path(__file__).parent / "fixtures" / "findmyremote_listing.html").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} error", response=self)


def _card(
    *,
    title: str = "Senior iOS Engineer",
    company: str | None = "Example Co",
    location: str | None = "Remote",
    job: str = "/companies/example-co/jobs/senior-ios-engineer-1",
) -> str:
    company_html = f'<a href="/companies/example-co">{company}</a>' if company else ""
    location_html = (
        f'<div><svg class="tabler-icon tabler-icon-map-pin"></svg><p>{location}</p></div>' if location else ""
    )
    return (
        f'<div data-slot="card"><div data-slot="card-title"><a href="{job}">{title}</a></div>'
        f"{company_html}{location_html}</div>"
    )


def _serve(monkeypatch: pytest.MonkeyPatch, body: str | None | Exception) -> list[dict]:
    calls: list[dict] = []

    def fetch(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(body, Exception):
            raise body
        return body

    monkeypatch.setattr(findmyremote, "fetch_text_allowing_bot_wall", fetch)
    return calls


def _by_title(jobs: list[dict]) -> dict[str, dict]:
    return {job["title"]: job for job in jobs}


def test_parse_listing_reads_every_card_of_the_page() -> None:
    records, found, skipped = findmyremote.parse_listing(FIXTURE)

    assert (found, skipped) == (4, 0)
    assert [record["company"] for record in records] == [
        "Example Engineering", "Example Studio", "Example Mobile", "Example Labs",
    ]


def test_collect_keeps_native_ios_titles_through_the_existing_topic_filter(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE)

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_HEALTHY
    assert result.source_id == "findmyremote:ios-listing"
    assert result.items_scanned == 4
    assert [job["title"] for job in result.jobs] == [
        "Senior iOS Engineer", "iOS Developer (SwiftUI)", "Swift Engineer",
    ]


def test_allowed_countries_reach_the_location_field(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE)

    jobs = _by_title(findmyremote.collect_findmyremote().jobs)

    assert jobs["Senior iOS Engineer"]["location"] == "United States"
    assert jobs["iOS Developer (SwiftUI)"]["location"] == "Hungary, United Kingdom"
    assert jobs["Swift Engineer"]["location"] == "Remote"
    assert {job["remote"] for job in jobs.values()} == {"remote"}


def test_us_only_entry_is_labelled_and_never_dropped(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE)

    vacancies = {vacancy.title: vacancy for vacancy in normalize_many(findmyremote.collect_findmyremote().jobs)}

    us_only = vacancies["Senior iOS Engineer"]
    assert is_inbox_candidate(us_only)
    assert vacancy_labels(us_only)["location_needs_check"] is True
    assert vacancy_labels(us_only)["work_mode"] == "remote"
    assert vacancy_labels(vacancies["Swift Engineer"])["location_needs_check"] is False


def test_url_is_the_employer_posting_link_or_else_the_page_on_the_site(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE)

    jobs = _by_title(findmyremote.collect_findmyremote().jobs)

    assert jobs["Senior iOS Engineer"]["url"] == (
        "https://careers.example.com/positions/100001?gh_jid=100001&utm_source=findmyremote.ai"
    )
    assert jobs["Swift Engineer"]["url"] == "https://findmyremote.ai/companies/example-labs/jobs/swift-engineer-100004"
    canonical = {vacancy.title: vacancy.canonical_url for vacancy in normalize_many(list(jobs.values()))}
    assert canonical["Senior iOS Engineer"] == "https://careers.example.com/positions/100001?gh_jid=100001"


def test_one_request_goes_to_the_listing_page_with_an_honest_user_agent(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url: str, headers: dict, timeout: int) -> FakeResponse:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse(text=FIXTURE)

    monkeypatch.setattr(http_client.requests, "get", fake_get)

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_HEALTHY
    assert len(calls) == 1
    assert calls[0]["url"] == "https://findmyremote.ai/jobs?category=engineering&skill=ios"
    assert calls[0]["timeout"] == findmyremote._TIMEOUT_SECONDS
    agent = calls[0]["headers"]["User-Agent"]
    assert agent == findmyremote.USER_AGENT
    assert "ios-vacancy-radar" in agent
    assert "https://github.com/vil4max/ios-vacancy-radar" in agent
    assert "hunter" not in agent.lower()
    assert "Mozilla" not in agent


def test_listing_url_stays_within_what_robots_txt_allows() -> None:
    parts = urlsplit(findmyremote.LISTING_URL)

    assert (parts.scheme, parts.hostname, parts.path) == ("https", "findmyremote.ai", "/jobs")
    assert not parts.path.startswith(("/api/", "/app/", "/auth/"))


def test_refused_request_fails_without_impersonating_a_browser(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, headers: dict, timeout: int) -> FakeResponse:
        calls.append(url)
        return FakeResponse(status_code=403)

    def no_impersonation(*_args, **_kwargs):
        raise AssertionError("a refused request must not be retried as a browser")

    monkeypatch.setattr(http_client.requests, "get", fake_get)
    monkeypatch.setattr(http_client, "fetch_impersonated", no_impersonation)

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_FAILED
    assert result.jobs == []
    assert is_access_blocked(result.error)
    assert len(calls) == 1


def test_failed_fetch_is_reported_as_failed_not_as_an_empty_result(monkeypatch) -> None:
    _serve(monkeypatch, requests.ConnectionError("connection reset"))

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_FAILED
    assert "connection reset" in result.error
    assert result.jobs == []
    assert result.items_scanned == 0


def test_empty_response_is_reported_as_failed(monkeypatch) -> None:
    _serve(monkeypatch, "  \n")

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_FAILED
    assert "empty response" in result.error


def test_page_without_job_cards_is_degraded(monkeypatch) -> None:
    _serve(monkeypatch, "<html><body><h1>Something went wrong</h1></body></html>")

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_DEGRADED
    assert "no job cards" in result.error
    assert result.jobs == []
    assert result.items_scanned == 0


def test_cards_in_a_changed_wrapper_are_degraded(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE.replace('data-slot="card"', 'data-slot="panel"'))

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_DEGRADED
    assert "4 job cards found but none readable" in result.error
    assert result.items_scanned == 0
    assert result.items_skipped == 4


def test_cards_without_allowed_country_text_are_degraded(monkeypatch) -> None:
    _serve(monkeypatch, FIXTURE.replace("tabler-icon-map-pin", "tabler-icon-pin"))

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_DEGRADED
    assert "allowed-country" in result.error
    assert [job["location"] for job in result.jobs] == [None, None, None]


def test_one_unreadable_card_is_skipped_and_counted(monkeypatch) -> None:
    page = _card() + _card(title="iOS Developer", company=None, job="/companies/example-co/jobs/ios-developer-2")
    _serve(monkeypatch, f"<html><body>{page}</body></html>")

    result = findmyremote.collect_findmyremote()

    assert result.status == STATUS_HEALTHY
    assert result.items_scanned == 1
    assert result.items_skipped == 1
    assert [job["title"] for job in result.jobs] == ["Senior iOS Engineer"]


def test_collect_findmyremote_is_registered_in_the_pipeline() -> None:
    from collector.companies import _python_collectors

    assert findmyremote.collect_findmyremote in _python_collectors()


def test_repeated_card_link_is_read_once(monkeypatch) -> None:
    _serve(monkeypatch, f"<html><body>{_card()}{_card()}</body></html>")

    result = findmyremote.collect_findmyremote()

    assert result.items_scanned == 1
    assert len(result.jobs) == 1
