"""Mayor Radar: what Georgia mayors and city halls announced that small businesses should know."""

import pandas as pd
import plotly.express as px
import streamlit as st

from app.ui import CATEGORY_LABELS, briefing_badges, open_briefing, run_with_progress, setup_page
from crier.models import Briefing
from crier.pipeline import Pipeline


def sidebar_filters(pipeline: Pipeline) -> dict:
    st.sidebar.header("Filters")
    cities = [c.city for c in pipeline.sources.cities]
    return {
        "cities": st.sidebar.multiselect("Cities", cities),
        "categories": st.sidebar.multiselect(
            "Type",
            ["program", "policy_decision", "event"],
            format_func=lambda c: CATEGORY_LABELS[c][0],
        ),
        "verified_only": st.sidebar.toggle("Verified only"),
        "min_relevance": st.sidebar.slider(
            "Min relevance", 0, 100, pipeline.settings.min_relevance
        ),
    }


def sidebar_scan(pipeline: Pipeline) -> None:
    st.sidebar.header("Scan now")
    if not pipeline.can("scan"):
        st.sidebar.info("Scanning is off until the search keys above are in .env.")
        return
    ready = [c.city for c in pipeline.scannable_cities]
    if not ready:
        st.sidebar.info(
            "No city has handles or domains yet. Run `python -m scripts.discover_handles`."
        )
        return
    city = st.sidebar.selectbox("City", ready)
    if st.sidebar.button("Scan now", type="primary", width="stretch"):
        summary = run_with_progress(
            f"Scanning {city} with {pipeline.providers.label('scan')}",
            lambda progress: pipeline.scan([city], on_progress=progress),
        )
        if summary:
            st.toast(f"{city}: {summary.found} announcements analyzed, {summary.new} new")
            for error in summary.errors:
                st.sidebar.error(error)


def apply_filters(briefings: list[Briefing], filters: dict) -> list[Briefing]:
    result = []
    for b in briefings:
        if b.is_campaign_or_personal or b.category == "not_relevant":
            continue
        if b.relevance_score < filters["min_relevance"]:
            continue
        if filters["cities"] and b.city not in filters["cities"]:
            continue
        if filters["categories"] and b.category not in filters["categories"]:
            continue
        if filters["verified_only"] and b.verification != "verified":
            continue
        result.append(b)
    return result


def coverage_map(pipeline: Pipeline, briefings: list[Briefing]) -> None:
    counts = pd.Series([b.city for b in briefings]).value_counts().to_dict()
    frame = pd.DataFrame(
        [
            {
                "city": c.label,
                "lat": c.lat,
                "lon": c.lon,
                "briefings": counts.get(c.city, 0),
                "monitored": "Not configured" if pipeline.scan_blocker(c) else "Monitored",
            }
            for c in pipeline.sources.cities
        ]
    )
    frame["size"] = frame["briefings"].clip(lower=0) + 3
    figure = px.scatter_map(
        frame,
        lat="lat",
        lon="lon",
        size="size",
        color="monitored",
        hover_name="city",
        hover_data={"briefings": True, "size": False, "lat": False, "lon": False},
        zoom=5.6,
        center={"lat": 32.7, "lon": -83.4},
        height=430,
        map_style="carto-positron",
    )
    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend={"title": "", "orientation": "h", "x": 0, "y": 1.06},
    )
    st.plotly_chart(figure, width="stretch")


def feed(briefings: list[Briefing]) -> None:
    if not briefings:
        st.info("No briefings match. Run a scan or loosen the filters.")
        return
    for b in briefings:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(f"**{b.headline}**")
            left.markdown(briefing_badges(b), unsafe_allow_html=True)
            deadline = f" | Deadline {b.deadline.isoformat()}" if b.deadline else ""
            left.markdown(
                f'<span class="crier-muted">{b.city} | {b.source_label} | '
                f"{b.posted_on.isoformat()}{deadline}</span>",
                unsafe_allow_html=True,
            )
            if right.button("Open", key=f"open-{b.id}", width="stretch"):
                open_briefing(b.id)


pipeline = setup_page()
filters = sidebar_filters(pipeline)
sidebar_scan(pipeline)

st.title("Mayor Radar")
st.caption(
    "What Georgia mayors and city halls announced on X and their official sites that small "
    "businesses need to know, checked against official city and state websites."
)

all_briefings = pipeline.store.list_briefings()
shown = apply_filters(all_briefings, filters)
drafts = pipeline.store.list_drafts()
cols = st.columns(4)
cols[0].metric("Cities monitored", len(pipeline.scannable_cities))
cols[1].metric(
    "Business-relevant announcements",
    len(
        apply_filters(
            all_briefings, {**filters, "cities": [], "categories": [], "verified_only": False}
        )
    ),
)
cols[2].metric("Verified", sum(b.verification == "verified" for b in shown))
cols[3].metric("Videos approved", sum(d.status == "approved" for d in drafts))

map_col, feed_col = st.columns([2, 3])
with map_col:
    coverage_map(pipeline, shown)
    runs = pipeline.store.list_scan_runs(limit=5)
    if runs:
        st.caption("Recent scans")
        st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")
with feed_col:
    feed(shown)
