"""Pre-runs the full pipeline so the demo has real, cached results.

Usage: python -m scripts.seed [--cities Atlanta Savannah] [--videos 3] [--hero 1] [--skip-scan]
"""

from __future__ import annotations

import argparse
import sys

from crier.bootstrap import build_pipeline, configure_logging
from crier.pipeline import Pipeline, PolicyError
from crier.ports import ProviderError
from crier.render.ffmpeg import RenderError
from crier.settings import ConfigError


def pick_briefings(pipeline: Pipeline, count: int) -> list[str]:
    candidates = [
        b
        for b in pipeline.store.list_briefings()
        if b.is_publishable(pipeline.settings.min_relevance)
        and b.verification == "verified"
        and pipeline.store.latest_draft_for(b.id) is None
    ]
    candidates.sort(key=lambda b: b.relevance_score, reverse=True)
    return [b.id for b in candidates[:count]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="*", help="cities to scan (default: all configured)")
    parser.add_argument("--videos", type=int, default=3, help="how many videos to render")
    parser.add_argument("--hero", type=int, default=1, help="how many use AI video clips")
    parser.add_argument("--skip-scan", action="store_true")
    args = parser.parse_args()
    configure_logging()
    try:
        pipeline = build_pipeline()
        if not args.skip_scan:
            summary = pipeline.scan(args.cities or None, on_progress=print)
            print(
                f"Scan: {summary.cities} cities, {summary.found} posts, {summary.new} new, "
                f"{summary.rejected} rejected"
            )
            for error in summary.errors:
                print(f"  error: {error}")
        if args.hero and not pipeline.can("video"):
            print("No video provider key set: rendering stills only.")
        for index, briefing_id in enumerate(pick_briefings(pipeline, args.videos)):
            mode = "hero" if index < args.hero and pipeline.can("video") else "stills"
            draft = pipeline.create_draft(briefing_id, on_progress=print)
            draft = pipeline.render(draft.id, mode, on_progress=print)
            print(f"Rendered {mode}: {draft.video_paths}")
    except (ConfigError, PolicyError, ProviderError, RenderError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
