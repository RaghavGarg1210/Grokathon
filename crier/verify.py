"""Checks a briefing against official government websites."""

from __future__ import annotations

import logging

from crier.evidence import on_domains
from crier.models import Briefing, VerificationResult, parse_iso_date
from crier.ports import Verifier

log = logging.getLogger(__name__)


def verify_briefing(verifier: Verifier, briefing: Briefing, domains: list[str]) -> Briefing:
    if not domains:
        return briefing.model_copy(
            update={
                "verification": "announced_only",
                "verification_notes": "No official domains configured.",
            }
        )
    if on_domains(briefing.post_url, domains):
        return briefing.model_copy(
            update={
                "verification": "verified",
                "official_url": briefing.post_url,
                "verification_notes": "Published on an official government website.",
            }
        )
    return apply_verification(briefing, verifier.check(briefing, domains), domains)


def apply_verification(
    briefing: Briefing, result: VerificationResult, domains: list[str]
) -> Briefing:
    status = result.status
    official_url = result.official_url
    if status == "verified" and not on_domains(official_url, domains):
        log.warning(
            "downgrading %s: official url %r not on allowed domains", briefing.id, official_url
        )
        status, official_url = "announced_only", None
    update: dict = {
        "verification": status,
        "official_url": official_url if status != "announced_only" else None,
        "verification_notes": result.notes.strip(),
    }
    official_deadline = parse_iso_date(result.deadline)
    if status == "verified" and official_deadline:
        update["deadline"] = official_deadline
    return briefing.model_copy(update=update)
