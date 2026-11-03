"""Helpers for search evidence: URL matching, domain checks, and formatting hits for prompts."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from crier.models import X_POST_URL_RE
from crier.ports import SearchHit


def host_of(url: str) -> str:
    return (urlparse(url.strip()).hostname or "").lower().removeprefix("www.")


def on_domains(url: str | None, domains: list[str]) -> bool:
    """True if the URL's host is one of `domains` or a subdomain of one."""
    if not url:
        return False
    host = host_of(url)
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


def canonical_url(url: str) -> str:
    """Lowercase host, no fragment, no trailing slash: stable for dedupe and display."""
    parts = urlparse(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunparse((parts.scheme.lower(), parts.netloc.lower(), path, "", parts.query, ""))


def matches_any(url: str, candidates: list[str]) -> bool:
    """Whether `url` is one of `candidates` (X posts compare by status id)."""
    if not url:
        return False
    match = X_POST_URL_RE.match(url.strip())
    if match:
        status_id = match.group("id")
        return any(
            (m := X_POST_URL_RE.match(c.strip())) and m.group("id") == status_id for c in candidates
        )
    target = _comparable(url)
    return any(_comparable(c) == target for c in candidates)


def format_hits(hits: list[SearchHit]) -> str:
    blocks = [
        f"[{index}] URL: {hit.url}\n"
        f"Published: {hit.published_date or 'unknown'}\n"
        f"Title: {hit.title}\n"
        f"Content: {hit.content}"
        for index, hit in enumerate(hits, start=1)
    ]
    return "\n\n".join(blocks)


def _comparable(url: str) -> str:
    parts = urlparse(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{parts.path.rstrip('/')}{query}"
