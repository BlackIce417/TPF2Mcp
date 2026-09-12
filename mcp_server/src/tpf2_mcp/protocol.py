from __future__ import annotations

import time
import uuid
from typing import Any

SCHEMA_VERSION = 1


def request(command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if command not in {"ping", "get_game_state", "get_towns", "get_town", "get_rail_network", "get_operational_telemetry", "get_line_demand", "get_vehicle_dispatch_state", "get_timetable_status", "execute_operation"}:
        raise ValueError(f"unsupported command: {command}")
    return {"schema_version": SCHEMA_VERSION, "request_id": str(uuid.uuid4()), "command": command,
            "params": params or {}, "timestamp": time.time()}


def error_response(request_id: str, code: str, message: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "request_id": request_id, "ok": False, "result": None,
            "error": {"code": code, "message": message}, "timestamp": time.time()}
