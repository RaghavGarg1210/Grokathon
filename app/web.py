"""County Crier web UI server (standard library only). Run: python -m app.web [--port 8000]

Serves `app/static/index.html` and a small JSON API over `crier.pipeline.Pipeline`.
Long actions (scan, script, render) run as background jobs the page polls.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import ValidationError

from crier.bootstrap import build_pipeline, configure_logging
from crier.models import Briefing, Draft, VideoScript
from crier.pipeline import Pipeline, PolicyError
from crier.ports import CAPABILITY_ACTIONS, ProviderError
from crier.render.ffmpeg import RenderError
from crier.settings import ConfigError

log = logging.getLogger("crier.web")

STATIC_DIR = Path(__file__).resolve().parent / "static"
USER_ERRORS = (PolicyError, ProviderError, RenderError, ConfigError)
PROVIDER_SUMMARY = (("scan", "Scan"), ("script", "Scripts"), ("voice", "Voice"), ("video", "Video"))
DEMO_STAGES = (
    "Writing English + Spanish script",
    "Recording voiceovers",
    "Generating scene images",
    "Assembling 9:16 video with captions",
    "Adding the source card",
)


class Jobs:
    """Runs `fn(on_progress)` on a thread; the page polls `get` for messages and the result."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, fn: Callable[[Callable[[str], None]], Any]) -> str:
        job_id = uuid.uuid4().hex[:10]
        job: dict[str, Any] = {"status": "running", "messages": [], "error": "", "result": None}
        with self._lock:
            self._jobs[job_id] = job

        def progress(message: str) -> None:
            job["messages"].append(message)

        def run() -> None:
            try:
                job["result"] = fn(progress)
                job["status"] = "done"
            except USER_ERRORS as exc:
                job["error"], job["status"] = str(exc), "error"
            except Exception:  # noqa: BLE001 - surfaced as a safe message, logged in full
                log.exception("job %s failed", job_id)
                job["error"], job["status"] = "Unexpected error. See the server log.", "error"

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)


