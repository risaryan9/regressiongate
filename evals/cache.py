"""Judge cache: the same (case, agent output, rubric, judge model) always gets the same verdict.

This makes re-scoring repeatable and free. Fresh agent runs usually word their reply a little
differently, so expect misses there; hits come from identical outputs and re-scored runs.
"""

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime

from pydantic import BaseModel

DEFAULT_CACHE_DB = os.environ.get("JUDGE_CACHE_DB", "judge_cache.db")


def cache_key(*parts: BaseModel | dict | str) -> str:
    def norm(p):
        return p.model_dump(mode="json") if isinstance(p, BaseModel) else p

    blob = json.dumps([norm(p) for p in parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class JudgeCache:
    def __init__(self, path: str = DEFAULT_CACHE_DB):
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS judge_cache (key TEXT PRIMARY KEY, verdict TEXT NOT NULL, created_at TEXT NOT NULL)")

    def get(self, key: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT verdict FROM judge_cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, verdict_json: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO judge_cache (key, verdict, created_at) VALUES (?, ?, ?)",
                (key, verdict_json, datetime.now(UTC).isoformat()),
            )
