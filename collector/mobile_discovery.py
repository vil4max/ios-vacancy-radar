"""Find DOU companies whose own careers page shows iOS or mobile hiring.

Company size is not a criterion: any company in the jobs.dou.ua catalog can
hire iOS engineers. A company is registered only when the signal is strong and
the radar's own watchlist collector can parse its careers page, so a new entry
does not become a permanently degraded source.
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collector.career_discovery import discover_career_url
from collector.dou_careers import extract_company_site_url

IOS = re.compile(r"(?i)(?<![a-z0-9])(?:ios|swift|swiftui|iphone|ipad|objective[- ]?c)(?![a-z0-9])")
MOBILE = re.compile(
    r"(?i)(?<![a-zа-яіїєґ0-9])(?:mobile|android|flutter|react[ -]?native|kotlin multiplatform|kmm|"
    r"мобільн\w*|мобильн\w*)(?![a-zа-яіїєґ0-9])"
)
# A bare "mobile" is often benefit text ("mobile communication"); a named stack is a role.
MOBILE_STACK = ("android", "flutter", "react native", "react-native", "reactnative", "kmm", "kotlin multiplatform")
_SKIP_SITE_HOSTS = ("dou.ua", "facebook.com", "linkedin.com", "instagram.com", "t.me")
_PAGE_LINK = re.compile(r"(?i)(?:/page/\d+/?$|[?&](?:page|p)=\d+)")
_LIST_LINK = re.compile(
    r"(?i)(?:vacanc|open[ -]?(?:position|role)|all[ -]?(?:jobs|positions|vacancies)|job[ -]?openings|"
    r"вакансі|вакансии|відкриті|открытые)"
)
# Training schools and event pages talk about careers in iOS without hiring for them.
_NOT_A_CAREERS_PAGE = re.compile(r"(?i)(?:event|webinar|course|lesson|/blog|/news)")
_MAX_EXTRA_PAGES = 5
# Below this much visible text a page is a client-rendered shell, not a vacancy list.
_MIN_PAGE_TEXT = 400

Fetch = Callable[[str], tuple[int, str]]


def page_text(html: str) -> str:
    document = BeautifulSoup(html, "lxml")
    for node in document(["script", "style", "noscript", "svg"]):
        node.decompose()
    return " ".join(document.get_text(" ").split())


def signals(text: str) -> dict[str, list[str]]:
    return {
        "ios": sorted({match.group(0).lower() for match in IOS.finditer(text)}),
        "mobile": sorted({match.group(0).lower() for match in MOBILE.finditer(text)}),
    }


def verdict(found: dict[str, list[str]]) -> str:
    return "ios" if found["ios"] else "mobile" if found["mobile"] else "none"


def extra_pages(url: str, html: str) -> list[str]:
    """Same-host pagination and "all vacancies" links a careers landing page may hide roles behind."""
    host = urlparse(url).hostname
    pages: list[str] = []
    lists: list[str] = []
    for anchor in BeautifulSoup(html, "lxml").select("a[href]"):
        href = urljoin(url, str(anchor.get("href")))
        if urlparse(href).hostname != host or href.split("#")[0].rstrip("/") == url.rstrip("/"):
            continue
        if _PAGE_LINK.search(href):
            if href not in pages:
                pages.append(href)
        elif _LIST_LINK.search(f"{href} {anchor.get_text(' ', strip=True)}") and href not in lists:
            lists.append(href)
    return (lists[:1] + pages)[:_MAX_EXTRA_PAGES]


def dou_vacancy_signals(html: str) -> dict[str, list[str]]:
    titles = [anchor.get_text(" ", strip=True) for anchor in BeautifulSoup(html, "lxml").select("a.vt")]
    return signals(" ".join(titles))


def inspect_company(slug: str, fetch: Fetch, *, has_dou_vacancies: bool) -> dict[str, Any]:
    """Read the company's DOU vacancies and its own careers page; never retries a refusal."""
    row: dict[str, Any] = {"slug": slug, "dou": None, "career_url": None, "career_state": None, "career": None}
    if has_dou_vacancies:
        status, html = fetch(f"https://jobs.dou.ua/companies/{slug}/vacancies/")
        row["dou"] = dou_vacancy_signals(html) if status == 200 else None
    status, profile = fetch(f"https://jobs.dou.ua/companies/{slug}/")
    site = extract_company_site_url(profile) if status == 200 else None
    host = (urlparse(site or "").hostname or "").lower()
    if not site or any(host == skip or host.endswith(f".{skip}") for skip in _SKIP_SITE_HOSTS):
        row["career_state"] = "no_site"
        return row
    status, home = fetch(site)
    if status != 200:
        row["career_state"] = "unreadable"
        return row
    career_url = discover_career_url(site, home)
    if not career_url or urlparse(career_url).path in ("", "/") or _NOT_A_CAREERS_PAGE.search(career_url):
        # A homepage "iOS" is usually an App Store link, not a vacancy.
        row["career_state"] = "career_not_found"
        return row
    if (urlparse(career_url).hostname or "").lower().endswith("dou.ua"):
        # The DOU RSS feed already carries vacancies published on DOU.
        row["career_state"] = "on_dou"
        return row
    if career_url.rstrip("/") == site.rstrip("/"):
        html = home
    else:
        status, html = fetch(career_url)
        if status != 200:
            row["career_state"] = "unreadable"
            return row
    text = page_text(html)
    found = signals(text)
    if verdict(found) == "none":
        for extra in extra_pages(career_url, html):
            status, extra_html = fetch(extra)
            if status != 200:
                continue
            text = f"{text} {page_text(extra_html)}"
            found = signals(text)
            if verdict(found) == "ios":
                break
    row["career_url"] = career_url
    row["career_state"] = "read" if len(text) >= _MIN_PAGE_TEXT else "js_rendered"
    row["career"] = found if row["career_state"] == "read" else None
    return row


def strength(row: dict[str, Any]) -> str | None:
    """"ios" or "mobile_stack" for a readable careers page with a strong signal, else None."""
    if row.get("career_state") != "read":
        return None
    career = row.get("career") or {"ios": [], "mobile": []}
    dou = row.get("dou") or {"ios": [], "mobile": []}
    if career["ios"] or dou["ios"]:
        return "ios"
    if any(word in MOBILE_STACK for word in career["mobile"] + dou["mobile"]):
        return "mobile_stack"
    return None
