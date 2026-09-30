from __future__ import annotations

import json

import pytest

from collector import bespoke


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch):
    def apply(*, text=None, payload=None, form=None):
        if text is not None:
            handler = text if callable(text) else (lambda url, **_k: text)
            monkeypatch.setattr(bespoke, "fetch_text", handler)
            monkeypatch.setattr(bespoke, "fetch_text_allowing_bot_wall", handler)
        if payload is not None:
            handler = payload if callable(payload) else (lambda url, **_k: payload)
            monkeypatch.setattr(bespoke, "fetch_json", handler)
        if form is not None:
            monkeypatch.setattr(bespoke, "fetch_text", lambda *args, **kwargs: "")
            monkeypatch.setattr(bespoke, "post_form_data", form)

    return apply


def _raiser(message: str):
    def boom(*_args, **_kwargs):
        raise RuntimeError(message)

    return boom


def _next_data(payload: dict) -> str:
    return f'<html><script id="__NEXT_DATA__">{json.dumps(payload)}</script></html>'


def test_andersen_matches_by_title_or_technology(stub) -> None:
    stub(
        payload=[
            {"name": "Senior iOS Developer", "vacancy_id": 10},
            {"name": "Developer", "technologies": ["Swift", "UIKit"], "id": 11},
            {"name": "Accountant", "id": 12},
            {"name": "iOS Developer"},
        ]
    )

    result = bespoke.collect_andersen()

    assert result.items_scanned == 4
    assert [job["url"] for job in result.jobs] == [
        "https://people.andersenlab.com/vacancy/10",
        "https://people.andersenlab.com/vacancy/11",
    ]


def test_andersen_reads_wrapped_payload(stub) -> None:
    stub(payload={"vacancies": [{"name": "iOS Engineer", "id": 1}]})

    assert len(bespoke.collect_andersen().jobs) == 1


def test_andersen_handles_unexpected_payload(stub) -> None:
    stub(payload={"vacancies": "nope"})

    result = bespoke.collect_andersen()

    assert result.items_scanned == 0
    assert result.status == "healthy"


def test_andersen_reports_failure(stub) -> None:
    stub(payload=_raiser("api down"))

    assert bespoke.collect_andersen().status == "failed"


def test_onix_reads_next_data(stub) -> None:
    stub(
        text=_next_data(
            {
                "props": {
                    "pageProps": {
                        "careerList": [
                            {"attributes": {"name": "iOS Engineer", "url": "ios-engineer"}},
                            {
                                "attributes": {
                                    "name": "Swift Engineer",
                                    "canonical": "https://onix-systems.com/careers/swift",
                                }
                            },
                            {"attributes": {"name": "Recruiter", "url": "recruiter"}},
                            {"no-attributes": True},
                        ]
                    }
                }
            }
        )
    )

    result = bespoke.collect_onix()

    assert result.items_scanned == 4
    assert [job["url"] for job in result.jobs] == [
        "https://onix-systems.com/careers/ios-engineer",
        "https://onix-systems.com/careers/swift",
    ]


def test_onix_without_next_data_scans_nothing(stub) -> None:
    stub(text="<html>no script</html>")

    result = bespoke.collect_onix()

    assert result.items_scanned == 0
    assert result.status == "healthy"


def test_onix_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_onix().status == "failed"


def test_nortal_filters_and_tags_ukraine(stub) -> None:
    stub(
        payload={
            "jobs": [
                {"data": {"title": "iOS Developer", "apply_url": "https://nortal.com/1"}},
                {"data": {"title": "iOS Developer"}},
                {"data": {"title": "Project Manager", "apply_url": "https://nortal.com/2"}},
                {"no-data": 1},
            ]
        }
    )

    result = bespoke.collect_nortal()

    assert result.items_scanned == 4
    assert result.jobs == [
        {
            "company": "Nortal",
            "title": "iOS Developer",
            "url": "https://nortal.com/1",
            "source": "company",
            "location": "Ukraine",
        }
    ]


def test_nortal_reports_failure(stub) -> None:
    stub(payload=_raiser("boom"))

    assert bespoke.collect_nortal().status == "failed"


def test_ciklum_handles_missing_items(stub) -> None:
    stub(payload={"items": []})

    assert bespoke.collect_ciklum().items_scanned == 0


def test_ciklum_reports_failure(stub) -> None:
    stub(payload=_raiser("boom"))

    assert bespoke.collect_ciklum().status == "failed"


def test_sigma_stops_when_response_not_successful(stub) -> None:
    stub(form=lambda url, fields, **_k: json.dumps({"success": False}))

    result = bespoke.collect_sigma()

    assert result.items_scanned == 0
    assert result.status == "healthy"


