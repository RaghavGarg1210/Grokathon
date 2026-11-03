"""Checks every configured provider (keys, model names, one cheap call each).

Usage: python -m scripts.smoke_test [--image] [--video]
(--image and --video spend credits; search, text and TTS are cheap.)
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from crier.bootstrap import configure_logging
from crier.ports import ProviderError, Providers
from crier.providers.registry import ClientFactory, build_providers
from crier.settings import ConfigError, Settings, load_settings

Check = tuple[str, Callable[[], str]]


class SmokeAnswer(BaseModel):
    summary: str
    keywords: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="store_true", help="also generate one image")
    parser.add_argument("--video", action="store_true", help="also generate one short clip")
    args = parser.parse_args()
    configure_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 1
    clients = ClientFactory(settings)
    providers = build_providers(settings, clients)
    out = settings.data_dir / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for capability, keys in providers.missing.items():
        failures += 1
        print(f"FAIL {capability}: set {' and '.join(keys)} in .env")
    for name, check in build_checks(settings, clients, providers, out, args):
        try:
            print(f"PASS {name}: {check()}")
        except (ProviderError, ConfigError) as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    return 1 if failures else 0


def build_checks(
    settings: Settings,
    clients: ClientFactory,
    providers: Providers,
    out: Path,
    args: argparse.Namespace,
) -> list[Check]:
    checks: list[Check] = []
    for provider, wanted in _models_in_use(settings).items():
        client = clients.get(provider)
        if client is not None:
            checks.append((f"{provider} models", lambda c=client, w=wanted: _check_models(c, w)))
    if providers.search:
        checks.append((f"search ({providers.search.label})", lambda: _check_search(providers)))
    if providers.llm:
        checks.append((f"structured output ({providers.llm.label})", lambda: _check_llm(providers)))
    if providers.speech:
        checks.append((f"tts ({providers.speech.label})", lambda: _check_tts(providers, out)))
    if args.image and providers.images:
        prompt = "A Georgia main street at golden hour, no people, no text"
        checks.append(
            (
                f"image ({providers.images.label})",
                lambda: _write(out / "image.jpg", providers.images.generate_image(prompt)),
            )
        )
    if args.video and providers.video:
        checks.append((f"video ({providers.video.label})", lambda: _check_video(providers, out)))
    return checks


def _models_in_use(settings: Settings) -> dict[str, list[str]]:
    choice = settings.providers
    wanted: dict[str, list[str]] = {}
    if "gemini" in {choice.llm, choice.image, choice.tts}:
        g = settings.gemini
        wanted["gemini"] = [g.text_model, g.image_model, g.tts_model]
    if "xai" in {choice.search, choice.llm, choice.image, choice.tts, choice.video}:
        x = settings.xai
        wanted["xai"] = [x.text_model, x.image_model, x.video_model]
    return wanted


def _check_models(client, wanted: list[str]) -> str:
    models = client.list_models()
    missing = [m for m in wanted if m not in models]
    note = f" (not listed: {', '.join(missing)}; check .env model names)" if missing else ""
    return f"{len(models)} models available{note}"


def _check_search(providers: Providers) -> str:
    hits = providers.search.search(
        "Atlanta Georgia small business grant program",
        include_domains=["atlantaga.gov"],
        max_results=3,
    )
    return f"{len(hits)} results, first: {hits[0].url if hits else 'none'}"


def _check_llm(providers: Providers) -> str:
    answer = providers.llm.parse(
        instructions="Answer briefly.",
        prompt="In one sentence, what does a city facade improvement grant pay for?",
        schema=SmokeAnswer,
    ).value
    return f"{answer.summary[:120]!r} keywords={answer.keywords[:3]}"


def _check_tts(providers: Providers, out: Path) -> str:
    lines = []
    for language, text in (("en", "Hello from County Crier."), ("es", "Hola desde County Crier.")):
        speech = providers.speech.tts(text, language=language)
        path = out / f"hello_{language}.{speech.extension}"
        path.write_bytes(speech.audio)
        lines.append(f"{language} {speech.duration:.2f}s -> {path}")
    return "; ".join(lines)


def _check_video(providers: Providers, out: Path) -> str:
    still = out / "image.jpg"
    image = still.read_bytes() if still.exists() else _placeholder_still()
    job_id = providers.video.start_video(
        "Slow pan across a sunny Georgia main street, no people, no text", image=image, duration=4
    )
    return _write(out / "video.mp4", providers.video.wait_for_video(job_id))


def _placeholder_still() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (720, 1280), (230, 160, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return f"{len(data) // 1024} KB -> {path}"


if __name__ == "__main__":
    sys.exit(main())
