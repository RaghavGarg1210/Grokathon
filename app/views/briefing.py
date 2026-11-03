"""Briefing: the original announcement next to the AI analysis and the verification result."""

import html

import streamlit as st
import streamlit.components.v1 as components

from app.ui import (
    VERIFICATION_LABELS,
    briefing_badges,
    open_studio,
    replay_progress,
    run_with_progress,
    selected_briefing,
    setup_page,
)
from crier.models import Briefing
from crier.pipeline import Pipeline


def demo_stages(pipeline: Pipeline) -> list[str]:
    label = pipeline.providers.label
    return [
        f"Writing English + Spanish script with {label('script')}",
        f"Recording EN voiceover with {label('voice')}",
        f"Recording ES voiceover with {label('voice')}",
        f"Generating scene images with {label('images')}",
        "Assembling EN video",
        "Assembling ES video",
    ]


def show_source(briefing: Briefing) -> None:
    if briefing.is_x_post:
        url = html.escape(briefing.post_url.replace("https://x.com", "https://twitter.com"))
        components.html(
            f'<blockquote class="twitter-tweet" data-dnt="true"><a href="{url}"></a></blockquote>'
            '<script async src="https://platform.twitter.com/widgets.js"></script>',
            height=560,
            scrolling=True,
        )
        st.markdown(f"[Open on X]({briefing.post_url})")
    else:
        with st.container(border=True):
            st.markdown(f"**Official page on {briefing.author_handle}**")
            st.markdown(f"[{briefing.post_url}]({briefing.post_url})")
    with st.expander("Announcement text as read by the model", expanded=not briefing.is_x_post):
        st.write(briefing.post_text)


def analysis(briefing: Briefing) -> None:
    st.subheader(briefing.headline)
    st.markdown(briefing_badges(briefing), unsafe_allow_html=True)
    st.markdown(f"**What changed.** {briefing.what_changed}")
    st.markdown(f"**Who it affects.** {', '.join(briefing.who_it_affects) or 'Local businesses'}")
    st.markdown(f"**What to do.** {briefing.what_to_do}")
    facts = []
    if briefing.deadline:
        facts.append(f"Deadline: **{briefing.deadline.isoformat()}**")
    if briefing.amount:
        facts.append(f"Amount: **{briefing.amount}**")
    facts.append(f"Analysis confidence: **{briefing.confidence}**")
    st.markdown(" | ".join(facts))


def verification(pipeline: Pipeline, briefing: Briefing) -> None:
    label, _ = VERIFICATION_LABELS[briefing.verification]
    with st.container(border=True):
        st.markdown(f"**Verification:** {label}")
        if briefing.official_url:
            st.markdown(f"Official source: [{briefing.official_url}]({briefing.official_url})")
        if briefing.verification_notes:
            st.caption(briefing.verification_notes)
        if st.button("Re-check official sites", disabled=not pipeline.can("verify")):
            updated = run_with_progress(
                "Checking official sites", lambda _: pipeline.reverify(briefing.id)
            )
            if updated:
                st.rerun()


def make_video(pipeline: Pipeline, briefing: Briefing) -> None:
    existing = pipeline.store.latest_draft_for(briefing.id)
    if existing and existing.status in {"ready", "approved"}:
        if st.button("Make video", type="primary", width="stretch"):
            if pipeline.settings.demo_mode:
                replay_progress("Producing explainer video", demo_stages(pipeline))
            open_studio(briefing.id)
        return
    if existing:
        st.caption(f"A draft exists (status: {existing.status}).")
        if st.button("Open in Video Studio", type="primary", width="stretch"):
            open_studio(briefing.id)
        return
    if briefing.verification == "contradicted":
        st.warning("An official site contradicts this announcement, so no video can be made.")
        return
    if st.button(
        "Make video", type="primary", width="stretch", disabled=not pipeline.can("script")
    ):
        draft = run_with_progress(
            "Writing the script", lambda progress: pipeline.create_draft(briefing.id, progress)
        )
        if draft:
            open_studio(briefing.id)


pipeline = setup_page()
st.title("Briefing")
current = selected_briefing(pipeline)
if current:
    st.caption(
        f"{current.city}, {current.county} County | {current.source_label} | "
        f"published {current.posted_on.isoformat()}"
    )
    post_col, analysis_col = st.columns([2, 3])
    with post_col:
        show_source(current)
    with analysis_col:
        analysis(current)
        verification(pipeline, current)
        make_video(pipeline, current)
