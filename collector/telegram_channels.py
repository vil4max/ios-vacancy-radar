from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from storage.telegram_cursors import default_telegram_cursors_path, load_telegram_cursors
from parser.normalize import is_target_job

from collector.types import SourceResult

TELEGRAM_CHANNELS: tuple[str, ...] = (
    "itrecruit_ua",
    "remotejobss",
    "itfreelancers",
    "mobile_jobs",
    "hirifyme_bot",
)

_LOOKBACK = 100
_HIRIFY_CHANNEL = "hirifyme_bot"
_HIRIFY_JOB_URL = re.compile(
    r"https?://(?:www\.)?hirify\.me/jobs/(\d+)[^\s]*",
    re.IGNORECASE,
)
_HIRIFY_HEADING = re.compile(r"(?m)^\s*(?P<title>.+?)\s+в\s+(?P<company>[^\n]+?)\s*$")

_HASHTAG_TOKEN_RE = re.compile(r"#([\w]+)", flags=re.UNICODE)

_CANDIDATE_HASHTAGS: frozenset[str] = frozenset(
    {
        "candidates",
        "candidate",
        "резюме",
        "resume",
        "resumes",
        "cv",
        "ищу",
        "candidatebench",
    }
)

_CANDIDATE_PHRASES: tuple[str, ...] = (
    "looking for new opportunities",
    "looking for opportunities",
    "open to work",
    "open for opportunities",
    "ищу работу",
    "ищу роботу",
    "ищу позицию",
    "ищу позицію",
    "шукаю роботу",
    "шукаю проєкт",
    "шукаю проект",
    "available candidate",
    "propose partnership",
    "white-label",
    "outstaffing projects",
    "outsourcing & outstaffing",
)

_VACANCY_HASHTAGS: frozenset[str] = frozenset(
    {
        "вакансія",
        "вакансия",
        "vacancy",
        "job",
        "jobs",
        "hiring",
        "itjobs",
        "remote_jobs",
        "remotejobs",
        "techjobs",
        "ищут",
    }
)

_VACANCY_PHRASES: tuple[str, ...] = (
    "вакансія",
    "вакансия",
    "job opportunity",
    "jobs opportunity",
    "we're hiring",
    "we are hiring",
    "now hiring",
    "hiring:",
    "hiring ",
    "looking for",
    "шукаємо",
    "шукає",
    "ищем",
    "ищут",
    "за деталями",
    "open role",
    "open position",
    "open positions",
    "ready to apply",
    "apply using the button",
    "how to apply",
    "send your resume",
    "send your cv",
    "send dm",
)

_TITLE_NOISE: tuple[str, ...] = (
    "job opportunity",
    "ready to apply",
    "apply using the button below",
    "apply using the button",
    "tags",
    "how to apply",
)

_APPLY_URL = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
_SKIP_APPLY_HOSTS = (
    "t.me",
    "telegram.me",
    "telegram.org",
)

# Labelled fields name the employer outright; they win over hiring phrases.
_COMPANY_FIELD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?im)^[^\w#]*company\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^[^\w#]*компані[яя]\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^[^\w#]*компания\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^[^\w#]*название\s+компании\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^[^\w#]*назва\s+компанії\s*[:\-]\s*(.+)$"),
)
# "<Company> is hiring / ищет / шукає ...": the subject is often a pronoun or a
# generic noun ("We are looking for"), which _HIRING_SUBJECT_STOPWORDS rejects.
_COMPANY_HIRING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?im)^(.{2,80}?)\s+шука(?:[єе]|ють)\b"),
    re.compile(r"(?im)^(.{2,80}?)\s+ищ(?:ет|ут)\b"),
    re.compile(r"(?im)^(.{2,80}?)\s+(?:is|are)\s+hiring\b"),
    re.compile(r"(?im)^(.{2,80}?)\s+(?:(?:is|are)\s+)?looking\s+for\b"),
)
_HIRING_SUBJECT_STOPWORDS: frozenset[str] = frozenset(
    {
        "we", "we're", "i", "our", "the", "a", "an", "this", "who", "they", "client",
        "team", "startup", "product", "hiring", "job", "vacancy",
        "мы", "ми", "я", "наш", "наша", "наші", "наши", "команда", "клиент", "клієнт",
        "вакансія", "вакансия", "in", "if", "as", "for", "currently", "now", "hi", "hello",
    }
)
# Words that belong to a sentence, not to an employer name.
_HIRING_SUBJECT_SENTENCE_WORDS: frozenset[str] = frozenset(
    {"you", "your", "we", "our", "will", "be", "role", "position", "who", "which"}
)
_COMPANY_WORD_LIMIT = 6
_COMPANY_PREFIX = re.compile(r"(?i)^(?:company|компания|компанія)\s+")


