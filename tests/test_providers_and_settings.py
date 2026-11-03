import pytest

from crier.ports import SpeechResult
from crier.providers.gemini import GeminiClient
from crier.providers.magic_hour import MagicHourClient
from crier.providers.registry import build_providers
from crier.providers.tavily import TavilyClient
from crier.scanners import SearchScanner, XSearchScanner
from crier.settings import (
    ConfigError,
    GeminiSettings,
    MagicHourSettings,
    ProviderChoice,
    TavilySettings,
    XaiSettings,
    load_settings,
    validate,
)
from tests.fakes import make_settings


def test_default_providers_are_tavily_gemini_magic_hour(tmp_path):
    providers = build_providers(make_settings(tmp_path))
    assert isinstance(providers.scanner, SearchScanner)
    assert isinstance(providers.search, TavilyClient)
    assert isinstance(providers.llm, GeminiClient)
    assert providers.speech is providers.llm and providers.images is providers.llm
    assert isinstance(providers.video, MagicHourClient)
    assert providers.missing == {}
    assert providers.label("scan") == "Tavily + Gemini"


def test_missing_keys_are_reported_per_capability(tmp_path):
    settings = make_settings(
        tmp_path,
        tavily=TavilySettings(),
        gemini=GeminiSettings(),
        magic_hour=MagicHourSettings(),
        xai=XaiSettings(),
    )
    providers = build_providers(settings)
    assert not providers.can("scan") and not providers.can("voice")
    assert providers.missing["scan"] == ["TAVILY_API_KEY", "GEMINI_API_KEY"]
    assert providers.missing["video"] == ["MAGIC_HOUR_API_KEY"]
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        providers.require("script")


def test_grok_can_be_selected_per_step(tmp_path):
    choice = ProviderChoice(search="xai", tts="xai")
    providers = build_providers(make_settings(tmp_path, providers=choice))
    assert isinstance(providers.scanner, XSearchScanner)
    assert providers.speech.label == "Grok" and providers.llm.label == "Gemini"


def test_unknown_provider_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="CRIER_VIDEO_PROVIDER"):
        validate(make_settings(tmp_path, providers=ProviderChoice(video="sora")))


def test_settings_load_provider_choice_from_env(monkeypatch):
    monkeypatch.setenv("CRIER_TTS_PROVIDER", "XAI")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-custom")
    monkeypatch.setenv("TAVILY_MAX_RESULTS", "7")
    settings = load_settings()
    assert settings.providers.tts == "xai" and settings.providers.search == "tavily"
    assert settings.gemini.text_model == "gemini-custom"
    assert settings.tavily.max_results == 7


def test_estimated_timing_spans_audio_and_pauses_on_punctuation():
    speech = SpeechResult.with_estimated_timing(b"", "Hi, you", 2.0, "wav")
    durations = [end - start for start, end in speech.times]
    assert speech.times[-1][1] == pytest.approx(2.0)
    assert durations[2] == pytest.approx(4 * durations[0])
