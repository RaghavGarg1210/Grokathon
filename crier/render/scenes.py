"""Scene visuals: one AI still per beat, optionally animated into an AI video clip."""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crier.ports import ImageGenerator, ProviderError, VideoGenerator
from crier.render.cards import render_fallback_scene

log = logging.getLogger(__name__)

Progress = Callable[[str], None]
MAX_PARALLEL_JOBS = 4


@dataclass
class SceneAsset:
    still: Path
    hero_video: Path | None = None


def build_scene_assets(
    images: ImageGenerator | None,
    video: VideoGenerator | None,
    prompts: list[str],
    fallback_texts: list[str],
    out_dir: Path,
    *,
    hero_seconds: list[int] | None,
    on_progress: Progress,
    font_path: Path | None = None,
) -> list[SceneAsset]:
    """One still per beat (branded card if no image provider); if `hero_seconds` is given
    and a video provider is configured, each still is animated too."""
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = [_cache_key(prompt) for prompt in prompts]
    if images is None:
        on_progress("No image provider configured: using branded scene cards")
    else:
        on_progress(f"Generating {len(prompts)} scene images with {images.label}")
    with ThreadPoolExecutor(MAX_PARALLEL_JOBS) as pool:
        stills = list(
            pool.map(
                lambda i: _make_still(
                    images,
                    prompts[i],
                    fallback_texts[i],
                    out_dir / f"scene{i}_{keys[i]}.jpg",
                    font_path,
                ),
                range(len(prompts)),
            )
        )
    assets = [SceneAsset(still=still) for still in stills]
    if hero_seconds is None or video is None:
        return assets
    on_progress(f"Animating {len(prompts)} scenes with {video.label} (this takes a few minutes)")
    with ThreadPoolExecutor(MAX_PARALLEL_JOBS) as pool:
        videos = list(
            pool.map(
                lambda i: _make_video(
                    video,
                    prompts[i],
                    stills[i],
                    hero_seconds[i],
                    out_dir / f"scene{i}_{keys[i]}_{hero_seconds[i]}s.mp4",
                    on_progress,
                ),
                range(len(prompts)),
            )
        )
    for asset, clip in zip(assets, videos, strict=True):
        asset.hero_video = clip
    return assets


def _cache_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode()).hexdigest()[:10]


def _make_still(
    images: ImageGenerator | None,
    prompt: str,
    fallback_text: str,
    path: Path,
    font_path: Path | None,
) -> Path:
    if path.exists():
        return path
    if images is None:
        render_fallback_scene(fallback_text, path, font_path)
        return path
    try:
        _save_as_jpeg(images.generate_image(prompt), path)
    except (ProviderError, OSError) as exc:
        log.warning("image generation failed, using branded fallback: %s", exc)
        render_fallback_scene(fallback_text, path, font_path)
    return path


def _save_as_jpeg(data: bytes, path: Path) -> None:
    """Providers return PNG or JPEG; ffmpeg picks the decoder from the .jpg extension."""
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGB").save(path, format="JPEG", quality=92)


def _make_video(
    video: VideoGenerator,
    prompt: str,
    still: Path,
    seconds: int,
    path: Path,
    on_progress: Progress,
) -> Path | None:
    if path.exists():
        return path
    try:
        job_id = video.start_video(prompt, image=still.read_bytes(), duration=seconds)
        path.write_bytes(video.wait_for_video(job_id))
        on_progress(f"Scene clip ready: {path.name}")
        return path
    except ProviderError as exc:
        log.warning("video generation failed for %s, falling back to still: %s", path.name, exc)
        on_progress(f"Scene {path.stem} fell back to an animated still")
        return None
