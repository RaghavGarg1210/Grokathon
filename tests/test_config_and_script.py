import pytest

from crier.config import CitySource, SourcesConfig, load_sources
from crier.script import (
    SCENE_RULES,
    ScriptError,
    enforce_scene_rules,
    validate_script,
    write_script,
)
from crier.settings import PROJECT_ROOT, ConfigError
from tests.fakes import CITY, FakeLLM, briefing, video_script


def test_shipped_sources_file_is_valid():
    config = load_sources(PROJECT_ROOT / "config" / "sources.yaml")
    assert len(config.cities) >= 8
    assert any(city.rural for city in config.cities)


def test_handles_are_cleaned_and_capped():
    city = CitySource.model_validate({**CITY.model_dump(), "handles": ["@CityA", " CityB ", ""]})
    assert city.handles == ["CityA", "CityB"]
    with pytest.raises(ValueError):
        CitySource.model_validate({**CITY.model_dump(), "handles": [f"h{i}" for i in range(21)]})


def test_verification_domains_capped_at_five():
    config = SourcesConfig(
        state_domains=["a.gov", "b.gov", "c.gov", "d.gov"],
        cities=[CITY.model_copy(update={"domains": ["x.gov", "y.gov"]})],
    )
    assert config.verification_domains(config.cities[0]) == [
        "x.gov",
        "y.gov",
        "a.gov",
        "b.gov",
        "c.gov",
    ]


def test_missing_sources_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_sources(tmp_path / "missing.yaml")


def test_script_validation_rejects_wrong_beat_count():
    with pytest.raises(ScriptError):
        validate_script(video_script(beats=2))
    with pytest.raises(ScriptError):
        validate_script(video_script(beats=6))


def test_scene_rules_appended_once():
    script = enforce_scene_rules(enforce_scene_rules(video_script()))
    assert all(beat.scene_prompt.count(SCENE_RULES) == 1 for beat in script.beats)


def test_write_script_prompt_contains_official_link():
    llm = FakeLLM([video_script()])
    script = write_script(llm, briefing())
    assert "https://exampleton.gov/facade-grant" in llm.calls[0]["prompt"]
    assert "@ExampletonGA on X" in llm.calls[0]["prompt"]
    assert SCENE_RULES in script.beats[0].scene_prompt
