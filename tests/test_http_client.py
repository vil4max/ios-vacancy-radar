from __future__ import annotations

import pytest
import requests

from integrations import http_client


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: object = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)


def _record_get(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url: str, headers: dict, timeout: int) -> FakeResponse:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http_client.requests, "get", fake_get)
    return calls


def test_fetch_text_returns_body_and_sends_browser_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(monkeypatch, [FakeResponse(text="<html>ok</html>")])

    assert http_client.fetch_text("https://example.com") == "<html>ok</html>"
    assert "Mozilla/5.0" in calls[0]["headers"]["User-Agent"]
    assert calls[0]["timeout"] == 30


def test_fetch_text_merges_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(monkeypatch, [FakeResponse(text="ok")])

    http_client.fetch_text("https://example.com", headers={"Accept": "text/html", "X-Test": "1"})

    assert calls[0]["headers"]["Accept"] == "text/html"
    assert calls[0]["headers"]["X-Test"] == "1"
    assert "Mozilla/5.0" in calls[0]["headers"]["User-Agent"]


def test_fetch_json_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(payload={"jobs": [1, 2]})])

    assert http_client.fetch_json("https://example.com") == {"jobs": [1, 2]}


def test_get_retries_on_server_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(
        monkeypatch,
        [FakeResponse(status_code=503), FakeResponse(status_code=503), FakeResponse(text="late")],
    )

    assert http_client.fetch_text("https://example.com") == "late"
    assert len(calls) == 3


def test_get_raises_after_exhausting_server_error_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(monkeypatch, [FakeResponse(status_code=500)])

    with pytest.raises(requests.HTTPError):
        http_client.fetch_text("https://example.com")
    assert len(calls) == 3


def test_get_does_not_retry_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(monkeypatch, [FakeResponse(status_code=404)])

    with pytest.raises(requests.HTTPError):
        http_client.fetch_text("https://example.com")
    assert len(calls) == 1


def test_get_retries_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_get(
        monkeypatch,
        [requests.ConnectionError("boom"), requests.ConnectionError("boom"), FakeResponse(text="ok")],
    )

    assert http_client.fetch_text("https://example.com") == "ok"
    assert len(calls) == 3


def test_get_reraises_connection_error_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [requests.ConnectionError("boom")])

    with pytest.raises(requests.ConnectionError):
        http_client.fetch_text("https://example.com")


@pytest.mark.parametrize(
    "body",
    [
        '<html><script src="/_Incapsula_Resource?SWJIYLWA=x"></script></html>',
        "<html><title>Just a moment...</title></html>",
        "<html>Checking your browser before accessing example.com</html>",
        "<html><title>Attention Required! | Cloudflare</title></html>",
    ],
)
def test_fetch_text_falls_back_to_impersonate_on_bot_wall(
    monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    _record_get(monkeypatch, [FakeResponse(text=body)])
    monkeypatch.setattr(http_client, "fetch_impersonated", lambda *a, **k: "real-content")

    assert http_client.fetch_text("https://example.com") == "real-content"


def test_fetch_text_falls_back_to_impersonate_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(status_code=403)])
    monkeypatch.setattr(http_client, "fetch_impersonated", lambda *a, **k: "via-curl")

    assert http_client.fetch_text("https://example.com") == "via-curl"


def test_long_page_mentioning_cloudflare_is_not_a_bot_wall(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "We use Cloudflare for CDN protection. " + ("x" * 5000)
    _record_get(monkeypatch, [FakeResponse(text=body)])

    assert http_client.fetch_text("https://example.com") == body


def test_cloudflare_challenge_page_is_bot_wall() -> None:
    body = (
        "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        "<body><script>window._cf_chl_opt={};</script>"
        + ("y" * 5500)
        + "</body></html>"
    )
    assert len(body) > 4000
    assert http_client.looks_like_bot_wall(body) is True


def test_fetch_impersonated_warms_then_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSession:
        def __init__(self, impersonate: str) -> None:
            self.impersonate = impersonate

        def get(self, url: str, headers: dict, timeout: int) -> FakeResponse:
            calls.append(url)
            if url.endswith("/warm"):
                return FakeResponse(text="warm-ok")
            return FakeResponse(text='[{"id": 1}]')

    class FakeCurlRequests:
        @staticmethod
        def Session(impersonate: str) -> FakeSession:
            return FakeSession(impersonate)

    import sys
    import types

    fake_mod = types.ModuleType("curl_cffi")
    fake_mod.requests = FakeCurlRequests()
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_mod)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_mod.requests)

    text = http_client.fetch_impersonated(
        "https://example.com/api",
        warm_urls=("https://example.com/warm",),
        accept=lambda body: body.lstrip().startswith("["),
    )

    assert text == '[{"id": 1}]'
    assert calls == ["https://example.com/warm", "https://example.com/api"]


def test_fetch_impersonated_tries_next_fingerprint_on_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    class FakeSession:
        def __init__(self, impersonate: str) -> None:
            self.impersonate = impersonate
            attempts.append(impersonate)

        def get(self, url: str, headers: dict, timeout: int) -> FakeResponse:
            if self.impersonate == http_client._IMPERSONATE_CANDIDATES[0]:
                return FakeResponse(status_code=403)
            return FakeResponse(text="ok-body")

    class FakeCurlRequests:
        @staticmethod
        def Session(impersonate: str) -> FakeSession:
            return FakeSession(impersonate)

    import sys
    import types

    fake_mod = types.ModuleType("curl_cffi")
    fake_mod.requests = FakeCurlRequests()
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_mod)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_mod.requests)

    assert http_client.fetch_impersonated("https://example.com") == "ok-body"
    assert attempts[0] == http_client._IMPERSONATE_CANDIDATES[0]
    assert attempts[1] == http_client._IMPERSONATE_CANDIDATES[1]


