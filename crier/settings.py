"""Runtime configuration loaded from environment variables (and `.env`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROVIDER_OPTIONS = {
    "search": ("tavily", "xai"),
    "llm": ("gemini", "xai"),
    "image": ("gemini", "xai"),
    "tts": ("gemini", "xai"),
    "video": ("magic_hour", "xai"),
}
PROVIDER_KEY_ENV = {
    "tavily": "TAVILY_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "magic_hour": "MAGIC_HOUR_API_KEY",
    "xai": "XAI_API_KEY",
}


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _str_env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> Path:
    path = Path(_str_env(name, default))
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class ProviderChoice:
    """Which provider runs each pipeline step."""

    search: str = "tavily"
    llm: str = "gemini"
    image: str = "gemini"
    tts: str = "gemini"
    video: str = "magic_hour"


@dataclass(frozen=True)
class TavilySettings:
    api_key: str = ""
    search_depth: str = "advanced"
    max_results: int = 10


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = ""
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    text_model: str = "gemini-3-flash-preview"
    image_model: str = "gemini-3.1-flash-image"
    tts_model: str = "gemini-3.8-flash-tts"
    tts_voice_en: str = "Kore"
    tts_voice_es: str = "Kore"
    tts_language_en: str = "en-US"
    tts_language_es: str = "es-US"


@dataclass(frozen=True)
class MagicHourSettings:
    api_key: str = ""
    base_url: str = "https://api.magichour.ai"
    video_model: str = "ltx-2.5"


@dataclass(frozen=True)
class XaiSettings:
    api_key: str = ""
    base_url: str = "https://api.x.ai/v1"
    text_model: str = "grok-4.7"
    image_model: str = "grok-imagine-image-2.0"
    video_model: str = "grok-imagine-video-1.5"
    tts_voice_en: str = "eve"
    tts_voice_es: str = "eve"
    tts_language_es: str = "es-MX"
    search_max_turns: int = 2


@dataclass(frozen=True)
class Settings:
    providers: ProviderChoice
    tavily: TavilySettings
    gemini: GeminiSettings
    magic_hour: MagicHourSettings
    xai: XaiSettings
    demo_mode: bool
    data_dir: Path
    sources_path: Path
    scan_days: int
    min_relevance: int
    render_resolution: str
    max_hero_renders_per_day: int
    video_poll_timeout_s: int
    font_path: Path | None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "crier.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def api_key(self, provider: str) -> str:
        return {
            "tavily": self.tavily.api_key,
            "gemini": self.gemini.api_key,
            "magic_hour": self.magic_hour.api_key,
            "xai": self.xai.api_key,
        }[provider]


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    font = _str_env("CRIER_FONT_PATH", "")
    settings = Settings(
        providers=_load_providers(),
        tavily=TavilySettings(
            api_key=_str_env("TAVILY_API_KEY", ""),
            search_depth=_str_env("TAVILY_SEARCH_DEPTH", TavilySettings.search_depth),
            max_results=_int_env("TAVILY_MAX_RESULTS", TavilySettings.max_results),
        ),
        gemini=_load_gemini(),
        magic_hour=MagicHourSettings(
            api_key=_str_env("MAGIC_HOUR_API_KEY", ""),
            base_url=_str_env("MAGIC_HOUR_BASE_URL", MagicHourSettings.base_url).rstrip("/"),
            video_model=_str_env("MAGIC_HOUR_VIDEO_MODEL", MagicHourSettings.video_model),
        ),
        xai=_load_xai(),
        demo_mode=_bool_env("CRIER_DEMO_MODE"),
        data_dir=_path_env("CRIER_DATA_DIR", "data"),
        sources_path=_path_env("CRIER_SOURCES_PATH", "config/sources.yaml"),
        scan_days=_int_env("CRIER_SCAN_DAYS", 30),
        min_relevance=_int_env("CRIER_MIN_RELEVANCE", 50),
        render_resolution=_str_env("CRIER_RENDER_RESOLUTION", "720p"),
        max_hero_renders_per_day=_int_env("CRIER_MAX_HERO_RENDERS_PER_DAY", 6),
        video_poll_timeout_s=_int_env("CRIER_VIDEO_POLL_TIMEOUT_S", 600),
        font_path=Path(font) if font else None,
    )
    validate(settings)
    return settings


def _load_providers() -> ProviderChoice:
    defaults = ProviderChoice()
    return ProviderChoice(
        **{
            step: _str_env(f"CRIER_{step.upper()}_PROVIDER", getattr(defaults, step)).lower()
            for step in PROVIDER_OPTIONS
        }
    )


def _load_gemini() -> GeminiSettings:
    d = GeminiSettings()
    return GeminiSettings(
        api_key=_str_env("GEMINI_API_KEY", ""),
        base_url=_str_env("GEMINI_BASE_URL", d.base_url).rstrip("/"),
        text_model=_str_env("GEMINI_TEXT_MODEL", d.text_model),
        image_model=_str_env("GEMINI_IMAGE_MODEL", d.image_model),
        tts_model=_str_env("GEMINI_TTS_MODEL", d.tts_model),
        tts_voice_en=_str_env("GEMINI_TTS_VOICE_EN", d.tts_voice_en),
        tts_voice_es=_str_env("GEMINI_TTS_VOICE_ES", d.tts_voice_es),
        tts_language_en=_str_env("GEMINI_TTS_LANGUAGE_EN", d.tts_language_en),
        tts_language_es=_str_env("GEMINI_TTS_LANGUAGE_ES", d.tts_language_es),
    )


def _load_xai() -> XaiSettings:
    d = XaiSettings()
    return XaiSettings(
        api_key=_str_env("XAI_API_KEY", ""),
        base_url=_str_env("XAI_BASE_URL", d.base_url).rstrip("/"),
        text_model=_str_env("XAI_TEXT_MODEL", d.text_model),
        image_model=_str_env("XAI_IMAGE_MODEL", d.image_model),
        video_model=_str_env("XAI_VIDEO_MODEL", d.video_model),
        tts_voice_en=_str_env("XAI_TTS_VOICE_EN", d.tts_voice_en),
        tts_voice_es=_str_env("XAI_TTS_VOICE_ES", d.tts_voice_es),
        tts_language_es=_str_env("XAI_TTS_LANGUAGE_ES", d.tts_language_es),
        search_max_turns=_int_env("CRIER_X_SEARCH_MAX_TURNS", d.search_max_turns),
    )


def validate(settings: Settings) -> None:
    for step, options in PROVIDER_OPTIONS.items():
        chosen = getattr(settings.providers, step)
        if chosen not in options:
            raise ConfigError(
                f"CRIER_{step.upper()}_PROVIDER must be one of {', '.join(options)}, got {chosen!r}"
            )
    if settings.tavily.search_depth not in {"basic", "advanced", "fast", "ultra-fast"}:
        raise ConfigError("TAVILY_SEARCH_DEPTH must be basic, advanced, fast or ultra-fast")
    if not 1 <= settings.tavily.max_results <= 20:
        raise ConfigError("TAVILY_MAX_RESULTS must be between 1 and 20")
    if not 0 <= settings.min_relevance <= 100:
        raise ConfigError("CRIER_MIN_RELEVANCE must be between 0 and 100")
    if settings.scan_days < 1:
        raise ConfigError("CRIER_SCAN_DAYS must be at least 1")
    if settings.render_resolution not in {"480p", "720p", "1080p"}:
        raise ConfigError("CRIER_RENDER_RESOLUTION must be 480p, 720p or 1080p")
