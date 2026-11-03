"""Shared Streamlit helpers: pipeline singleton, styling, badges, progress."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import streamlit as st

from crier.bootstrap import build_pipeline, configure_logging
from crier.models import Briefing
from crier.pipeline import Pipeline, PolicyError
from crier.ports import CAPABILITY_ACTIONS, ProviderError
from crier.render.ffmpeg import RenderError
from crier.settings import ConfigError

T = TypeVar("T")

PAGES = {
    "radar": "views/radar.py",
    "briefing": "views/briefing.py",
    "studio": "views/studio.py",
    "library": "views/library.py",
}
CATEGORY_LABELS = {
    "program": ("Program", "#1f8a4c"),
    "policy_decision": ("Policy decision", "#2563eb"),
    "event": ("Business event", "#7c3aed"),
    "not_relevant": ("Not relevant", "#6b7280"),
}
VERIFICATION_LABELS = {
    "verified": ("Verified on official site", "#15803d"),
    "announced_only": ("Announced only, not confirmed", "#b45309"),
    "contradicted": ("Contradicted by official site", "#b91c1c"),
    "unverified": ("Not checked yet", "#6b7280"),
}
USER_ERRORS = (PolicyError, ProviderError, RenderError, ConfigError)
PROVIDER_SUMMARY = (("scan", "Scan"), ("script", "Scripts"), ("voice", "Voice"), ("video", "Video"))

CSS = """
<style>
.crier-badge {display:inline-block;padding:2px 10px;border-radius:999px;color:#fff;
  font-size:0.78rem;font-weight:600;margin-right:6px;}
.crier-muted {color:#6b7280;font-size:0.85rem;}
</style>
"""


@st.cache_resource
def get_pipeline() -> Pipeline:
    configure_logging()
    return build_pipeline()


def setup_page() -> Pipeline:
    st.markdown(CSS, unsafe_allow_html=True)
    pipeline = get_pipeline()
    if pipeline.settings.demo_mode:
        st.sidebar.caption("Demo mode: cached renders replay their recorded pipeline stages.")
    show_provider_status(pipeline)
    return pipeline


def show_provider_status(pipeline: Pipeline) -> None:
    providers = pipeline.providers
    st.sidebar.caption(
        " | ".join(f"{name}: {providers.label(cap)}" for cap, name in PROVIDER_SUMMARY)
    )
    actions_by_key: dict[str, list[str]] = {}
    for capability, keys in providers.missing.items():
        for key in keys:
            actions_by_key.setdefault(key, []).append(CAPABILITY_ACTIONS[capability])
    for key, actions in actions_by_key.items():
        st.sidebar.warning(f"Add {key} to .env to {', '.join(actions)}.")


def badge(text: str, color: str) -> str:
    return f'<span class="crier-badge" style="background:{color}">{text}</span>'


def briefing_badges(briefing: Briefing) -> str:
    category = badge(*CATEGORY_LABELS[briefing.category])
    verification = badge(*VERIFICATION_LABELS[briefing.verification])
    return category + verification + badge(f"Relevance {briefing.relevance_score}", "#334155")


def run_with_progress(label: str, action: Callable[[Callable[[str], None]], T]) -> T | None:
    """Runs `action(on_progress)` inside a live status box; shows user-safe errors."""
    with st.status(label, expanded=True) as status:
        try:
            result = action(status.write)
        except USER_ERRORS as exc:
            status.update(label=f"{label}: failed", state="error")
            st.error(str(exc))
            return None
        status.update(label=f"{label}: done", state="complete", expanded=False)
        return result


def replay_progress(label: str, stages: list[str], delay_s: float = 0.7) -> None:
    with st.status(label, expanded=True) as status:
        for stage in stages:
            status.write(stage)
            time.sleep(delay_s)
        status.update(
            label=f"{label}: done (replayed from cache)", state="complete", expanded=False
        )


def open_briefing(briefing_id: str) -> None:
    st.session_state["briefing_id"] = briefing_id
    st.switch_page(PAGES["briefing"])


def open_studio(briefing_id: str) -> None:
    st.session_state["briefing_id"] = briefing_id
    st.switch_page(PAGES["studio"])


def selected_briefing(pipeline: Pipeline) -> Briefing | None:
    briefing_id = st.session_state.get("briefing_id")
    briefing = pipeline.store.get_briefing(briefing_id) if briefing_id else None
    if briefing:
        return briefing
    options = pipeline.store.list_briefings()
    if not options:
        st.info("No briefings yet. Run a scan from the Mayor Radar.")
        return None
    choice = st.selectbox(
        "Choose a briefing", options, format_func=lambda b: f"{b.city}: {b.headline}"
    )
    st.session_state["briefing_id"] = choice.id
    return choice
