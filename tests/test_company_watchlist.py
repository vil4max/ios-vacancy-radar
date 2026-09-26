from __future__ import annotations

import requests

from collector import company_watchlist
from collector.company_watchlist import collect_watchlist_company, extract_ios_jobs
from collector.types import STATUS_FAILED


def test_extract_ios_jobs_keeps_relevant_anchor_and_json_ld() -> None:
    html = """
    <a href="/jobs/senior-ios-engineer">Senior iOS Engineer</a>
    <a href="/jobs/backend-engineer">Backend Engineer</a>
    <article><a href="/jobs/mobile">Mobile Engineer</a><span>Native Swift and Kotlin</span></article>
    <script type="application/ld+json">
      {"@type":"JobPosting","title":"Swift Developer","url":"/vacancies/swift"}
    </script>
    """

    jobs, scanned = extract_ios_jobs("Acme", "https://acme.test/careers", html)

    assert {job["title"] for job in jobs} == {
        "Senior iOS Engineer",
        "Mobile Engineer",
        "Swift Developer",
    }
    assert scanned == 4


def test_extract_ios_jobs_rejects_marketing_page_without_job_url() -> None:
    html = '<a href="/services/ios-development">iOS Development Services</a>'

    jobs, scanned = extract_ios_jobs("Acme", "https://acme.test/careers", html)

    assert jobs == []
    assert scanned == 0


def test_extract_ios_jobs_does_not_share_description_between_sibling_links() -> None:
    html = """
    <div class="vacancies">
      <a href="/jobs/java-engineer">Java Software Engineer</a>
      <a href="/jobs/ios-engineer">Senior iOS Engineer</a>
    </div>
    """

    jobs, scanned = extract_ios_jobs("Acme", "https://acme.test/careers", html)

    assert [job["title"] for job in jobs] == ["Senior iOS Engineer"]
    assert scanned == 2


def test_extract_ios_jobs_excludes_explicit_zoolatech_mexico_location() -> None:
    html = """
    <a class="item" href="/career/vacancies/swift-ios-mexico-1.html">
      <span class="name">Swift / iOS Engineer</span>
      <span class="country">Mexico</span>
    </a>
    <a class="item" href="/career/vacancies/swift-ios-europe-2.html">
      <span class="name">Swift / iOS Engineer</span>
      <span class="country">Eastern Europe</span>
    </a>
    """

    jobs, _ = extract_ios_jobs("Zoolatech", "https://zoolatech.com/career/vacancies/", html)

    assert len(jobs) == 1
    assert jobs[0]["location"] == "Eastern Europe"


def test_extract_ios_jobs_reads_avenga_teamtailor_location() -> None:
    html = """
    <div>
      <a href="/jobs/8255594-senior-ios-engineer">Senior iOS Engineer</a>
      <div class="mt-1 text-md"><span>Buenos Aires</span></div>
    </div>
    """

    jobs, _ = extract_ios_jobs("Avenga", "https://career.avenga.com/jobs", html)

    assert jobs[0]["location"] == "Buenos Aires"


def test_unresolved_company_is_an_explicit_failed_source() -> None:
    result = collect_watchlist_company(
        {
            "name": "Acme",
            "slug": "acme",
            "company_site_url": "https://acme.test",
            "career_url": None,
        }
    )

    assert result.status == STATUS_FAILED
    assert result.source_id == "company-watchlist:acme"
    assert result.error == "official career URL unresolved"


def test_rate_limited_page_retries_with_impersonation(monkeypatch) -> None:
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError(response=response)
    monkeypatch.setattr(company_watchlist, "fetch_text", lambda _url: (_ for _ in ()).throw(error))
    monkeypatch.setattr(
        company_watchlist,
        "fetch_impersonated",
        lambda _url: '<a href="/jobs/ios">iOS Engineer</a>',
    )

    result = collect_watchlist_company(
        {"name": "Acme", "slug": "acme", "career_url": "https://acme.test/careers"}
    )

    assert result.status == "healthy"
    assert [job["title"] for job in result.jobs] == ["iOS Engineer"]


def test_conscensia_uses_wordpress_api(monkeypatch) -> None:
    monkeypatch.setattr(
        company_watchlist,
        "fetch_json",
        lambda url: [
            {
                "id": 42,
                "title": {"rendered": "Senior iOS Engineer"},
                "link": "https://careers.conscensia.com/jobs/ios/",
            },
            {
                "id": 43,
                "title": {"rendered": "Backend Engineer"},
                "link": "https://careers.conscensia.com/jobs/backend/",
            },
        ],
    )

    result = collect_watchlist_company(
        {
            "name": "Conscensia",
            "slug": "conscensia",
            "career_url": "https://careers.conscensia.com/jobs/",
        }
    )

    assert result.status == "healthy"
    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["Senior iOS Engineer"]


