"""Persistent, truthful MCP adjustment log for the railway map UI."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any


class McpWorkLogStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS mcp_work_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                occurred_at REAL NOT NULL,
                action_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                line_id INTEGER,
                vehicle_id INTEGER,
                applied INTEGER NOT NULL CHECK(applied IN (0,1)),
                verification_status TEXT NOT NULL,
                details_json TEXT NOT NULL
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS mcp_work_log_time ON mcp_work_log(occurred_at DESC)")
        return connection

    @staticmethod
    def _timestamp(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                from datetime import datetime
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return time.time()

    def _insert(self, row: tuple[Any, ...]) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT OR IGNORE INTO mcp_work_log
                   (source_key,occurred_at,action_type,summary,line_id,vehicle_id,applied,verification_status,details_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""", row,
            )

    def sync_task_journal(self, path: Path) -> int:
        """Import only postcondition-verified task steps; proposals are never logged as work done."""
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return 0
        completed: dict[str, dict[str, Any]] = {}
        for raw in lines:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("status") == "COMPLETED" and item.get("task_id"):
                completed[item["task_id"]] = item
        before = len(self.query(500))
        labels = {
            "BUY_VEHICLE": "购买车辆", "ASSIGN_VEHICLE_TO_LINE": "车辆分配到线路",
            "SET_LINE_STOP_POLICY": "调整停站策略", "SET_LINE_STOPS": "调整线路停靠站台",
            "CREATE_LINE": "创建线路", "CREATE_LINE_FROM_SOURCE_ROUTE": "创建线路",
            "SELL_VEHICLE": "出售车辆", "RENAME_LINE": "重命名线路",
            "HOLD_VEHICLE": "扣停列车", "RELEASE_VEHICLE": "放行列车",
        }
        for task in completed.values():
            goal = task.get("goal") or {}
            for step in task.get("steps", []):
                verification = step.get("verification") or {}
                if step.get("status") != "POSTCONDITION_VERIFIED" and verification.get("status") != "POSTCONDITION_VERIFIED":
                    continue
                operation = str(step.get("operation_type") or "UNKNOWN")
                target = (task.get("planned_steps") or [{}])[min(max(int(step.get("sequence", 1)) - 1, 0), max(len(task.get("planned_steps") or [{}]) - 1, 0))].get("target", {})
                line_id = target.get("line_id") or goal.get("target_line_id")
                vehicle_id = target.get("vehicle_id") or goal.get("created_vehicle_id") or goal.get("vehicle_id")
                label = labels.get(operation, operation)
                suffix = f"线路 {line_id}" if isinstance(line_id, int) else f"车辆 {vehicle_id}" if isinstance(vehicle_id, int) else "游戏对象"
                verified_at = verification.get("verified_at") or task.get("timeline", [{}])[-1].get("at")
                self._insert((f"task:{task['task_id']}:{step.get('step_id') or step.get('sequence')}", self._timestamp(verified_at),
                              operation, f"{label} · {suffix}", line_id, vehicle_id, 1,
                              "POSTCONDITION_VERIFIED", json.dumps(step, ensure_ascii=False, separators=(",", ":"))))
        return max(0, len(self.query(500)) - before)

    def sync_timetable_plan(self, path: Path) -> None:
        try:
            raw = Path(path).read_bytes()
            plan = json.loads(raw.decode("utf-8"))
            modified = Path(path).stat().st_mtime
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        digest = hashlib.sha256(raw).hexdigest()[:20]
        counts = plan.get("counts") or {}
        conflict = plan.get("global_conflict_plan") or {}
        summary = f"生成全网运行图影子方案 · {counts.get('planned_lines', 0)} 条线路，消除 {conflict.get('conflicts_removed', 0)} 个站场相位冲突"
        self._insert((f"plan:{digest}", modified, "TIMETABLE_PLAN_GENERATED", summary, None, None, 0,
                      "PLAN_ONLY_NOT_APPLIED", json.dumps({"counts": counts, "global_conflict_plan": conflict}, ensure_ascii=False, separators=(",", ":"))))

    def query(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(500, int(limit)))
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id,occurred_at,action_type,summary,line_id,vehicle_id,applied,verification_status
                   FROM mcp_work_log ORDER BY occurred_at DESC,id DESC LIMIT ?""", (bounded,),
            ).fetchall()
        return [{**dict(row), "applied": bool(row["applied"])} for row in rows]