def test_sigma_reports_failure(stub) -> None:
    stub(form=_raiser("ajax down"))

    assert bespoke.collect_sigma().status == "failed"


def test_dataart_builds_urls_from_slug(stub) -> None:
    stub(
        payload={
            "vacancies": {
                "items": [
                    {"title": "iOS Developer", "slug": "ios-developer"},
                    {"title": "iOS Developer"},
                    {"title": "Copywriter", "slug": "copywriter"},
                ]
            }
        }
    )

    result = bespoke.collect_dataart()

    assert result.items_scanned == 6
    assert result.jobs[0]["url"] == "https://www.dataart.team/vacancies/ios-developer"
    assert "categories=569" in result.source_url
    assert "skills=771" not in result.source_url


def test_dataart_android_only_mobile_page_is_healthy_not_empty_scan(stub) -> None:
    stub(
        payload={
            "vacancies": {
                "items": [
                    {"title": "Senior Android Developer", "slug": "ADR00037"},
                    {"title": "Android Technical Lead", "slug": "ADR00045"},
                ]
            }
        }
    )

    result = bespoke.collect_dataart()

    assert result.status == "healthy"
    assert result.items_scanned == 4
    assert result.jobs == []


def test_dataart_reads_flat_items(stub) -> None:
    stub(payload={"items": [{"title": "Swift Engineer", "slug": "swift"}]})

    assert len(bespoke.collect_dataart().jobs) == 1


def test_dataart_reports_failure(stub) -> None:
    stub(payload=_raiser("boom"))

    assert bespoke.collect_dataart().status == "failed"


_GRID_HTML = """
<div data-vacancies='[
  {"id": 1, "title": "Senior iOS Engineer", "countryLocations": [{"city": "Kyiv", "country": "Ukraine"}]},
  {"id": 2, "title": "iOS Engineer", "relatedLocations": ["Buenos Aires, Argentina"]},
  {"id": 3, "title": "Java Engineer", "countryLocations": [{"city": "Kyiv", "country": "Ukraine"}]},
  {"title": "iOS Engineer", "relatedLocations": ["Kyiv, Ukraine"]}
]'></div>
"""


def test_grid_dynamics_parses_plain_json_attribute(stub) -> None:
    stub(text=_GRID_HTML)

    result = bespoke.collect_grid_dynamics()

    assert result.items_scanned == 4
    assert [job["source_job_id"] for job in result.jobs] == ["1", "2"]
    assert result.jobs[0]["location"] == "Kyiv, Ukraine"
    assert result.jobs[1]["location"] == "Buenos Aires, Argentina"


def test_grid_dynamics_unescapes_html_entities(stub) -> None:
    stub(
        text=(
            "<div data-vacancies='["
            '{&quot;id&quot;: 9, &quot;title&quot;: &quot;iOS Engineer&quot;, '
            '&quot;relatedLocations&quot;: [&quot;Kyiv, Ukraine&quot;]}'
            "]'></div>"
        )
    )

    result = bespoke.collect_grid_dynamics()

    assert [job["source_job_id"] for job in result.jobs] == ["9"]


def test_grid_dynamics_without_attribute_scans_nothing(stub) -> None:
    stub(text="<div></div>")

    result = bespoke.collect_grid_dynamics()

    assert result.items_scanned == 0
    assert result.status == "healthy"


def test_grid_dynamics_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_grid_dynamics().status == "failed"


def test_rbi_merges_sitemap_and_list_page(stub) -> None:
    pages = {
        "https://www.rbi-ri.com.ua/sitemap.xml": (
            "<urlset><url><loc>https://www.rbi-ri.com.ua/career/ios-developer</loc></url></urlset>"
        ),
        "https://www.rbi-ri.com.ua/career": (
            '<a href="https://www.rbi-ri.com.ua/career/ios-developer">a</a>'
            '<a href="https://rbi-ri.com.ua/career/qa-engineer">b</a>'
        ),
        "https://www.rbi-ri.com.ua/career/ios-developer": (
            '<meta property="og:title" content="Vacancy iOS Developer &#039;26 — RBI Retail Innovation"/>'
        ),
        "https://www.rbi-ri.com.ua/career/qa-engineer": "<title>QA Engineer</title>",
    }
    stub(text=lambda url, **_k: pages[url])

    result = bespoke.collect_rbi()

    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["iOS Developer '26"]


