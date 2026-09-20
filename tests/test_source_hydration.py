

from collector import bespoke, company_watchlist as watchlist


DESCRIPTION = 'Build reliable LLM APIs and agent orchestration with structured outputs and evaluations.'
BASE = 'https://acme.test/careers'


def collect(monkeypatch, detail):
    listing = '<a href="/jobs/ios">Senior iOS Engineer</a><a href="/jobs/ai">AI Engineer</a>'
    monkeypatch.setattr(watchlist, 'fetch_text', lambda _: listing)
    monkeypatch.setattr(watchlist, '_fetch_ai_detail', detail)
    return watchlist.collect_watchlist_company({'name': 'Acme', 'career_url': BASE})


def test_rbi_all_failed_detail_pages_are_not_healthy(monkeypatch):
    monkeypatch.setattr(bespoke, 'fetch_text', lambda url:
                        '<loc>https://www.rbi-ri.com.ua/career/ai-engineer</loc>'
                        if url.endswith('sitemap.xml') else '<html>No verified job</html>')
    result = bespoke.collect_rbi()
    assert result.status == 'failed'
    assert result.jobs == []


def test_rbi_generic_career_page_does_not_verify_sitemap_job(monkeypatch):
    monkeypatch.setattr(bespoke, 'fetch_text', lambda url:
                        '<loc>https://www.rbi-ri.com.ua/career/ios-engineer</loc>'
                        if url.endswith('sitemap.xml') else '<title>Careers</title>')
    result = bespoke.collect_rbi()
    assert result.status == 'failed'
    assert result.jobs == []
