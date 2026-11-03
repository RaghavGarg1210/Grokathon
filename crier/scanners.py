"""Post scanners: web search + LLM extraction (default), or Grok's native X search."""

from __future__ import annotations

from datetime import date

from crier.config import CitySource
from crier.evidence import format_hits
from crier.models import ScanResult
from crier.ports import AgenticModel, LanguageModel, ScanBatch, SearchHit, WebSearch

X_DOMAINS = ["x.com", "twitter.com"]
MAX_HANDLES_IN_QUERY = 5

CATEGORY_RULES = """\
Return one entry per announcement by the mayor or city government about any of:
- program: a grant, loan, incentive, training, assistance program, or other scheme
- policy_decision: an ordinance, fee or tax change, permit or licensing rule, zoning decision, \
or infrastructure project that affects local businesses
- event: a workshop, hearing, or info session aimed at businesses
Use not_relevant for anything else you include.

Rules:
- Only include real announcements you were shown. Never invent posts, numbers, or deadlines.
- Set is_campaign_or_personal=true for election, campaign, partisan, or personal posts.
- Write neutrally and attribute claims ("The mayor announced..."). No opinions, no praise.
- headline: plain language, at most 80 characters.
- what_to_do: the concrete next step for an owner (apply, comment, attend, comply), or \
"No action needed" if none.
- relevance_score: 0-100 for how much a typical local small business should care.
- confidence: low if the source is vague or details are missing.
- Return an empty list if nothing relevant was found."""

EXTRACT_INSTRUCTIONS = f"""\
You monitor a Georgia (USA) city's mayor and city government for news that small-business \
owners need to know. You are given numbered search results: posts from the city's official \
X accounts and pages from its official website.

{CATEGORY_RULES}
- post_url: copy the result's URL exactly. Never edit, combine, or invent URLs.
- author_handle: the X handle without @ for X posts; an empty string for web pages.
- posted_on: the date the announcement was published (from the content or the Published \
line). Skip results whose date you cannot tell or that fall outside the date range.
- Skip results that are not from the mayor or city government (news outlets, residents)."""

X_SEARCH_INSTRUCTIONS = f"""\
You monitor the official X accounts of a Georgia (USA) city's mayor and city government for \
news that small-business owners need to know. Use X search to read the accounts' posts in \
the given date range.

{CATEGORY_RULES}
- post_url must be the exact URL of the post (https://x.com/<handle>/status/<id>)."""


class SearchScanner:
    """Searches official X accounts and city websites, then has an LLM extract briefings.
    Only URLs that came back from the search can become briefings."""

    def __init__(self, search: WebSearch, llm: LanguageModel, max_results: int = 10) -> None:
        self._search = search
        self._llm = llm
        self._max_results = max_results
        self.label = f"{search.label} + {llm.label}"

    def missing_config(self, source: CitySource) -> str | None:
        if source.handles or source.domains:
            return None
        return "no official X handles or website domains configured"

    def scan(self, source: CitySource, *, from_date: date, to_date: date) -> ScanBatch:
        hits = self.find_hits(source, from_date=from_date, to_date=to_date)
        if not hits:
            return ScanBatch(posts=[], source_urls=[], grounded=True, usage={"search_results": 0})
        result = self._llm.parse(
            instructions=EXTRACT_INSTRUCTIONS,
            prompt=build_extract_prompt(source, hits, from_date, to_date),
            schema=ScanResult,
        )
        return ScanBatch(
            posts=result.value.posts,
            source_urls=[hit.url for hit in hits],
            grounded=True,
            usage={"search_results": len(hits), "llm": result.usage},
        )

    def find_hits(self, source: CitySource, *, from_date: date, to_date: date) -> list[SearchHit]:
        queries: list[tuple[str, list[str]]] = []
        if source.handles:
            queries.append((x_query(source), X_DOMAINS))
        if source.domains:
            queries.append((web_query(source), source.domains))
        hits: dict[str, SearchHit] = {}
        for query, domains in queries:
            for hit in self._search.search(
                query,
                include_domains=domains,
                start_date=from_date,
                end_date=to_date,
                max_results=self._max_results,
            ):
                hits.setdefault(hit.url, hit)
        return list(hits.values())


class XSearchScanner:
    """Grok reads the configured X accounts directly with server-side X search."""

    label = "Grok X search"

    def __init__(self, model: AgenticModel, max_turns: int) -> None:
        self._model = model
        self._max_turns = max_turns

    def missing_config(self, source: CitySource) -> str | None:
        return None if source.handles else "no official X handles configured"

    def scan(self, source: CitySource, *, from_date: date, to_date: date) -> ScanBatch:
        tool = {
            "type": "x_search",
            "allowed_x_handles": source.handles,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "enable_video_understanding": True,
        }
        result = self._model.parse(
            instructions=X_SEARCH_INSTRUCTIONS,
            prompt=_city_header(source, from_date, to_date)
            + "Find every post in this range about programs, policy decisions, or business events.",
            schema=ScanResult,
            tools=[tool],
            max_turns=self._max_turns,
        )
        return ScanBatch(
            posts=result.value.posts,
            source_urls=result.citations,
            grounded=False,
            usage=result.usage,
        )


def x_query(source: CitySource) -> str:
    handles = " ".join("@" + h for h in source.handles[:MAX_HANDLES_IN_QUERY])
    return f"{handles} {source.city} Georgia announcement small business program grant ordinance"


def web_query(source: CitySource) -> str:
    return (
        f"{source.city} Georgia city news announcement small business grant program "
        "ordinance permit fee zoning"
    )


def build_extract_prompt(
    source: CitySource, hits: list[SearchHit], from_date: date, to_date: date
) -> str:
    return f"{_city_header(source, from_date, to_date)}\nSearch results:\n\n{format_hits(hits)}"


def _city_header(source: CitySource, from_date: date, to_date: date) -> str:
    handles = ", ".join("@" + h for h in source.handles) or "none configured"
    domains = ", ".join(source.domains) or "none configured"
    return (
        f"City: {source.city}, {source.county} County, Georgia. "
        f"Mayor: {source.mayor or 'the mayor'}.\n"
        f"Official X accounts: {handles}.\n"
        f"Official websites: {domains}.\n"
        f"Date range: {from_date.isoformat()} to {to_date.isoformat()}.\n"
    )
