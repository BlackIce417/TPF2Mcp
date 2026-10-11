"""Persistent, fail-closed control plane for continuous TPF2 operations."""
from __future__ import annotations

import configparser
import hashlib
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .save_scope import snapshot_save_id
from .speed_zones import map_chainage_zone
from .infrastructure_speed import build_infrastructure_speed_profile, compile_vehicle_speed_leases
from .train_spacing import DEFAULT_POLICY as DEFAULT_SPACING_POLICY, compile_train_spacing


MODES = {"DISABLED", "SHADOW", "ARMED"}
FEATURES = ("timetable", "fleet", "routing", "speed", "spacing", "station", "path")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return deepcopy(default)


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def default_config() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "mode": "DISABLED",
        "features": {name: False for name in FEATURES},
        "cycle_interval_seconds": 2,
        "plan_interval_seconds": 60,
        "demand_sample_interval_seconds": 300,
        "health_stale_seconds": 45,
        "lease_seconds": 120,
        "fleet_cooldown_seconds": 3600,
        "max_actions_per_cycle": 1,
        "failure_trip_count": 3,
        "path_penalty_seconds": 300,
        "automatic_infrastructure_speed_limits": True,
        "infrastructure_speed_policy": {"default_side_kmh": 45, "platform_kmh": 45, "overrides": {}},
        "spacing_policy": dict(DEFAULT_SPACING_POLICY),
        "speed_rules": [],
        "edge_speed_rules": [],
        "station_rules": [],
        "path_rules": [],
        "routing_rules": [],
    }


class ControlEventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        value = {"event_id": f"control-{uuid.uuid4()}", "at": time.time(), **event}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock, self.path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return value

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return []
        result = []
        for line in lines[-max(1, min(500, int(limit))):]:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(result))


