import pytest

from collector import company_watchlist as watchlist


ADAPTIQ = {"name": "Adaptiq", "slug": "adaptiq", "career_url": "https://adaptiq.co/careers/"}
DEVART = {"name": "Devart", "slug": "devart", "career_url": "https://www.devart.com/vacancies/"}
DESCRIPTION = "Build reliable LLM APIs and agent orchestration with structured outputs and evaluations."


@pytest.fixture(autouse=True)
def no_detail_cache(monkeypatch):
    monkeypatch.delenv("DETAIL_CACHE_PATH", raising=False)


def adaptiq_page(*titles, total=None, page_size=1):
    cards = "".join(
        f'<a class="position-card" href="https://adaptiq.co/vacancies/{index}/">'
        f'<p class="title"><span>{title}</span><span class="-arrow"></span></p>'
        '<div class="job-main-description__left">Adaptiq FinTech</div>'
        '<div class="job-main-description__right"><p>Ukraine, Poland</p><p>Remote</p></div></a>'
        for index, title in enumerate(titles)
    )
    count = len(titles)
    return (f'<div class="position-list" data-post-count="{page_size}">'
            f'<div class="position-list__container" data-all-posts-count="{count if total is None else total}" '
            f'data-current-posts-count="{count}">{cards}</div></div>')


def devart_page():
    return ('<a class="vacancies" href="ai-engineer-skyvia.html"><h4>AI Engineer</h4>'
            '<div class="vacancies-locations__text">Remote</div>'
            '<div class="vacancies-locations__text">Ukraine</div></a>')


def devart_detail(heading="AI Engineer, Skyvia BU", breadcrumb=None):
    return (f'<main><div class="vacancies-location">Remote, Slovakia, Ukraine</div><h1>{heading}</h1>'
            '<div><ul class="vacancies-breadcrumb">'
            f'<li class="active">{breadcrumb or heading}</li></ul><h2>Requirements</h2><p>{DESCRIPTION}</p></div>'
            '<aside>Strong Python required for another role</aside></main>')


@pytest.mark.parametrize("next_page", [
    adaptiq_page("Senior iOS Engineer", total=2),
    adaptiq_page(total=2),
    adaptiq_page("Senior iOS Engineer", "Backend Engineer", total=3),
    "<html>Not a vacancy response</html>",
])
def test_adaptiq_incomplete_pages_are_degraded_and_keep_prior_jobs(monkeypatch, next_page):
    monkeypatch.setattr(watchlist, "fetch_text", lambda _: adaptiq_page("Senior iOS Engineer", total=2))
    monkeypatch.setattr(watchlist, "post_form_data", lambda *_a, **_k: next_page)
    result = watchlist.collect_watchlist_company(ADAPTIQ)
    assert result.status == "degraded"
    assert result.items_scanned == 1
    assert [job["title"] for job in result.jobs] == ["Senior iOS Engineer"]
    assert "Adaptiq page 2" in result.error


def test_adaptiq_later_request_failure_preserves_ios(monkeypatch):
    monkeypatch.setattr(watchlist, "fetch_text", lambda _: adaptiq_page("Senior iOS Engineer", total=2))

    def fail(*_a, **_k):
        raise RuntimeError("503")

    monkeypatch.setattr(watchlist, "post_form_data", fail)
    result = watchlist.collect_watchlist_company(ADAPTIQ)
    assert result.status == "degraded"
    assert len(result.jobs) == 1
    assert "503" in result.error


def test_adaptiq_pagination_budget_is_reported(monkeypatch):
    monkeypatch.setattr(watchlist, "_ADAPTIQ_PAGE_LIMIT", 2)
    monkeypatch.setattr(watchlist, "fetch_text", lambda _: adaptiq_page("Senior iOS Engineer", total=3))
    monkeypatch.setattr(watchlist, "post_form_data", lambda *_a, **_k:
                        adaptiq_page("Senior iOS Engineer", "Backend Engineer", total=3))
    result = watchlist.collect_watchlist_company(ADAPTIQ)
    assert result.status == "degraded"
    assert result.items_scanned == 2
    assert "scanned 2 of 3" in result.error


def test_adaptiq_explicit_empty_listing_is_healthy(monkeypatch):
    monkeypatch.setattr(watchlist, "fetch_text", lambda _: adaptiq_page())
    monkeypatch.setattr(watchlist, "post_form_data", lambda *_a, **_k: pytest.fail("unexpected request"))
    result = watchlist.collect_watchlist_company(ADAPTIQ)
    assert result.status == "healthy"
    assert result.items_scanned == 0


def test_adaptiq_malformed_initial_listing_is_failed(monkeypatch):
    monkeypatch.setattr(watchlist, "fetch_text", lambda _: "<main>Careers</main>")
    result = watchlist.collect_watchlist_company(ADAPTIQ)
    assert result.status == "failed"
    assert "container missing" in result.error


def test_devart_business_unit_title_exception_is_origin_scoped():
    description, _ = watchlist._matching_detail("AI Engineer", devart_detail(), "https://other.test/jobs/ai")
    assert description == ""


def test_career_cards_reject_foreign_detail_links():
    with pytest.raises(ValueError, match="career card"):
        watchlist.extract_ios_jobs("Devart", DEVART["career_url"],
                                   devart_page().replace("ai-engineer-skyvia.html", "https://other.test/vacancies/ai"))


def test_devart_watchlist_uses_official_career_page():
    company = next(c for c in watchlist.load_company_watchlist() if c["slug"] == "devart")
    assert company["career_url"] == DEVART["career_url"]


def test_geniusee_watchlist_uses_official_vacancies_page():
    company = next(c for c in watchlist.load_company_watchlist() if c["slug"] == "geniusee")
    assert company["career_url"] == "https://geniusee.com/vacancies"
    assert company["enabled"] is True


def test_luxoft_watchlist_uses_official_jobs_page():
    company = next(c for c in watchlist.load_company_watchlist() if c["slug"] == "luxoft")
    assert company["career_url"] == "https://career.luxoft.com/jobs"
    assert company["enabled"] is True


def test_eleks_watchlist_uses_official_vacancies_page():
    company = next(c for c in watchlist.load_company_watchlist() if c["slug"] == "eleks")
    assert company["career_url"] == "https://careers.eleks.com/vacancies/"
    assert company["enabled"] is True


