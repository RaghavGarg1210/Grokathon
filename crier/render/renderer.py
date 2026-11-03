"""Renders a draft into one captioned 9:16 MP4 (plus SRT) per language."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from crier.models import Briefing, Draft, Language, RenderMode
from crier.ports import ImageGenerator, SpeechSynthesizer, VideoGenerator
from crier.render import ffmpeg
from crier.render.captions import to_srt
from crier.render.cards import SourceCard, render_source_card, render_text_panel
from crier.render.scenes import SceneAsset, build_scene_assets
from crier.render.voice import Narration, narrate
from crier.settings import Settings

Progress = Callable[[str], None]
LANGUAGES: tuple[Language, ...] = ("en", "es")
SOURCE_CARD_SECONDS = 4.0
MAX_CLIP_SECONDS = 15


@dataclass(frozen=True)
class MediaProviders:
    speech: SpeechSynthesizer
    images: ImageGenerator | None
    video: VideoGenerator | None


def render_draft(
    media: MediaProviders,
    settings: Settings,
    briefing: Briefing,
    draft: Draft,
    mode: RenderMode,
    on_progress: Progress,
) -> Draft:
    out_dir = settings.media_dir / draft.id
    script = draft.script
    narrations: dict[str, Narration] = {}
    for language in LANGUAGES:
        on_progress(f"Recording {language.upper()} voiceover with {media.speech.label}")
        narrations[language] = narrate(
            media.speech,
            script.narration(language),
            language=language,
            out_dir=out_dir / "audio",
        )
    hero_seconds = None
    if mode == "hero":
        longest = [
            max(pair) for pair in zip(*(n.beat_durations for n in narrations.values()), strict=True)
        ]
        hero_seconds = [min(MAX_CLIP_SECONDS, math.ceil(d)) for d in longest]
    assets = build_scene_assets(
        media.images,
        media.video,
        [beat.scene_prompt for beat in script.beats],
        script.on_screen("en"),
        out_dir / "scenes",
        hero_seconds=hero_seconds,
        on_progress=on_progress,
        font_path=settings.font_path,
    )
    video_paths, srt_paths = {}, {}
    for language in LANGUAGES:
        on_progress(f"Assembling {language.upper()} video")
        narration = narrations[language]
        card = _source_card(
            briefing, script.title_en if language == "en" else script.title_es, language
        )
        card_png = render_source_card(card, out_dir / f"{language}_card.jpg", settings.font_path)
        final = _assemble(
            assets, narration, script.on_screen(language), card_png, out_dir, settings
        )
        srt = out_dir / f"county_crier_{language}.srt"
        srt.write_text(to_srt(narration.cues))
        video_paths[language], srt_paths[language] = str(final), str(srt)
    on_progress("Done")
    return draft.model_copy(
        update={
            "status": "ready",
            "render_mode": mode,
            "video_paths": video_paths,
            "srt_paths": srt_paths,
            "error": "",
        }
    )


def _assemble(
    assets: list[SceneAsset],
    narration: Narration,
    labels: list[str],
    card_png: Path,
    out_dir: Path,
    settings: Settings,
) -> Path:
    language = narration.language
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, (asset, duration) in enumerate(zip(assets, narration.beat_durations, strict=True)):
        clip = work / f"{language}_scene{index}.mp4"
        if asset.hero_video:
            ffmpeg.run(ffmpeg.video_clip(asset.hero_video, duration, clip))
        else:
            ffmpeg.run(ffmpeg.still_clip(asset.still, duration, clip))
        clips.append(clip)
    body = work / f"{language}_body.mp4"
    ffmpeg.run(
        ffmpeg.concat_videos(ffmpeg.write_concat_list(clips, work / f"{language}_clips.txt"), body)
    )
    voice = work / f"{language}_voice.m4a"
    ffmpeg.run(ffmpeg.narration_track(narration.beat_audio, narration.beat_durations, voice))
    overlays = _overlays(narration, labels, work, settings.font_path)
    main = work / f"{language}_main.mp4"
    ffmpeg.run(ffmpeg.overlay_and_mux(body, voice, overlays, main))
    card = work / f"{language}_card.mp4"
    ffmpeg.run(ffmpeg.card_clip(card_png, SOURCE_CARD_SECONDS, card))
    final = out_dir / f"county_crier_{language}.mp4"
    ffmpeg.run(ffmpeg.join_av(main, card, final))
    return final


def _overlays(
    narration: Narration, labels: list[str], work: Path, font_path: Path | None
) -> list[ffmpeg.Overlay]:
    language = narration.language
    overlays = []
    for index, (label, start, duration) in enumerate(
        zip(labels, narration.beat_starts, narration.beat_durations, strict=True)
    ):
        png = render_text_panel(
            label.upper(),
            work / f"{language}_label{index}.png",
            size=58,
            color=(255, 196, 0, 255),
            font_path=font_path,
        )
        overlays.append(ffmpeg.Overlay(png, start, start + duration, "170"))
    for index, cue in enumerate(narration.cues):
        png = render_text_panel(
            cue.text, work / f"{language}_cue{index}.png", size=66, font_path=font_path
        )
        overlays.append(ffmpeg.Overlay(png, cue.start, cue.end, "H-h-330"))
    return overlays


def _source_card(briefing: Briefing, title: str, language: str) -> SourceCard:
    return SourceCard(
        title=title,
        official_url=briefing.official_url,
        post_url=briefing.post_url,
        checked_on=briefing.scanned_at.date().isoformat(),
        verified=briefing.verification == "verified",
        language=language,
    )
