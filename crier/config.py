"""Loads and validates `config/sources.yaml` (which mayors and sites we monitor)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from crier.settings import ConfigError

MAX_X_HANDLES = 20
MAX_WEB_DOMAINS = 5


class CitySource(BaseModel):
    city: str
    county: str
    mayor: str = ""
    lat: float
    lon: float
    rural: bool = False
    handles: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)

    @field_validator("handles")
    @classmethod
    def _clean_handles(cls, handles: list[str]) -> list[str]:
        cleaned = [h.strip().lstrip("@") for h in handles if h and h.strip()]
        if len(cleaned) > MAX_X_HANDLES:
            raise ValueError(f"at most {MAX_X_HANDLES} handles per city (x_search limit)")
        return cleaned

    @field_validator("domains")
    @classmethod
    def _clean_domains(cls, domains: list[str]) -> list[str]:
        return [d.strip().lower().removeprefix("https://").removeprefix("www.") for d in domains]

    @property
    def label(self) -> str:
        return f"{self.city} ({self.county} County)"


class SourcesConfig(BaseModel):
    state_domains: list[str] = Field(default_factory=list)
    cities: list[CitySource]

    def verification_domains(self, city: CitySource) -> list[str]:
        """City domains first, then state domains, capped at the web_search limit."""
        ordered = list(dict.fromkeys(city.domains + self.state_domains))
        return ordered[:MAX_WEB_DOMAINS]

    def get_city(self, name: str) -> CitySource:
        for city in self.cities:
            if city.city.lower() == name.lower():
                return city
        raise ConfigError(f"Unknown city {name!r} in sources config")


def load_sources(path: Path) -> SourcesConfig:
    if not path.exists():
        raise ConfigError(f"Sources file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
        return SourcesConfig.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"Invalid sources file {path}: {exc}") from exc


SOURCES_HEADER = (
    "# Georgia cities County Crier monitors.\n"
    "# handles: official mayor/city X accounts without '@' (max 20); only posts from these count.\n"
    "# domains: official city sites; their news pages are scanned and used for verification.\n"
    "# Generated/edited by scripts.discover_handles.\n"
)


def save_sources(config: SourcesConfig, path: Path) -> None:
    body = yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True)
    path.write_text(SOURCES_HEADER + body)
