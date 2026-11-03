"""Application service: scan -> verify -> store, then draft -> render -> approve."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from crier.config import CitySource, SourcesConfig
from crier.models import Briefing, Draft, RenderMode, VideoScript
from crier.ports import ProviderError, Providers
from crier.render.ffmpeg import RenderError
from crier.render.renderer import MediaProviders, render_draft
from crier.scan import scan_city
from crier.script import ScriptError, enforce_scene_rules, validate_script, write_script
from crier.settings import Settings
from crier.store import Store
from crier.verify import verify_briefing

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


def _ignore(_: str) -> None:
    return None


class PolicyError(RuntimeError):
    """An action blocked by a trust or budget rule (safe to show to the reviewer)."""


@dataclass
class ScanSummary:
    cities: int = 0
    found: int = 0
    new: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self, settings: Settings, store: Store, sources: SourcesConfig, providers: Providers
    ) -> None:
        self.settings = settings
        self.store = store
        self.sources = sources
        self.providers = providers

    def can(self, capability: str) -> bool:
        return self.providers.can(capability)

    def scan_blocker(self, city: CitySource) -> str | None:
        """Why this city's sources config cannot be scanned, or None if it can.
        (Missing API keys are reported separately via `providers.missing`.)"""
        if self.providers.scanner is None:
            return None if city.handles or city.domains else "no handles or domains configured"
        return self.providers.scanner.missing_config(city)

    @property
    def scannable_cities(self) -> list[CitySource]:
        return [c for c in self.sources.cities if self.scan_blocker(c) is None]

    def scan(
        self,
        city_names: list[str] | None = None,
        on_progress: Progress = _ignore,
        today: date | None = None,
    ) -> ScanSummary:
        self.providers.require("scan")
        today = today or date.today()
        cities = (
            [self.sources.get_city(n) for n in city_names] if city_names else self.scannable_cities
        )
        summary = ScanSummary()
        for city in cities:
            summary.cities += 1
            self._scan_one(city, today, summary, on_progress)
        return summary

    def _scan_one(
        self, city: CitySource, today: date, summary: ScanSummary, on_progress: Progress
    ) -> None:
        blocker = self.scan_blocker(city)
        if blocker:
            summary.errors.append(f"{city.city}: {blocker}")
            return
        on_progress(f"Searching {city.city} sources with {self.providers.label('scan')}")
        try:
            result = scan_city(
                self.providers.require("scan"),
                city,
                today=today,
                scan_days=self.settings.scan_days,
            )
        except ProviderError as exc:
            log.exception("scan failed for %s", city.city)
            summary.errors.append(f"{city.city}: {exc}")
            self.store.record_scan_run(city.city, kept=0, new=0, rejected=0, error=str(exc))
            return
        new = 0
        for briefing in result.briefings:
            if self.store.get_briefing(briefing.id):
                continue
            if briefing.is_publishable(self.settings.min_relevance):
                on_progress(f"Verifying on official sites: {briefing.headline}")
                briefing = self._verify(briefing, city)
            new += int(self.store.add_briefing(briefing))
        summary.found += len(result.briefings)
        summary.new += new
        summary.rejected += result.rejected
        self.store.record_scan_run(
            city.city,
            kept=len(result.briefings),
            new=new,
            rejected=result.rejected,
            usage=result.usage,
        )
        on_progress(f"{city.city}: {len(result.briefings)} announcements analyzed, {new} new")

    def _verify(self, briefing: Briefing, city: CitySource) -> Briefing:
        try:
            return verify_briefing(
                self.providers.require("verify"),
                briefing,
                self.sources.verification_domains(city),
            )
        except ProviderError as exc:
            log.warning("verification failed for %s: %s", briefing.id, exc)
            return briefing.model_copy(update={"verification_notes": f"Verification failed: {exc}"})

    def reverify(self, briefing_id: str) -> Briefing:
        briefing = self._require_briefing(briefing_id)
        updated = self._verify(briefing, self.sources.get_city(briefing.city))
        self.store.update_briefing(updated)
        return updated

    def create_draft(self, briefing_id: str, on_progress: Progress = _ignore) -> Draft:
        briefing = self._require_briefing(briefing_id)
        llm = self.providers.require("script")
        on_progress(f"Writing English + Spanish script with {self.providers.label('script')}")
        script = write_script(llm, briefing)
        draft = Draft(id=uuid.uuid4().hex[:12], briefing_id=briefing.id, script=script)
        return self.store.save_draft(draft)

    def update_script(self, draft_id: str, script: VideoScript) -> Draft:
        draft = self._require_draft(draft_id)
        try:
            validate_script(script)
        except ScriptError as exc:
            raise PolicyError(str(exc)) from exc
        return self.store.save_draft(
            draft.model_copy(update={"script": enforce_scene_rules(script), "status": "draft"})
        )

    def render(
        self,
        draft_id: str,
        mode: RenderMode,
        on_progress: Progress = _ignore,
        override_unverified: bool = False,
    ) -> Draft:
        draft = self._require_draft(draft_id)
        briefing = self._require_briefing(draft.briefing_id)
        if not briefing.can_make_video(override_unverified):
            raise PolicyError(
                "Not verified on an official site. Tick the override to render anyway."
            )
        media = self._media(mode)
        if mode == "hero" and self._hero_renders_today() >= self.settings.max_hero_renders_per_day:
            raise PolicyError("Daily hero video budget reached. Use the stills render.")
        draft = self.store.save_draft(
            draft.model_copy(
                update={"status": "rendering", "override_unverified": override_unverified}
            )
        )
        try:
            rendered = render_draft(media, self.settings, briefing, draft, mode, on_progress)
        except (ProviderError, RenderError, OSError) as exc:
            log.exception("render failed for draft %s", draft_id)
            self.store.save_draft(draft.model_copy(update={"status": "failed", "error": str(exc)}))
            raise
        return self.store.save_draft(rendered)

    def approve(self, draft_id: str, note: str = "") -> Draft:
        draft = self._require_draft(draft_id)
        if draft.status not in {"ready", "approved"}:
            raise PolicyError("Only rendered drafts can be approved.")
        return self.store.save_draft(
            draft.model_copy(update={"status": "approved", "reviewer_note": note})
        )

    def reject(self, draft_id: str, note: str = "") -> Draft:
        draft = self._require_draft(draft_id)
        return self.store.save_draft(
            draft.model_copy(update={"status": "rejected", "reviewer_note": note})
        )

    def _media(self, mode: RenderMode) -> MediaProviders:
        """Voice is required; images fall back to branded cards; hero mode needs video."""
        return MediaProviders(
            speech=self.providers.require("voice"),
            images=self.providers.images,
            video=self.providers.require("video") if mode == "hero" else None,
        )

    def _hero_renders_today(self) -> int:
        return self.store.count_hero_renders_on(datetime.now(UTC).date())

    def _require_briefing(self, briefing_id: str) -> Briefing:
        briefing = self.store.get_briefing(briefing_id)
        if briefing is None:
            raise PolicyError(f"Briefing {briefing_id} not found")
        return briefing

    def _require_draft(self, draft_id: str) -> Draft:
        draft = self.store.get_draft(draft_id)
        if draft is None:
            raise PolicyError(f"Draft {draft_id} not found")
        return draft