def credentials_configured() -> bool:
    return bool(
        os.environ.get("TELEGRAM_API_ID", "").strip()
        and os.environ.get("TELEGRAM_API_HASH", "").strip()
        and os.environ.get("TELEGRAM_SESSION", "").strip()
    )


def _iter_hashtags(text_lower: str) -> list[str]:
    return _HASHTAG_TOKEN_RE.findall(text_lower)


def _is_candidate_hashtag(tag: str) -> bool:
    if tag in _CANDIDATE_HASHTAGS:
        return True
    if tag.startswith("резюме") or tag.startswith("resume"):
        return True
    if tag.startswith("ищу") and not tag.startswith("ищут"):
        return True
    return False


def is_candidate_post(text: str) -> bool:
    lowered = text.lower()
    if any(_is_candidate_hashtag(tag) for tag in _iter_hashtags(lowered)):
        return True
    return any(phrase in lowered for phrase in _CANDIDATE_PHRASES)


def looks_like_vacancy(text: str) -> bool:
    lowered = text.lower()
    if any(tag in _VACANCY_HASHTAGS for tag in _iter_hashtags(lowered)):
        return True
    return any(phrase in lowered for phrase in _VACANCY_PHRASES)


def should_keep_message(text: str, *, channel: str | None = None) -> bool:
    if not text.strip():
        return False
    if is_candidate_post(text):
        return False
    if not is_target_job(text):
        return False
    if channel == _HIRIFY_CHANNEL:
        return _HIRIFY_HEADING.search(text) is not None
    if not looks_like_vacancy(text):
        return False
    return True


def _is_hirify_vacancy_candidate(text: str) -> bool:
    lowered = text.lower()
    return is_target_job(text) and (
        "по подписке:" in lowered or _HIRIFY_HEADING.search(text) is not None
    )


def _strip_line_noise(line: str) -> str:
    cleaned = re.sub(r"\s+", " ", line).strip(" -–—|━_")
    cleaned = re.sub(r"^[\W_]+", "", cleaned)
    return cleaned.strip()


def _is_title_noise(line: str) -> bool:
    lowered = _strip_line_noise(line).lower()
    if not lowered:
        return True
    if lowered in _TITLE_NOISE:
        return True
    if re.match(r"^company\s*[:\-]", lowered):
        return True
    if re.match(r"^компані[яя]\s*[:\-]", lowered):
        return True
    if re.fullmatch(r"[\W_]+", line):
        return True
    return False


def extract_title(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") and " " not in line.lstrip("#").replace("_", ""):
            continue
        if re.fullmatch(r"(?:#\w[\w+-]*\s*)+", line, flags=re.UNICODE):
            continue
        if _is_title_noise(line):
            continue
        cleaned = _strip_line_noise(line)
        if cleaned:
            return cleaned[:160]
    return "iOS / Swift vacancy"


def extract_apply_url(text: str) -> str | None:
    for match in _APPLY_URL.finditer(text or ""):
        raw = match.group(0).rstrip(".,;\"'")
        host = (urlsplit(raw).hostname or "").lower()
        if not host:
            continue
        if any(host == skip or host.endswith(f".{skip}") for skip in _SKIP_APPLY_HOSTS):
            continue
        return raw
    return None


def _preferred_apply_url(urls: list[str]) -> str | None:
    cleaned = [url.strip() for url in urls if url and url.strip()]
    for url in cleaned:
        if _HIRIFY_JOB_URL.match(url):
            return url
    return extract_apply_url("\n".join(cleaned))


def _message_urls(message: Any, text: str) -> list[str]:
    urls: list[str] = []
    inline_url = extract_apply_url(text)
    if inline_url:
        urls.append(inline_url)

    for entity in getattr(message, "entities", None) or ():
        url = getattr(entity, "url", None)
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())

    for row in getattr(message, "buttons", None) or ():
        buttons = row if isinstance(row, (list, tuple)) else (row,)
        for button in buttons:
            url = getattr(button, "url", None)
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
    return urls