def test_conscensia_retries_blocked_api_with_impersonation(monkeypatch) -> None:
    response = requests.Response()
    response.status_code = 454
    error = requests.HTTPError(response=response)
    monkeypatch.setattr(
        company_watchlist,
        "fetch_json",
        lambda _url: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        company_watchlist,
        "fetch_impersonated",
        lambda _url: '[{"id": 42, "title": {"rendered": "iOS Engineer"}, "link": "https://careers.conscensia.com/jobs/ios/"}]',
    )

    result = collect_watchlist_company(
        {
            "name": "Conscensia",
            "slug": "conscensia",
            "career_url": "https://careers.conscensia.com/jobs/",
        }
    )

    assert result.status == "healthy"
    assert result.items_scanned == 1
    assert [job["title"] for job in result.jobs] == ["iOS Engineer"]


def test_svitla_api_paginates_and_keeps_ios_job(monkeypatch) -> None:
    pages = {
        1: {"pages": 2, "items": [{"id": 1, "position": "Backend Engineer"}]},
        2: {
            "pages": 2,
            "items": [
                {
                    "id": 2,
                    "position": "Middle iOS Developer",
                    "slug": "middle-ios-developer",
                    "jobCities": [{"city": {"name": "Kyiv", "country": "Ukraine"}}],
                }
            ],
        },
    }
    monkeypatch.setattr(
        company_watchlist,
        "fetch_json",
        lambda url: pages[int(url.rsplit("=", 1)[1])],
    )

    result = collect_watchlist_company(
        {
            "name": "Svitla Systems",
            "slug": "svitla-systems-inc",
            "career_url": "https://svitla.com/career/",
        }
    )

    assert result.items_scanned == 2
    assert result.jobs[0]["location"] == "Kyiv, Ukraine"
    assert result.jobs[0]["url"] == "https://svitla.com/career/job/middle-ios-developer"


def _mobilunity_card(title: str, slug: str, country: str = "Ukraine") -> str:
    return f"""
    <div class="one-vacancy">
        <div class="svacancy-header">
            <div class="svacancy-badges">
                <div class="vacancy-country"><img alt="{country}"></div>
            </div>
        </div>
        <div class="svacancy-content">
            <h5 class="svacancy-name"><a href="https://mobilunity.com/vacancy/{slug}/">{title}</a></h5>
            <div class="svacancy-excerpt"><p>Synthetic listing for tests.</p></div>
        </div>
    </div>
    """


def test_mobilunity_paginates_and_skips_filter_chips(monkeypatch) -> None:
    # The tag sidebar's filter chips all share the listing's own URL (a real site quirk, not a
    # test fixture simplification) -- the fix must key off card markup, not "does this href look
    # job-shaped", or a chip like "iOS 1" becomes a fake vacancy.
    page_one = f"""
    <script>var paramsVacancy = {{"ajaxVacancy":"https://mobilunity.com/wp-admin/admin-ajax.php","nonce":"deadbeef01"}};</script>
    <ul class="vacancy-term-list term-list-tech">
        <li><a href="/vacancy/?tech=ios" class="vacancy-term-item"><span class="term-name">iOS</span><span class="term-count">1</span></a></li>
    </ul>
    <div class="vacancies-wrap" data-max="2">
        {_mobilunity_card("iOS Platform Engineer", "ios-platform-engineer")}
        <div class="one-vacancy">
            <div class="svacancy-content">
                <h5 class="svacancy-name"><a href="https://mobilunity.com/vacancy/backend-engineer/">Backend Engineer</a></h5>
            </div>
        </div>
    </div>
    """
    page_two = _mobilunity_card("iOS Release Engineer", "ios-release-engineer", country="Poland")
    monkeypatch.setattr(company_watchlist, "fetch_text", lambda _url: page_one)
    monkeypatch.setattr(
        company_watchlist,
        "post_form_data",
        lambda _url, form, **_kwargs: page_two if form.get("current_page") == "2" else (_ for _ in ()).throw(
            AssertionError(f"unexpected form: {form}")
        ),
    )

    result = collect_watchlist_company(
        {"name": "Mobilunity", "slug": "mobilunity", "career_url": "http://mobilunity.com/vacancy/"}
    )

    assert result.status == "healthy"
    assert result.items_scanned == 3
    titles = {job["title"] for job in result.jobs}
    assert titles == {"iOS Platform Engineer", "iOS Release Engineer"}
    assert all(job["url"].startswith("https://mobilunity.com/vacancy/") for job in result.jobs)
    assert all("tech=" not in job["url"] for job in result.jobs)
    second = next(job for job in result.jobs if job["title"] == "iOS Release Engineer")
    assert second["location"] == "Poland"


