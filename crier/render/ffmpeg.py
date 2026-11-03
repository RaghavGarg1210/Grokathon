"""ffmpeg command builders (pure) plus a runner.

The local ffmpeg may lack libass/freetype, so text is never drawn by ffmpeg: captions arrive
as PNG overlays rendered by Pillow.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from crier.render.cards import FRAME_SIZE

FPS = 30
AUDIO_RATE = 44100
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "160k", "-ar", str(AUDIO_RATE), "-ac", "2"]


class RenderError(RuntimeError):
    """An ffmpeg/ffprobe step failed."""


@dataclass(frozen=True)
class Overlay:
    image: Path
    start: float
    end: float
    y: str  # ffmpeg expression, e.g. "160" or "H-h-320"


def _fit_filter(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"


def still_clip(image: Path, duration: float, out: Path) -> list[str]:
    """Slow push-in (Ken Burns) on a still image."""
    width, height = FRAME_SIZE
    frames = max(1, round(duration * FPS))
    zoom = (
        f"zoompan=z='min(zoom+0.0006,1.12)':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={FPS}"
    )
    vf = f"{_fit_filter(width * 2, height * 2)},{zoom},format=yuv420p"
    return ["ffmpeg", "-y", "-i", str(image), "-vf", vf, "-frames:v", str(frames), *X264, str(out)]


def video_clip(video: Path, duration: float, out: Path) -> list[str]:
    """Fits a generated clip to the frame and loops/trims it to `duration` (audio dropped)."""
    width, height = FRAME_SIZE
    vf = f"{_fit_filter(width, height)},fps={FPS},format=yuv420p"
    return [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(video),
        "-t",
        f"{duration:.3f}",
        "-vf",
        vf,
        "-an",
        *X264,
        str(out),
    ]


def concat_videos(list_file: Path, out: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(out),
    ]


def narration_track(audio: list[Path], durations: list[float], out: Path) -> list[str]:
    """Pads each beat's voiceover to its beat length and joins them."""
    if len(audio) != len(durations):
        raise ValueError("audio and durations must have the same length")
    inputs = [arg for path in audio for arg in ("-i", str(path))]
    parts = [
        f"[{i}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=whole_dur={d:.3f},atrim=0:{d:.3f}[a{i}]"
        for i, d in enumerate(durations)
    ]
    joined = "".join(f"[a{i}]" for i in range(len(audio)))
    graph = ";".join(parts) + f";{joined}concat=n={len(audio)}:v=0:a=1[out]"
    return ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", *AAC, str(out)]


def overlay_and_mux(body: Path, narration: Path, overlays: list[Overlay], out: Path) -> list[str]:
    inputs = ["-i", str(body), "-i", str(narration)]
    for overlay in overlays:
        inputs += ["-i", str(overlay.image)]
    if not overlays:
        return [
            "ffmpeg",
            "-y",
            *inputs,
            "-map",
            "0:v",
            "-map",
            "1:a",
            *X264,
            *AAC,
            "-shortest",
            str(out),
        ]
    steps, previous = [], "[0:v]"
    for index, overlay in enumerate(overlays):
        label = f"[v{index + 1}]"
        steps.append(
            f"{previous}[{index + 2}:v]overlay=x=(W-w)/2:y={overlay.y}"
            f":enable='between(t,{overlay.start:.2f},{overlay.end:.2f})'{label}"
        )
        previous = label
    return [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(steps),
        "-map",
        previous,
        "-map",
        "1:a",
        *X264,
        *AAC,
        "-shortest",
        str(out),
    ]


def card_clip(image: Path, duration: float, out: Path) -> list[str]:
    width, height = FRAME_SIZE
    return [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration:.2f}",
        "-i",
        str(image),
        "-f",
        "lavfi",
        "-t",
        f"{duration:.2f}",
        "-i",
        f"anullsrc=r={AUDIO_RATE}:cl=stereo",
        "-vf",
        f"{_fit_filter(width, height)},fps={FPS},format=yuv420p",
        *X264,
        *AAC,
        "-shortest",
        str(out),
    ]


def join_av(first: Path, second: Path, out: Path) -> list[str]:
    graph = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]"
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        *X264,
        *AAC,
        "-movflags",
        "+faststart",
        str(out),
    ]


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RenderError(f"{cmd[0]} failed ({result.returncode}): {result.stderr[-800:]}")


def write_concat_list(clips: list[Path], list_file: Path) -> Path:
    list_file.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clips))
    return list_file