class App:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.jobs = Jobs()
        self.data_dir = pipeline.settings.data_dir.resolve()

    # ----- serializers -----
    def media_url(self, path: str) -> str | None:
        try:
            relative = Path(path).resolve().relative_to(self.data_dir)
        except ValueError:
            return None
        return "/media/" + relative.as_posix()

    def briefing_json(self, b: Briefing) -> dict[str, Any]:
        data = b.model_dump(mode="json")
        data.update(
            source_label=b.source_label,
            is_x_post=b.is_x_post,
            publishable=b.is_publishable(self.pipeline.settings.min_relevance),
            can_make_video=b.can_make_video(),
        )
        return data

    def draft_json(self, d: Draft | None) -> dict[str, Any] | None:
        if d is None:
            return None
        data = d.model_dump(mode="json")
        data["videos"] = {k: self.media_url(v) for k, v in d.video_paths.items()}
        data["srts"] = {k: self.media_url(v) for k, v in d.srt_paths.items()}
        data.pop("video_paths"), data.pop("srt_paths")
        return data

    # ----- reads -----
    def state(self) -> dict[str, Any]:
        p = self.pipeline
        providers = [
            {"name": name, "label": p.providers.label(cap), "ok": p.can(cap)}
            for cap, name in PROVIDER_SUMMARY
        ]
        warnings: dict[str, list[str]] = {}
        for cap, keys in p.providers.missing.items():
            for key in keys:
                warnings.setdefault(key, []).append(CAPABILITY_ACTIONS[cap])
        cities = []
        for city in p.sources.cities:
            blocker = p.scan_blocker(city)
            cities.append(
                {
                    "city": city.city,
                    "county": city.county,
                    "mayor": city.mayor,
                    "rural": city.rural,
                    "scannable": blocker is None,
                    "blocker": blocker,
                }
            )
        return {
            "demo_mode": p.settings.demo_mode,
            "min_relevance": p.settings.min_relevance,
            "scan_days": p.settings.scan_days,
            "providers": providers,
            "missing_keys": [
                {"key": k, "actions": ", ".join(v)} for k, v in warnings.items()
            ],
            "cities": cities,
            "scan_runs": p.store.list_scan_runs(5),
        }

    def briefings(self) -> list[dict[str, Any]]:
        out = []
        for b in self.pipeline.store.list_briefings():
            draft = self.pipeline.store.latest_draft_for(b.id)
            item = self.briefing_json(b)
            item["draft_status"] = draft.status if draft else None
            out.append(item)
        return out

    def briefing(self, briefing_id: str) -> dict[str, Any]:
        b = self.pipeline.store.get_briefing(briefing_id)
        if b is None:
            raise PolicyError("Briefing not found")
        item = self.briefing_json(b)
        item["draft"] = self.draft_json(self.pipeline.store.latest_draft_for(b.id))
        return item

    def drafts(self, status: str | None) -> list[dict[str, Any]]:
        out = []
        for d in self.pipeline.store.list_drafts(status):
            b = self.pipeline.store.get_briefing(d.briefing_id)
            if b:
                out.append({"draft": self.draft_json(d), "briefing": self.briefing_json(b)})
        return out

    # ----- actions -----
    def start_scan(self, cities: list[str] | None) -> str:
        return self.jobs.start(
            lambda progress: asdict(self.pipeline.scan(cities or None, on_progress=progress))
        )

    def start_reverify(self, briefing_id: str) -> str:
        return self.jobs.start(
            lambda _p: self.briefing_json(self.pipeline.reverify(briefing_id))
        )

    def start_script(self, briefing_id: str) -> str:
        return self.jobs.start(
            lambda progress: self.draft_json(self.pipeline.create_draft(briefing_id, progress))
        )

    def start_render(self, draft_id: str, mode: str, override: bool) -> str:
        if mode not in ("stills", "hero"):
            raise PolicyError("Unknown render mode")

        def run(progress: Callable[[str], None]) -> dict[str, Any] | None:
            store = self.pipeline.store
            draft = store.get_draft(draft_id)
            cached = draft and draft.status in ("ready", "approved") and draft.video_paths
            if self.pipeline.settings.demo_mode and cached:
                for stage in DEMO_STAGES:
                    progress(stage)
                    time.sleep(0.7)
                progress("Replayed from cache")
                return self.draft_json(draft)
            return self.draft_json(
                self.pipeline.render(draft_id, mode, progress, override_unverified=override)  # type: ignore[arg-type]
            )

        return self.jobs.start(run)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CountyCrier/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug(fmt, *args)

        # ----- plumbing -----
        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise PolicyError("Request body is not valid JSON") from exc
            return data if isinstance(data, dict) else {}

        def _guard(self, fn: Callable[[], Any]) -> None:
            try:
                self._json(fn())
            except USER_ERRORS as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except ValidationError as exc:
                self._json({"error": f"Invalid script: {exc.errors()[0]['msg']}"}, 400)
            except Exception:  # noqa: BLE001
                log.exception("request failed: %s", self.path)
                self._json({"error": "Unexpected error. See the server log."}, 500)

        def _file(self, path: Path, content_type: str | None = None) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else size - 1
                else:
                    start = max(0, size - int(match.group(2)))
                end = min(end, size - 1)
                status = 206
            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header(
                "Content-Type",
                content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(65536, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)

        # ----- routes -----
        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            if path in ("/", "/index.html"):
                return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/media/"):
                target = (app.data_dir / unquote(path[len("/media/") :])).resolve()
                if app.data_dir not in target.parents:
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return self._file(target)
            if path == "/api/state":
                return self._guard(app.state)
            if path == "/api/briefings":
                return self._guard(app.briefings)
            if match := re.fullmatch(r"/api/briefings/(\w+)", path):
                return self._guard(lambda: app.briefing(match.group(1)))
            if path == "/api/drafts":
                return self._guard(lambda: app.drafts((query.get("status") or [None])[0]))
            if match := re.fullmatch(r"/api/jobs/(\w+)", path):
                job = app.jobs.get(match.group(1))
                return self._json(job or {"error": "Unknown job"}, 200 if job else 404)
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path

            def job(start: Callable[[], str]) -> None:
                self._guard(lambda: {"job": start()})

            if path == "/api/scan":
                return self._guard_job(lambda body: app.start_scan(body.get("cities")))
            if match := re.fullmatch(r"/api/briefings/(\w+)/reverify", path):
                return job(lambda: app.start_reverify(match.group(1)))
            if match := re.fullmatch(r"/api/briefings/(\w+)/draft", path):
                return job(lambda: app.start_script(match.group(1)))
            if match := re.fullmatch(r"/api/drafts/(\w+)/render", path):
                return self._guard_job(
                    lambda body: app.start_render(
                        match.group(1),
                        str(body.get("mode", "stills")),
                        bool(body.get("override_unverified")),
                    )
                )
            if match := re.fullmatch(r"/api/drafts/(\w+)/(approve|reject)", path):
                draft_id, action = match.groups()

                def decide() -> Any:
                    note = str(self._body().get("note", ""))
                    pipeline = app.pipeline
                    draft = (pipeline.approve if action == "approve" else pipeline.reject)(
                        draft_id, note
                    )
                    return app.draft_json(draft)

                return self._guard(decide)
            self.send_error(HTTPStatus.NOT_FOUND)

        def _guard_job(self, start: Callable[[dict[str, Any]], str]) -> None:
            self._guard(lambda: {"job": start(self._body())})

        def do_PUT(self) -> None:  # noqa: N802
            match = re.fullmatch(r"/api/drafts/(\w+)/script", urlparse(self.path).path)
            if not match:
                return self.send_error(HTTPStatus.NOT_FOUND)

            def save() -> Any:
                script = VideoScript.model_validate(self._body())
                return app.draft_json(app.pipeline.update_script(match.group(1), script))

            self._guard(save)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_logging()
    app = App(build_pipeline())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"County Crier running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
