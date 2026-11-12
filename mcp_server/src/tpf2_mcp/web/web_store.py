"""SQLite persistence owned by the local Web/query service."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any
from contextlib import closing


class WebMutationStore:
    """Append-only audit records for state-changing HTTP requests.

    Live telemetry remains in immutable Bridge snapshots.  SQLite owns durable
    Web mutations and their results, which are low-frequency and auditable.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as database, database:
            database.execute(
                """
                CREATE TABLE IF NOT EXISTS web_mutations (
                    request_id TEXT PRIMARY KEY,
                    occurred_at REAL NOT NULL,
                    save_id TEXT,
                    endpoint TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )
            database.execute(
                "CREATE INDEX IF NOT EXISTS web_mutations_save_time "
                "ON web_mutations(save_id, occurred_at DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=5)
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA busy_timeout=5000")
        return database

    def record(
        self,
        *,
        save_id: str | None,
        endpoint: str,
        action: str,
        status_code: int,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> str:
        request_id = str(uuid.uuid4())
        with closing(self._connect()) as database, database:
            database.execute(
                "INSERT INTO web_mutations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    time.time(),
                    save_id,
                    endpoint,
                    action,
                    status_code,
                    json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        return request_id

    def recent(self, save_id: str | None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query = (
            "SELECT request_id, occurred_at, save_id, endpoint, action, status_code, "
            "request_json, response_json FROM web_mutations"
        )
        parameters: tuple[Any, ...]
        if save_id:
            query += " WHERE save_id = ? ORDER BY occurred_at DESC LIMIT ?"
            parameters = (save_id, limit)
        else:
            query += " ORDER BY occurred_at DESC LIMIT ?"
            parameters = (limit,)
        with closing(self._connect()) as database:
            database.row_factory = sqlite3.Row
            rows = database.execute(query, parameters).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if key not in {"request_json", "response_json"}},
                "request": json.loads(row["request_json"]),
                "response": json.loads(row["response_json"]),
            }
            for row in rows
        ]
