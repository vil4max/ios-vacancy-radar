from __future__ import annotations

import json

import pytest

from collector import dou_service_ratings
from collector.mobile_discovery import extra_pages, inspect_company, signals, strength, verdict

FILLER = "<p>" + "We build products for customers across Europe. " * 12 + "</p>"
PROFILE = '<div class="site"><a href="https://example-studio.test/" target="_blank" rel="nofollow">site</a></div>'
HOME = '<a href="/careers">Careers</a>' + FILLER
LANDING = '<a href="/careers/page/2">2</a><a href="/careers/backend-engineer">Backend Engineer</a>' + FILLER
PAGE_2 = '<a href="/careers/senior-ios-engineer">Senior iOS Engineer</a>'
DOU_LIST = '<a class="vt" href="https://jobs.dou.ua/companies/example-studio/vacancies/1/">Flutter Developer</a>'


def _fetcher(pages: dict[str, str]):
    def fetch(url: str) -> tuple[int, str]:
        return (200, pages[url]) if url in pages else (404, "")
    return fetch


SITE = {
    "https://jobs.dou.ua/companies/example-studio/": PROFILE,
    "https://example-studio.test/": HOME,
    "https://example-studio.test/careers": LANDING,
    "https://example-studio.test/careers/page/2": PAGE_2,
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Senior iOS Engineer (SwiftUI)", "ios"),
        ("Flutter Developer", "mobile"),
        ("Мобільний розробник", "mobile"),
        ("Studios and scenarios for bios", "none"),
    ],
)
def test_verdict(text: str, expected: str) -> None:
    assert verdict(signals(text)) == expected


def test_extra_pages_prefers_vacancy_list_then_pagination() -> None:
    html = ('<a href="/careers/page/2">2</a><a href="https://other.test/jobs">x</a>'
            '<a href="/careers/all">All vacancies</a><a href="/careers#top">top</a>')
    assert extra_pages("https://example.test/careers", html) == [
        "https://example.test/careers/all",
        "https://example.test/careers/page/2",
    ]


def test_ios_role_behind_pagination_is_found() -> None:
    row = inspect_company("example-studio", _fetcher(SITE), has_dou_vacancies=False)

    assert row["career_url"] == "https://example-studio.test/careers"
    assert row["career_state"] == "read"
    assert strength(row) == "ios"


def test_named_mobile_stack_in_dou_titles_is_strong() -> None:
    pages = dict(SITE, **{"https://jobs.dou.ua/companies/example-studio/vacancies/": DOU_LIST,
                          "https://example-studio.test/careers/page/2": "<p>Office manager</p>"})
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=True)

    assert strength(row) == "mobile_stack"


def test_bare_mobile_word_is_not_enough() -> None:
    pages = dict(SITE, **{"https://example-studio.test/careers/page/2": "<p>Mobile communication compensation</p>"})
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=False)

    assert verdict(row["career"]) == "mobile"
    assert strength(row) is None


def test_homepage_only_signal_is_not_a_careers_page() -> None:
    pages = {
        "https://jobs.dou.ua/companies/example-studio/": PROFILE,
        "https://example-studio.test/": "<a href='https://apps.apple.com/app/1'>Download for iOS</a>" + FILLER,
    }
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=False)

    assert row["career_state"] == "career_not_found"
    assert strength(row) is None


@pytest.mark.parametrize("status", [403, -1])
def test_refused_site_is_skipped_not_retried(status: int) -> None:
    calls: list[str] = []

    def fetch(url: str) -> tuple[int, str]:
        calls.append(url)
        return (200, PROFILE) if "dou.ua" in url else (status, "")

    row = inspect_company("example-studio", fetch, has_dou_vacancies=False)

    assert row["career_state"] == "unreadable"
    assert strength(row) is None
    assert calls == ["https://jobs.dou.ua/companies/example-studio/", "https://example-studio.test/"]


def test_client_rendered_shell_is_not_read() -> None:
    pages = dict(SITE, **{"https://example-studio.test/careers": "<div id='root'></div><p>iOS</p>"})
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=False)

    assert row["career_state"] == "js_rendered"
    assert strength(row) is None


def test_missing_discovered_file_reads_as_empty(tmp_path) -> None:
    assert dou_service_ratings.load_manual_additions(tmp_path / "company_discovered.json") == []
    path = tmp_path / "list.json"
    path.write_text(json.dumps([{"name": "Example", "slug": "example", "career_url": "https://e.test/jobs"}]))
    assert dou_service_ratings.load_manual_additions(path)[0]["slug"] == "example"


def test_careers_page_on_dou_is_left_to_the_rss_feed() -> None:
    pages = dict(SITE, **{"https://example-studio.test/": '<a href="https://jobs.dou.ua/companies/example-studio/vacancies/">Jobs</a>' + FILLER})
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=False)

    assert row["career_state"] == "on_dou"
    assert strength(row) is None


def test_selection_takes_new_companies_then_oldest_stale_checks() -> None:
    from datetime import date

    from scripts.discover_mobile_companies import select_companies

    catalog = [{"slug": slug} for slug in ("on-radar", "new", "recent", "old", "older")]
    state = {"recent": "2026-09-01", "old": "2026-05-01", "older": "2026-01-01"}

    chosen = select_companies(
        catalog, known={"on-radar"}, state=state, today=date(2026, 9, 21), recheck_days=90, recheck_limit=1,
    )

    assert [company["slug"] for company in chosen] == ["new", "older"]


def test_dou_requests_are_paced_and_other_hosts_are_not(monkeypatch) -> None:
    from scripts import discover_mobile_companies as script

    clock = {"now": 100.0}
    sleeps: list[float] = []
    monkeypatch.setattr(script.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(script.time, "sleep", lambda seconds: sleeps.append(seconds))
    pace = script._DouPace(1.5)

    pace.wait("https://jobs.dou.ua/companies/")
    pace.wait("https://jobs.dou.ua/companies/a/")
    pace.wait("https://example.test/careers")

    assert sleeps == [1.5]


def test_event_page_is_not_a_careers_page() -> None:
    pages = dict(SITE, **{"https://example-studio.test/": '<a href="/event/webinar-start-in-ios">Jobs webinar</a>' + FILLER})
    row = inspect_company("example-studio", _fetcher(pages), has_dou_vacancies=False)

    assert row["career_state"] == "career_not_found"
