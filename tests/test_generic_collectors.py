from __future__ import annotations

import pytest

from collector import generic
from integrations.http_client import BotWallError


@pytest.fixture
def stub_text(monkeypatch: pytest.MonkeyPatch):
    def apply(pages: dict[str, str] | str):
        def fake_fetch(url: str, **_kwargs) -> str:
            if isinstance(pages, str):
                return pages
            if url not in pages:
                raise AssertionError(f"unexpected url {url}")
            return pages[url]

        monkeypatch.setattr(generic, "fetch_text", fake_fetch)

    return apply


@pytest.fixture
def stub_json(monkeypatch: pytest.MonkeyPatch):
    def apply(payloads: dict[str, object] | object):
        def fake_fetch(url: str, **_kwargs) -> object:
            if isinstance(payloads, dict) and url in payloads:
                return payloads[url]
            if isinstance(payloads, dict) and all(key.startswith("http") for key in payloads):
                raise AssertionError(f"unexpected url {url}")
            return payloads

        monkeypatch.setattr(generic, "fetch_json", fake_fetch)

    return apply


def test_title_from_slug_handles_query_and_separators() -> None:
    assert generic.title_from_slug("https://x.com/jobs/senior-ios_engineer/?a=1") == "senior ios engineer"


def test_title_from_slug_falls_back_to_input() -> None:
    assert generic.title_from_slug("") == ""
    assert generic.title_from_slug("///") == "///"


@pytest.mark.parametrize(
    ("href", "base", "expected"),
    [
        ("https://x.com/a", "https://y.com/", "https://x.com/a"),
        ("http://x.com/a", "https://y.com/", "http://x.com/a"),
        ("/careers/ios", "https://x.com/", "https://x.com/careers/ios"),
        ("careers/ios", "https://x.com/", "https://x.com/careers/ios"),
        ("/careers/ios", "https://x.com/sub/page", "https://x.com/careers/ios"),
        ("  /a  ", "https://x.com/", "https://x.com/a"),
    ],
)
def test_absolute_url(href: str, base: str, expected: str) -> None:
    assert generic.absolute_url(href, base) == expected


def test_wp_rest_strips_markup_from_titles(stub_json) -> None:
    stub_json(
        [
            {"title": {"rendered": "<b>iOS</b> Developer &amp; Lead"}, "link": "https://x.com/1", "id": 1},
            {"title": "Swift Engineer", "link": "https://x.com/2", "id": 2},
            {"title": {"rendered": "Java Developer"}, "link": "https://x.com/3", "id": 3},
            {"title": {"rendered": "iOS Developer"}, "link": "", "id": 4},
        ]
    )

    result = generic.collect_wp_rest("Acme", "https://x.com/wp-json")

    assert result.items_scanned == 4
    assert [job["title"] for job in result.jobs] == ["iOS Developer & Lead", "Swift Engineer"]
    assert result.jobs[0]["source_job_id"] == 1


def test_wp_rest_handles_non_list_payload(stub_json) -> None:
    stub_json({"unexpected": True})

    result = generic.collect_wp_rest("Acme", "https://x.com/wp-json")

    assert result.status == "healthy"
    assert result.items_scanned == 0


def test_wp_rest_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generic, "fetch_json", lambda url, **_k: (_ for _ in ()).throw(OSError("x")))

    assert generic.collect_wp_rest("Acme", "https://x.com/wp-json").status == "failed"


def test_html_regex_builds_absolute_urls_from_whole_match(stub_text) -> None:
    stub_text(
        """
        <a href="https://acme.com/vacancies/senior-ios-developer/">one</a>
        <a href="https://acme.com/vacancies/senior-ios-developer/">dup</a>
        <a href="https://acme.com/vacancies/backend-developer/">two</a>
        """
    )

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers/",
        "https://acme.com/",
        r"https://acme\.com/vacancies/([a-z0-9-]+)/",
    )

    assert result.items_scanned == 2
    assert result.jobs == [
        {
            "company": "Acme",
            "title": "senior ios developer",
            "url": "https://acme.com/vacancies/senior-ios-developer/",
            "source": "company",
        }
    ]