class NativeLeaseWriter:
    """Atomically publish bounded native leases and a legacy first lease."""

    def __init__(self, bridge: Path):
        self.path = Path(bridge) / "native-control.ini"

    @staticmethod
    def _encode(raw: Any) -> str:
        # Win32 profile integer readers accept 0/1, not Python's True/False.
        if isinstance(raw, bool):
            return "1" if raw else "0"
        if isinstance(raw, list):
            return ",".join(map(str, raw))
        return str(raw)

    @staticmethod
    def _native_fields(kind: str, item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in item if key not in {"kind", "lease_id", "created_at"}}

    def write(self, generation: int, leases: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        active = [deepcopy(item) for item in leases if float(item.get("expires_at") or 0) > now]
        by_kind = {kind: [item for item in active if item.get("kind") == kind]
                   for kind in ("speed", "station", "routing", "path")}
        value = configparser.ConfigParser()
        value["meta"] = {"schema_version": "2", "generation": str(int(generation)), "written_at": str(now)}
        for kind, items in by_kind.items():
            value["meta"][f"{kind}_count"] = str(len(items))
            for index, item in enumerate(items):
                section = f"{kind}_{index}"
                fields = self._native_fields(kind, item)
                value[section] = {key: self._encode(raw)
                                  for key, raw in fields.items() if raw is not None}
                value[section]["enabled"] = "1"
        # Older injected builds remain fail-closed and can execute the first
        # lease of each kind until the multi-lease native build is loaded.
        for kind in ("speed", "station", "routing", "path"):
            first = by_kind[kind][0] if by_kind[kind] else None
            value[kind] = {"enabled": "1" if first else "0"}
            if first:
                fields = self._native_fields(kind, first)
                aliases = {"edge_ids": first.get("edge_ids", [])}
                for key, raw in {**fields, **aliases}.items():
                    if key in {"kind", "lease_id", "created_at", "expires_at"} or raw is None:
                        continue
                    value[kind][key] = self._encode(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".ini.tmp")
        with temporary.open("w", encoding="ascii") as stream:
            value.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        return active


class EngineeringControlSystem:
    """Compute and execute one bounded control cycle.

    Callbacks keep policy deterministic in tests and keep Bridge writes in the
    owning service process. A cycle never writes to the game unless mode is
    ARMED and every health gate passes.
    """

    def __init__(self, bridge: Path, state_directory: Path,
                 timetable_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 timetable_clearer: Callable[[int], dict[str, Any]] | None = None,
                 fleet_executor: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None):
        self.bridge = Path(bridge)
        self.state_directory = Path(state_directory)
        self.config_path = self.state_directory / "control-system-config.json"
        self.state_path = self.state_directory / "control-system-state.json"
        self.lease_path = self.state_directory / "control-system-leases.json"
        self.events = ControlEventLog(self.state_directory / "control-system-events.jsonl")
        self.native = NativeLeaseWriter(self.bridge)
        self.timetable_executor = timetable_executor
        self.timetable_clearer = timetable_clearer
        self.fleet_executor = fleet_executor
        self._lock = threading.Lock()
        self._last_cycle = 0.0
        loaded_config = _read_json(self.config_path, default_config())
        self._config = default_config()
        if isinstance(loaded_config, dict):
            for key, value in loaded_config.items():
                if key != "features":
                    self._config[key] = value
            if isinstance(loaded_config.get("features"), dict):
                self._config["features"].update({key: value for key, value in loaded_config["features"].items()
                                                  if key in FEATURES and isinstance(value, bool)})
            if int(loaded_config.get("schema_version") or 1) < 2:
                self._config["schema_version"] = 2
                if loaded_config.get("cycle_interval_seconds") == 10:
                    self._config["cycle_interval_seconds"] = 2
        self._state = _read_json(self.state_path, self._empty_state())
        self._leases = _read_json(self.lease_path, {"schema_version": 1, "generation": 0, "leases": []})
        if not self.config_path.exists() or self._config != loaded_config:
            _atomic_json(self.config_path, self._config)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"schema_version": 1, "lifecycle": "DISABLED", "configured_mode": "DISABLED",
                "save_id": None, "last_cycle_at": None, "last_success_at": None,
                "consecutive_failures": 0, "trip_reason": None, "health": {},
                "decisions": [], "actions": [], "applied_timetables": {}, "cooldowns": {}}

    def config(self) -> dict[str, Any]:
        return deepcopy(self._config)

    def view(self, event_limit: int = 50) -> dict[str, Any]:
        return {"schema_version": 1, "config": self.config(), "state": deepcopy(self._state),
                "leases": deepcopy(self._leases), "events": self.events.recent(event_limit)}

    def configure(self, patch: dict[str, Any], save_id: str | None, confirmation: str | None = None) -> dict[str, Any]:
        with self._lock:
            value = deepcopy(self._config)
            if "mode" in patch:
                mode = str(patch["mode"]).upper()
                if mode not in MODES:
                    raise ValueError(f"mode must be one of {sorted(MODES)}")
                if mode == "ARMED" and confirmation != f"ARM:{save_id}":
                    raise ValueError("arming requires confirmation ARM:<current-save-id>")
                value["mode"] = mode
            if "features" in patch:
                if not isinstance(patch["features"], dict):
                    raise ValueError("features must be an object")
                for name, enabled in patch["features"].items():
                    if name not in FEATURES or not isinstance(enabled, bool):
                        raise ValueError(f"invalid feature switch {name}")
                    value["features"][name] = enabled
            for key, lower, upper in (
                ("cycle_interval_seconds", 2, 300), ("plan_interval_seconds", 15, 3600),
                ("demand_sample_interval_seconds", 30, 86400), ("lease_seconds", 15, 3600),
                ("health_stale_seconds", 10, 120),
                ("fleet_cooldown_seconds", 300, 86400), ("max_actions_per_cycle", 1, 10),
                ("failure_trip_count", 1, 20),
                ("path_penalty_seconds", 1, 3600),
            ):
                if key in patch:
                    number = int(patch[key])
                    if not lower <= number <= upper:
                        raise ValueError(f"{key} must be {lower}..{upper}")
                    value[key] = number
            if "automatic_infrastructure_speed_limits" in patch:
                if not isinstance(patch["automatic_infrastructure_speed_limits"], bool):
                    raise ValueError("automatic_infrastructure_speed_limits must be boolean")
                value["automatic_infrastructure_speed_limits"] = patch["automatic_infrastructure_speed_limits"]
            if "infrastructure_speed_policy" in patch:
                policy = patch["infrastructure_speed_policy"]
                if not isinstance(policy, dict):
                    raise ValueError("infrastructure_speed_policy must be an object")
                default_side = float(policy.get("default_side_kmh", 45))
                platform = float(policy.get("platform_kmh", 45))
                if not 10 <= default_side <= 160 or not 10 <= platform <= 160:
                    raise ValueError("infrastructure operating speeds must be 10..160 km/h")
                if not isinstance(policy.get("overrides", {}), dict):
                    raise ValueError("infrastructure speed overrides must be an object")
                value["infrastructure_speed_policy"] = {"default_side_kmh": default_side,
                                                          "platform_kmh": platform,
                                                          "overrides": deepcopy(policy.get("overrides", {}))}
            if "spacing_policy" in patch:
                policy = patch["spacing_policy"]
                if not isinstance(policy, dict):
                    raise ValueError("spacing_policy must be an object")
                merged = {**value.get("spacing_policy", DEFAULT_SPACING_POLICY), **policy}
                bounds = {
                    "reaction_seconds": (0.5, 15.0), "fixed_margin_m": (5.0, 200.0),
                    "position_uncertainty_m": (0.0, 100.0), "projection_tolerance_m": (1.0, 50.0),
                    "conservative_deceleration_mps2": (0.1, 3.0), "minimum_limit_kmh": (1.0, 30.0),
                    "hysteresis_kmh": (0.0, 20.0), "max_lookahead_m": (50.0, 10000.0),
                    "maximum_footprint_age_seconds": (0.5, 10.0),
                }
                for name, (lower, upper) in bounds.items():
                    number = merged.get(name)
                    if not isinstance(number, (int, float)) or isinstance(number, bool) or not lower <= float(number) <= upper:
                        raise ValueError(f"spacing_policy.{name} must be {lower}..{upper}")
                    merged[name] = float(number)
                if not isinstance(merged.get("armed_execution"), bool):
                    raise ValueError("spacing_policy.armed_execution must be boolean")
                value["spacing_policy"] = merged
            if "speed_rules" in patch:
                rules = patch["speed_rules"]
                if not isinstance(rules, list) or len(rules) > 64:
                    raise ValueError("speed_rules must be a list with at most 64 entries")
                normalized = []
                for item in rules:
                    required = ("vehicle_id", "line_id", "start_km", "end_km", "speed_kmh")
                    if not isinstance(item, dict) or not all(isinstance(item.get(key), (int, float)) for key in required):
                        raise ValueError("each speed rule requires numeric vehicle_id, line_id, start_km, end_km, speed_kmh")
                    if item["vehicle_id"] < 0 or item["line_id"] < 0 or not 0 <= item["start_km"] < item["end_km"] or item["speed_kmh"] <= 0:
                        raise ValueError("invalid speed rule bounds")
                    direction = str(item.get("direction") or "FORWARD").upper()
                    if direction != "FORWARD":
                        raise ValueError("only FORWARD chainage is supported until native direction matching is available")
                    normalized.append({"rule_id": str(item.get("rule_id") or f"speed-{uuid.uuid4()}"),
                                       "vehicle_id": int(item["vehicle_id"]), "line_id": int(item["line_id"]),
                                       "start_km": float(item["start_km"]), "end_km": float(item["end_km"]),
                                       "speed_kmh": float(item["speed_kmh"]),
                                       "direction": direction,
                                       "enabled": item.get("enabled", True) is True,
                                       "priority": int(item.get("priority") or 50),
                                       "expires_at": float(item["expires_at"]) if isinstance(item.get("expires_at"), (int, float)) else None})
                value["speed_rules"] = normalized
            if "edge_speed_rules" in patch:
                rules = patch["edge_speed_rules"]
                if not isinstance(rules, list) or len(rules) > 256:
                    raise ValueError("edge_speed_rules must be a list with at most 256 entries")
                normalized = []
                for item in rules:
                    hold = item.get("hold") is True
                    speed = item.get("speed_kmh", 0 if hold else None)
                    edges = item.get("edge_ids")
                    if (not isinstance(item, dict) or not isinstance(item.get("vehicle_id"), int)
                            or not isinstance(edges, list) or not edges or len(edges) > 2048
                            or not all(isinstance(edge, int) and edge > 0 for edge in edges)
                            or not isinstance(speed, (int, float)) or speed < 0 or (speed == 0 and not hold)):
                        raise ValueError("edge speed rule requires vehicle_id, 1..2048 positive edge_ids, and positive speed or hold=true")
                    normalized.append({"rule_id": str(item.get("rule_id") or f"edge-speed-{uuid.uuid4()}"),
                                       "vehicle_id": int(item["vehicle_id"]),
                                       "line_id": int(item["line_id"]) if isinstance(item.get("line_id"), int) else None,
                                       "edge_ids": list(dict.fromkeys(int(edge) for edge in edges)),
                                       "speed_kmh": float(speed), "hold": hold,
                                       "enabled": item.get("enabled", True) is True,
                                       "priority": int(item.get("priority") or 50),
                                       "expires_at": float(item["expires_at"]) if isinstance(item.get("expires_at"), (int, float)) else None})
                value["edge_speed_rules"] = normalized
            if "station_rules" in patch:
                rules = patch["station_rules"]
                if not isinstance(rules, list) or len(rules) > 64:
                    raise ValueError("station_rules must be a list with at most 64 entries")
                normalized = []
                for item in rules:
                    required = ("vehicle_id", "station_group_id", "station_index", "terminal_index")
                    if (not isinstance(item, dict) or not all(isinstance(item.get(key), int) for key in required)
                            or min(item[key] for key in required) < 0):
                        raise ValueError("station rule requires non-negative vehicle/station/terminal identifiers")
                    normalized.append({"rule_id": str(item.get("rule_id") or f"station-{uuid.uuid4()}"),
                                       "vehicle_id": item["vehicle_id"],
                                       "line_id": item.get("line_id") if isinstance(item.get("line_id"), int) else None,
                                       "stop_index": item.get("stop_index") if isinstance(item.get("stop_index"), int) else None,
                                       "station_group_id": item["station_group_id"],
                                       "station_index": item["station_index"], "terminal_index": item["terminal_index"],
                                       "priority": int(item.get("priority") or 50),
                                       "expires_at": float(item["expires_at"]) if isinstance(item.get("expires_at"), (int, float)) else None,
                                       "enabled": item.get("enabled", True) is True})
                value["station_rules"] = normalized
            if "path_rules" in patch:
                rules = patch["path_rules"]
                if not isinstance(rules, list) or len(rules) > 64:
                    raise ValueError("path_rules must be a list with at most 64 entries")
                normalized = []
                for item in rules:
                    edges, penalty = item.get("edge_ids"), item.get("penalty_seconds")
                    if (not isinstance(item, dict) or not isinstance(item.get("vehicle_id"), int)
                            or item["vehicle_id"] < 0 or not isinstance(edges, list) or not edges or len(edges) > 2048
                            or not all(isinstance(edge, int) and edge > 0 for edge in edges)
                            or not isinstance(penalty, (int, float)) or not 0 < penalty <= 3600):
                        raise ValueError("path rule requires vehicle_id, 1..2048 edge_ids and penalty_seconds 0..3600")
                    normalized.append({"rule_id": str(item.get("rule_id") or f"path-{uuid.uuid4()}"),
                                       "vehicle_id": item["vehicle_id"], "edge_ids": list(dict.fromkeys(edges)),
                                       "penalty_seconds": float(penalty),
                                       "priority": int(item.get("priority") or 50),
                                       "expires_at": float(item["expires_at"]) if isinstance(item.get("expires_at"), (int, float)) else None,
                                       "enabled": item.get("enabled", True) is True})
                value["path_rules"] = normalized
            if "routing_rules" in patch:
                rules = patch["routing_rules"]
                if not isinstance(rules, list) or len(rules) > 32:
                    raise ValueError("routing_rules must be a list with at most 32 entries")
                normalized = []
                required = ("source_line", "target_line", "source_stop0", "source_stop1",
                            "target_stop0", "target_stop1", "max_assignments")
                for item in rules:
                    entity_kind = str(item.get("entity_kind") or "").upper() if isinstance(item, dict) else ""
                    if (not isinstance(item, dict) or not all(isinstance(item.get(key), int) for key in required)
                            or min(item[key] for key in required) < 0 or item["source_line"] == item["target_line"]
                            or not 1 <= item["max_assignments"] <= 10000 or entity_kind not in {"PERSON", "CARGO"}):
                        raise ValueError("routing rule requires distinct lines, non-negative stop pairs, bounded count and entity_kind")
                    if entity_kind == "CARGO":
                        raise ValueError("cargo routing rules require a native cargo-type verifier and are currently unavailable")
                    normalized.append({"rule_id": str(item.get("rule_id") or f"routing-{uuid.uuid4()}"),
                                       **{key: item[key] for key in required}, "entity_kind": entity_kind,
                                       "cargo_id": 0,
                                       "priority": int(item.get("priority") or 50),
                                       "expires_at": float(item["expires_at"]) if isinstance(item.get("expires_at"), (int, float)) else None,
                                       "enabled": item.get("enabled", True) is True})
                value["routing_rules"] = normalized
            self._config = value
            _atomic_json(self.config_path, value)
            self.events.append({"kind": "CONFIG_UPDATED", "mode": value["mode"], "features": value["features"]})
            if value["mode"] != "ARMED" and self._leases.get("leases"):
                self._disable_native(f"CONFIG_{value['mode']}")
            return self.view()

    def emergency_stop(self, reason: str = "USER_REQUEST") -> dict[str, Any]:
        with self._lock:
            applied = [int(key) for key in self._state.get("applied_timetables", {})]
            self._config["mode"] = "DISABLED"
            _atomic_json(self.config_path, self._config)
            self._disable_native(reason)
            cleared = []
            if self.timetable_clearer:
                for line_id in applied:
                    try:
                        cleared.append({"line_id": line_id, "result": self.timetable_clearer(line_id)})
                    except Exception as exc:  # fail closed and retain evidence
                        cleared.append({"line_id": line_id, "error": str(exc)})
            self._state.update(lifecycle="DISABLED", configured_mode="DISABLED", trip_reason=reason,
                               applied_timetables={}, actions=cleared)
            _atomic_json(self.state_path, self._state)
            self.events.append({"kind": "EMERGENCY_STOP", "reason": reason, "cleared_timetables": cleared})
            return self.view()

    def due(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now - self._last_cycle >= float(self._config["cycle_interval_seconds"])

    def _disable_native(self, reason: str) -> None:
        generation = int(self._leases.get("generation") or 0) + 1
        self.native.write(generation, [])
        self._leases = {"schema_version": 1, "generation": generation, "leases": []}
        _atomic_json(self.lease_path, self._leases)
        self.events.append({"kind": "NATIVE_LEASES_CLEARED", "reason": reason, "generation": generation})

    @staticmethod
    def _health(snapshot: dict[str, Any], manifest: dict[str, Any], live: dict[str, Any],
                heartbeat: dict[str, Any], native_status: dict[str, Any], now: float,
                stale_seconds: float = 45) -> dict[str, Any]:
        save_id = snapshot_save_id(snapshot)
        heartbeat_age = now - float(heartbeat.get("last_update") or 0)
        live_age = now - float(live.get("sampled_at") or 0)
        checks = {
            "bridge_fresh": bool(heartbeat.get("bridge_ready")) and 0 <= heartbeat_age < stale_seconds,
            "save_consistent": manifest.get("save_id") == save_id and live.get("save_id") == save_id,
            "live_fresh": 0 <= live_age < stale_seconds,
            "simulation_running": (live.get("simulation") or {}).get("analysis_allowed") is True,
            "native_loaded": (native_status.get("supervisor_state") == "LOADED"
                              and native_status.get("state") == "ACTIVE"
                              and native_status.get("native_update_pending") is not True),
            "lua_write_enabled": heartbeat.get("allow_write_operations") is True,
        }
        return {"ready_read": all(checks[key] for key in ("bridge_fresh", "save_consistent", "live_fresh", "simulation_running")),
                "ready_native": checks["native_loaded"], "ready_lua_write": checks["lua_write_enabled"],
                "checks": checks, "heartbeat_age_seconds": round(heartbeat_age, 2), "live_age_seconds": round(live_age, 2)}

    @staticmethod
    def _explicit_station_decisions(plan: dict[str, Any], live: dict[str, Any], rules: list[dict[str, Any]],
                                    expires_at: float, now: float) -> list[dict[str, Any]]:
        lines = {item.get("line_id"): item for item in plan.get("lines", [])}
        vehicles = {item.get("entity_id"): item for item in live.get("vehicles", [])}
        result = []
        for rule in rules:
            if not rule.get("enabled") or float(rule.get("expires_at") or expires_at) <= now:
                continue
            vehicle = vehicles.get(rule["vehicle_id"])
            if not vehicle:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "VEHICLE_NOT_LIVE"})
                continue
            if rule.get("line_id") is not None and vehicle.get("line_id") != rule["line_id"]:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "VEHICLE_OR_LINE_MISMATCH"})
                continue
            if vehicle.get("approaching_station") is not True or vehicle.get("arrival_station_terminal_locked") is True:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "NOT_APPROACHING_OR_ALREADY_LOCKED"})
                continue
            line, stop_index = lines.get(vehicle.get("line_id")), vehicle.get("stop_index")
            if rule.get("stop_index") is not None and stop_index != rule["stop_index"]:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "STOP_INDEX_MISMATCH"})
                continue
            if not line or not isinstance(stop_index, int) or not line.get("stops"):
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "PLAN_STOP_UNAVAILABLE"})
                continue
            stop = line["stops"][stop_index % len(line["stops"])]
            option = next((item for item in (stop.get("platform_fit") or {}).get("options", [])
                           if item.get("station_index") == rule["station_index"]
                           and item.get("terminal_index") == rule["terminal_index"]), None)
            if stop.get("station_group_id") != rule["station_group_id"] or not option:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "TARGET_NOT_IN_CURRENT_STOP"})
                continue
            if option.get("fits_longest_assigned_train") is not True:
                result.append({"kind": "station_rejected", "rule_id": rule["rule_id"], "reason": "PLATFORM_FIT_NOT_VERIFIED"})
                continue
            result.append({"kind": "station", "lease_id": rule["rule_id"],
                           "vehicle_id": rule["vehicle_id"], "line_id": vehicle.get("line_id"),
                           "stop_index": stop_index, "station_group_id": rule["station_group_id"],
                           "station_index": rule["station_index"], "terminal_index": rule["terminal_index"],
                           "priority": rule.get("priority", 50),
                           "expires_at": min(expires_at, float(rule.get("expires_at") or expires_at)),
                           "reason": "EXPLICIT_PLATFORM_ASSIGNMENT"})
        return result

    @staticmethod
    def _explicit_path_decisions(network: dict[str, Any], live: dict[str, Any], rules: list[dict[str, Any]],
                                 expires_at: float, now: float) -> list[dict[str, Any]]:
        vehicles = {item.get("entity_id") for item in live.get("vehicles", [])}
        edges = {item.get("entity_id") for item in network.get("edges", [])}
        result = []
        for rule in rules:
            if not rule.get("enabled") or float(rule.get("expires_at") or expires_at) <= now:
                continue
            if rule["vehicle_id"] not in vehicles:
                result.append({"kind": "path_rejected", "rule_id": rule["rule_id"], "reason": "VEHICLE_NOT_LIVE"})
                continue
            missing = [edge for edge in rule["edge_ids"] if edge not in edges]
            if missing:
                result.append({"kind": "path_rejected", "rule_id": rule["rule_id"],
                               "reason": "EDGE_NOT_IN_NETWORK", "edge_ids": missing[:20]})
                continue
            result.append({"kind": "path", "lease_id": rule["rule_id"], "vehicle_id": rule["vehicle_id"],
                           "penalty_seconds": rule["penalty_seconds"], "edge_ids": rule["edge_ids"],
                           "priority": rule.get("priority", 50),
                           "expires_at": min(expires_at, float(rule.get("expires_at") or expires_at)),
                           "reason": "EXPLICIT_PATH_COST"})
        return result

    @staticmethod
    def _explicit_routing_decisions(plan: dict[str, Any], rules: list[dict[str, Any]],
                                    expires_at: float, now: float) -> list[dict[str, Any]]:
        lines = {item.get("line_id"): item for item in plan.get("lines", [])}
        result = []
        for rule in rules:
            if not rule.get("enabled") or float(rule.get("expires_at") or expires_at) <= now:
                continue
            if rule.get("entity_kind") != "PERSON":
                result.append({"kind": "routing_rejected", "rule_id": rule["rule_id"],
                               "reason": "CARGO_TYPE_FILTER_UNAVAILABLE"})
                continue
            source, target = lines.get(rule["source_line"]), lines.get(rule["target_line"])
            try:
                source_pair = [source["stops"][rule["source_stop0"]]["station_group_id"],
                               source["stops"][rule["source_stop1"]]["station_group_id"]]
                target_pair = [target["stops"][rule["target_stop0"]]["station_group_id"],
                               target["stops"][rule["target_stop1"]]["station_group_id"]]
            except (TypeError, KeyError, IndexError):
                result.append({"kind": "routing_rejected", "rule_id": rule["rule_id"], "reason": "LINE_OR_STOP_UNAVAILABLE"})
                continue
            if source_pair != target_pair:
                result.append({"kind": "routing_rejected", "rule_id": rule["rule_id"],
                               "reason": "OD_DIRECTION_OR_STATION_MISMATCH",
                               "source_station_pair": source_pair, "target_station_pair": target_pair})
                continue
            result.append({"kind": "routing", "lease_id": rule["rule_id"],
                           **{key: rule[key] for key in ("source_line", "target_line", "source_stop0", "source_stop1",
                                                        "target_stop0", "target_stop1", "max_assignments")},
                           "entity_kind": "PERSON", "cargo_id": 0, "shared_station_pair": source_pair,
                           "priority": rule.get("priority", 50),
                           "expires_at": min(expires_at, float(rule.get("expires_at") or expires_at)),
                           "reason": "EXPLICIT_OD_REASSIGNMENT"})
        return result

    @staticmethod
    def _station_decisions(plan: dict[str, Any], live: dict[str, Any], expires_at: float) -> list[dict[str, Any]]:
        line_by_id = {int(item["line_id"]): item for item in plan.get("lines", []) if isinstance(item.get("line_id"), int)}
        occupancy: dict[tuple[int, int, int], int] = {}
        for vehicle in live.get("vehicles", []):
            station_index, terminal = vehicle.get("arrival_station_index"), vehicle.get("arrival_terminal_index")
            line, stop_index = line_by_id.get(vehicle.get("line_id")), vehicle.get("stop_index")
            if isinstance(station_index, int) and isinstance(terminal, int) and line and isinstance(stop_index, int) and line.get("stops"):
                station_group = line["stops"][stop_index % len(line["stops"])].get("station_group_id")
                if isinstance(station_group, int):
                    key = (station_group, station_index, terminal)
                    occupancy[key] = occupancy.get(key, 0) + 1
        decisions = []
        for vehicle in live.get("vehicles", []):
            if vehicle.get("approaching_station") is not True or vehicle.get("arrival_station_terminal_locked") is True:
                continue
            line = line_by_id.get(vehicle.get("line_id"))
            stop_index = vehicle.get("stop_index")
            if not line or not isinstance(stop_index, int) or not line.get("stops"):
                continue
            stop = line["stops"][stop_index % len(line["stops"])]
            station_group = stop.get("station_group_id")
            fit = (stop.get("platform_fit") or {}).get("options", [])
            candidates = [item for item in fit if isinstance(item.get("station_index"), int)
                          and isinstance(item.get("terminal_index"), int)
                          and item.get("fits_longest_assigned_train") is True]
            if not candidates:
                continue
            selected = min(candidates, key=lambda item: (occupancy.get((station_group, item["station_index"], item["terminal_index"]), 0),
                                                         not item.get("primary", False), item["terminal_index"]))
            decisions.append({"kind": "station", "lease_id": f"station:{vehicle['entity_id']}:{stop_index}",
                              "vehicle_id": int(vehicle["entity_id"]), "line_id": int(vehicle["line_id"]),
                              "stop_index": stop_index, "station_group_id": station_group, "station_index": int(selected["station_index"]),
                              "terminal_index": int(selected["terminal_index"]), "expires_at": expires_at,
                              "reason": "MINIMUM_RESERVED_OCCUPANCY_THEN_PRIMARY"})
            key = (station_group, selected["station_index"], selected["terminal_index"])
            occupancy[key] = occupancy.get(key, 0) + 1
        return decisions

    @staticmethod
    def _routing_decisions(plan: dict[str, Any], expires_at: float) -> list[dict[str, Any]]:
        result = []
        for diagnostic in plan.get("parallel_service_diagnostics", []):
            if diagnostic.get("status") != "OBSERVED_PARALLEL_OD_IMBALANCE":
                continue
            source = max(diagnostic.get("lines", []), key=lambda item: item.get("demand_share", 0), default=None)
            allocations = (diagnostic.get("proposed_adjustment") or {}).get("allocations", [])
            target = next((item for item in allocations if item.get("assigned", 0) > 0 and source and item.get("line_id") != source.get("line_id")), None)
            source_pair = (source or {}).get("source_stop_pair")
            target_line = next((item for item in diagnostic.get("lines", []) if target and item.get("line_id") == target.get("line_id")), None)
            target_pair = (target_line or {}).get("source_stop_pair")
            if not source or not target or not (isinstance(source_pair, list) and len(source_pair) == 2) or not (isinstance(target_pair, list) and len(target_pair) == 2):
                continue
            cargo_id = diagnostic.get("cargo_id", 0)
            if cargo_id != 0:
                result.append({"kind": "routing_rejected",
                               "rule_id": f"routing:{source['line_id']}:{source_pair[0]}:{source_pair[1]}:{target['line_id']}",
                               "reason": "CARGO_TYPE_FILTER_UNAVAILABLE", "cargo_id": cargo_id})
                continue
            result.append({"kind": "routing", "lease_id": f"routing:{source['line_id']}:{source_pair[0]}:{source_pair[1]}:{target['line_id']}",
                           "source_line": int(source["line_id"]), "target_line": int(target["line_id"]),
                           "source_stop0": int(source_pair[0]), "source_stop1": int(source_pair[1]),
                           "target_stop0": int(target_pair[0]), "target_stop1": int(target_pair[1]),
                           "source_waiting": int(source.get("waiting") or 0),
                           "target_waiting": int((target_line or {}).get("waiting") or 0),
                           "shared_station_pair": diagnostic.get("shared_station_pair"),
                           "cargo_id": 0, "entity_kind": "PERSON",
                           "max_assignments": min(10000, int(target["assigned"])), "expires_at": expires_at,
                           "reason": "MAX_AVAILABLE_CAPACITY_FIRST"})
        return result

    def _speed_decisions(self, snapshot: dict[str, Any], network: dict[str, Any], expires_at: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        vehicles = {int(item["entity_id"]): item for item in snapshot.get("vehicles", []) if isinstance(item.get("entity_id"), int)}
        edges = {int(item["entity_id"]): item for item in network.get("edges", []) if isinstance(item.get("entity_id"), int)}
        leases, rejected = [], []
        for rule in self._config.get("speed_rules", []):
            if not rule.get("enabled"):
                continue
            rule_expiry = rule.get("expires_at")
            if isinstance(rule_expiry, (int, float)) and rule_expiry <= time.time():
                rejected.append({"kind": "speed_rejected", "rule_id": rule["rule_id"], "reason": "RULE_EXPIRED"})
                continue
            vehicle = vehicles.get(rule["vehicle_id"])
            if not vehicle or vehicle.get("line_id") != rule["line_id"]:
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": "VEHICLE_OR_LINE_MISMATCH"})
                continue
            try:
                zone = map_chainage_zone(network, rule["line_id"], rule["start_km"], rule["end_km"],
                                         rule["speed_kmh"], rule["vehicle_id"], rule["direction"])
            except ValueError as exc:
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": str(exc)})
                continue
            vehicle_limit = vehicle.get("consist_top_speed_kmh")
            infrastructure = [float(edges[edge].get("speed_limit_mps")) * 3.6 for edge in zone["edge_ids"]
                              if edge in edges and isinstance(edges[edge].get("speed_limit_mps"), (int, float))]
            if ((isinstance(vehicle_limit, (int, float)) and rule["speed_kmh"] >= float(vehicle_limit))
                    or (infrastructure and rule["speed_kmh"] >= min(infrastructure))):
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": "LIMIT_NOT_BELOW_VEHICLE_AND_INFRASTRUCTURE"})
                continue
            leases.append({"kind": "speed", "lease_id": rule["rule_id"], "vehicle_id": rule["vehicle_id"],
                           "line_id": rule["line_id"], "speed_mps": zone["speed_mps"], "speed_kmh": rule["speed_kmh"],
                           "priority": rule.get("priority", 50),
                           "edge_ids": zone["edge_ids"],
                           "expires_at": min(expires_at, rule_expiry or expires_at), "reason": "VALIDATED_CHAINAGE_RULE"})
        for rule in self._config.get("edge_speed_rules", []):
            if not rule.get("enabled"):
                continue
            if rule.get("hold") is True:
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"],
                                 "reason": "NATIVE_ZERO_STOP_UNVERIFIED_USE_OFFICIAL_USER_STOP"})
                continue
            vehicle = vehicles.get(rule["vehicle_id"])
            if not vehicle or (rule.get("line_id") is not None and vehicle.get("line_id") != rule["line_id"]):
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": "VEHICLE_OR_LINE_MISMATCH"})
                continue
            rule_expiry = rule.get("expires_at")
            if isinstance(rule_expiry, (int, float)) and rule_expiry <= time.time():
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": "RULE_EXPIRED"})
                continue
            missing = [edge for edge in rule["edge_ids"] if edge not in edges]
            if missing:
                rejected.append({"kind": "speed", "rule_id": rule["rule_id"], "reason": "EDGE_NOT_IN_NETWORK",
                                 "edge_ids": missing[:20]})
                continue
            leases.append({"kind": "speed", "lease_id": rule["rule_id"], "vehicle_id": rule["vehicle_id"],
                           "line_id": rule.get("line_id"), "speed_mps": round(rule["speed_kmh"] / 3.6, 6),
                           "speed_kmh": rule["speed_kmh"], "hold": rule.get("hold") is True,
                           "priority": rule.get("priority", 50),
                           "edge_ids": rule["edge_ids"], "expires_at": min(expires_at, rule_expiry or expires_at),
                           "reason": "PROTECTIVE_EDGE_STOP" if rule.get("hold") else "VALIDATED_EDGE_SPEED_RULE"})
        return leases, rejected

    def _path_decisions(self, live: dict[str, Any], expires_at: float) -> list[dict[str, Any]]:
        """Penalize occupied blocks while the native pathfinder chooses an approach.

        The native hook changes only the A* cost. The game still generates and
        validates the path, so direction, signals, terminal reachability and
        vehicle compatibility remain authoritative.
        """
        occupied: dict[int, set[int]] = {}
        for block in live.get("path_blocks", live.get("blocks", [])):
            vehicles = {int(value) for value in block.get("occupied_vehicle_ids", [])
                        if isinstance(value, int)}
            if not vehicles:
                continue
            for edge_id in block.get("edge_ids", []):
                if isinstance(edge_id, int) and edge_id > 0:
                    occupied.setdefault(edge_id, set()).update(vehicles)
        result = []
        penalty = float(self._config.get("path_penalty_seconds") or 300)
        for vehicle in live.get("vehicles", []):
            vehicle_id = vehicle.get("entity_id")
            if not isinstance(vehicle_id, int) or vehicle_id <= 0 or vehicle.get("approaching_station") is not True:
                continue
            penalized = sorted(edge_id for edge_id, occupants in occupied.items()
                               if any(other != vehicle_id for other in occupants))
            if not penalized:
                continue
            result.append({"kind": "path", "lease_id": f"path:{vehicle_id}",
                           "vehicle_id": vehicle_id, "penalty_seconds": penalty,
                           "edge_ids": penalized, "expires_at": expires_at,
                           "reason": "OCCUPIED_BLOCK_COST_PENALTY"})
        return result

    def cycle(self, snapshot: dict[str, Any], manifest: dict[str, Any], network: dict[str, Any],
              live: dict[str, Any], heartbeat: dict[str, Any], native_status: dict[str, Any],
              plan: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            if now - self._last_cycle < float(self._config["cycle_interval_seconds"]):
                return self.view(10)
            self._last_cycle = now
            expired_rule_ids = []
            for collection in ("speed_rules", "edge_speed_rules", "station_rules", "path_rules", "routing_rules"):
                retained = []
                for rule in self._config.get(collection, []):
                    expiry = rule.get("expires_at")
                    if isinstance(expiry, (int, float)) and expiry <= now:
                        expired_rule_ids.append(rule.get("rule_id"))
                    else:
                        retained.append(rule)
                self._config[collection] = retained
            if expired_rule_ids:
                _atomic_json(self.config_path, self._config)
                self.events.append({"kind": "COMMAND_RULES_EXPIRED", "rule_ids": expired_rule_ids})
            mode = self._config["mode"]
            save_id = snapshot_save_id(snapshot)
            health = self._health(snapshot, manifest, live, heartbeat, native_status, now,
                                  float(self._config.get("health_stale_seconds") or 45))
            decisions, actions = [], []
            verification_faults: list[str] = []
            live_by_id = {int(item["entity_id"]): item for item in live.get("vehicles", [])
                          if isinstance(item.get("entity_id"), int)}
            for lease in self._leases.get("leases", []):
                vehicle = live_by_id.get(lease.get("vehicle_id"))
                if lease.get("kind") == "station" and vehicle:
                    matched = (vehicle.get("arrival_station_terminal_locked") is True
                               and vehicle.get("arrival_station_index") == lease.get("station_index")
                               and vehicle.get("arrival_terminal_index") == lease.get("terminal_index"))
                    if matched:
                        actions.append({"kind": "STATION_ASSIGNMENT_VERIFIED", "lease_id": lease.get("lease_id"),
                                        "vehicle_id": lease.get("vehicle_id")})
                    elif float(lease.get("expires_at") or 0) <= now:
                        actions.append({"kind": "STATION_ASSIGNMENT_EXPIRED_DEFAULT_FALLBACK", "lease_id": lease.get("lease_id"),
                                        "vehicle_id": lease.get("vehicle_id")})
                elif lease.get("kind") == "speed" and vehicle and vehicle.get("edge_id") in set(lease.get("edge_ids", [])):
                    observed = vehicle.get("speed_kmh")
                    if isinstance(observed, (int, float)):
                        actions.append({"kind": "SPEED_ZONE_OBSERVED", "lease_id": lease.get("lease_id"),
                                        "vehicle_id": lease.get("vehicle_id"), "speed_kmh": observed,
                                        "within_limit": observed <= float(lease.get("speed_kmh") or 0) + 1.0})
                        if observed > float(lease.get("speed_kmh") or 0) + 3.0:
                            verification_faults.append(f"speed lease {lease.get('lease_id')} exceeded its limit")
                elif lease.get("kind") == "routing":
                    diagnostic = next((item for item in plan.get("parallel_service_diagnostics", [])
                                       if item.get("shared_station_pair") == lease.get("shared_station_pair")
                                       and item.get("cargo_id", 0) == lease.get("cargo_id")), None)
                    if diagnostic:
                        lines = {item.get("line_id"): item for item in diagnostic.get("lines", [])}
                        source = lines.get(lease.get("source_line"), {})
                        target = lines.get(lease.get("target_line"), {})
                        source_waiting = int(source.get("waiting") or 0)
                        target_waiting = int(target.get("waiting") or 0)
                        actions.append({"kind": "OD_WAITING_DISTRIBUTION_OBSERVED", "lease_id": lease.get("lease_id"),
                                        "source_waiting_delta": source_waiting - int(lease.get("source_waiting") or 0),
                                        "target_waiting_delta": target_waiting - int(lease.get("target_waiting") or 0),
                                        "source_waiting": source_waiting, "target_waiting": target_waiting})
                    age = now - float(lease.get("created_at") or now)
                    attempts_delta = int(native_status.get("routing_attempts") or 0) - int(lease.get("routing_attempts_start") or 0)
                    successes_delta = int(native_status.get("routing_successes") or 0) - int(lease.get("routing_successes_start") or 0)
                    if age >= min(30.0, float(self._config["lease_seconds"]) * .5) and attempts_delta >= 20 and successes_delta <= 0:
                        verification_faults.append(f"routing lease {lease.get('lease_id')} produced no successful reassignment")
            previous_routing_successes = int((self._state.get("native_counters") or {}).get("routing_successes") or 0)
            observed_routing_successes = int(native_status.get("routing_successes") or 0)
            if observed_routing_successes > previous_routing_successes:
                actions.append({"kind": "OD_REASSIGNMENT_NATIVE_VERIFIED",
                                "success_delta": observed_routing_successes - previous_routing_successes,
                                "success_total": observed_routing_successes})
            if mode == "DISABLED":
                lifecycle = "DISABLED"
                if self._leases.get("leases"):
                    self._disable_native("DISABLED_CYCLE")
            elif not health["ready_read"]:
                lifecycle = "DEGRADED"
            elif int(self._state.get("consecutive_failures") or 0) >= int(self._config["failure_trip_count"]):
                lifecycle = "TRIPPED"
            else:
                lifecycle = mode

            expires_at = now + float(self._config["lease_seconds"])
            features = self._config["features"]
            if mode in {"SHADOW", "ARMED"} and health["ready_read"] and plan.get("save_id") == save_id:
                decisions.extend(self._explicit_routing_decisions(
                    plan, self._config.get("routing_rules", []), expires_at, now))
                decisions.extend(self._explicit_station_decisions(
                    plan, live, self._config.get("station_rules", []), expires_at, now))
                decisions.extend(self._explicit_path_decisions(
                    network, live, self._config.get("path_rules", []), expires_at, now))
                if features.get("routing"):
                    decisions.extend(self._routing_decisions(plan, expires_at))
                if features.get("station"):
                    decisions.extend(self._station_decisions(plan, live, expires_at))
                if features.get("speed") or self._config.get("speed_rules") or self._config.get("edge_speed_rules"):
                    speed, rejected = self._speed_decisions(snapshot, network, expires_at)
                    decisions.extend(speed); decisions.extend(rejected)
                    if features.get("speed") and self._config.get("automatic_infrastructure_speed_limits"):
                        policy = self._config.get("infrastructure_speed_policy") or {}
                        profile = build_infrastructure_speed_profile(
                            network, policy.get("overrides"), float(policy.get("default_side_kmh") or 45),
                            float(policy.get("platform_kmh") or 45))
                        remaining = max(0, 256 - len(speed))
                        decisions.extend(compile_vehicle_speed_leases(profile, network, live, expires_at, remaining))
                if features.get("spacing"):
                    spacing_policy = self._config.get("spacing_policy") or {}
                    decisions.extend(compile_train_spacing(
                        network, live, expires_at, spacing_policy,
                        publishable=(mode == "ARMED" and spacing_policy.get("armed_execution") is True), now=now))
                if features.get("path"):
                    decisions.extend(self._path_decisions(live, expires_at))
                if features.get("timetable"):
                    for line in plan.get("lines", []):
                        decisions.append({"kind": "timetable", "line_id": line["line_id"],
                                          "fingerprint": _fingerprint({key: line.get(key) for key in ("cycle_seconds", "epoch_game_time_ms", "late_release_seconds", "priority", "stops")}),
                                          "plan": line})
                if features.get("fleet"):
                    for line in plan.get("lines", []):
                        action = (line.get("fleet_policy") or {}).get("action_plan")
                        if action:
                            decisions.append({"kind": "fleet", "line_id": line["line_id"], "action_plan": action, "plan": line})

            try:
                if lifecycle == "ARMED":
                    if verification_faults:
                        raise RuntimeError("; ".join(verification_faults))
                    execution_count = 0
                    native_decisions = [
                        item for item in decisions
                        if item.get("kind") in {"routing", "station", "speed", "path"}
                        and isinstance(item.get("lease_id"), str)
                    ]
                    native_decisions.sort(key=lambda item: (-int(item.get("priority") or 0), str(item["lease_id"])))
                    native_features_active = (any(features.get(name) for name in ("routing", "station", "speed", "path"))
                                              or (features.get("spacing") and
                                                  (self._config.get("spacing_policy") or {}).get("armed_execution") is True)
                                              or any(self._config.get(name) for name in
                                                     ("routing_rules", "station_rules", "speed_rules", "edge_speed_rules", "path_rules")))
                    if native_features_active and not health["ready_native"]:
                        raise RuntimeError("native control module is not active")
                    previous_by_id = {item.get("lease_id"): item for item in self._leases.get("leases", [])}
                    for item in native_decisions:
                        previous = previous_by_id.get(item.get("lease_id"), {})
                        item["created_at"] = float(previous.get("created_at") or now)
                        if item.get("kind") == "routing":
                            item["routing_attempts_start"] = int(previous.get("routing_attempts_start")
                                                                 if "routing_attempts_start" in previous
                                                                 else native_status.get("routing_attempts") or 0)
                            item["routing_successes_start"] = int(previous.get("routing_successes_start")
                                                                  if "routing_successes_start" in previous
                                                                  else native_status.get("routing_successes") or 0)
                    generation = int(self._leases.get("generation") or 0) + 1
                    active = self.native.write(generation, native_decisions, now)
                    self._leases = {"schema_version": 1, "generation": generation, "leases": active}
                    _atomic_json(self.lease_path, self._leases)
                    if native_decisions:
                        actions.append({"kind": "NATIVE_LEASES_PUBLISHED", "count": len(active), "generation": generation})
                    if features.get("timetable"):
                        if not health["ready_lua_write"]:
                            raise RuntimeError("Lua write operations are disabled")
                        allowed = set(heartbeat.get("allowed_operations") or [])
                        if "APPLY_LINE_TIMETABLE" not in allowed:
                            raise RuntimeError("APPLY_LINE_TIMETABLE is not allowed by the active Mod")
                        applied = self._state.setdefault("applied_timetables", {})
                        for item in (value for value in decisions if value.get("kind") == "timetable"):
                            key = str(item["line_id"])
                            existing = applied.get(key)
                            if (isinstance(existing, dict) and existing.get("fingerprint") == item["fingerprint"]
                                    and float(existing.get("expires_at") or 0) > now + float(self._config["lease_seconds"]) * .4):
                                continue
                            if execution_count >= int(self._config["max_actions_per_cycle"]):
                                break
                            if not self.timetable_executor:
                                raise RuntimeError("timetable executor unavailable")
                            leased_plan = {**item["plan"], "control_lease_expires_at": expires_at}
                            result = self.timetable_executor(leased_plan)
                            if not result.get("accepted"):
                                raise RuntimeError(f"timetable rejected for line {item['line_id']}: {result}")
                            applied[key] = {"fingerprint": item["fingerprint"], "expires_at": expires_at}
                            actions.append({"kind": "TIMETABLE_APPLIED", "line_id": item["line_id"], "result": result})
                            execution_count += 1
                    if features.get("fleet") and execution_count < int(self._config["max_actions_per_cycle"]):
                        if not health["ready_lua_write"]:
                            raise RuntimeError("Lua write operations are disabled")
                        for item in (value for value in decisions if value.get("kind") == "fleet"):
                            cooldown_key = f"fleet:{item['line_id']}"
                            if now < float(self._state.get("cooldowns", {}).get(cooldown_key) or 0):
                                continue
                            if not self.fleet_executor:
                                raise RuntimeError("fleet executor unavailable")
                            result = self.fleet_executor(item["action_plan"], item["plan"])
                            actions.append({"kind": "FLEET_ACTION", "line_id": item["line_id"], "result": result})
                            execution_count += 1
                            if result.get("status") not in {"COMPLETED", "POSTCONDITION_VERIFIED", "COMPENSATED_FAIL_CLOSED"}:
                                raise RuntimeError(f"fleet action failed: {result}")
                            self._state.setdefault("cooldowns", {})[cooldown_key] = now + float(self._config["fleet_cooldown_seconds"])
                            break
                    self._state["consecutive_failures"] = 0
                    self._state["last_success_at"] = now
                elif lifecycle in {"DISABLED", "SHADOW", "DEGRADED", "TRIPPED"}:
                    if self._leases.get("leases"):
                        self._disable_native(lifecycle)
                self._state["trip_reason"] = None if lifecycle not in {"DEGRADED", "TRIPPED"} else self._state.get("trip_reason")
            except Exception as exc:
                failures = int(self._state.get("consecutive_failures") or 0) + 1
                self._state["consecutive_failures"] = failures
                self._state["trip_reason"] = str(exc)
                lifecycle = "TRIPPED" if failures >= int(self._config["failure_trip_count"]) else "DEGRADED"
                self._disable_native(f"CONTROL_FAILURE:{exc}")
                self.events.append({"kind": "CYCLE_FAILED", "save_id": save_id, "reason": str(exc), "consecutive_failures": failures})

            self._state.update(lifecycle=lifecycle, configured_mode=mode, save_id=save_id, last_cycle_at=now,
                               health=health, decisions=[{key: value for key, value in item.items() if key != "plan"} for item in decisions], actions=actions)
            self._state["native_counters"] = {"routing_attempts": int(native_status.get("routing_attempts") or 0),
                                               "routing_successes": observed_routing_successes,
                                               "speed_matches": int(native_status.get("edge_matches") or 0),
                                               "path_edge_matches": int(native_status.get("path_edge_matches") or 0),
                                               "path_penalties": int(native_status.get("path_penalties") or 0)}
            _atomic_json(self.state_path, self._state)
            if actions:
                self.events.append({"kind": "CYCLE_ACTIONS", "save_id": save_id, "lifecycle": lifecycle, "actions": actions})
            return self.view(20)
