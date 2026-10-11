"""Versioned public facade for the mixed Lua/native dispatch backends."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable


CAPABILITIES = {
    "OBSERVE_TRAIN": {"backend": "ENGINE_API", "write": False},
    "APPLY_TIMETABLE": {"backend": "OFFICIAL_LUA_API", "feature": "timetable", "write": True},
    "HOLD_TRAIN": {"backend": "OFFICIAL_LUA_API", "feature": "timetable", "operation": "HOLD_VEHICLE_AT_TERMINAL", "write": True},
    "RELEASE_TRAIN": {"backend": "OFFICIAL_LUA_API", "feature": "timetable", "operation": "RELEASE_VEHICLE_FROM_HOLD", "write": True},
    "SET_SPEED_LIMIT": {"backend": "NATIVE_SPEED_HOOK", "feature": "speed", "write": True},
    "PROTECTIVE_STOP": {"backend": "OFFICIAL_LUA_API", "operation": "STOP_VEHICLE", "write": True},
    "RESUME_TRAIN": {"backend": "OFFICIAL_LUA_API", "operation": "START_VEHICLE", "write": True},
    "SET_PLATFORM_POLICY": {"backend": "NATIVE_STATION_HOOK", "feature": "station", "write": True},
    "SET_PATH_POLICY": {"backend": "NATIVE_PATH_COST_HOOK", "feature": "path", "write": True},
    "BALANCE_OD": {"backend": "NATIVE_OD_HOOK", "feature": "routing", "write": True},
    "ASSIGN_PLATFORM": {"backend": "NATIVE_STATION_HOOK", "write": True},
    "SET_PATH_COST": {"backend": "NATIVE_PATH_COST_HOOK", "write": True},
    "REASSIGN_OD": {"backend": "NATIVE_OD_HOOK", "write": True},
    "CANCEL_COMMAND": {"backend": "CONTROL_PLANE", "write": True},
}


class DispatchControlPlatform:
    """Expose dispatch intent while hiding Bridge files and native INI details."""

    def __init__(self, control_system: Any, state_directory: Path,
                 operation_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 speed_profile_provider: Callable[[], dict[str, Any]] | None = None):
        self.control_system = control_system
        self.path = Path(state_directory) / "dispatch-platform-commands.jsonl"
        self.operation_executor = operation_executor
        self.speed_profile_provider = speed_profile_provider

    def _record(self, value: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return value

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return []
        values = []
        for line in lines[-max(1, min(500, limit)):]:
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return list(reversed(values))

    def _find_command(self, command_id: str) -> dict[str, Any] | None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return None
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if value.get("command_id") == command_id:
                return value
        return None

    def view(self, save_id: str | None, live: dict[str, Any], heartbeat: dict[str, Any],
             native_status: dict[str, Any], speed_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self.control_system.config()
        native_ready = (native_status.get("supervisor_state") == "LOADED"
                        and native_status.get("state") == "ACTIVE"
                        and native_status.get("native_update_pending") is not True)
        lua_ready = heartbeat.get("allow_write_operations") is True
        allowed_operations = set(heartbeat.get("allowed_operations") or [])
        capabilities = {}
        for name, definition in CAPABILITIES.items():
            backend = definition["backend"]
            if not definition.get("write"):
                status, reason = "AVAILABLE", "live engine telemetry"
            elif backend == "CONTROL_PLANE":
                status, reason = "AVAILABLE", "local command registry"
            elif backend == "OFFICIAL_LUA_API":
                operation = definition.get("operation")
                ready = lua_ready and (not operation or operation in allowed_operations)
                status, reason = (("AVAILABLE", "official Lua operation enabled") if ready else
                                  ("DEGRADED", "official Lua operation disabled or not allowlisted"))
            else:
                status, reason = ("AVAILABLE", "version-locked native module active") if native_ready else ("UNAVAILABLE", "native module inactive or update pending")
            feature = definition.get("feature")
            capabilities[name] = {**definition, "status": status, "reason": reason,
                                  "policy_enabled": bool((config.get("features") or {}).get(feature)) if feature else True}
        sampled_at = live.get("sampled_at")
        now = time.time()
        return {"schema_version": 1, "platform": "TPF2_DISPATCH_CONTROL", "save_id": save_id,
                "mode": config.get("mode"), "capabilities": capabilities,
                "fleet": {"sampled_at": sampled_at,
                          "age_seconds": round(now - sampled_at, 2) if isinstance(sampled_at, (int, float)) else None,
                          "vehicles": live.get("vehicles", []), "counts": live.get("counts", {})},
                "infrastructure_speed_profile": speed_profile or {}, "recent_commands": self.recent(30)}

    def submit(self, raw: dict[str, Any], save_id: str | None, confirmation: str | None = None) -> dict[str, Any]:
        command_type = str(raw.get("type") or "").upper()
        if command_type not in CAPABILITIES or command_type == "OBSERVE_TRAIN":
            raise ValueError(f"unsupported command type {command_type or '<empty>'}")
        command_save = raw.get("save_id")
        if not save_id or command_save != save_id:
            raise ValueError("command save_id must match the active save")
        target, parameters = raw.get("target") or {}, raw.get("parameters") or {}
        if not isinstance(target, dict) or not isinstance(parameters, dict):
            raise ValueError("target and parameters must be objects")
        now = time.time()
        expires_at = float(raw.get("expires_at") or now + 120)
        if expires_at <= now or expires_at > now + 86400:
            raise ValueError("expires_at must be within the next 24 hours")
        command_id = str(raw.get("command_id") or f"dispatch-{uuid.uuid4()}")
        priority = int(raw.get("priority") or 50)
        if not 0 <= priority <= 100:
            raise ValueError("priority must be 0..100")
        base = {"schema_version": 1, "command_id": command_id, "type": command_type,
                "save_id": save_id, "target": target, "parameters": parameters,
                "priority": priority, "expires_at": expires_at,
                "source": str(raw.get("source") or "UI_API"),
                "reason": str(raw.get("reason") or "USER_DISPATCH_INTENT"), "submitted_at": now}
        prior = self._find_command(command_id)
        if prior:
            immutable = ("type", "save_id", "target", "parameters", "priority", "expires_at", "source", "reason")
            if any(prior.get(key) != base.get(key) for key in immutable):
                raise ValueError("command_id already exists with different content")
            return {**prior, "status": "DUPLICATE", "duplicate_of": command_id}
        config = self.control_system.config()
        if command_type == "CANCEL_COMMAND":
            target_id = target.get("command_id")
            if not isinstance(target_id, str) or not target_id:
                raise ValueError("CANCEL_COMMAND requires target.command_id")
            patch, removed = {}, []
            for collection in ("speed_rules", "edge_speed_rules", "station_rules", "path_rules", "routing_rules"):
                current = list(config.get(collection, []))
                retained = [item for item in current if item.get("rule_id") != target_id]
                if len(retained) != len(current):
                    patch[collection] = retained
                    removed.append(collection)
            if patch:
                self.control_system.configure(patch, save_id, confirmation)
            return self._record({**base, "status": "CANCELLED" if removed else "NOT_FOUND",
                                 "backend": "CONTROL_PLANE", "cancelled_command_id": target_id,
                                 "removed_from": removed})
        if command_type == "SET_SPEED_LIMIT":
            required_target = all(isinstance(target.get(key), int) for key in ("vehicle_id", "line_id"))
            required_parameters = all(isinstance(parameters.get(key), (int, float)) for key in ("start_km", "end_km", "speed_kmh"))
            if not required_target or not required_parameters:
                raise ValueError("SET_SPEED_LIMIT requires integer vehicle_id/line_id and numeric start_km/end_km/speed_kmh")
            rule = {"rule_id": command_id, "vehicle_id": target["vehicle_id"], "line_id": target["line_id"],
                    "start_km": parameters["start_km"], "end_km": parameters["end_km"],
                    "speed_kmh": parameters["speed_kmh"], "direction": parameters.get("direction", "FORWARD"),
                    "expires_at": expires_at, "priority": base["priority"], "enabled": True}
            rules = [item for item in config.get("speed_rules", []) if item.get("rule_id") != command_id] + [rule]
            self.control_system.configure({"speed_rules": rules}, save_id, confirmation)
            return self._record({**base, "status": "ACCEPTED", "backend": "NATIVE_SPEED_HOOK",
                                 "execution": "LEASE_COMPILED_BY_NEXT_CONTROL_CYCLE"})
        if command_type == "ASSIGN_PLATFORM":
            vehicle_id = target.get("vehicle_id")
            required = ("station_group_id", "station_index", "terminal_index")
            if not isinstance(vehicle_id, int) or not all(isinstance(parameters.get(key), int) for key in required):
                raise ValueError("ASSIGN_PLATFORM requires target.vehicle_id and integer station_group_id/station_index/terminal_index")
            rule = {"rule_id": command_id, "vehicle_id": vehicle_id,
                    "line_id": target.get("line_id"), "stop_index": parameters.get("stop_index"),
                    "station_group_id": parameters["station_group_id"],
                    "station_index": parameters["station_index"], "terminal_index": parameters["terminal_index"],
                    "expires_at": expires_at, "priority": base["priority"], "enabled": True}
            rules = [item for item in config.get("station_rules", []) if item.get("rule_id") != command_id] + [rule]
            self.control_system.configure({"station_rules": rules}, save_id, confirmation)
            return self._record({**base, "status": "ACCEPTED", "backend": "NATIVE_STATION_HOOK",
                                 "execution": "EXPLICIT_LEASE_COMPILED_BY_NEXT_CONTROL_CYCLE"})
        if command_type == "SET_PATH_COST":
            vehicle_id, edge_ids = target.get("vehicle_id"), parameters.get("edge_ids")
            penalty = parameters.get("penalty_seconds")
            if (not isinstance(vehicle_id, int) or not isinstance(edge_ids, list) or not edge_ids
                    or not all(isinstance(edge, int) and edge > 0 for edge in edge_ids)
                    or not isinstance(penalty, (int, float))):
                raise ValueError("SET_PATH_COST requires target.vehicle_id, positive integer edge_ids and penalty_seconds")
            rule = {"rule_id": command_id, "vehicle_id": vehicle_id,
                    "edge_ids": list(dict.fromkeys(edge_ids)), "penalty_seconds": penalty,
                    "expires_at": expires_at, "priority": base["priority"], "enabled": True}
            rules = [item for item in config.get("path_rules", []) if item.get("rule_id") != command_id] + [rule]
            self.control_system.configure({"path_rules": rules}, save_id, confirmation)
            return self._record({**base, "status": "ACCEPTED", "backend": "NATIVE_PATH_COST_HOOK",
                                 "execution": "EXPLICIT_LEASE_COMPILED_BY_NEXT_CONTROL_CYCLE"})
        if command_type == "REASSIGN_OD":
            required = ("source_line", "target_line", "source_stop0", "source_stop1",
                        "target_stop0", "target_stop1", "max_assignments")
            if not all(isinstance(parameters.get(key), int) for key in required):
                raise ValueError("REASSIGN_OD requires integer source/target line, stop pairs and max_assignments")
            entity_kind = str(parameters.get("entity_kind") or "").upper()
            if entity_kind not in {"PERSON", "CARGO"}:
                raise ValueError("REASSIGN_OD requires entity_kind PERSON or CARGO")
            cargo_id = parameters.get("cargo_id")
            if entity_kind == "CARGO":
                if not isinstance(cargo_id, int):
                    raise ValueError("CARGO reassignment requires cargo_id")
                raise ValueError("cargo-type-specific reassignment is unavailable until the native hook can verify cargo_id")
            rule = {"rule_id": command_id, **{key: parameters[key] for key in required},
                    "entity_kind": entity_kind, "cargo_id": 0, "expires_at": expires_at,
                    "priority": base["priority"], "enabled": True}
            rules = [item for item in config.get("routing_rules", []) if item.get("rule_id") != command_id] + [rule]
            self.control_system.configure({"routing_rules": rules}, save_id, confirmation)
            return self._record({**base, "status": "ACCEPTED", "backend": "NATIVE_OD_HOOK",
                                 "execution": "EXPLICIT_LEASE_COMPILED_BY_NEXT_CONTROL_CYCLE"})
        if command_type == "PROTECTIVE_STOP":
            vehicle_id, edge_ids = target.get("vehicle_id"), parameters.get("edge_ids")
            if not isinstance(vehicle_id, int) or not isinstance(edge_ids, list) or not edge_ids or not all(isinstance(edge, int) for edge in edge_ids):
                raise ValueError("PROTECTIVE_STOP requires integer vehicle_id and non-empty integer edge_ids")
            profile = self.speed_profile_provider() if self.speed_profile_provider else {}
            turnout_edges = {edge for turnout in profile.get("turnouts", []) for edge in turnout.get("incident_edge_ids", [])}
            conflicts = sorted(set(edge_ids) & turnout_edges)
            if conflicts and parameters.get("emergency") is not True:
                raise ValueError("ordinary protective stop cannot target a turnout conflict edge; choose an approach edge or set emergency=true")
            if config.get("mode") != "ARMED":
                return self._record({**base, "status": "PLANNED_SHADOW", "backend": "OFFICIAL_LUA_API",
                                     "execution": "CONTROL_SYSTEM_NOT_ARMED", "turnout_conflicts": conflicts})
            if not self.operation_executor:
                raise ValueError("official operation executor unavailable")
            maximum = max(5, min(120, int(expires_at-now)))
            result = self.operation_executor({"protocol_version": 1, "operation_id": command_id,
                "operation_type": "STOP_VEHICLE", "target": {"vehicle_id": vehicle_id},
                "parameters": {"max_stop_seconds": maximum}})
            return self._record({**base, "status": "EXECUTED", "backend": "OFFICIAL_LUA_API",
                                 "execution": "USER_STOP_COMMAND_SENT_WITH_WATCHDOG",
                                 "turnout_conflicts": conflicts, "result": result})
        if command_type == "RESUME_TRAIN":
            vehicle_id = target.get("vehicle_id")
            if not isinstance(vehicle_id, int):
                raise ValueError("RESUME_TRAIN requires integer vehicle_id")
            if config.get("mode") != "ARMED":
                return self._record({**base, "status": "PLANNED_SHADOW", "backend": "OFFICIAL_LUA_API",
                                     "execution": "CONTROL_SYSTEM_NOT_ARMED"})
            if not self.operation_executor:
                raise ValueError("official operation executor unavailable")
            result = self.operation_executor({"protocol_version": 1, "operation_id": command_id,
                "operation_type": "START_VEHICLE", "target": {"vehicle_id": vehicle_id}, "parameters": {}})
            return self._record({**base, "status": "EXECUTED", "backend": "OFFICIAL_LUA_API",
                                 "execution": "USER_STOP_CLEARED", "result": result})
        if command_type in {"HOLD_TRAIN", "RELEASE_TRAIN"}:
            vehicle_id = target.get("vehicle_id")
            if not isinstance(vehicle_id, int):
                raise ValueError(f"{command_type} requires integer vehicle_id")
            if config.get("mode") != "ARMED":
                return self._record({**base, "status": "PLANNED_SHADOW", "backend": "OFFICIAL_LUA_API",
                                     "execution": "CONTROL_SYSTEM_NOT_ARMED"})
            if not self.operation_executor:
                raise ValueError("official operation executor unavailable")
            operation = "HOLD_VEHICLE_AT_TERMINAL" if command_type == "HOLD_TRAIN" else "RELEASE_VEHICLE_FROM_HOLD"
            result = self.operation_executor({"protocol_version": 1, "operation_id": command_id,
                                              "operation_type": operation, "target": {"vehicle_id": vehicle_id},
                                              "parameters": parameters})
            return self._record({**base, "status": "EXECUTED", "backend": "OFFICIAL_LUA_API", "result": result})
        feature = CAPABILITIES[command_type].get("feature")
        if feature:
            features = dict(config.get("features") or {})
            features[feature] = True
            self.control_system.configure({"features": features}, save_id, confirmation)
        return self._record({**base, "status": "POLICY_ACCEPTED", "backend": CAPABILITIES[command_type]["backend"],
                             "execution": "CLOSED_LOOP_POLICY_NEXT_CYCLE"})
