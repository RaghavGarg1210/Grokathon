"""Finds each city's mayor, official X handles and official website via search + LLM.

Usage:
  python -m scripts.discover_handles [--city Atlanta]   # writes config/sources.suggested.yaml
  python -m scripts.discover_handles --apply            # copies suggestions into empty fields
Always review the suggested file before applying: these accounts drive what gets monitored.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from crier.bootstrap import configure_logging
from crier.config import MAX_X_HANDLES, CitySource, SourcesConfig, load_sources, save_sources
from crier.evidence import format_hits, on_domains
from crier.ports import LanguageModel, ProviderError, SearchHit, WebSearch
from crier.providers.registry import build_providers
from crier.scanners import X_DOMAINS
from crier.settings import ConfigError, load_settings

MAX_DOMAINS = 2


class HandleSuggestion(BaseModel):
    mayor_name: str
    mayor_handles: list[str]
    city_handles: list[str]
    official_domains: list[str]
    notes: str


INSTRUCTIONS = """\
From the numbered search results only, identify the CURRENT mayor of the given Georgia (USA) \
city and the official X accounts used for city business: the mayor's official account(s), the \
main city government account, and the city's economic development or small-business accounts. \
Only include accounts that the results show are official. Handles without '@'. \
official_domains: the city government's own website domain(s), max 2 (e.g. atlantaga.gov). \
If unsure about anything, leave it out and say why in notes."""


def suggest(search: WebSearch, llm: LanguageModel, city: CitySource) -> HandleSuggestion:
    place = f"{city.city}, {city.county} County, Georgia"
    hits: dict[str, SearchHit] = {}
    for query, domains in (
        (f"{place} mayor official city government website X twitter account", []),
        (f"{place} mayor city government official account", X_DOMAINS),
    ):
        for hit in search.search(query, include_domains=domains, max_results=8):
            hits.setdefault(hit.url, hit)
    evidence = list(hits.values())
    if not evidence:
        return HandleSuggestion(
            mayor_name="",
            mayor_handles=[],
            city_handles=[],
            official_domains=[],
            notes="No search results.",
        )
    found = llm.parse(
        instructions=INSTRUCTIONS,
        prompt=f"City: {place}.\n\nSearch results:\n\n{format_hits(evidence)}",
        schema=HandleSuggestion,
    ).value
    return keep_evidenced(found, evidence)


def keep_evidenced(found: HandleSuggestion, evidence: list[SearchHit]) -> HandleSuggestion:
    """Drops handles and domains that never appear in the search results."""
    corpus = " ".join(f"{h.url} {h.title} {h.content}" for h in evidence).lower()

    def seen_handle(handle: str) -> bool:
        h = handle.strip().lstrip("@").lower()
        return bool(h) and any(f"{p}{h}" in corpus for p in ("@", "x.com/", "twitter.com/"))

    def seen_domain(domain: str) -> bool:
        d = domain.strip().lower().removeprefix("www.")
        return bool(d) and (d in corpus or any(on_domains(h.url, [d]) for h in evidence))

    return found.model_copy(
        update={
            "mayor_handles": [h for h in found.mayor_handles if seen_handle(h)],
            "city_handles": [h for h in found.city_handles if seen_handle(h)],
            "official_domains": [d for d in found.official_domains if seen_domain(d)],
        }
    )


def merge(target: CitySource, suggestion: CitySource) -> CitySource:
    """Fills only empty fields so human edits are never overwritten."""
    return target.model_copy(
        update={
            "mayor": target.mayor or suggestion.mayor,
            "handles": target.handles or suggestion.handles,
            "domains": target.domains or suggestion.domains,
        }
    )


def run_discovery(
    config: SourcesConfig, search: WebSearch, llm: LanguageModel, only_city: str | None
) -> SourcesConfig:
    cities = []
    for city in config.cities:
        if only_city and city.city.lower() != only_city.lower():
            cities.append(city)
            continue
        try:
            found = suggest(search, llm, city)
        except ProviderError as exc:
            print(f"{city.city}: FAILED {exc}")
            cities.append(city)
            continue
        handles = list(dict.fromkeys(found.mayor_handles + found.city_handles))[:MAX_X_HANDLES]
        domains = found.official_domains[:MAX_DOMAINS]
        print(f"{city.city}: mayor={found.mayor_name!r} handles={handles} domains={domains}")
        if found.notes:
            print(f"  notes: {found.notes}")
        cities.append(
            city.model_copy(
                update={"mayor": found.mayor_name, "handles": handles, "domains": domains}
            )
        )
    return config.model_copy(update={"cities": cities})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", help="only discover this city")
    parser.add_argument(
        "--apply", action="store_true", help="merge the suggested file into sources"
    )
    args = parser.parse_args()
    configure_logging()
    try:
        settings = load_settings()
        config = load_sources(settings.sources_path)
        suggested_path = settings.sources_path.with_name("sources.suggested.yaml")
        if args.apply:
            suggested = load_sources(suggested_path)
            by_name = {c.city: c for c in suggested.cities}
            merged = [merge(c, by_name[c.city]) if c.city in by_name else c for c in config.cities]
            save_sources(config.model_copy(update={"cities": merged}), settings.sources_path)
            print(f"Applied suggestions to {settings.sources_path}")
            return 0
        providers = build_providers(settings)
        if providers.search is None or providers.llm is None:
            raise ConfigError("Discovery needs TAVILY_API_KEY and a key for CRIER_LLM_PROVIDER")
        updated = run_discovery(config, providers.search, providers.llm, args.city)
        save_sources(updated, suggested_path)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"\nReview {suggested_path}, then run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
