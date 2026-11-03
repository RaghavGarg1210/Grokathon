"""Domain models.

`ScannedPost`, `ScanResult`, `VerificationResult` and `VideoScript` are sent to the language
model as structured-output schemas, so they use only JSON-friendly field types (dates are
strings). `Briefing` and `Draft` are the validated records the app stores and displays.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

X_POST_URL_RE = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/"
    r"(?P<handle>[A-Za-z0-9_]{1,15})/status(?:es)?/(?P<id>\d+)"
)

Category = Literal["program", "policy_decision", "event", "not_relevant"]
Confidence = Literal["high", "medium", "low"]
Verification = Literal["unverified", "verified", "announced_only", "contradicted"]
DraftStatus = Literal["draft", "rendering", "ready", "approved", "rejected", "failed"]
RenderMode = Literal["stills", "hero"]
Language = Literal["en", "es"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


class ScannedPost(BaseModel):
    post_url: str = Field(description="Exact URL of the X post or official web page")
    author_handle: str = Field(description="X handle without @ for X posts, empty for web pages")
    posted_on: str = Field(description="YYYY-MM-DD")
    post_text: str = Field(description="The announcement text, verbatim or lightly trimmed")
    category: Category
    is_campaign_or_personal: bool
    headline: str = Field(description="Plain-language headline, max 80 characters")
    what_changed: str
    who_it_affects: list[str] = Field(description="Business types affected")
    what_to_do: str
    deadline: str | None = Field(default=None, description="YYYY-MM-DD or null")
    amount: str | None = None
    relevance_score: int = Field(description="0-100: how much a local small business should care")
    confidence: Confidence

    @field_validator("relevance_score")
    @classmethod
    def _clamp_relevance(cls, value: int) -> int:
        return max(0, min(100, value))


class ScanResult(BaseModel):
    posts: list[ScannedPost]


class VerificationResult(BaseModel):
    status: Literal["verified", "announced_only", "contradicted"]
    official_url: str | None = None
    notes: str
    deadline: str | None = Field(default=None, description="Deadline per the official page")


class Briefing(BaseModel):
    id: str
    city: str
    county: str
    mayor: str
    post_url: str
    author_handle: str
    posted_on: date
    post_text: str
    category: Category
    is_campaign_or_personal: bool
    headline: str
    what_changed: str
    who_it_affects: list[str]
    what_to_do: str
    deadline: date | None = None
    amount: str | None = None
    relevance_score: int
    confidence: Confidence
    verification: Verification = "unverified"
    official_url: str | None = None
    verification_notes: str = ""
    scanned_at: datetime = Field(default_factory=utc_now)

    @staticmethod
    def make_id(post_url: str) -> str:
        return hashlib.sha1(post_url.lower().encode()).hexdigest()[:16]

    @property
    def is_x_post(self) -> bool:
        return bool(X_POST_URL_RE.match(self.post_url))

    @property
    def source_label(self) -> str:
        """`@handle on X` for X posts, the website host for official pages."""
        return f"@{self.author_handle} on X" if self.is_x_post else self.author_handle

    def is_publishable(self, min_relevance: int) -> bool:
        return (
            not self.is_campaign_or_personal
            and self.category != "not_relevant"
            and self.relevance_score >= min_relevance
        )

    def can_make_video(self, override_unverified: bool = False) -> bool:
        if self.verification == "contradicted":
            return False
        return self.verification == "verified" or override_unverified


class ScriptBeat(BaseModel):
    narration_en: str
    narration_es: str
    on_screen_text_en: str = Field(description="Max 6 words")
    on_screen_text_es: str = Field(description="Max 6 words")
    scene_prompt: str = Field(description="Visual prompt, no real people, no text, no logos")


class VideoScript(BaseModel):
    title_en: str
    title_es: str
    beats: list[ScriptBeat]
    caption_en: str = Field(description="Social post caption ending with the official link")
    caption_es: str

    def narration(self, language: Language) -> list[str]:
        return [beat.narration_en if language == "en" else beat.narration_es for beat in self.beats]

    def on_screen(self, language: Language) -> list[str]:
        attr = "on_screen_text_en" if language == "en" else "on_screen_text_es"
        return [getattr(beat, attr) for beat in self.beats]

    def caption(self, language: Language) -> str:
        return self.caption_en if language == "en" else self.caption_es


class Draft(BaseModel):
    id: str
    briefing_id: str
    script: VideoScript
    status: DraftStatus = "draft"
    render_mode: RenderMode = "stills"
    video_paths: dict[str, str] = Field(default_factory=dict)
    srt_paths: dict[str, str] = Field(default_factory=dict)
    override_unverified: bool = False
    reviewer_note: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