def test_rbi_survives_missing_sitemap(stub) -> None:
    pages = {
        "https://www.rbi-ri.com.ua/career": '<a href="https://www.rbi-ri.com.ua/career/ios-dev">a</a>',
        "https://www.rbi-ri.com.ua/career/ios-dev": "<title>iOS Developer</title>",
    }

    def fake_text(url: str, **_kwargs) -> str:
        if url.endswith("sitemap.xml"):
            raise RuntimeError("404")
        return pages[url]

    stub(text=fake_text)

    assert [job["title"] for job in bespoke.collect_rbi().jobs] == ["iOS Developer"]


def test_rbi_skips_pages_that_fail_to_load(stub) -> None:
    def fake_text(url: str, **_kwargs) -> str:
        if url.endswith("sitemap.xml"):
            return "<urlset><loc>https://www.rbi-ri.com.ua/career/ios-dev</loc></urlset>"
        if url.endswith("/career"):
            return ""
        raise RuntimeError("detail down")

    stub(text=fake_text)

    result = bespoke.collect_rbi()

    assert result.jobs == []
    assert result.status == "failed"
    assert "detail down" in result.error


def test_rbi_reports_failure_when_list_page_is_down(stub) -> None:
    def fake_text(url: str, **_kwargs) -> str:
        raise RuntimeError("site down")

    stub(text=fake_text)

    assert bespoke.collect_rbi().status == "failed"


def test_rbi_title_does_not_invent_title_from_slug(stub) -> None:
    stub(text=lambda url, **_k: "<html>no title</html>")

    assert bespoke._rbi_title("https://www.rbi-ri.com.ua/career/ios-developer") is None


def test_nix_html_parses_numbered_titles(stub) -> None:
    stub(
        text=(
            '<a href="/jobs/ios-dev/"> Senior iOS Developer (#123) </a>'
            '<a href="/jobs/ios-dev/"> Senior iOS Developer (#123) </a>'
            '<a href="/jobs/qa/"> QA Engineer (#124) </a>'
        )
    )

    result = bespoke.collect_nix_html()

    assert result.items_scanned == 2
    assert result.jobs[0]["url"] == "https://careers.n-ix.com/jobs/ios-dev/"


def test_nix_html_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_nix_html().status == "failed"


def test_intellias_parses_vacancy_links(stub) -> None:
    stub(
        text=(
            '<a href="https://career.intellias.com/vacancy/ios-engineer/">Senior iOS Engineer</a>'
            '<a href="https://career.intellias.com/vacancy/ios-engineer/">Senior iOS Engineer</a>'
            '<a href="https://career.intellias.com/vacancy/pm/">Project Manager</a>'
        )
    )

    result = bespoke.collect_intellias()

    assert result.items_scanned == 2
    assert len(result.jobs) == 1


def test_intellias_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_intellias().status == "failed"


def test_infopulse_skips_apply_links(stub) -> None:
    stub(
        text=(
            '<a href="/job/1/">Senior iOS Developer</a>'
            '<a href="/job/1/">Apply</a>'
            '<a href="/job/2/">Cloud Architect</a>'
        )
    )

    result = bespoke.collect_infopulse()

    assert result.items_scanned == 2
    assert result.jobs[0]["url"] == "https://careers.tieto.com/job/1/"


def test_infopulse_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_infopulse().status == "failed"


def test_softserve_filters_ios_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bespoke,
        "_fetch_softserve_vacancies",
        lambda: [
            {
                "id": 12345,
                "name": "Senior iOS Engineer",
                "urlSegment": "senior-ios-engineer-12345",
                "city": "Ukraine",
            },
            {
                "id": 12345,
                "name": "Senior iOS Engineer",
                "urlSegment": "senior-ios-engineer-12345",
                "city": "Ukraine",
            },
            {
                "id": 777,
                "name": "Database Admin",
                "urlSegment": "database-admin-777",
                "city": "Poland",
            },
            {
                "id": 888,
                "name": "Senior Mobile Robotics Engineer",
                "urlSegment": "senior-mobile-robotics-engineer-888",
                "city": "Ukraine",
            },
        ],
    )

    result = bespoke.collect_softserve()

    assert result.status == "healthy"
    assert result.items_scanned == 4
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Senior iOS Engineer"
    assert result.jobs[0]["url"] == (
        "https://career.softserveinc.com/en-us/vacancies/senior-ios-engineer-12345"
    )
    assert result.jobs[0]["location"] == "Ukraine"
    assert result.jobs[0]["source_job_id"] == "12345"