def _clean_company(raw: str) -> str:
    company = re.sub(r"\s+", " ", raw).strip(" -–—|🎯🚀⚓️🏢")
    company = re.sub(r"^(?:#\S+\s*)+", "", company)
    company = re.sub(r"^[^\w\"«(]+", "", company)
    return company.strip(" .,:;!-–—")


def _is_plausible_hiring_subject(company: str) -> bool:
    words = [word.lower().replace("’", "'").strip("\"'«»,.") for word in company.split()]
    if not words or len(words) > _COMPANY_WORD_LIMIT:
        return False
    if words[0] in _HIRING_SUBJECT_STOPWORDS:
        return False
    return not any(word in _HIRING_SUBJECT_SENTENCE_WORDS for word in words)


def extract_company(text: str) -> str | None:
    """The employer named in a post, or None: a guess would mislabel the role."""
    for pattern in _COMPANY_FIELD_PATTERNS:
        match = pattern.search(text)
        if match:
            company = _clean_company(match.group(1))
            if 2 <= len(company) <= 80:
                return company
    for pattern in _COMPANY_HIRING_PATTERNS:
        for match in pattern.finditer(text):
            company = _COMPANY_PREFIX.sub("", _clean_company(match.group(1)))
            if 2 <= len(company) <= 80 and _is_plausible_hiring_subject(company):
                return company
    return None


def description_snippet(text: str, *, title: str, limit: int = 140) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if re.fullmatch(r"(?:#\w[\w+-]*\s*)+", line, flags=re.UNICODE):
            continue
        if line == title:
            continue
        lines.append(line)
    blob = " · ".join(lines) if lines else text.strip()
    blob = re.sub(r"\s+", " ", blob).strip()
    if len(blob) <= limit:
        return blob
    return blob[: limit - 1].rstrip() + "…"


def message_url(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}"


def job_from_message(
    channel: str,
    message_id: int,
    text: str,
    *,
    published_at: datetime | None = None,
    apply_urls: list[str] | None = None,
) -> dict[str, Any] | None:
    if not should_keep_message(text, channel=channel):
        return None
    hirify_match = _HIRIFY_HEADING.search(text) if channel == _HIRIFY_CHANNEL else None
    title = _strip_line_noise(hirify_match.group("title")) if hirify_match else extract_title(text)
    company = (
        _strip_line_noise(hirify_match.group("company"))
        if hirify_match
        # Unknown stays empty: a placeholder would read as the employer.
        else extract_company(text) or ""
    )
    apply_url = _preferred_apply_url(apply_urls or []) or extract_apply_url(text)
    hirify_id_match = _HIRIFY_JOB_URL.match(apply_url or "")
    if channel == _HIRIFY_CHANNEL and hirify_id_match is None:
        return None
    source_job_id = (
        f"hirify:{hirify_id_match.group(1)}"
        if hirify_id_match
        else f"{channel}:{message_id}"
    )
    return {
        "company": company,
        "title": title,
        "url": apply_url or message_url(channel, message_id),
        "source": "hirify.me" if channel == _HIRIFY_CHANNEL else "telegram",
        "source_job_id": source_job_id,
        "description": description_snippet(text, title=title, limit=4000),
        "published_at": published_at.isoformat() if published_at else None,
    }


def _source_ok(
    channel: str,
    jobs: list[dict[str, Any]],
    started: float,
    *,
    scanned: int,
    checkpoint: int | None = None,
    skipped: int = 0,
) -> SourceResult:
    return SourceResult(
        source_id=f"telegram:{channel}",
        source_name=f"Telegram @{channel}",
        source_url=f"https://t.me/{channel}",
        jobs=jobs,
        status="healthy",
        error=None,
        response_ms=int((time.perf_counter() - started) * 1000),
        # Health classification counts messages read, not vacancies kept; without
        # it every channel turns degraded and the pipeline stops advancing cursors.
        items_scanned=scanned,
        # A cursor-based channel legitimately reads nothing when no posts arrived.
        empty_is_healthy=channel == _HIRIFY_CHANNEL,
        checkpoint=checkpoint,
        items_skipped=skipped,
    )


