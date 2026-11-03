"""Tavily web search: finds recent X posts and official city pages for a query."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from crier.ports import ProviderError, SearchHit
from crier.providers.http import ApiHttp
from crier.settings import TavilySettings

log = logging.getLogger(__name__)

BASE_URL = "https://api.tavily.com"
MAX_QUERY_CHARS = 400
MAX_CONTENT_CHARS = 2000


class TavilyError(ProviderError):
    """A failed Tavily request."""


class TavilyClient:
    label = "Tavily"

    def __init__(
        self, settings: TavilySettings, http: httpx.Client | None = None, backoff_s: float = 2.0
    ) -> None:
        if not settings.api_key:
            raise TavilyError("TAVILY_API_KEY is not set")
        self._settings = settings
        self._api = ApiHttp(
            name="Tavily",
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            error=TavilyError,
            client=http,
            backoff_s=backoff_s,
        )

    def search(
        self,
        query: str,
        *,
        include_domains: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        max_results: int | None = None,
    ) -> list[SearchHit]:
        body: dict[str, Any] = {
            "query": query[:MAX_QUERY_CHARS],
            "search_depth": self._settings.search_depth,
            "topic": "general",
            "max_results": max_results or self._settings.max_results,
            "include_published_date": True,
            "include_answer": False,
            "include_raw_content": False,
        }
        if include_domains:
            body["include_domains"] = include_domains
        if start_date:
            body["start_date"] = start_date.isoformat()
        if end_date:
            body["end_date"] = end_date.isoformat()
        payload = self._api.json("POST", "/search", json=body)
        hits = [_to_hit(item) for item in payload.get("results") or []]
        kept = [hit for hit in hits if hit is not None]
        log.info("tavily %r -> %d results", query[:60], len(kept))
        return kept

    def close(self) -> None:
        self._api.close()


def _to_hit(item: dict[str, Any]) -> SearchHit | None:
    url = str(item.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    return SearchHit(
        url=url,
        title=str(item.get("title") or "").strip(),
        content=str(item.get("content") or "").strip()[:MAX_CONTENT_CHARS],
        published_date=item.get("published_date") or None,
    )
