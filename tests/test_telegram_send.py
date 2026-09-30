from __future__ import annotations

import pytest
import requests

from integrations import telegram


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", url: str = "https://api.telegram.org") -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.ok = status_code < 400


def test_split_telegram_text_keeps_short_message() -> None:
    assert telegram.split_telegram_text("hello") == ["hello"]


def test_split_telegram_text_breaks_on_newlines() -> None:
    first = "a" * 100
    second = "b" * 100
    chunks = telegram.split_telegram_text(f"{first}\n{second}", limit=120)
    assert chunks == [first, second]


def test_split_telegram_text_hard_splits_without_newlines() -> None:
    body = "x" * 250
    chunks = telegram.split_telegram_text(body, limit=100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_send_message_prints_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    telegram.send_message("ping")
    assert capsys.readouterr().out.strip() == "ping"


def test_send_message_chunks_posts_and_logs_delivery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    posts: list[dict] = []

    def fake_post(url: str, data: dict, headers: dict, timeout: int) -> FakeResponse:
        posts.append({"url": url, "data": data, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    monkeypatch.setattr(
        telegram,
        "split_telegram_text",
        lambda text, limit=telegram.TELEGRAM_MAX_LENGTH: ["one", "two"],
    )
    telegram.send_message("ignored")
    assert [post["data"]["text"] for post in posts] == ["one", "two"]
    assert posts[0]["data"]["chat_id"] == "42"
    assert "bottoken/sendMessage" in posts[0]["url"]
    assert capsys.readouterr().out.strip() == "Telegram delivery accepted: 2 message(s)"


def test_send_message_redacts_token_in_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def fake_post(url: str, data: dict, headers: dict, timeout: int) -> FakeResponse:
        return FakeResponse(
            status_code=400,
            text='{"description":"message is too long"}',
            url="https://api.telegram.org/bottoken/sendMessage",
        )

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    with pytest.raises(requests.HTTPError, match=r"bot\[redacted\].*message is too long"):
        telegram.send_message("hello")


@pytest.mark.parametrize("missing", ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"])
def test_send_message_suppresses_private_fallback_in_actions(monkeypatch, capsys, missing):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv(missing)
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: pytest.fail("Unexpected network call"))

    telegram.send_message("Private application decision for Example Company")

    output = capsys.readouterr()
    assert "Private application" not in output.out + output.err
    assert "credentials are missing" in output.out
