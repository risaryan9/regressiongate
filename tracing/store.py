"""SQLite storage for spans. One row per span, plain sqlite3, no ORM."""

import os
import sqlite3
from typing import Literal

from pydantic import BaseModel

DEFAULT_DB = os.environ.get("TRACE_DB", "traces.db")

SpanKind = Literal["eval", "agent", "llm", "tool", "judge"]


class Span(BaseModel):
    trace_id: str
    span_id: str
    parent_id: str | None = None
    run_id: str | None = None  # set when the span belongs to an eval run
    name: str
    kind: SpanKind
    input: str | None = None  # JSON text
    output: str | None = None  # JSON text
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    started_at: str  # ISO 8601, UTC


_COLUMNS = list(Span.model_fields)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS spans (
    {", ".join(_COLUMNS)},
    PRIMARY KEY (span_id)
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_run ON spans (run_id);
"""


class TraceStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        with self._connect() as conn:
            # WAL lets parallel eval workers write spans without blocking readers, and is much faster per insert.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # A fresh connection per call keeps this safe if spans are saved from several threads.
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; a crash loses at most the last few spans
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, span: Span) -> None:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO spans ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                [getattr(span, c) for c in _COLUMNS],
            )

    def get_trace(self, trace_id: str) -> list[Span]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at", (trace_id,)
            ).fetchall()
        return [Span(**dict(row)) for row in rows]

    def find_traces(self, prefix: str) -> list[str]:
        """Trace IDs starting with prefix, so the CLI accepts short IDs like git does."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trace_id FROM spans WHERE trace_id LIKE ?", (prefix + "%",)
            ).fetchall()
        return [row[0] for row in rows]

    def latencies(self, run_id: str, kind: SpanKind = "agent") -> list[float]:
        """Latency of every span of one kind in a run. kind='agent' gives end-to-end times."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT latency_ms FROM spans WHERE run_id = ? AND kind = ? AND latency_ms IS NOT NULL",
                (run_id, kind),
            ).fetchall()
        return [row[0] for row in rows]
