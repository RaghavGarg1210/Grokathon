"""Wires settings, sources, store and the configured providers into a Pipeline."""

from __future__ import annotations

import logging

from crier.config import load_sources
from crier.pipeline import Pipeline
from crier.providers.registry import build_providers
from crier.settings import Settings, load_settings
from crier.store import Store


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def build_pipeline(settings: Settings | None = None) -> Pipeline:
    settings = settings or load_settings()
    return Pipeline(
        settings=settings,
        store=Store(settings.db_path),
        sources=load_sources(settings.sources_path),
        providers=build_providers(settings),
    )
