from __future__ import annotations

import json

import pytest

from collector import epam
from collector.epam import discover_ios_vacancy_urls, parse_vacancy_page
from storage.source_health import classify_degraded


def _html_with_job(job: dict) -> str:
    payload = {
        "props": {
            "pageProps": {
                "job": job,
            }
        }
    }
    return f'<html><script id="__NEXT_DATA__">{json.dumps(payload)}</script></html>'


def test_discover_ios_vacancy_urls_filters_slug() -> None:
    sitemap = """
    <urlset>
      <loc>https://careers.epam.com/en/vacancy/ios-software-engineer-blt1_en</loc>
      <loc>https://careers.epam.com/en/vacancy/senior-java-developer-blt2_en</loc>
      <loc>https://careers.epam.com/en/vacancy/swift-developer-blt3_en</loc>
    </urlset>
    """
    urls = discover_ios_vacancy_urls(sitemap)
    assert urls == [
        "https://careers.epam.com/en/vacancy/ios-software-engineer-blt1_en",
        "https://careers.epam.com/en/vacancy/swift-developer-blt3_en",
    ]


def test_parse_vacancy_page_accepts_ukraine_remote() -> None:
    html = _html_with_job(
        {
            "name": "Senior iOS Engineer",
            "uid": "blt-ua",
            "description": "Build SwiftUI apps",
            "is_expired": False,
            "metadata": {
                "country": [{"title": "Ukraine"}],
                "city": [{"title": "Kyiv"}],
                "vacancy_type": [{"title": "Remote"}],
            },
        }
    )
    job = parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/senior-ios-engineer-blt-ua_en")
    assert job is not None
    assert job["title"] == "Senior iOS Engineer"
    assert job["location"] == "Kyiv, Ukraine"
    assert job["remote"] == "remote"
    assert job["company"] == "EPAM"


def test_parse_vacancy_page_keeps_argentina_hybrid() -> None:
    html = _html_with_job(
        {
            "name": "iOS Software Engineer",
            "uid": "blt-ar",
            "description": "Swift and UIKit",
            "is_expired": False,
            "metadata": {
                "country": [
                    {"title": "Argentina"},
                    {"title": "Chile"},
                    {"title": "Colombia"},
                    {"title": "Mexico"},
                ],
                "city": [],
                "vacancy_type": [{"title": "Hybrid"}],
            },
        }
    )
    job = parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/ios-software-engineer-blt-ar_en")
    assert job is not None
    assert job["location"] == "Argentina / Chile / Colombia / Mexico"


def test_parse_vacancy_page_skips_expired() -> None:
    html = _html_with_job(
        {
            "name": "Senior iOS Engineer",
            "uid": "blt-exp",
            "is_expired": True,
            "metadata": {
                "country": [{"title": "Ukraine"}],
                "city": [],
                "vacancy_type": [{"title": "Remote"}],
            },
        }
    )
    job = parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/senior-ios-engineer-blt-exp_en")
    assert job is None


def test_discover_ios_vacancy_urls_dedupes() -> None:
    sitemap = (
        "<loc>https://careers.epam.com/en/vacancy/ios-engineer-blt1_en</loc>"
        "<loc>https://careers.epam.com/en/vacancy/ios-engineer-blt1_en</loc>"
    )

    assert discover_ios_vacancy_urls(sitemap) == [
        "https://careers.epam.com/en/vacancy/ios-engineer-blt1_en"
    ]


def test_parse_vacancy_page_without_next_data() -> None:
    assert parse_vacancy_page("<html></html>", "https://careers.epam.com/en/vacancy/x") is None


def test_parse_vacancy_page_with_invalid_json() -> None:
    html = '<script id="__NEXT_DATA__">{broken</script>'

    assert parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/x") is None


def test_parse_vacancy_page_without_job_object() -> None:
    html = _html_with_job(None)  # type: ignore[arg-type]

    assert parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/x") is None


def test_parse_vacancy_page_requires_a_title() -> None:
    html = _html_with_job({"name": "  ", "metadata": {}})

    assert parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/x") is None


def test_parse_vacancy_page_ignores_non_ios_roles() -> None:
    html = _html_with_job({"name": "Java Developer", "description": "Spring"})

    assert parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/x") is None


def test_parse_vacancy_page_reads_top_level_fields_and_blank_description() -> None:
    html = _html_with_job(
        {
            "name": "iOS Engineer",
            "text": "   ",
            "unique_id": "uid-7",
            "country": [{"name": "Ukraine"}],
            "city": [{"name": "Lviv"}],
            "vacancy_type": [{"name": "Hybrid office"}],
        }
    )

    job = parse_vacancy_page(html, "https://careers.epam.com/en/vacancy/ios-engineer")

    assert job is not None
    assert job["description"] is None
    assert job["source_job_id"] == "uid-7"
    assert job["location"] == "Lviv, Ukraine"
    assert job["remote"] == "hybrid"


