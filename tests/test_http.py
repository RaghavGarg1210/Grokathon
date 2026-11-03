import httpx
import pytest

from crier.ports import ProviderError
from crier.providers.http import ApiHttp, retry_after_header


def _api(responses: list[httpx.Response], slept: list[float], **kwargs) -> ApiHttp:
    queue = iter(responses)
    http = httpx.Client(transport=httpx.MockTransport(lambda request: next(queue)))
    return ApiHttp(
        name="Test",
        base_url="https://api.test",
        headers={"Authorization": "Bearer k"},
        error=ProviderError,
        client=http,
        backoff_s=2,
        sleep=slept.append,
        **kwargs,
    )


def test_retries_with_exponential_backoff_then_succeeds():
    slept: list[float] = []
    api = _api([httpx.Response(503), httpx.Response(502), httpx.Response(200, json={})], slept)

    assert api.json("GET", "/x") == {}
    assert slept == [2, 4]


def test_waits_as_long_as_the_server_asks():
    slept: list[float] = []
    busy = httpx.Response(429, headers={"Retry-After": "30"})
    api = _api([busy, httpx.Response(200, json={"ok": True})], slept)

    assert api.json("GET", "/x") == {"ok": True}
    assert slept == [30]


def test_fails_fast_when_the_server_asks_for_too_long_a_wait():
    slept: list[float] = []
    api = _api([httpx.Response(429, headers={"Retry-After": "3600"}, text="daily quota")], slept)

    with pytest.raises(ProviderError, match="429: daily quota"):
        api.json("GET", "/x")
    assert slept == []


def test_does_not_retry_client_errors():
    slept: list[float] = []
    api = _api([httpx.Response(400, text="bad")], slept)

    with pytest.raises(ProviderError, match="400: bad"):
        api.json("GET", "/x")
    assert slept == []


def test_a_broken_retry_hint_falls_back_to_backoff():
    def broken(response: httpx.Response) -> float | None:
        raise ValueError("unparseable")

    slept: list[float] = []
    api = _api([httpx.Response(503), httpx.Response(200, json={})], slept, retry_hint=broken)

    assert api.json("GET", "/x") == {}
    assert slept == [2]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "12"}, 12.0),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
        ({}, None),
    ],
)
def test_retry_after_header(headers, expected):
    assert retry_after_header(httpx.Response(429, headers=headers)) == expected
