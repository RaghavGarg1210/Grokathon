import subprocess
from datetime import date
from pathlib import Path

import pytest

from crier.config import SourcesConfig
from crier.models import Draft, ScanResult, VerificationResult
from crier.pipeline import Pipeline, PolicyError
from crier.ports import Providers
from crier.scanners import SearchScanner
from crier.settings import ConfigError
from crier.store import Store
from crier.verifiers import SearchVerifier
from tests.fakes import (
    CITY,
    POST_URL,
    FakeLLM,
    FakeMedia,
    FakeSearch,
    briefing,
    hit,
    make_settings,
    scanned_post,
    video_script,
)

TODAY = date(2026, 11, 2)
CAMPAIGN_URL = "https://x.com/MayorExample/status/2"


def make_providers(
    llm: FakeLLM | None = None, search: FakeSearch | None = None, media: FakeMedia | None = None
) -> Providers:
    llm, search, media = llm or FakeLLM(), search or FakeSearch(), media or FakeMedia()
    return Providers(
        scanner=SearchScanner(search, llm),
        verifier=SearchVerifier(search, llm),
        llm=llm,
        search=search,
        images=media,
        speech=media,
        video=media,
    )


def make_pipeline(tmp_path: Path, providers: Providers | None = None) -> Pipeline:
    settings = make_settings(tmp_path)
    sources = SourcesConfig(state_domains=["georgia.gov"], cities=[CITY])
    return Pipeline(settings, Store(settings.db_path), sources, providers or make_providers())


def test_scan_verifies_publishable_posts_and_dedupes(tmp_path):
    official = "https://exampleton.gov/g"
    search = FakeSearch(
        [
            [hit(), hit(CAMPAIGN_URL)],  # X search
            [],  # city site search
            [hit(official)],  # verification search
            [hit()],  # second scan: X search
            [],  # second scan: city site search
        ]
    )
    campaign = scanned_post(post_url=CAMPAIGN_URL, is_campaign_or_personal=True)
    llm = FakeLLM(
        [
            ScanResult(posts=[scanned_post(), campaign]),
            VerificationResult(status="verified", official_url=official, notes="ok"),
            ScanResult(posts=[scanned_post()]),
        ]
    )
    pipeline = make_pipeline(tmp_path, make_providers(llm, search))
    first = pipeline.scan(today=TODAY)
    assert (first.found, first.new) == (2, 2)
    stored = {b.post_url: b for b in pipeline.store.list_briefings()}
    assert stored[POST_URL].verification == "verified"
    assert stored[CAMPAIGN_URL].verification == "unverified"
    assert search.calls[2]["include_domains"] == ["exampleton.gov", "georgia.gov"]
    second = pipeline.scan(today=TODAY)
    assert second.new == 0 and len(llm.calls) == 3


def test_scan_without_scanner_names_missing_keys(tmp_path):
    providers = Providers(missing={"scan": ["TAVILY_API_KEY", "GEMINI_API_KEY"]})
    pipeline = make_pipeline(tmp_path, providers)
    with pytest.raises(ConfigError, match="TAVILY_API_KEY and GEMINI_API_KEY"):
        pipeline.scan(today=TODAY)
    assert pipeline.scannable_cities == [CITY]


def test_render_blocked_when_unverified_without_override(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.store.add_briefing(briefing(verification="announced_only", official_url=None))
    pipeline.store.save_draft(Draft(id="d1", briefing_id=briefing().id, script=video_script()))
    with pytest.raises(PolicyError):
        pipeline.render("d1", "stills")


def test_hero_render_requires_video_provider(tmp_path):
    media = FakeMedia()
    providers = make_providers(media=media)
    providers.video = None
    providers.missing = {"video": ["MAGIC_HOUR_API_KEY"]}
    pipeline = make_pipeline(tmp_path, providers)
    pipeline.store.add_briefing(briefing())
    pipeline.store.save_draft(Draft(id="d1", briefing_id=briefing().id, script=video_script()))
    with pytest.raises(ConfigError, match="MAGIC_HOUR_API_KEY"):
        pipeline.render("d1", "hero")


def test_approve_requires_rendered_draft(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.store.save_draft(Draft(id="d1", briefing_id="b1", script=video_script()))
    with pytest.raises(PolicyError):
        pipeline.approve("d1")


def test_hero_budget_enforced(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.store.add_briefing(briefing())
    pipeline.store.save_draft(
        Draft(id="old", briefing_id="x", script=video_script(), status="ready", render_mode="hero")
    )
    pipeline.store.save_draft(Draft(id="d1", briefing_id=briefing().id, script=video_script()))
    with pytest.raises(PolicyError, match="budget"):
        pipeline.render("d1", "hero")


def test_full_stills_render_produces_bilingual_videos(tmp_path):
    pipeline = make_pipeline(tmp_path, make_providers(media=FakeMedia(fail_images=True)))
    pipeline.store.add_briefing(briefing())
    pipeline.store.save_draft(Draft(id="d1", briefing_id=briefing().id, script=video_script()))
    draft = pipeline.render("d1", "stills", on_progress=lambda _: None)
    assert draft.status == "ready"
    for language in ("en", "es"):
        video = Path(draft.video_paths[language])
        assert video.exists() and video.stat().st_size > 10_000
        assert _duration(video) == pytest.approx(3 * 1.55 + 4.0, abs=0.5)
        assert "-->" in Path(draft.srt_paths[language]).read_text()
    pipeline.approve("d1", "looks good")
    assert pipeline.store.list_drafts(status="approved")[0].reviewer_note == "looks good"


def test_hero_render_with_png_stills_falls_back_when_video_fails(tmp_path):
    media = FakeMedia()
    pipeline = make_pipeline(tmp_path, make_providers(media=media))
    pipeline.store.add_briefing(briefing())
    pipeline.store.save_draft(Draft(id="d1", briefing_id=briefing().id, script=video_script()))
    draft = pipeline.render("d1", "hero", on_progress=lambda _: None)
    assert draft.status == "ready" and media.videos_started == 3
    assert Path(draft.video_paths["en"]).stat().st_size > 10_000


def _duration(path: Path) -> float:
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(output.strip())
