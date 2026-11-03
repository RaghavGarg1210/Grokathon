"""Capability ports: what the pipeline needs from AI and search providers.

Each step (search, language model, images, voice, video) depends on one small protocol, so
the provider behind it (Tavily, Gemini, Magic Hour, xAI) is chosen in `.env`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from crier.config import CitySource
from crier.models import Briefing, Language, ScannedPost, VerificationResult
from crier.settings import ConfigError

T = TypeVar("T", bound=BaseModel)

PAUSE_CHARS = ".,;:!?"
PAUSE_WEIGHT = 4.0


class ProviderError(RuntimeError):
    """Any failure talking to an external provider, with a message safe to show in the UI."""


@dataclass
class ParsedResult(Generic[T]):
    value: T
    citations: list[str]
    usage: dict[str, Any]


@dataclass
class SpeechResult:
    audio: bytes
    chars: list[str]
    times: list[tuple[float, float]]
    duration: float
    extension: str = "mp3"

    @classmethod
    def with_estimated_timing(
        cls, audio: bytes, text: str, duration: float, extension: str
    ) -> SpeechResult:
        """For TTS engines without timestamps: spreads characters across the audio, pausing
        longer on punctuation, so captions stay roughly in sync."""
        chars = list(text)
        weights = [PAUSE_WEIGHT if char in PAUSE_CHARS else 1.0 for char in chars]
        total = sum(weights) or 1.0
        times, cursor = [], 0.0
        for weight in weights:
            step = duration * weight / total
            times.append((cursor, cursor + step))
            cursor += step
        return cls(audio, chars, times, duration, extension)


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    content: str
    published_date: str | None = None


@dataclass
class ScanBatch:
    """Posts a scanner found for one city.

    grounded=True means `source_urls` lists every page the model was shown, so any post
    URL outside it is invented and must be rejected. Otherwise `source_urls` are citations.
    """

    posts: list[ScannedPost]
    source_urls: list[str]
    grounded: bool
    usage: dict[str, Any] = field(default_factory=dict)


class LanguageModel(Protocol):
    label: str

    def parse(self, *, instructions: str, prompt: str, schema: type[T]) -> ParsedResult[T]: ...


class AgenticModel(Protocol):
    """A model that runs server-side search tools itself (xAI Responses API)."""

    def parse(
        self,
        *,
        instructions: str,
        prompt: str,
        schema: type[T],
        tools: list[dict[str, Any]] | None = None,
        max_turns: int | None = None,
    ) -> ParsedResult[T]: ...


class WebSearch(Protocol):
    label: str

    def search(
        self,
        query: str,
        *,
        include_domains: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        max_results: int | None = None,
    ) -> list[SearchHit]: ...


class ImageGenerator(Protocol):
    label: str

    def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> bytes: ...


class SpeechSynthesizer(Protocol):
    label: str

    def tts(self, text: str, *, language: Language) -> SpeechResult: ...


class VideoGenerator(Protocol):
    label: str

    def start_video(
        self, prompt: str, *, image: bytes | None, duration: int, aspect_ratio: str = "9:16"
    ) -> str: ...

    def wait_for_video(
        self, job_id: str, on_progress: Callable[[int], None] | None = None
    ) -> bytes: ...


class PostScanner(Protocol):
    label: str

    def missing_config(self, source: CitySource) -> str | None:
        """Why this city cannot be scanned (e.g. no handles), or None if it can."""
        ...

    def scan(self, source: CitySource, *, from_date: date, to_date: date) -> ScanBatch: ...


class Verifier(Protocol):
    def check(self, briefing: Briefing, domains: list[str]) -> VerificationResult: ...


CAPABILITY_ACTIONS = {
    "scan": "scan for announcements",
    "verify": "check official sites",
    "script": "write scripts",
    "voice": "record voiceovers",
    "images": "generate scene images",
    "video": "render hero video clips",
}
CAPABILITY_ATTRS = {
    "scan": "scanner",
    "verify": "verifier",
    "script": "llm",
    "voice": "speech",
    "images": "images",
    "video": "video",
}


@dataclass
class Providers:
    """The provider behind each capability; None when its API key is missing."""

    scanner: PostScanner | None = None
    verifier: Verifier | None = None
    llm: LanguageModel | None = None
    search: WebSearch | None = None
    images: ImageGenerator | None = None
    speech: SpeechSynthesizer | None = None
    video: VideoGenerator | None = None
    labels: dict[str, str] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)

    def can(self, capability: str) -> bool:
        return getattr(self, CAPABILITY_ATTRS[capability]) is not None

    def require(self, capability: str) -> Any:
        provider = getattr(self, CAPABILITY_ATTRS[capability])
        if provider is None:
            keys = " and ".join(self.missing.get(capability, [])) or "an API key"
            raise ConfigError(f"To {CAPABILITY_ACTIONS[capability]}, add {keys} to .env")
        return provider

    def label(self, capability: str) -> str:
        return self.labels.get(capability, capability)