def test_html_regex_resolves_relative_links(stub_text) -> None:
    stub_text('<a href="/vacancy/senior-swift-engineer/">x</a>')

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers/",
        "https://acme.com/",
        r"/vacancy/([a-z0-9-]+)/",
    )

    assert result.jobs[0]["url"] == "https://acme.com/vacancy/senior-swift-engineer/"


def test_html_regex_uses_explicit_title_and_url_groups(stub_text) -> None:
    stub_text('<h3 class="t">Senior iOS Engineer</h3><a href="https://acme.com/article-5">go</a>')

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers/",
        "https://acme.com/",
        r'<h3 class="t">\s*([^<]+?)\s*</h3>[\s\S]*?href="(https://acme\.com/article-[^"]+)"',
        url_group=2,
        title_group=1,
    )

    assert result.jobs[0]["title"] == "Senior iOS Engineer"
    assert result.jobs[0]["url"] == "https://acme.com/article-5"


def test_html_regex_can_point_every_job_at_the_list_page(stub_text) -> None:
    stub_text(
        '<h3 class="chess-item-title">iOS Developer</h3>'
        '<h3 class="chess-item-title">iOS Developer</h3>'
        '<h3 class="chess-item-title">DevOps</h3>'
    )

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r'<h3 class="chess-item-title">([^<]+)</h3>',
        title_group=1,
        use_list_url_as_job_url=True,
    )

    assert result.items_scanned == 2
    assert [job["url"] for job in result.jobs] == ["https://acme.com/careers"]


def test_html_regex_skips_matches_without_the_requested_group(stub_text) -> None:
    stub_text("<div>ios developer</div>")

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r"<div>[^<]+</div>",
        url_group=3,
    )

    assert result.jobs == []
    assert result.items_scanned == 0


def test_html_regex_skips_url_group_beyond_pattern_when_title_is_known(stub_text) -> None:
    stub_text('<h3 class="t">iOS Engineer</h3>')

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r'<h3 class="t">([^<]+)</h3>',
        title_group=1,
        url_group=2,
    )

    assert result.jobs == []
    assert result.items_scanned == 0


def test_html_regex_ignores_empty_titles(stub_text) -> None:
    stub_text('<h3 class="t">   </h3>')

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r'<h3 class="t">([^<]*)</h3>',
        title_group=1,
        use_list_url_as_job_url=True,
    )

    assert result.jobs == []


def test_html_regex_treats_bot_wall_as_empty_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generic, "fetch_text_allowing_bot_wall", lambda url, **_kwargs: None)

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r"/vacancy/([a-z]+)/",
        allow_bot_wall=True,
    )

    assert result.status == "healthy"
    assert result.items_scanned == 0


def test_html_regex_uses_bot_wall_body_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generic,
        "fetch_text_allowing_bot_wall",
        lambda url, **_kwargs: '<a href="/vacancy/ios/">x</a>',
    )

    result = generic.collect_html_regex(
        "Acme",
        "https://acme.com/careers",
        "https://acme.com/",
        r"/vacancy/([a-z]+)/",
        allow_bot_wall=True,
    )

    assert result.jobs[0]["url"] == "https://acme.com/vacancy/ios/"


def test_html_regex_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **_kwargs) -> str:
        raise BotWallError("blocked")

    monkeypatch.setattr(generic, "fetch_text", boom)

    result = generic.collect_html_regex("Acme", "https://acme.com/c", "https://acme.com/", r"(x)")

    assert result.status == "failed"
    assert "blocked" in (result.error or "")


