"""Persistent, bounded history of engine-observed per-line demand samples."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


class DemandHistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS line_demand_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_id INTEGER NOT NULL,
                observed_at REAL NOT NULL,
                sampled_game_time_ms INTEGER,
                source_status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS line_demand_line_time ON line_demand_samples(line_id, observed_at DESC)"
        )
        return connection

    def record(self, sample: dict[str, Any], observed_at: float | None = None) -> None:
        line_id = sample.get("line_id")
        if not isinstance(line_id, int):
            raise ValueError("line demand sample requires integer line_id")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO line_demand_samples
                   (line_id,observed_at,sampled_game_time_ms,source_status,payload_json) VALUES (?,?,?,?,?)""",
                (line_id, time.time() if observed_at is None else observed_at, sample.get("sampled_game_time_ms"),
                 sample.get("source_status") or "UNKNOWN", json.dumps(sample, ensure_ascii=False, separators=(",", ":"))),
            )

    def query(self, line_id: int, limit: int = 12) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM line_demand_samples WHERE line_id=? ORDER BY observed_at DESC,id DESC LIMIT ?",
                (line_id, max(1, min(1000, int(limit)))),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in reversed(rows)]

    def histories(self, line_ids: list[int], limit: int = 12) -> dict[int, list[dict[str, Any]]]:
        return {line_id: values for line_id in line_ids if (values := self.query(line_id, limit))}