def test_softserve_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bespoke, "_fetch_softserve_vacancies", _raiser("anti-bot challenge"))

    result = bespoke.collect_softserve()

    assert result.status == "failed"
    assert "anti-bot" in (result.error or "")


def test_softserve_empty_catalog_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bespoke, "_fetch_softserve_vacancies", lambda: [])

    result = bespoke.collect_softserve()

    assert result.status == "healthy"
    assert result.items_scanned == 0
    assert result.jobs == []


def test_globallogic_reads_job_boxes(stub) -> None:
    stub(
        text=(
            '<a class="job_box" href="/ua/careers/senior-ios-engineer-irc123/">'
            '<span class="job_location">Argentina</span>'
            '<span class="job_location">Buenos Aires</span>'
            '<span class="job_tag">Remote</span>'
            "<h4>Senior iOS Engineer IRC123</h4></a>"
            '<a class="job_box" href="/ua/careers/senior-ios-engineer-irc123/"><h4>dup</h4></a>'
            '<a class="job_box" href="/ua/careers/ios-engineer/"><h4>iOS Engineer</h4></a>'
            '<a class="job_box" href="/ua/careers/data-engineer-irc124/"><h4>Data Engineer</h4></a>'
        )
    )

    result = bespoke.collect_globallogic()

    assert result.items_scanned == 2
    assert result.jobs[0]["title"] == "Senior iOS Engineer"
    assert result.jobs[0]["url"] == "https://www.globallogic.com/ua/careers/senior-ios-engineer-irc123/"
    assert result.jobs[0]["location"] == "Argentina, Buenos Aires"
    assert result.jobs[0]["remote"] == "Remote"


def test_globallogic_falls_back_to_raw_urls(stub) -> None:
    stub(text="see https://www.globallogic.com/ua/careers/ios-developer-irc999/ for details")

    result = bespoke.collect_globallogic()

    assert result.jobs[0]["title"] == "ios developer"


def test_globallogic_reports_failure(stub) -> None:
    stub(text=_raiser("403"))

    assert bespoke.collect_globallogic().status == "failed"


def test_luxoft_parses_specialization_jobs(stub) -> None:
    stub(
        text=(
            '<a class="jobs__list__job" href="/jobs/senior-ios-developer-26100">'
            "<h2>Senior iOS Developer</h2>"
            "<p>iOS (Objective-C/Swift)</p>"
            '<div class="jobs__list__job__details__tags__location">'
            "<p>Kyiv</p><p>Ukraine</p></div>"
            "<div data-job='"
            '{"title":"Senior iOS Developer","city":"Kyiv","location":"Ukraine",'
            '"url":"/jobs/senior-ios-developer-26100"}'
            "'></div></a>"
            '<a class="jobs__list__job" href="/jobs/senior-ios-developer-26100">dup</a>'
            '<a class="jobs__list__job" href="/jobs/senior-ios-bengaluru-26102">'
            "<h2>Senior iOS Developer</h2>"
            '<div class="jobs__list__job__details__tags__location">'
            "<p>Bengaluru</p><p>India</p></div>"
            "<div data-job='"
            '{"title":"Senior iOS Developer","city":"Bengaluru","location":"India",'
            '"url":"/jobs/senior-ios-bengaluru-26102"}'
            "'></div></a>"
            '<a class="jobs__list__job" href="/jobs/senior-ios-cairo-26103">'
            "<h2>Senior iOS Developer</h2>"
            '<div class="jobs__list__job__details__tags__location">'
            "<p>Cairo</p><p>Egypt</p></div></a>"
            '<a href="/jobs/java-developer-26101">Java Developer Java India Facebook</a>'
        )
    )

    result = bespoke.collect_luxoft()

    assert result.status == "healthy"
    assert result.items_scanned == 4
    assert len(result.jobs) == 3
    assert result.jobs[0]["title"] == "Senior iOS Developer"
    assert result.jobs[0]["url"] == "https://career.luxoft.com/jobs/senior-ios-developer-26100"
    assert result.jobs[0]["location"] == "Kyiv, Ukraine"


def test_luxoft_resolves_location_from_job_json_ld(stub) -> None:
    listing = (
        '<a class="jobs__list__job" href="/jobs/senior-mobile-engineer-ios-swift-24568">'
        "<h2>Senior Mobile Engineer - iOS Swift</h2>"
        "<p>iOS (Objective-C/Swift)</p></a>"
    )
    detail = (
        "<html><script type=\"application/ld+json\">"
        '{"@type":"JobPosting","title":"Senior Mobile Engineer - iOS Swift",'
        '"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",'
        '"addressLocality":"Kuala Lumpur","addressCountry":"MY"}}}'
        "</script></html>"
    )

    def handler(url: str, **_kwargs: object) -> str:
        if "senior-mobile-engineer-ios-swift-24568" in url and "specialization" not in url:
            return detail
        return listing

    stub(text=handler)
    result = bespoke.collect_luxoft()
    assert result.status == "healthy"
    assert len(result.jobs) == 1
    assert result.jobs[0]["location"] == "Kuala Lumpur, Malaysia"


