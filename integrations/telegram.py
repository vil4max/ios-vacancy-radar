from __future__ import annotations

import os
from urllib.parse import urlsplit

import requests

from integrations.http_client import _merge_headers
from integrations.public_log import logs_are_public, print_private

TELEGRAM_MAX_LENGTH = 4096


def split_telegram_text(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        split_at = window.rfind("\n")
        if split_at <= 0:
            split_at = limit
        chunk = remaining[:split_at].rstrip("\n")
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def _redact_token(url: str, token: str) -> str:
    if not token or token not in url:
        return url
    split = urlsplit(url)
    if split.scheme and split.netloc and split.path.startswith("/bot"):
        return split._replace(path=split.path.replace(f"/bot{token}", "/bot[redacted]", 1)).geturl()
    return url.replace(token, "[redacted]")


def _post_message(token: str, chat_id: str, text: str, timeout: int = 30) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        },
        headers=_merge_headers(None),
        timeout=timeout,
    )
    if response.ok:
        return
    detail = (response.text or "").strip()
    if len(detail) > 500:
        detail = detail[:500] + "…"
    safe_url = _redact_token(response.url or url, token)
    raise requests.HTTPError(
        f"{response.status_code} Client Error for url: {safe_url}"
        + (f"; body={detail}" if detail else ""),
        response=response,
    )


def send_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        if logs_are_public():
            print("Telegram delivery skipped: credentials are missing; message suppressed in public logs")
        print_private(text)
        return

    chunks = split_telegram_text(text)
    for chunk in chunks:
        _post_message(token, chat_id, chunk)
    print(f"Telegram delivery accepted: {len(chunks)} message(s)")
