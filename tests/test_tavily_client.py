import json
from datetime import date

import httpx
import pytest

from crier.providers.tavily import TavilyClient, TavilyError
from tests.fakes import make_settings


def _client(tmp_path, handler) -> TavilyClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return TavilyClient(make_settings(tmp_path).tavily, http=http, backoff_s=0)


def test_search_sends_filters_and_parses_results(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://x.com/CityA/status/1",
                        "title": "post",
                        "content": "Grants open",
                        "published_date": "2026-10-20",
                    },
                    {"url": "javascript:alert(1)", "title": "bad", "content": ""},
                ]
            },
        )

    hits = _client(tmp_path, handler).search(
        "grants",
        include_domains=["x.com"],
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 2),
        max_results=5,
    )
    assert [h.url for h in hits] == ["https://x.com/CityA/status/1"]
    assert hits[0].published_date == "2026-10-20"
    request = seen["request"]
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["Authorization"] == "Bearer tvly-test"
    body = json.loads(request.content)
    assert body["include_domains"] == ["x.com"]
    assert (body["start_date"], body["end_date"]) == ("2026-10-01", "2026-11-02")
    assert body["max_results"] == 5 and body["search_depth"] == "advanced"


def test_empty_domain_list_is_not_sent(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    assert _client(tmp_path, handler).search("mayor", include_domains=[]) == []
    assert "include_domains" not in seen["body"] and "start_date" not in seen["body"]


def test_retries_rate_limit_then_fails_with_status(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    with pytest.raises(TavilyError, match="429"):
        _client(tmp_path, handler).search("q", include_domains=[])
    assert calls["n"] == 3