def test_fetch_text_allowing_bot_wall_returns_none_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(status_code=403)])

    assert http_client.fetch_text_allowing_bot_wall("https://example.com") is None


def test_fetch_text_allowing_bot_wall_returns_none_on_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(text="<html>Just a moment...</html>")])

    assert http_client.fetch_text_allowing_bot_wall("https://example.com") is None


def test_fetch_text_allowing_bot_wall_reraises_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(status_code=404)])

    with pytest.raises(requests.HTTPError):
        http_client.fetch_text_allowing_bot_wall("https://example.com")


def test_fetch_text_allowing_bot_wall_returns_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_get(monkeypatch, [FakeResponse(text="fine")])

    assert http_client.fetch_text_allowing_bot_wall("https://example.com") == "fine"


def test_post_form_raises_for_status(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, data: dict, headers: dict, timeout: int) -> FakeResponse:
        captured.update({"url": url, "data": data, "headers": headers})
        return FakeResponse(status_code=500)

    monkeypatch.setattr(http_client.requests, "post", fake_post)

    with pytest.raises(requests.HTTPError):
        http_client.post_form("https://example.com", {"a": "b"})
    assert captured["data"] == {"a": "b"}


def test_post_form_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_client.requests,
        "post",
        lambda url, data, headers, timeout: FakeResponse(text=""),
    )

    assert http_client.post_form("https://example.com", {"a": "b"}) is None


def test_post_form_data_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url: str, data: dict, headers: dict, timeout: int) -> FakeResponse:
        captured.update({"headers": headers})
        return FakeResponse(text="payload")

    monkeypatch.setattr(http_client.requests, "post", fake_post)

    assert http_client.post_form_data("https://example.com", {"a": "b"}, headers={"X": "1"}) == "payload"
    assert captured["headers"]["X"] == "1"


def test_looks_like_bot_wall_on_clean_page() -> None:
    assert http_client.looks_like_bot_wall("<html><body>jobs</body></html>") is False


@pytest.mark.parametrize('status', [429, 503])
def test_retry_after_seconds_is_respected(monkeypatch, status):
    response = FakeResponse(status_code=status)
    response.headers = {'Retry-After': '3'}
    calls = _record_get(monkeypatch, [response, FakeResponse(text='ok')])
    sleeps = []
    monkeypatch.setattr(http_client.time, 'sleep', sleeps.append)
    assert http_client.fetch_text('https://example.com') == 'ok'
    assert len(calls) == 2
    assert sleeps == [3.0]


def test_retry_after_http_date(monkeypatch):
    response = FakeResponse(status_code=429)
    response.headers = {'Retry-After': 'Thu, 01 Jan 1970 00:16:45 GMT'}
    _record_get(monkeypatch, [response, FakeResponse(text='ok')])
    sleeps = []
    monkeypatch.setattr(http_client.time, 'time', lambda: 1000)
    monkeypatch.setattr(http_client.time, 'sleep', sleeps.append)
    assert http_client.fetch_text('https://example.com') == 'ok'
    assert sleeps == [5.0]


def test_excessive_retry_after_fails_without_early_retry(monkeypatch):
    response = FakeResponse(status_code=429)
    response.headers = {'Retry-After': '3600'}
    calls = _record_get(monkeypatch, [response])
    monkeypatch.setattr(http_client.time, 'sleep', lambda _: pytest.fail('must not sleep'))
    with pytest.raises(http_client.RetryBudgetError):
        http_client.fetch_text('https://example.com')
    assert len(calls) == 1


def test_shared_get_limits_same_domain_concurrency(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    two_entered = threading.Event()
    release = threading.Event()
    active = maximum = 0
    def get(*_args, **_kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                two_entered.set()
        assert release.wait(3)
        with lock:
            active -= 1
        return FakeResponse(text='ok')
    monkeypatch.setattr(http_client.requests, 'get', get)
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks = [pool.submit(http_client.fetch_text, f'https://bounded.example/jobs/{i}') for i in range(5)]
        try:
            assert two_entered.wait(3)
            assert maximum == 2
        finally:
            release.set()
        assert all(task.result() == 'ok' for task in tasks)
    assert maximum == 2


def test_malformed_retry_after_uses_bounded_backoff(monkeypatch):
    response = FakeResponse(status_code=503)
    response.headers = {'Retry-After': 'later'}
    calls = _record_get(monkeypatch, [response])
    sleeps = []
    monkeypatch.setattr(http_client.time, 'sleep', sleeps.append)
    with pytest.raises(requests.HTTPError):
        http_client.fetch_text('https://example.com')
    assert len(calls) == 3
    assert sleeps == [0.4, 0.8]


def test_impersonation_does_not_bypass_server_rate_limit(monkeypatch):
    import sys
    import types

    attempts = []
    class Session:
        def __init__(self, impersonate):
            attempts.append(impersonate)
        def get(self, *args, **kwargs):
            response = FakeResponse(status_code=429)
            response.headers = {'Retry-After': '3600'}
            return response
    module = types.ModuleType('curl_cffi')
    module.requests = types.SimpleNamespace(Session=Session)
    monkeypatch.setitem(sys.modules, 'curl_cffi', module)
    with pytest.raises(http_client.RetryBudgetError):
        http_client.fetch_impersonated('https://example.com')
    assert len(attempts) == 1