def test_luxoft_reports_failure(stub) -> None:
    stub(text=_raiser("down"))

    assert bespoke.collect_luxoft().status == "failed"


def test_mind_studios_reads_api(stub) -> None:
    stub(
        payload=[
            {"title": "iOS Developer", "slug": "ios-developer", "id": 3, "location": "Kyiv"},
            {"title": "iOS Developer", "slug": ""},
            {"title": "Marketing Manager", "slug": "marketing"},
            "not-a-dict",
        ]
    )

    result = bespoke.collect_mind_studios()

    assert result.items_scanned == 4
    assert result.jobs == [
        {
            "company": "Mind Studios",
            "title": "iOS Developer",
            "url": "https://themindstudios.com/careers/ios-developer",
            "source": "company",
            "source_job_id": "3",
            "location": "Kyiv",
        }
    ]


def test_mind_studios_reads_wrapped_payload(stub) -> None:
    stub(payload={"data": [{"name": "Swift Engineer", "slug": "swift"}]})

    assert len(bespoke.collect_mind_studios().jobs) == 1


def test_mind_studios_empty_board_is_healthy(stub) -> None:
    stub(payload=[])

    result = bespoke.collect_mind_studios()

    assert result.status == "healthy"
    assert result.items_scanned == 0


def test_mind_studios_reports_failure(stub) -> None:
    stub(payload=_raiser("boom"))

    assert bespoke.collect_mind_studios().status == "failed"


def test_mwdn_dedupes_comeet_positions(stub) -> None:
    stub(
        text=(
            '<a class="comeet-position" href="/careers/co/mobile/ios-engineer/all/">'
            '<span class="comeet-position-name">iOS Engineer</span></a>'
            '<a class="comeet-position" href="/careers/co/mobile/ios-engineer/remote/">'
            '<span class="comeet-position-name">iOS Engineer</span></a>'
            '<a class="comeet-position" href="/careers/co/core/backend/all/">'
            '<span class="comeet-position-name">Backend</span></a>'
        )
    )

    result = bespoke.collect_mwdn()

    assert result.items_scanned == 2
    assert len(result.jobs) == 1


def test_mwdn_title_falls_back_to_slug(stub) -> None:
    stub(text='<a class="comeet-position" href="/careers/co/ios-engineer/"></a>')

    assert bespoke.collect_mwdn().jobs[0]["title"] == "ios engineer"


def test_mwdn_reports_failure(stub) -> None:
    stub(text=_raiser("boom"))

    assert bespoke.collect_mwdn().status == "failed"


def test_zone3000_filters_ios_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": 380,
            "title": "Middle + / Senior Mobile iOS Developer in Mobile System Team (#1204)",
            "url": "middle-----senior-mobile-ios-developer-in-mobile-system-team---1204-",
            "remote": 1,
        },
        {
            "id": 117,
            "title": "Customer Support Specialist",
            "url": "customer-support-specialist",
            "remote": 1,
        },
        {
            "id": 1,
            "title": "Android Platform Engineer",
            "url": "android-platform-engineer",
            "remote": 0,
        },
    ]
    monkeypatch.setattr(bespoke, "_fetch_zone3000_api_text", lambda: json.dumps(payload))

    result = bespoke.collect_zone3000()

    assert result.status == "healthy"
    assert result.source_id == "company:zone3000@zone3000.net"
    assert result.items_scanned == 3
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"].startswith("Middle + / Senior Mobile iOS")
    assert (
        result.jobs[0]["url"]
        == "https://zone3000.net/vacancies/middle-----senior-mobile-ios-developer-in-mobile-system-team---1204-"
    )
    assert result.jobs[0]["location"] == "Remote"
    assert result.jobs[0]["source_job_id"] == "380"


def test_zone3000_empty_list_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bespoke, "_fetch_zone3000_api_text", lambda: "[]")

    result = bespoke.collect_zone3000()

    assert result.status == "healthy"
    assert result.items_scanned == 0
    assert result.jobs == []


def test_zone3000_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bespoke, "_fetch_zone3000_api_text", _raiser("api down"))

    assert bespoke.collect_zone3000().status == "failed"