def test_label_your_data_uses_workable_widget(monkeypatch) -> None:
    from collector import ats_boards

    monkeypatch.setattr(
        ats_boards,
        "fetch_json",
        lambda url, **_kwargs: {
            "jobs": [
                {
                    "title": "iOS Engineer",
                    "url": "https://apply.workable.com/j/IOS1/",
                    "shortcode": "IOS1",
                    "locations": [{"city": "Kyiv", "country": "Ukraine"}],
                    "telecommuting": True,
                },
                {"title": "Data Annotator", "shortcode": "DATA1"},
            ]
        },
    )

    result = collect_watchlist_company(
        {
            "name": "Label Your Data",
            "slug": "label-your-data",
            "career_url": "https://apply.workable.com/labelyourdata/",
        }
    )

    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["iOS Engineer"]
    assert result.jobs[0]["remote"] == "remote"


def test_api_collectors_fail_on_unexpected_payload(monkeypatch) -> None:
    monkeypatch.setattr(company_watchlist, "fetch_json", lambda _url: {})

    result = collect_watchlist_company(
        {
            "name": "Conscensia",
            "slug": "conscensia",
            "career_url": "https://careers.conscensia.com/jobs/",
        }
    )

    assert result.status == STATUS_FAILED
    assert "unexpected payload" in (result.error or "")


def test_playrix_uses_api_and_counts_only_visible_jobs(monkeypatch) -> None:
    payloads = {
        "job/getList": {
            "success": True,
            "items": [
                {
                    "id": 1,
                    "name": "Middle iOS Engineer",
                    "code": "middle-ios-engineer",
                    "parentId": 10,
                    "isHidden": False,
                    "workFormat": "Remote",
                },
                {
                    "id": 2,
                    "name": "Backend Engineer",
                    "code": "backend-engineer",
                    "parentId": 10,
                    "isHidden": False,
                },
                {
                    "id": 3,
                    "name": "Hidden iOS Engineer",
                    "code": "hidden-ios-engineer",
                    "parentId": 10,
                    "isHidden": True,
                },
            ],
        },
        "job/getSectionList": {
            "success": True,
            "items": [{"id": 10, "code": "engineering"}],
        },
    }
    monkeypatch.setattr(company_watchlist, "_playrix_payload", payloads.__getitem__)

    result = collect_watchlist_company(
        {
            "name": "Playrix",
            "slug": "playrix",
            "career_url": "https://playrix.com/job/open",
        }
    )

    assert result.status == "healthy"
    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["Middle iOS Engineer"]
    assert result.jobs[0]["url"] == "https://playrix.com/job/open/engineering/middle-ios-engineer"


def test_valtech_api_paginates_and_keeps_ios_job(monkeypatch) -> None:
    pages = {
        0: {
            "list": [
                {
                    "id": 1,
                    "title": "Backend Engineer",
                    "url": "/career/jobs/backend/",
                    "offices": ["Berlin"],
                }
            ],
            "page": {"itemTotal": 2},
        },
        1: {
            "list": [
                {
                    "id": 2,
                    "title": "Senior/Lead iOS Developer",
                    "url": "/career/jobs/4961788101/",
                    "offices": ["Sofia"],
                }
            ],
            "page": {"itemTotal": 2},
        },
    }

    def fake_fetch_json(url: str):
        if "offset=0" in url:
            return pages[0]
        if "offset=1" in url:
            return pages[1]
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(company_watchlist, "fetch_json", fake_fetch_json)

    result = collect_watchlist_company(
        {
            "name": "Valtech",
            "slug": "valtech",
            "career_url": "https://www.valtech.com/career/jobs/",
        }
    )

    assert result.status == "healthy"
    assert result.items_scanned == 2
    assert [job["title"] for job in result.jobs] == ["Senior/Lead iOS Developer"]
    assert result.jobs[0]["location"] == "Sofia"
    assert result.jobs[0]["url"] == "https://www.valtech.com/career/jobs/4961788101/"
