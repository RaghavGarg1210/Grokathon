"""Approved Library: videos cleared for posting, ready to download."""

from pathlib import Path

import streamlit as st

from app.ui import open_briefing, setup_page

COLUMNS = 3

pipeline = setup_page()
st.title("Approved Library")
st.caption("Approved explainers, ready to post on your own channels.")

approved = pipeline.store.list_drafts(status="approved")
if not approved:
    st.info("No approved videos yet. Approve one in the Video Studio.")

for start in range(0, len(approved), COLUMNS):
    for column, draft in zip(st.columns(COLUMNS), approved[start : start + COLUMNS], strict=False):
        briefing = pipeline.store.get_briefing(draft.briefing_id)
        with column, st.container(border=True):
            st.markdown(f"**{draft.script.title_en}**")
            if briefing:
                st.caption(
                    f"{briefing.city} | {briefing.source_label} | {briefing.posted_on.isoformat()}"
                )
            video = Path(draft.video_paths.get("en", ""))
            if video.exists():
                st.video(str(video))
            for language in ("en", "es"):
                path = Path(draft.video_paths.get(language, ""))
                if path.exists():
                    st.download_button(
                        f"Download {language.upper()} MP4",
                        path.read_bytes(),
                        path.name,
                        "video/mp4",
                        key=f"lib-{draft.id}-{language}",
                    )
            if briefing and st.button("Open briefing", key=f"lib-open-{draft.id}"):
                open_briefing(briefing.id)
