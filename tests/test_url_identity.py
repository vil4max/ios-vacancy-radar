from __future__ import annotations

from parser.normalize import canonicalize_url


def test_canonicalize_url_strips_trailing_slash() -> None:
    assert canonicalize_url("https://Example.com/jobs/123/") == "https://example.com/jobs/123"


def test_canonicalize_url_removes_fragment() -> None:
    assert canonicalize_url("https://example.com/jobs/123#apply") == "https://example.com/jobs/123"


def test_canonicalize_url_removes_utm_params() -> None:
    assert (
        canonicalize_url("https://example.com/jobs/123?utm_source=a&utm_medium=b")
        == "https://example.com/jobs/123"
    )


def test_canonicalize_url_sorts_query_params() -> None:
    assert (
        canonicalize_url("https://example.com/jobs/123?b=2&a=1")
        == "https://example.com/jobs/123?a=1&b=2"
    )


def test_canonicalize_url_preserves_meaningful_query_params() -> None:
    assert (
        canonicalize_url("https://example.com/jobs/123?gh_jid=4912838101&utm_source=x")
        == "https://example.com/jobs/123?gh_jid=4912838101"
    )


def test_canonicalize_url_normalizes_andersen_career_host_alias() -> None:
    assert canonicalize_url(
        "https://people.andersenlab.com/vacancy/2509387"
    ) == canonicalize_url(
        "https://people-andersenlab.com/vacancy/2509387"
    )
