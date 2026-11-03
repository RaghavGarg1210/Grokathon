"""Builds the providers chosen in `.env` and reports which API keys each step still needs."""

from __future__ import annotations

from typing import Any

from crier.ports import Providers
from crier.providers.gemini import GeminiClient
from crier.providers.magic_hour import MagicHourClient
from crier.providers.tavily import TavilyClient
from crier.providers.xai import XaiClient
from crier.scanners import SearchScanner, XSearchScanner
from crier.settings import PROVIDER_KEY_ENV, ConfigError, Settings
from crier.verifiers import GrokVerifier, SearchVerifier

PROVIDER_LABELS = {
    "tavily": "Tavily",
    "gemini": "Gemini",
    "magic_hour": "Magic Hour",
    "xai": "Grok",
}


class ClientFactory:
    """Creates at most one client per provider, only when its API key is set."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[str, Any] = {}

    def get(self, provider: str) -> Any:
        if provider not in self._cache:
            has_key = bool(self._settings.api_key(provider))
            self._cache[provider] = self._create(provider) if has_key else None
        return self._cache[provider]

    def _create(self, provider: str) -> Any:
        s = self._settings
        video_options = {
            "resolution": s.render_resolution,
            "poll_timeout_s": s.video_poll_timeout_s,
        }
        if provider == "tavily":
            return TavilyClient(s.tavily)
        if provider == "gemini":
            return GeminiClient(s.gemini)
        if provider == "magic_hour":
            return MagicHourClient(s.magic_hour, **video_options)
        if provider == "xai":
            return XaiClient(s.xai, **video_options)
        raise ConfigError(f"Unknown provider {provider!r}")


def build_providers(settings: Settings, clients: ClientFactory | None = None) -> Providers:
    choice = settings.providers
    clients = clients or ClientFactory(settings)
    providers = Providers(
        llm=clients.get(choice.llm),
        search=clients.get("tavily"),
        images=clients.get(choice.image),
        speech=clients.get(choice.tts),
        video=clients.get(choice.video),
    )
    if choice.search == "xai":
        search_needs = ["xai"]
        xai = clients.get("xai")
        if xai:
            providers.scanner = XSearchScanner(xai, settings.xai.search_max_turns)
            providers.verifier = GrokVerifier(xai)
    else:
        search_needs = ["tavily", choice.llm]
        if providers.search and providers.llm:
            providers.scanner = SearchScanner(
                providers.search, providers.llm, settings.tavily.max_results
            )
            providers.verifier = SearchVerifier(providers.search, providers.llm)
    needs = {
        "scan": search_needs,
        "verify": search_needs,
        "script": [choice.llm],
        "voice": [choice.tts],
        "images": [choice.image],
        "video": [choice.video],
    }
    providers.labels = {
        capability: " + ".join(PROVIDER_LABELS[p] for p in dict.fromkeys(names))
        for capability, names in needs.items()
    }
    for capability, names in needs.items():
        missing = [PROVIDER_KEY_ENV[p] for p in dict.fromkeys(names) if not settings.api_key(p)]
        if missing:
            providers.missing[capability] = missing
    return providers
