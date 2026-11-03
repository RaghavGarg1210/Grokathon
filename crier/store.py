"""SQLite persistence for briefings, drafts and scan runs (JSON documents per row)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from crier.models import Briefing, Draft, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS briefings (
    id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    posted_on TEXT NOT NULL,
    relevance INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL,
    status TEXT NOT NULL,
    render_mode TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    started_at TEXT NOT NULL,
    kept INTEGER NOT NULL,
    new INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    usage TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_drafts_briefing ON drafts(briefing_id);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_briefing(self, briefing: Briefing) -> bool:
        """Inserts a briefing; returns False if this post was already stored."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO briefings (id, city, posted_on, relevance, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    briefing.id,
                    briefing.city,
                    briefing.posted_on.isoformat(),
                    briefing.relevance_score,
                    briefing.model_dump_json(),
                ),
            )
            return cursor.rowcount == 1

    def update_briefing(self, briefing: Briefing) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE briefings SET relevance = ?, data = ? WHERE id = ?",
                (briefing.relevance_score, briefing.model_dump_json(), briefing.id),
            )

    def get_briefing(self, briefing_id: str) -> Briefing | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM briefings WHERE id = ?", (briefing_id,)).fetchone()
        return Briefing.model_validate_json(row["data"]) if row else None

    def list_briefings(self) -> list[Briefing]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM briefings ORDER BY posted_on DESC, relevance DESC"
            ).fetchall()
        return [Briefing.model_validate_json(row["data"]) for row in rows]

    def save_draft(self, draft: Draft) -> Draft:
        draft = draft.model_copy(update={"updated_at": utc_now()})
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO drafts "
                "(id, briefing_id, status, render_mode, updated_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    draft.id,
                    draft.briefing_id,
                    draft.status,
                    draft.render_mode,
                    draft.updated_at.isoformat(),
                    draft.model_dump_json(),
                ),
            )
        return draft

    def get_draft(self, draft_id: str) -> Draft | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row["data"]) if row else None

    def latest_draft_for(self, briefing_id: str) -> Draft | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM drafts WHERE briefing_id = ? ORDER BY updated_at DESC LIMIT 1",
                (briefing_id,),
            ).fetchone()
        return Draft.model_validate_json(row["data"]) if row else None

    def list_drafts(self, status: str | None = None) -> list[Draft]:
        query, params = "SELECT data FROM drafts", ()
        if status:
            query, params = query + " WHERE status = ?", (status,)
        with self._connect() as conn:
            rows = conn.execute(query + " ORDER BY updated_at DESC", params).fetchall()
        return [Draft.model_validate_json(row["data"]) for row in rows]

    def count_hero_renders_on(self, day: date) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM drafts WHERE render_mode = 'hero' "
                "AND status IN ('ready', 'approved', 'rejected') AND substr(updated_at, 1, 10) = ?",
                (day.isoformat(),),
            ).fetchone()
        return int(row["n"])

    def record_scan_run(
        self,
        city: str,
        *,
        kept: int,
        new: int,
        rejected: int,
        error: str = "",
        usage: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO scan_runs (city, started_at, kept, new, rejected, error, usage) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    city,
                    datetime.now(UTC).isoformat(),
                    kept,
                    new,
                    rejected,
                    error,
                    json.dumps(usage or {}, default=str),
                ),
            )

    def list_scan_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT city, started_at, kept, new, rejected, error FROM scan_runs "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
