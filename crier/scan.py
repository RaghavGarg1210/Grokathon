"""Turns a scanner's raw findings for one city into trusted briefings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from crier.config import CitySource
from crier.evidence import canonical_url, host_of, matches_any, on_domains
from crier.models import X_POST_URL_RE, Briefing, ScannedPost, parse_iso_date
from crier.ports import PostScanner, ScanBatch

log = logging.getLogger(__name__)


@dataclass
class CityScan:
    city: str
    briefings: list[Briefing] = field(default_factory=list)
    rejected: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


def scan_city(scanner: PostScanner, source: CitySource, *, today: date, scan_days: int) -> CityScan:
    reason = scanner.missing_config(source)
    if reason:
        raise ValueError(f"{source.city}: {reason}")
    from_date = today - timedelta(days=scan_days)
    batch = scanner.scan(source, from_date=from_date, to_date=today + timedelta(days=1))
    scan = CityScan(city=source.city, usage=batch.usage)
    seen: set[str] = set()
    for post in batch.posts:
        briefing = to_briefing(post, source, batch, today=today, from_date=from_date)
        if briefing is None:
            scan.rejected += 1
        elif briefing.id not in seen:
            seen.add(briefing.id)
            scan.briefings.append(briefing)
    log.info("scan %s: %d kept, %d rejected", source.city, len(scan.briefings), scan.rejected)
    return scan


def to_briefing(
    post: ScannedPost, source: CitySource, batch: ScanBatch, *, today: date, from_date: date
) -> Briefing | None:
    """Validates one scanned post; returns None if it cannot be trusted."""
    url = post.post_url.strip()
    if batch.grounded and not matches_any(url, batch.source_urls):
        log.warning("rejecting url that was not in the search results: %s", url)
        return None
    resolved = _resolve_source(url, source)
    if resolved is None:
        log.warning("rejecting post that is not from a monitored account or site: %s", url)
        return None
    canonical, author = resolved
    posted_on = parse_iso_date(post.posted_on)
    if posted_on is None or not from_date <= posted_on <= today + timedelta(days=1):
        log.warning("rejecting post with date %r outside the scan window: %s", post.posted_on, url)
        return None
    confidence = post.confidence
    if not batch.grounded and batch.source_urls and not matches_any(url, batch.source_urls):
        confidence = "low"
    return Briefing(
        id=Briefing.make_id(canonical),
        city=source.city,
        county=source.county,
        mayor=source.mayor,
        post_url=canonical,
        author_handle=author,
        posted_on=posted_on,
        post_text=post.post_text.strip(),
        category=post.category,
        is_campaign_or_personal=post.is_campaign_or_personal,
        headline=post.headline.strip()[:80],
        what_changed=post.what_changed.strip(),
        who_it_affects=[w.strip() for w in post.who_it_affects if w.strip()],
        what_to_do=post.what_to_do.strip(),
        deadline=parse_iso_date(post.deadline),
        amount=post.amount,
        relevance_score=post.relevance_score,
        confidence=confidence,
    )


def _resolve_source(url: str, source: CitySource) -> tuple[str, str] | None:
    """(canonical URL, author) for an X post from a monitored handle or a page on the
    city's official domains; None for anything else."""
    match = X_POST_URL_RE.match(url)
    if match:
        handle = match.group("handle")
        if handle.lower() not in {h.lower() for h in source.handles}:
            return None
        return f"https://x.com/{handle}/status/{match.group('id')}", handle
    if on_domains(url, source.domains):
        return canonical_url(url), host_of(url)
    return None
