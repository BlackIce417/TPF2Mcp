"""Persistent, bounded history of engine-observed per-line demand samples."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .save_scope import LEGACY_SAVE_ID


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
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(line_demand_samples)")}
        if "save_id" not in columns:
            connection.execute(
                f"ALTER TABLE line_demand_samples ADD COLUMN save_id TEXT NOT NULL DEFAULT '{LEGACY_SAVE_ID}'"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS line_demand_line_time ON line_demand_samples(line_id, observed_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS line_demand_save_line_time ON line_demand_samples(save_id,line_id,observed_at DESC)"
        )
        return connection

    def record(self, sample: dict[str, Any], save_id: str, observed_at: float | None = None) -> None:
        line_id = sample.get("line_id")
        if not isinstance(line_id, int):
            raise ValueError("line demand sample requires integer line_id")
        if not isinstance(save_id, str) or not save_id:
            raise ValueError("line demand sample requires save_id")
        payload = {**sample, "save_id": save_id}
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO line_demand_samples
                   (line_id,observed_at,sampled_game_time_ms,source_status,payload_json,save_id) VALUES (?,?,?,?,?,?)""",
                (line_id, time.time() if observed_at is None else observed_at, sample.get("sampled_game_time_ms"),
                 sample.get("source_status") or "UNKNOWN", json.dumps(payload, ensure_ascii=False, separators=(",", ":")), save_id),
            )

    def query(self, line_id: int, save_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM line_demand_samples WHERE save_id=? AND line_id=? ORDER BY observed_at DESC,id DESC LIMIT ?",
                (save_id, line_id, max(1, min(1000, int(limit)))),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in reversed(rows)]

    def histories(self, line_ids: list[int], save_id: str, limit: int = 12) -> dict[int, list[dict[str, Any]]]:
        return {line_id: values for line_id in line_ids if (values := self.query(line_id, save_id, limit))}
