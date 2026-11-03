"""Video Studio: edit the bilingual script, render, preview, approve and export."""

from pathlib import Path

import streamlit as st

from app.ui import USER_ERRORS, briefing_badges, run_with_progress, selected_briefing, setup_page
from crier.models import Briefing, Draft, ScriptBeat, VideoScript
from crier.pipeline import Pipeline


def render_modes(pipeline: Pipeline) -> dict[str, str]:
    label = pipeline.providers.label
    return {
        "stills": f"Fast: {label('images')} stills with motion (~1 min)",
        "hero": f"Hero: {label('video')} video clips (several minutes, uses video budget)",
    }


def script_editor(pipeline: Pipeline, draft: Draft) -> None:
    script = draft.script
    with st.form(f"script-{draft.id}"):
        st.subheader("Script")
        title_en = st.text_input("Title (EN)", script.title_en)
        title_es = st.text_input("Title (ES)", script.title_es)
        beats = []
        for index, beat in enumerate(script.beats, start=1):
            key = f"{draft.id}-{draft.updated_at.timestamp()}-{index}"
            with st.expander(f"Beat {index}: {beat.on_screen_text_en}", expanded=index == 1):
                en_col, es_col = st.columns(2)
                beats.append(
                    ScriptBeat(
                        narration_en=en_col.text_area(
                            "Narration EN", beat.narration_en, key=f"n-en-{key}"
                        ),
                        narration_es=es_col.text_area(
                            "Narration ES", beat.narration_es, key=f"n-es-{key}"
                        ),
                        on_screen_text_en=en_col.text_input(
                            "On-screen EN", beat.on_screen_text_en, key=f"o-en-{key}"
                        ),
                        on_screen_text_es=es_col.text_input(
                            "On-screen ES", beat.on_screen_text_es, key=f"o-es-{key}"
                        ),
                        scene_prompt=st.text_area(
                            "Scene prompt", beat.scene_prompt, key=f"s-{key}"
                        ),
                    )
                )
        caption_en = st.text_area("Post caption (EN)", script.caption_en)
        caption_es = st.text_area("Post caption (ES)", script.caption_es)
        if st.form_submit_button("Save script"):
            updated = VideoScript(
                title_en=title_en,
                title_es=title_es,
                beats=beats,
                caption_en=caption_en,
                caption_es=caption_es,
            )
            try:
                pipeline.update_script(draft.id, updated)
            except USER_ERRORS as exc:
                st.error(str(exc))
            else:
                st.toast("Script saved. Render again to update the video.")
                st.rerun()


def render_controls(pipeline: Pipeline, briefing: Briefing, draft: Draft) -> None:
    st.subheader("Render")
    modes = render_modes(pipeline)
    mode = st.radio("Visual style", list(modes), format_func=modes.get, horizontal=False)
    override = False
    if briefing.verification != "verified":
        override = st.checkbox(
            "Render without official verification (the video will say details are pending)"
        )
    can_render = pipeline.can("voice") and (mode == "stills" or pipeline.can("video"))
    if st.button("Render video", type="primary", disabled=not can_render):
        rendered = run_with_progress(
            "Producing explainer video",
            lambda progress: pipeline.render(
                draft.id, mode, progress, override_unverified=override
            ),
        )
        if rendered:
            st.rerun()
    if draft.status == "failed" and draft.error:
        st.error(f"Last render failed: {draft.error}")


def preview(draft: Draft) -> None:
    st.subheader("Preview")
    if not draft.video_paths:
        st.info("No video yet. Render to preview.")
        return
    for tab, language in zip(st.tabs(["English", "Español"]), ["en", "es"], strict=True):
        with tab:
            video = Path(draft.video_paths.get(language, ""))
            if not video.exists():
                st.warning("Video file missing. Render again.")
                continue
            st.video(str(video))
            caption = draft.script.caption(language)
            st.text_area("Post caption", caption, disabled=True, key=f"cap-view-{language}")
            cols = st.columns(3)
            cols[0].download_button(
                "MP4", video.read_bytes(), video.name, "video/mp4", key=f"mp4-{language}"
            )
            srt = Path(draft.srt_paths.get(language, ""))
            if srt.exists():
                cols[1].download_button(
                    "Captions (SRT)", srt.read_text(), srt.name, key=f"srt-{language}"
                )
            cols[2].download_button(
                "Post caption", caption, f"caption_{language}.txt", key=f"cap-{language}"
            )


def review(pipeline: Pipeline, draft: Draft) -> None:
    st.subheader("Review")
    st.caption(
        f"Status: **{draft.status}**. Nothing is posted automatically: "
        "approved videos are exported for your own channels."
    )
    note = st.text_input("Reviewer note", draft.reviewer_note)
    approve_col, reject_col = st.columns(2)
    if approve_col.button(
        "Approve",
        type="primary",
        disabled=draft.status not in {"ready", "approved"},
        width="stretch",
    ):
        _act(lambda: pipeline.approve(draft.id, note), "Approved. Find it in the Approved Library.")
    if reject_col.button("Reject", width="stretch"):
        _act(lambda: pipeline.reject(draft.id, note), "Rejected.")


def _act(action, message: str) -> None:
    try:
        action()
    except USER_ERRORS as exc:
        st.error(str(exc))
    else:
        st.toast(message)
        st.rerun()


pipeline = setup_page()
st.title("Video Studio")
briefing = selected_briefing(pipeline)
if briefing:
    st.markdown(f"**{briefing.headline}**")
    st.markdown(briefing_badges(briefing), unsafe_allow_html=True)
    draft = pipeline.store.latest_draft_for(briefing.id)
    if draft is None:
        st.info("No script yet. Open the briefing and click Make video.")
    else:
        edit_col, video_col = st.columns([3, 2])
        with edit_col:
            script_editor(pipeline, draft)
        with video_col:
            preview(draft)
            render_controls(pipeline, briefing, draft)
            review(pipeline, draft)
