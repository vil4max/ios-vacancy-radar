from __future__ import annotations

from collector.career_discovery import discover_career_url


def test_discover_career_url_prefers_official_ats_link() -> None:
    html = """
    <a href="/blog/jobs-to-be-done">Article</a>
    <a href="/about/careers">Careers</a>
    <a href="https://jobs.lever.co/acme">Open positions</a>
    """

    assert discover_career_url("https://acme.com", html) == "https://jobs.lever.co/acme"


def test_discover_career_url_resolves_relative_career_link() -> None:
    html = '<a href="/company/careers/">Join our team</a>'

    assert discover_career_url("https://acme.com/about", html) == "https://acme.com/company/careers/"


def test_discover_career_url_accepts_existing_career_page() -> None:
    assert (
        discover_career_url("https://careers.acme.com/open-positions", "")
        == "https://careers.acme.com/open-positions"
    )


def test_discover_career_url_returns_none_without_career_signal() -> None:
    assert discover_career_url("https://acme.com", '<a href="/services">Services</a>') is None
