"""Verifiers: official-site search + LLM judgement (default), or Grok web search."""

from __future__ import annotations

import logging

from crier.evidence import format_hits, matches_any
from crier.models import Briefing, VerificationResult
from crier.ports import AgenticModel, LanguageModel, WebSearch

log = logging.getLogger(__name__)

VERIFY_RULES = """\
Decide:
- verified: an official page confirms the announcement. Give its exact URL.
- contradicted: an official page clearly says something different (e.g. program closed, \
different deadline or amount). Give its URL and explain in notes.
- announced_only: no official page confirms it yet.
If the official page states a deadline, return it as YYYY-MM-DD. Notes: one or two neutral \
sentences. Never guess a URL."""

SEARCH_VERIFY_INSTRUCTIONS = f"""\
You fact-check local government announcements for small-business owners in Georgia (USA).
Use only the numbered official web pages provided; official_url must be one of their URLs.
{VERIFY_RULES}"""

GROK_VERIFY_INSTRUCTIONS = f"""\
You fact-check local government announcements for small-business owners in Georgia (USA).
Search only the official websites provided.
{VERIFY_RULES}"""


def build_verify_prompt(briefing: Briefing) -> str:
    deadline = briefing.deadline.isoformat() if briefing.deadline else "none stated"
    return (
        f"City: {briefing.city}, {briefing.county} County, Georgia.\n"
        f"Source: {briefing.source_label} ({briefing.posted_on.isoformat()}): "
        f"{briefing.post_url}\n"
        f"Announcement text: {briefing.post_text}\n"
        f"Claim: {briefing.headline}. {briefing.what_changed}\n"
        f"Deadline stated: {deadline}. Amount: {briefing.amount or 'none stated'}."
    )


class SearchVerifier:
    """Searches only the official domains, then asks an LLM to compare the pages to the claim.
    A cited page that the search did not return is treated as unconfirmed."""

    def __init__(self, search: WebSearch, llm: LanguageModel, max_results: int = 5) -> None:
        self._search = search
        self._llm = llm
        self._max_results = max_results

    def check(self, briefing: Briefing, domains: list[str]) -> VerificationResult:
        hits = self._search.search(
            f"{briefing.headline} {briefing.city} Georgia",
            include_domains=domains,
            max_results=self._max_results,
        )
        if not hits:
            return VerificationResult(
                status="announced_only", notes="No matching page found on the official sites."
            )
        result = self._llm.parse(
            instructions=SEARCH_VERIFY_INSTRUCTIONS,
            prompt=f"{build_verify_prompt(briefing)}\n\nOfficial pages:\n\n{format_hits(hits)}",
            schema=VerificationResult,
        ).value
        if result.status != "announced_only" and not matches_any(
            result.official_url or "", [hit.url for hit in hits]
        ):
            log.warning("verifier cited %r, which search did not return", result.official_url)
            return VerificationResult(
                status="announced_only",
                notes="The cited page was not among the official search results.",
            )
        return result


class GrokVerifier:
    """Grok searches the official domains itself with server-side web search."""

    def __init__(self, model: AgenticModel) -> None:
        self._model = model

    def check(self, briefing: Briefing, domains: list[str]) -> VerificationResult:
        return self._model.parse(
            instructions=GROK_VERIFY_INSTRUCTIONS,
            prompt=build_verify_prompt(briefing),
            schema=VerificationResult,
            tools=[{"type": "web_search", "filters": {"allowed_domains": domains}}],
            max_turns=2,
        ).value