def test_soup_links_reads_titles_and_locations(stub_text) -> None:
    stub_text(
        """
        <a class="row" href="/vacancy/1/"><div class="t"><h3>Senior iOS Engineer</h3></div>
          <div class="i"><span> Kyiv, Remote </span></div></a>
        <a class="row" href="/vacancy/2/"><div class="t"><h3>Go Engineer</h3></div></a>
        """
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        title_selector=".t h3",
        location_selector=".i span",
    )

    assert result.items_scanned == 2
    assert result.jobs == [
        {
            "company": "Acme",
            "title": "Senior iOS Engineer",
            "url": "https://acme.com/vacancy/1/",
            "source": "company",
            "location": "Kyiv, Remote",
        }
    ]


def test_soup_links_falls_back_to_anchor_text_then_slug(stub_text) -> None:
    stub_text(
        """
        <a class="row" href="/vacancy/ios-engineer/">  iOS Engineer  </a>
        <a class="row" href="/vacancy/swift-developer/"><span></span></a>
        """
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
    )

    assert [job["title"] for job in result.jobs] == ["iOS Engineer", "swift developer"]


def test_soup_links_applies_skip_rules_and_transform(stub_text) -> None:
    stub_text(
        """
        <a class="row" href="/careers/">index</a>
        <a class="row" href="https://acme.com/careers">index-abs</a>
        <a class="row" href="/careers/ios-dev/">ios dev</a>
        <a class="row" href="/other/ios-dev/">wrong section</a>
        <a class="row">no href</a>
        """
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        href_contains="/careers/",
        skip_exact={"https://acme.com/careers"},
        skip_hrefs={"/careers/"},
        title_transform=lambda title: title.upper(),
    )

    assert [job["url"] for job in result.jobs] == ["https://acme.com/careers/ios-dev/"]
    assert result.jobs[0]["title"] == "IOS DEV"


def test_soup_links_follows_discovered_pagination(stub_text) -> None:
    stub_text(
        {
            "https://acme.com/jobs/": (
                '<a class="row" href="/vacancy/1/">iOS Engineer</a>'
                '<a class="page" href="/jobs/page/2/">2</a>'
                '<a class="page" href="/jobs/page/2/">2 again</a>'
            ),
            "https://acme.com/jobs/page/2/": (
                '<a class="row" href="/vacancy/2/">Swift Engineer</a>'
                '<a class="page" href="/jobs/">1</a>'
            ),
        }
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        pagination_selector="a.page",
    )

    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["iOS Engineer", "Swift Engineer"]


def test_soup_links_ignores_empty_pagination_hrefs(stub_text) -> None:
    stub_text(
        '<a class="row" href="/vacancy/1/">iOS Engineer</a>'
        '<a class="page" href="">next</a>'
        '<a class="page">no href</a>'
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        pagination_selector="a.page",
    )

    assert result.items_scanned == 1


def test_soup_links_dedupes_the_same_vacancy_across_pages(stub_text) -> None:
    stub_text(
        {
            "https://acme.com/jobs/": (
                '<a class="row" href="/vacancy/1/">iOS Engineer</a>'
                '<a class="page" href="/jobs/page/2/">2</a>'
            ),
            "https://acme.com/jobs/page/2/": '<a class="row" href="/vacancy/1/">iOS Engineer</a>',
        }
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        pagination_selector="a.page",
    )

    assert result.items_scanned == 1
    assert len(result.jobs) == 1


def test_soup_links_honours_max_pages(stub_text) -> None:
    stub_text(
        {
            "https://acme.com/jobs/": (
                '<a class="row" href="/vacancy/1/">iOS Engineer</a>'
                '<a class="page" href="/jobs/page/2/">2</a>'
            ),
        }
    )

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a.row",
        pagination_selector="a.page",
        max_pages=1,
    )

    assert result.items_scanned == 1


def test_soup_links_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **_kwargs) -> str:
        raise RuntimeError("timeout")

    monkeypatch.setattr(generic, "fetch_text", boom)

    result = generic.collect_soup_links(
        "Acme",
        "https://acme.com/jobs/",
        base_url="https://acme.com/",
        selector="a",
    )

    assert result.status == "failed"
