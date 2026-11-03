"""Test doubles for the provider boundary. All data refers to a fictional city."""

from __future__ import annotations

import io
import subprocess
from datetime import date
from pathlib import Path

from PIL import Image

from crier.config import CitySource
from crier.models import Briefing, ScannedPost, ScriptBeat, VideoScript
from crier.ports import ParsedResult, ProviderError, SearchHit, SpeechResult
from crier.settings import (
    GeminiSettings,
    MagicHourSettings,
    ProviderChoice,
    Settings,
    TavilySettings,
    XaiSettings,
)

CITY = CitySource(
    city="Exampleton",
    county="Sample",
    mayor="Pat Example",
    lat=32.0,
    lon=-83.0,
    handles=["ExampletonGA", "MayorExample"],
    domains=["exampleton.gov"],
)
POST_URL = "https://x.com/ExampletonGA/status/1234567890"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "providers": ProviderChoice(),
        "tavily": TavilySettings(api_key="tvly-test"),
        "gemini": GeminiSettings(api_key="gemini-test", text_model="gemini-test"),
        "magic_hour": MagicHourSettings(api_key="mh-test"),
        "xai": XaiSettings(api_key="xai-test", text_model="grok-test"),
        "demo_mode": False,
        "data_dir": tmp_path / "data",
        "sources_path": tmp_path / "sources.yaml",
        "scan_days": 30,
        "min_relevance": 50,
        "render_resolution": "720p",
        "max_hero_renders_per_day": 1,
        "video_poll_timeout_s": 5,
        "font_path": None,
    }
    return Settings(**{**base, **overrides})


def scanned_post(**overrides) -> ScannedPost:
    base = {
        "post_url": POST_URL,
        "author_handle": "ExampletonGA",
        "posted_on": "2026-10-20",
        "post_text": "Applications open for the Main Street Facade Grant.",
        "category": "program",
        "is_campaign_or_personal": False,
        "headline": "Facade grants open for downtown shops",
        "what_changed": "The city opened facade improvement grants.",
        "who_it_affects": ["retail", "restaurants"],
        "what_to_do": "Apply online before the deadline.",
        "deadline": "2026-12-01",
        "amount": "Up to $5,000",
        "relevance_score": 80,
        "confidence": "high",
    }
    return ScannedPost(**{**base, **overrides})


def briefing(**overrides) -> Briefing:
    post = scanned_post()
    base = {
        "id": Briefing.make_id(post.post_url),
        "city": CITY.city,
        "county": CITY.county,
        "mayor": CITY.mayor,
        "post_url": post.post_url,
        "author_handle": post.author_handle,
        "posted_on": date(2026, 10, 20),
        "post_text": post.post_text,
        "category": "program",
        "is_campaign_or_personal": False,
        "headline": post.headline,
        "what_changed": post.what_changed,
        "who_it_affects": post.who_it_affects,
        "what_to_do": post.what_to_do,
        "deadline": date(2026, 12, 1),
        "amount": post.amount,
        "relevance_score": 80,
        "confidence": "high",
        "verification": "verified",
        "official_url": "https://exampleton.gov/facade-grant",
    }
    return Briefing(**{**base, **overrides})


def video_script(beats: int = 3) -> VideoScript:
    return VideoScript(
        title_en="Facade grants open",
        title_es="Subvenciones abiertas",
        beats=[
            ScriptBeat(
                narration_en=f"Beat {i} explains the grant clearly.",
                narration_es=f"El paso {i} explica la subvencion.",
                on_screen_text_en=f"Step {i}",
                on_screen_text_es=f"Paso {i}",
                scene_prompt="A small shop front in Georgia.",
            )
            for i in range(1, beats + 1)
        ],
        caption_en="Grants open. https://exampleton.gov/facade-grant",
        caption_es="Subvenciones abiertas. https://exampleton.gov/facade-grant",
    )


def hit(url: str = POST_URL, content: str = "Facade grants are open.", **overrides) -> SearchHit:
    base = {"url": url, "title": "Exampleton", "content": content, "published_date": "2026-10-20"}
    return SearchHit(**{**base, **overrides})


def tone_mp3(seconds: float) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


class FakeLLM:
    """Returns queued parse results (or raises queued exceptions); records every call."""

    label = "FakeLLM"

    def __init__(self, results: list | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []

    def parse(self, **kwargs) -> ParsedResult:
        self.calls.append(kwargs)
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, ParsedResult):
            return value
        return ParsedResult(value=value, citations=[], usage={})


class FakeSearch:
    """Returns queued hit lists, one per call; records the queries."""

    label = "FakeSearch"

    def __init__(self, results: list[list[SearchHit]] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []

    def search(self, query: str, **kwargs) -> list[SearchHit]:
        self.calls.append({"query": query, **kwargs})
        return self.results.pop(0) if self.results else []


class FakeMedia:
    """Image, speech and video provider that synthesizes real media for render tests."""

    label = "FakeMedia"

    def __init__(self, fail_images: bool = False) -> None:
        self.fail_images = fail_images
        self.videos_started = 0

    def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> bytes:
        if self.fail_images:
            raise ProviderError("image service down")
        buffer = io.BytesIO()
        Image.new("RGB", (540, 960), (40, 90, 140)).save(buffer, format="PNG")
        return buffer.getvalue()

    def tts(self, text: str, *, language: str) -> SpeechResult:
        duration = 1.2
        return SpeechResult.with_estimated_timing(tone_mp3(duration), text, duration, "mp3")

    def start_video(self, prompt: str, *, image, duration: int, aspect_ratio: str = "9:16") -> str:
        self.videos_started += 1
        raise ProviderError("video generation unavailable in tests")

    def wait_for_video(self, job_id: str, on_progress=None) -> bytes:
        raise ProviderError("not used")
