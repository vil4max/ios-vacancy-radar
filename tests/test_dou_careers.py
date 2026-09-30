from __future__ import annotations

from collector.dou_careers import collect_jobs_from_career_site, extract_company_site_url


def test_extract_company_site_url_reads_div_site_link() -> None:
    html = """
    <div class="site">
        <a href="https://career.softserveinc.com/en-us/vacancies" target="_blank" rel="nofollow">career.softserveinc.com/en-us/vacancies</a>
    </div>
    """

    assert extract_company_site_url(html) == "https://career.softserveinc.com/en-us/vacancies"


def test_extract_company_site_url_decodes_html_entities() -> None:
    html = """
    <div class="site">
        <a href="https://career.sigma.software/?utm_source=dou_profile&amp;utm_medium=sscw" target="_blank" rel="nofollow">career.sigma.software</a>
    </div>
    """

    assert (
        extract_company_site_url(html)
        == "https://career.sigma.software/?utm_source=dou_profile&utm_medium=sscw"
    )


def test_collect_jobs_from_career_site_scrapes_generic_ios_links() -> None:
    page_html = """
    <a href="/en-us/vacancies/senior-ios-engineer-123">Senior iOS Engineer</a>
    <a href="/en-us/vacancies/java-developer-456">Java Developer</a>
    """

    class FakeResponse:
        status_code = 200
        text = page_html

        def json(self):
            raise ValueError("not json")

    class FakeSession:
        def get(self, url: str, timeout: int = 30) -> FakeResponse:
            if url.endswith("/jobs.json"):
                response = FakeResponse()
                response.status_code = 404
                response.text = ""
                return response
            return FakeResponse()

    jobs = collect_jobs_from_career_site(
        "SoftServe",
        "https://career.softserveinc.com/en-us/vacancies",
        FakeSession(),  # type: ignore[arg-type]
    )

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior iOS Engineer"
    assert jobs[0]["url"] == "https://career.softserveinc.com/en-us/vacancies/senior-ios-engineer-123"
    assert jobs[0]["source"] == "company"