def _source_failed(channel: str, error: Exception, started: float) -> SourceResult:
    return SourceResult(
        source_id=f"telegram:{channel}",
        source_name=f"Telegram @{channel}",
        source_url=f"https://t.me/{channel}",
        jobs=[],
        status="failed",
        error=str(error),
        response_ms=int((time.perf_counter() - started) * 1000),
    )


def _source_skipped(channel: str, reason: str, started: float) -> SourceResult:
    return SourceResult(
        source_id=f"telegram:{channel}",
        source_name=f"Telegram @{channel}",
        source_url=f"https://t.me/{channel}",
        jobs=[],
        status="healthy",
        error=reason,
        response_ms=int((time.perf_counter() - started) * 1000),
    )


def _message_published_at(message: Any) -> datetime | None:
    raw = getattr(message, "date", None)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    return None


async def _fetch_channel_jobs(
    client: Any,
    channel: str,
    *,
    after_message_id: int | None = None,
) -> tuple[list[dict[str, Any]], int | None, int, int]:
    """Return jobs, the new checkpoint, messages read and messages skipped."""
    jobs: list[dict[str, Any]] = []
    skipped = 0
    if channel == _HIRIFY_CHANNEL and after_message_id is None:
        messages = await client.get_messages(channel, limit=1)
    elif channel == _HIRIFY_CHANNEL:
        messages = [
            message
            async for message in client.iter_messages(
                channel,
                min_id=after_message_id,
                reverse=True,
            )
        ]
    else:
        messages = await client.get_messages(channel, limit=_LOOKBACK)
    latest_message_id = max(
        (
            int(message.id)
            for message in messages
            if message is not None and getattr(message, "id", None)
        ),
        default=after_message_id,
    )
    scanned = sum(
        1 for message in messages if message is not None and getattr(message, "id", None)
    )
    if channel == _HIRIFY_CHANNEL and after_message_id is None:
        return [], latest_message_id, scanned, 0
    for message in messages:
        if message is None or not getattr(message, "id", None):
            continue
        text = (message.message or "").strip()
        if not text and getattr(message, "raw_text", None):
            text = str(message.raw_text).strip()
        job = job_from_message(
            channel,
            int(message.id),
            text,
            published_at=_message_published_at(message),
            apply_urls=_message_urls(message, text),
        )
        if job:
            jobs.append(job)
        elif channel == _HIRIFY_CHANNEL and _is_hirify_vacancy_candidate(text):
            # One malformed bot message must not fail the channel; the cursor
            # moves past it, so the count is the only trace it leaves.
            skipped += 1
    return jobs, latest_message_id, scanned, skipped


async def _collect_channels(
    channels: tuple[str, ...],
    cursors: dict[str, int],
) -> list[SourceResult]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = int(os.environ["TELEGRAM_API_ID"].strip())
    api_hash = os.environ["TELEGRAM_API_HASH"].strip()
    session = os.environ["TELEGRAM_SESSION"].strip()
    results: list[SourceResult] = []
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for channel in channels:
            started = time.perf_counter()
            try:
                jobs, checkpoint, scanned, skipped = await _fetch_channel_jobs(
                    client,
                    channel,
                    after_message_id=cursors.get(channel) if channel == _HIRIFY_CHANNEL else None,
                )
                results.append(
                    _source_ok(
                        channel, jobs, started, scanned=scanned, checkpoint=checkpoint, skipped=skipped
                    )
                )
            except Exception as error:  # noqa: BLE001
                results.append(_source_failed(channel, error, started))
    return results


def collect_telegram_channel(channel: str) -> SourceResult:
    return collect_telegram_channels((channel,))[0]


def collect_telegram_channels(
    channels: tuple[str, ...] = TELEGRAM_CHANNELS,
) -> list[SourceResult]:
    started = time.perf_counter()
    if not credentials_configured():
        return [_source_skipped(channel, "TELEGRAM_API_ID/HASH/SESSION not set", started) for channel in channels]
    cursors = load_telegram_cursors(default_telegram_cursors_path())
    return asyncio.run(_collect_channels(channels, cursors))
