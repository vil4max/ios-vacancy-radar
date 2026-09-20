from __future__ import annotations

import html as html_lib
import re
import time
from typing import Any, Callable
from urllib.parse import urljoin

from collector.results import source_failed, source_ok
from collector.types import SourceResult
from integrations.http_client import fetch_json, fetch_text, fetch_text_allowing_bot_wall
from parser.normalize import is_target_job


def collect_wp_rest(company: str, endpoint: str) -> SourceResult:
    started = time.perf_counter()
    try:
        payload = fetch_json(endpoint)
        items = payload if isinstance(payload, list) else []
        jobs: list[dict[str, Any]] = []
        for item in items:
            title_obj = item.get("title") or {}
            rendered = title_obj.get("rendered") if isinstance(title_obj, dict) else title_obj
            title = re.sub(r"<[^>]+>", "", str(rendered or "")).strip()
            title = html_lib.unescape(title)
            job_url = str(item.get("link") or "")
            content = item.get("content") or ""
            description = str(content.get("rendered") or "") if isinstance(content, dict) else str(content)
            if not is_target_job(title, description) or not job_url:
                continue
            jobs.append(
                {
                    "company": company,
                    "title": title,
                    "url": job_url,
                    "source": "company",
                    "source_job_id": item.get("id"),
                    "description": description or None,
                }
            )
        return source_ok(company, endpoint, jobs, started, scanned=len(items))
    except Exception as error:  # noqa: BLE001
        return source_failed(company, endpoint, error, started)


def title_from_slug(value: str) -> str:
    path = value.split("?", 1)[0]
    slug = [part for part in path.split("/") if part]
    if not slug:
        return value
    return slug[-1].replace("-", " ").replace("_", " ").strip()


def absolute_url(href: str, base_url: str) -> str:
    trimmed = href.strip()
    if trimmed.startswith("http://") or trimmed.startswith("https://"):
        return trimmed
    return urljoin(base_url, trimmed)


def collect_html_regex(
    company: str,
    list_url: str,
    base_url: str,
    pattern: str,
    *,
    url_group: int = 0,
    title_group: int | None = None,
    use_list_url_as_job_url: bool = False,
    allow_bot_wall: bool = False,
) -> SourceResult:
    started = time.perf_counter()
    try:
        if allow_bot_wall:
            html = fetch_text_allowing_bot_wall(list_url)
            if html is None:
                return source_ok(company, list_url, [], started, scanned=0)
        else:
            html = fetch_text(list_url)

        regex = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in regex.finditer(html):
            group_count = len(match.groups())
            if title_group is not None and title_group <= group_count:
                title = (match.group(title_group) or "").strip()
            elif url_group <= group_count:
                title = title_from_slug(match.group(url_group) or "")
            else:
                continue
            if not title:
                continue

            if use_list_url_as_job_url:
                job_url = list_url
                dedupe_key = title
            else:
                if url_group > group_count:
                    continue
                job_url = absolute_url(match.group(url_group) or "", base_url)
                dedupe_key = job_url

            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if not is_target_job(title):
                continue
            jobs.append({"company": company, "title": title, "url": job_url, "source": "company"})
        return source_ok(company, list_url, jobs, started, scanned=len(seen))
    except Exception as error:  # noqa: BLE001
        return source_failed(company, list_url, error, started)


def collect_soup_links(
    company: str,
    list_url: str,
    *,
    base_url: str,
    selector: str,
    title_selector: str | None = None,
    location_selector: str | None = None,
    href_contains: str | None = None,
    skip_hrefs: set[str] | None = None,
    skip_exact: set[str] | None = None,
    title_transform: Callable[[str], str] | None = None,
    pagination_selector: str | None = None,
    max_pages: int = 20,
) -> SourceResult:
    started = time.perf_counter()
    try:
        from bs4 import BeautifulSoup

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        skip_hrefs = skip_hrefs or set()
        skip_exact = skip_exact or set()

        pending: list[str] = [list_url]
        visited: set[str] = set()
        while pending:
            page_url = pending.pop(0)
            if page_url in visited or len(visited) >= max_pages:
                continue
            visited.add(page_url)
            html = fetch_text(page_url)
            document = BeautifulSoup(html, "lxml")

            if pagination_selector:
                for link in document.select(pagination_selector):
                    href = (link.get("href") or "").strip()
                    if not href:
                        continue
                    candidate = absolute_url(href, base_url)
                    if candidate not in visited and candidate not in pending:
                        pending.append(candidate)

            for anchor in document.select(selector):
                href = (anchor.get("href") or "").strip()
                if not href:
                    continue
                if href_contains and href_contains not in href:
                    continue
                absolute = absolute_url(href, base_url)
                if absolute in skip_exact or href in skip_exact:
                    continue
                if any(absolute.rstrip("/").endswith(skip.rstrip("/")) for skip in skip_hrefs):
                    continue
                if absolute in seen:
                    continue
                seen.add(absolute)

                title = ""
                if title_selector:
                    node = anchor.select_one(title_selector)
                    if node:
                        title = node.get_text(" ", strip=True)
                if not title:
                    title = anchor.get_text(" ", strip=True)
                if not title:
                    title = title_from_slug(absolute)
                if title_transform:
                    title = title_transform(title)
                if not is_target_job(title):
                    continue

                location = None
                if location_selector:
                    node = anchor.select_one(location_selector)
                    if node:
                        location = node.get_text(" ", strip=True) or None

                job = {"company": company, "title": title, "url": absolute, "source": "company"}
                if location:
                    job["location"] = location
                jobs.append(job)

        return source_ok(company, list_url, jobs, started, scanned=len(seen))
    except Exception as error:  # noqa: BLE001
        return source_failed(company, list_url, error, started)