@pytest.mark.parametrize(
    ("cities", "countries", "expected"),
    [
        ([], [], None),
        ([], ["Ukraine"], "Ukraine"),
        (["Kyiv"], [], "Kyiv"),
        (["Kyiv", "Lviv"], ["Ukraine"], "Kyiv / Lviv / Ukraine"),
    ],
)
def test_format_location(cities: list[str], countries: list[str], expected: str | None) -> None:
    assert epam._format_location(cities, countries) == expected


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        (["Remote"], "remote"),
        (["Hybrid"], "hybrid"),
        (["Office based"], "onsite"),
        (["On-site"], "onsite"),
        ([], "unknown"),
        (["Contract"], "unknown"),
    ],
)
def test_map_remote(types: list[str], expected: str) -> None:
    assert epam._map_remote(types) == expected


def test_titled_names_ignores_unusable_entries() -> None:
    assert epam._titled_names("not a list") == []
    assert epam._titled_names([{"title": "Ukraine"}, "x", {"other": 1}, {"name": " Kyiv "}]) == [
        "Ukraine",
        "Kyiv",
    ]


def _sitemap(*slugs: str) -> str:
    return "".join(f"<loc>https://careers.epam.com/en/vacancy/{slug}</loc>" for slug in slugs)


def test_collect_epam_returns_matching_vacancies(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = _html_with_job(
        {
            "name": "Senior iOS Engineer",
            "uid": "blt1",
            "metadata": {
                "country": [{"title": "Ukraine"}],
                "city": [{"title": "Kyiv"}],
                "vacancy_type": [{"title": "Remote"}],
            },
        }
    )

    def fake_fetch(url: str, **_kwargs) -> str:
        return _sitemap("ios-engineer-blt1_en") if url.endswith(".gz") else detail

    monkeypatch.setattr(epam, "fetch_text", fake_fetch)

    result = epam.collect_epam()

    assert result.status == "healthy"
    assert result.items_scanned == 1
    assert result.source_id == "company:epam@careers.epam.com"
    assert [job["title"] for job in result.jobs] == ["Senior iOS Engineer"]


def test_collect_epam_is_healthy_when_sitemap_has_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(epam, "fetch_text", lambda url, **_k: _sitemap("java-developer-blt2_en"))

    result = epam.collect_epam()

    assert result.status == "healthy"
    assert result.items_scanned == 1
    assert result.jobs == []


def test_collect_epam_scans_the_whole_sitemap_not_only_ios_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = _html_with_job({"name": "Senior iOS Engineer", "uid": "blt1", "metadata": {}})
    sitemap = _sitemap("ios-engineer-blt1_en", *(f"java-developer-blt{n}_en" for n in range(2, 12)))
    monkeypatch.setattr(epam, "fetch_text", lambda url, **_k: sitemap if url.endswith(".gz") else detail)
    baseline = {"company:epam@careers.epam.com": {"best_scanned": 12, "search_policy": "ios"}}

    result = epam.collect_epam()

    assert result.items_scanned == 11
    assert classify_degraded([result], baseline) == []
    assert len(result.jobs) == 1


def test_collect_epam_tolerates_some_broken_detail_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = _html_with_job(
        {
            "name": "iOS Engineer",
            "uid": "blt1",
            "metadata": {"country": [{"title": "Ukraine"}], "city": [], "vacancy_type": []},
        }
    )

    def fake_fetch(url: str, **_kwargs) -> str:
        if url.endswith(".gz"):
            return _sitemap("ios-engineer-blt1_en", "ios-engineer-blt2_en")
        if "blt2" in url:
            raise RuntimeError("detail down")
        return detail

    monkeypatch.setattr(epam, "fetch_text", fake_fetch)

    result = epam.collect_epam()

    assert result.status == "healthy"
    assert result.items_scanned == 1
    assert len(result.jobs) == 1


def test_collect_epam_fails_when_every_detail_page_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str, **_kwargs) -> str:
        if url.endswith(".gz"):
            return _sitemap("ios-engineer-blt1_en")
        raise RuntimeError("detail down")

    monkeypatch.setattr(epam, "fetch_text", fake_fetch)

    result = epam.collect_epam()

    assert result.status == "failed"
    assert "all 1 vacancy detail fetches failed" in (result.error or "")


def test_collect_epam_fails_when_sitemap_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **_kwargs) -> str:
        raise RuntimeError("sitemap down")

    monkeypatch.setattr(epam, "fetch_text", boom)

    result = epam.collect_epam()

    assert result.status == "failed"
    assert "sitemap down" in (result.error or "")


def test_full_body_reaches_admission_instead_of_summary(monkeypatch):
    summary = "Build AI services."
    body = "Requirements\nStrong Python expertise required.\nBuild LLM integrations."
    observed = []

    def admit(title, description):
        observed.append(description)
        return True

    monkeypatch.setattr(epam, "is_target_job", admit)
    job = parse_vacancy_page(_html_with_job({
        "name": "AI Software Engineer", "description": summary, "text": body,
    }), "https://example.com/jobs/1")
    assert observed == [body]
    assert job["description"] == body


@pytest.mark.parametrize("text", [None, "", "  \n "])
def test_missing_full_body_falls_back_to_summary(text):
    job = parse_vacancy_page(_html_with_job({
        "name": "Senior iOS Engineer", "description": "Build Swift SDKs.", "text": text,
    }), "https://example.com/jobs/1")
    assert job["description"] == "Build Swift SDKs."


