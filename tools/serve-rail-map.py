"""Local read-only HTTP/SSE host for the TPF2 railway dispatch map."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient, BridgeError  # noqa: E402
from tpf2_mcp.config import bridge_dir  # noqa: E402
from tpf2_mcp.dispatch import vehicle_dispatch_state  # noqa: E402
from tpf2_mcp.rail_live import RailSpatialIndex, derive_blocks, normalize_live_state, normalize_signals  # noqa: E402
from tpf2_mcp.save_scope import snapshot_save_id  # noqa: E402
from tpf2_mcp.snapshot import SnapshotIndex  # noqa: E402
from tpf2_mcp.station_log import StationEventStore  # noqa: E402
from tpf2_mcp.work_log import McpWorkLogStore  # noqa: E402


TILE_KEY = re.compile(r"^[0-9]+_[0-9]+$")
# One full round trip on this large save can exceed fifteen real minutes.  Keep
# the UI from proposing another consist until the recently added train has had a
# realistic chance to leave its depot and contribute representative demand data.
FLEET_CHANGE_STABILIZATION_SECONDS = 60 * 60
HIGH_SPEED_CONSIST_THRESHOLD_KMH = 250.0
WORK_ACTION_LABELS = {
    "BUY_VEHICLE": "购买车辆",
    "ASSIGN_VEHICLE_TO_LINE": "车辆分配到线路",
    "SET_LINE_STOP_POLICY": "调整停站策略",
    "SET_LINE_STOPS": "调整线路停靠站台",
    "CREATE_LINE": "创建线路",
    "CREATE_LINE_FROM_SOURCE_ROUTE": "创建线路",
    "SELL_VEHICLE": "出售车辆",
    "RENAME_LINE": "重命名线路",
    "HOLD_VEHICLE": "扣停列车",
    "HOLD_VEHICLE_AT_TERMINAL": "扣停列车",
    "RELEASE_VEHICLE": "放行列车",
}


class RailMapState:
    def __init__(self, root: Path, bridge: Path, exporter: Path, live_poll_seconds: float = 1.5):
        self.root = root
        self.bridge = bridge
        self.exporter = exporter
        self.stop = threading.Event()
        self.generation_lock = threading.Lock()
        self.live_lock = threading.Lock()
        self.live_poll_seconds = max(0.5, live_poll_seconds)
        self.last_live_poll = 0.0
        self.last_signal_poll = 0.0
        self.last_snapshot_poll = 0.0
        self.snapshot_poll_seconds = 3.0
        self.active_save_id: str | None = None
        self.save_switch_error: str | None = None
        self.live_error: str | None = None
        self.live_index: RailSpatialIndex | None = None
        self.live_network_mtime = 0
        self.live_control = None
        self.last_bridge_network_mtime = self._mtime(bridge / "rail-network.json")
        self.station_events = StationEventStore(bridge / "station-events.sqlite3")
        state_directory = bridge.parent / "tpf2_mcp_state"
        self.work_log = McpWorkLogStore(state_directory / "mcp-work-log.sqlite3")
        self.task_journal = state_directory / "tasks.jsonl"

    def _plan_path(self) -> Path:
        return self.root.parents[1] / "diagnostics" / "rail-operations" / "line-timetable-plan.json"

    def current_save_id(self) -> str:
        return snapshot_save_id(self.read_json(self.bridge / "state.json"))

    @staticmethod
    def _mtime(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    @staticmethod
    def read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def status(self) -> dict:
        heartbeat = self.read_json(self.bridge / "heartbeat.json")
        state = self.read_json(self.bridge / "state.json")
        manifest = self.read_json(self.root / "rail-network-manifest.json")
        save_id = self.current_save_id()
        telemetry = self.read_json(self.bridge / "operational-telemetry.json")
        live = self.read_json(self.bridge / "live-rail-state.json")
        age = max(0.0, time.time() - float(heartbeat.get("last_update", 0))) if heartbeat else None
        return {
            "bridge_connected": bool(heartbeat.get("bridge_ready")) and age is not None and age < 10,
            "heartbeat_age_seconds": round(age, 2) if age is not None else None,
            "snapshot_sequence": state.get("sequence") or heartbeat.get("snapshot_seq"),
            "snapshot_timestamp": state.get("timestamp"),
            "rail_generation": manifest.get("generated_at"),
            "save_id": save_id,
            "rail_save_id": manifest.get("save_id"),
            "save_transition": manifest.get("save_id") != save_id,
            "save_switch_error": self.save_switch_error,
            "rail_counts": manifest.get("counts"),
            "telemetry_generation": telemetry.get("generated_at"),
            "telemetry_counts": telemetry.get("counts"),
            "live_generation": live.get("sampled_at"),
            "live_counts": live.get("counts"),
            "simulation": live.get("simulation"),
            "live_error": self.live_error,
        }

    def operations_context(self) -> dict:
        """Return the compact operational subset needed by the station detail panel."""
        state = self.read_json(self.bridge / "state.json")
        plan = self.read_json(self._plan_path())
        save_id = snapshot_save_id(state)
        if plan.get("save_id") != save_id:
            plan = {}
        plan_by_line = {item.get("line_id"): item for item in plan.get("lines", [])}
        active_passenger_vehicles_by_line: dict[int, dict[str, int | float]] = {}
        for vehicle in state.get("vehicles", []):
            line_id = vehicle.get("line_id")
            if not isinstance(line_id, int) or isinstance(line_id, bool) or vehicle.get("raw_state") not in (1, 2):
                continue
            capacities = vehicle.get("capacity_by_cargo", [])
            carries_passengers = any(
                isinstance(item, dict)
                and item.get("cargo_id") == 0
                and isinstance(item.get("capacity"), (int, float))
                and item.get("capacity") > 0
                for item in capacities
            )
            if not carries_passengers:
                carries_passengers = 0 in vehicle.get("supported_cargo_ids", [])
            if not carries_passengers:
                continue
            profile = active_passenger_vehicles_by_line.setdefault(line_id, {
                "total": 0,
                "high_speed": 0,
                "conventional": 0,
                "unknown_speed": 0,
                "threshold_kmh": HIGH_SPEED_CONSIST_THRESHOLD_KMH,
            })
            profile["total"] += 1
            top_speed = vehicle.get("consist_top_speed_kmh")
            if not isinstance(top_speed, (int, float)):
                profile["unknown_speed"] += 1
            elif top_speed >= HIGH_SPEED_CONSIST_THRESHOLD_KMH - 0.5:
                # Engine values can contain small floating-point conversion noise
                # around an exact 250 km/h vehicle definition.
                profile["high_speed"] += 1
            else:
                profile["conventional"] += 1
        lines = []
        for line in state.get("lines", []):
            line_id = line.get("entity_id")
            timetable = plan_by_line.get(line_id, {})
            timetable_stops = {item.get("stop_index"): item for item in timetable.get("stops", [])}
            stops = []
            for stop in line.get("raw_stops", line.get("stops", [])):
                index = stop.get("sequence_index", stop.get("index"))
                scheduled = timetable_stops.get(index, {})
                stops.append({
                    "sequence_index": index,
                    "station_id": stop.get("station_id"),
                    "station_index": stop.get("station_index"),
                    "terminal_id": stop.get("terminal_id"),
                    "alternative_terminals": stop.get("alternative_terminals", []),
                    "policy": stop.get("policy", {}),
                    "scheduled_dwell_seconds": scheduled.get("scheduled_dwell_seconds"),
                    "arrival_offset_seconds": scheduled.get("arrival_offset_seconds"),
                    "departure_offset_seconds": scheduled.get("departure_offset_seconds"),
                })
            lines.append({
                "line_id": line_id,
                "name": line.get("name"),
                "frequency_seconds": line.get("frequency_seconds"),
                "vehicle_count": timetable.get("vehicle_count"),
                "headway_seconds": timetable.get("headway_seconds"),
                "active_passenger_vehicles": active_passenger_vehicles_by_line.get(line_id, {
                    "total": 0,
                    "high_speed": 0,
                    "conventional": 0,
                    "unknown_speed": 0,
                    "threshold_kmh": HIGH_SPEED_CONSIST_THRESHOLD_KMH,
                }),
                "stops": stops,
            })
        return {
            "schema_version": 1,
            "source_status": "ENGINE_SNAPSHOT_WITH_DERIVED_TIMETABLE",
            "snapshot_sequence": state.get("sequence"),
            "save_id": save_id,
            "lines": lines,
        }

    def vehicle_detail(self, vehicle_id: int) -> dict:
        """Compose one click-oriented vehicle view from cached motion and a bounded Bridge demand probe."""
        state = self.read_json(self.bridge / "state.json")
        index = SnapshotIndex(state)
        vehicle = index.vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            return {"error": "vehicle not found", "vehicle_id": vehicle_id}
        live_frame = self.read_json(self.bridge / "live-rail-state.json")
        live = next((item for item in live_frame.get("vehicles", []) if item.get("entity_id") == vehicle_id), None)
        line_id = (live or {}).get("line_id") if isinstance((live or {}).get("line_id"), int) else vehicle.get("line_id")
        demand = None
        if isinstance(line_id, int):
            demand = BridgeClient(self.bridge, timeout_seconds=12, poll_seconds=.04).line_demand(line_id, 50000)
        return vehicle_dispatch_state(index, vehicle_id, live, demand)

    def ai_suggestions(self) -> dict:
        """Render bounded, evidence-backed templates only for work MCP cannot finish autonomously."""
        plan_path = self._plan_path()
        plan = self.read_json(plan_path)
        save_id = self.current_save_id()
        if plan.get("save_id") != save_id:
            return {
                "schema_version": 2, "save_id": save_id, "policy": "Observation only; stale plans from another save are hidden.",
                "generated_at": time.time(), "suggestions": [], "total": 0, "stale_plan_hidden": bool(plan),
                "templates": {"PARALLEL_LINE_IMBALANCE": "并行线路分配失衡"},
            }
        generated_at = plan_path.stat().st_mtime if plan_path.exists() else time.time()
        now = time.time()
        recent_fleet_changes = {
            item.get("line_id")
            for item in self.work_log.query(save_id, 500)
            if item.get("applied")
            and item.get("action_type") in {
                "EXPAND_LINE_WITH_VEHICLE", "ASSIGN_VEHICLE_TO_LINE", "FLEET_EXPANSION_ROLLED_BACK",
            }
            and isinstance(item.get("line_id"), int)
            and now - float(item.get("occurred_at") or 0) < FLEET_CHANGE_STABILIZATION_SECONDS
        }
        suggestions = []
        for line in plan.get("lines", []):
            line_id, name = line.get("line_id"), line.get("line_name") or f"线路 {line.get('line_id')}"
            fleet = line.get("fleet_policy") or {}
            # Historic demand samples remain high immediately after a verified fleet
            # change.  Suppress another add proposal until the new service has had a
            # bounded period to circulate and produce representative samples.
            if fleet.get("decision") == "ADD_ONE_PROPOSAL" and line_id not in recent_fleet_changes:
                eligible = fleet.get("execution_eligibility") == "PROPOSAL_READY"
                suggestions.append({
                    "created_at": generated_at,
                    "template": "ADD_TRAIN", "template_label": "加车建议", "severity": "ACTION" if eligible else "BLOCKED",
                    "line_id": line_id, "line_name": name,
                    "title": f"{name} 建议加车 1 组" if eligible else f"{name} 加车被编组约束阻止",
                    "reason": f"候车 {((line.get('demand') or {}).get('waiting') or 0)}，连续样本 {((line.get('demand') or {}).get('sample_count') or 0)}",
                    "required_action": "需要批准受控购车任务" if eligible else "先解决编组速度、货物兼容性或站台长度硬约束",
                    "automation_status": "REQUIRES_APPROVAL" if eligible else "REQUIRES_MANUAL_FLEET_CORRECTION",
                })
            platform = line.get("platform_feasibility") or {}
            if platform.get("status") == "TOO_SHORT":
                bad = [stop for stop in line.get("stops", []) if (stop.get("platform_fit") or {}).get("status") == "TOO_SHORT"]
                affected = []
                for stop in bad:
                    fit = stop.get("platform_fit") or {}
                    short = [option for option in fit.get("options", []) if option.get("fits_longest_assigned_train") is False]
                    affected.append({"station_name": stop.get("station_name"), "train_length_m": fit.get("train_length_m"),
                                     "short_platform_lengths_m": sorted({option.get("platform_length_m") for option in short if option.get("platform_length_m") is not None})})
                detail = "；".join(f"{item.get('station_name') or '未知车站'} 站台 {','.join(str(value) for value in item['short_platform_lengths_m']) or 'UNKNOWN'} m" for item in affected[:4])
                suggestions.append({
                    "created_at": generated_at,
                    "template": "PLATFORM_TOO_SHORT", "template_label": "站台不足", "severity": "BLOCKED", "line_id": line_id, "line_name": name,
                    "title": f"{name} 存在站台短于列车", "reason": f"最长编组 {platform.get('longest_assigned_train_m')} m；{detail}",
                    "required_action": "人工延长站台，或人工指定经验证足够长的可选站台",
                    "automation_status": "REQUIRES_INFRASTRUCTURE_OR_ROUTE_DECISION", "affected_stops": affected,
                })
            elif platform.get("status") == "UNKNOWN":
                suggestions.append({
                    "created_at": generated_at,
                    "template": "PLATFORM_LENGTH_UNKNOWN", "template_label": "长度待采", "severity": "DATA", "line_id": line_id, "line_name": name,
                    "title": f"{name} 暂不能验证站台长度", "reason": "列车或至少一个可选站台缺少可靠长度",
                    "required_action": "等待长度采集完成；在此之前禁止自动扩编和站台分配",
                    "automation_status": "WAITING_FOR_VERIFIED_DATA",
                })
        for group in plan.get("parallel_service_diagnostics", []):
            if group.get("status") != "OBSERVED_PARALLEL_OD_IMBALANCE":
                continue
            members = sorted(group.get("lines", []), key=lambda item: item.get("demand_share", 0), reverse=True)
            labels = " / ".join(f"{item.get('line_name') or ('线路 ' + str(item.get('line_id')))} {item.get('demand') or 0}（{round((item.get('demand_share') or 0) * 100)}%）" for item in members)
            station_names = group.get("shared_station_names") or group.get("shared_station_pair") or []
            corridor = " ↔ ".join(str(value) for value in station_names)
            demand_kind = group.get("cargo_name") or ("乘客" if group.get("cargo_id") == 0 else f"货物 {group.get('cargo_id')}")
            suggestions.append({
                "created_at": generated_at,
                "template": "PARALLEL_LINE_IMBALANCE", "template_label": "分配失衡", "severity": "REVIEW", "title": f"{corridor} · {demand_kind}分配失衡",
                "reason": labels, "required_action": "仅记录并提交 AI 建议；当前不生成或执行调车、扩编、班次、停站或装卸调整",
                "automation_status": "OBSERVATION_ONLY", "station_pair": group.get("shared_station_pair"),
                "cargo_id": group.get("cargo_id"), "observation_only": True,
            })
        rank = {"BLOCKED": 0, "ACTION": 1, "REVIEW": 2, "DATA": 3}
        suggestions.sort(key=lambda item: (-float(item.get("created_at") or 0), rank.get(item.get("severity"), 9), -(next((line.get("demand", {}).get("waiting", 0) for line in plan.get("lines", []) if line.get("line_id") == item.get("line_id")), 0))))
        return {
            "schema_version": 2, "save_id": save_id,
            "policy": "Only unresolved, approval-gated, infrastructure, or unavailable-capability work appears here. Completed verified actions appear in MCP work log.",
            "templates": {
                "ADD_TRAIN": "线路建议加车", "PLATFORM_TOO_SHORT": "站台长度不足",
                "PLATFORM_LENGTH_UNKNOWN": "长度数据待验证", "PARALLEL_LINE_IMBALANCE": "并行线路分配失衡",
            },
            "generated_at": generated_at, "suggestions": suggestions, "total": len(suggestions),
        }

    def _task_audit_entries(self, save_id: str) -> list[dict]:
        try:
            raw_lines = self.task_journal.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return []
        latest: dict[str, dict] = {}
        for raw in raw_lines:
            try:
                task = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if task.get("save_id") == save_id and isinstance(task.get("task_id"), str):
                latest[task["task_id"]] = task
        entries = []
        for task in latest.values():
            task_status = str(task.get("status") or "UNKNOWN")
            if task_status == "COMPLETED":
                # Verified completed steps are already represented by the
                # durable SQLite entries and must not be shown twice.
                continue
            if task_status in {"BLOCKED", "FAILED", "PARTIALLY_COMPLETED"}:
                category = "BLOCKED"
            elif task_status == "CANCELLED":
                category = "CANCELLED"
            else:
                category = "PENDING"
            steps = task.get("steps") or []
            plans = task.get("planned_steps") or []
            action = (steps[-1] if steps else task.get("next_step") or (plans[0] if plans else {})) or {}
            target = action.get("target") or {}
            goal = task.get("goal") or {}
            line_id = target.get("line_id") if isinstance(target.get("line_id"), int) else goal.get("target_line_id") or goal.get("line_id")
            vehicle_id = target.get("vehicle_id") if isinstance(target.get("vehicle_id"), int) else goal.get("vehicle_id") or goal.get("created_vehicle_id")
            action_type = str(action.get("operation_type") or task.get("goal_type") or "UNKNOWN")
            label = WORK_ACTION_LABELS.get(action_type, action_type.removesuffix("_GOAL"))
            targets = []
            if isinstance(line_id, int):
                targets.append(f"线路 {line_id}")
            if isinstance(vehicle_id, int):
                targets.append(f"车辆 {vehicle_id}")
            result = task.get("result") or {}
            reason = result.get("reason") or result.get("execution_status")
            if not reason:
                reason = {
                    "CREATED": "等待规划",
                    "WAITING_FOR_APPROVAL": "等待批准",
                    "READY": "等待执行",
                    "REPLANNING": "等待重新规划",
                    "CANCELLED": "任务已取消",
                }.get(task_status, task_status)
            timeline = task.get("timeline") or []
            occurred_at = McpWorkLogStore._timestamp((timeline[-1] if timeline else {}).get("at"))
            entries.append({
                "id": f"task:{task['task_id']}",
                "task_id": task["task_id"],
                "save_id": save_id,
                "occurred_at": occurred_at,
                "action_type": action_type,
                "summary": " · ".join([label, *targets]) if targets else label,
                "line_id": line_id if isinstance(line_id, int) else None,
                "vehicle_id": vehicle_id if isinstance(vehicle_id, int) else None,
                "applied": bool((task.get("budget") or {}).get("writes_used")),
                "verification_status": (steps[-1] if steps else {}).get("status") or task_status,
                "task_status": task_status,
                "category": category,
                "reason": str(reason),
            })
        return entries

    def mcp_work_logs(self, limit: int | None = 30) -> dict:
        save_id = self.current_save_id()
        self.work_log.sync_task_journal(self.task_journal, save_id)
        self.work_log.sync_timetable_plan(self._plan_path(), save_id)
        rows = self.work_log.query(save_id, limit)
        for row in rows:
            row["category"] = "EXECUTED" if row.get("applied") else "TEST"
            row["reason"] = row.get("verification_status")
        rows.extend(self._task_audit_entries(save_id))
        rows.sort(key=lambda item: (float(item.get("occurred_at") or 0), str(item.get("id"))), reverse=True)
        if limit is not None:
            rows = rows[:max(1, min(500, int(limit)))]
        status_counts = {key: sum(item.get("category") == key for item in rows) for key in ("EXECUTED", "BLOCKED", "PENDING", "CANCELLED", "TEST")}
        return {"schema_version": 3, "save_id": save_id, "database": str(self.work_log.path), "entries": rows, "count": len(rows), "status_counts": status_counts}

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)

    def refresh_live(self) -> None:
        now = time.time()
        if now - self.last_live_poll < self.live_poll_seconds or not self.live_lock.acquire(blocking=False):
            return
        try:
            heartbeat = self.read_json(self.bridge / "heartbeat.json")
            age = now - float(heartbeat.get("last_update", 0)) if heartbeat else 999
            if not heartbeat.get("bridge_ready") or age >= 10:
                return
            client = BridgeClient(self.bridge, timeout_seconds=8, poll_seconds=.04)
            if now - self.last_signal_poll > 300 or not (self.bridge / "operational-telemetry-signals.json").exists():
                client.operational_telemetry("signals")
                self.last_signal_poll = now
                self.live_control = None
            client.operational_telemetry("vehicles_live")
            vehicle_payload = self.read_json(self.bridge / "operational-telemetry-vehicles_live.json")
            signal_payload = self.read_json(self.bridge / "operational-telemetry-signals.json")
            telemetry = {"vehicles": vehicle_payload.get("vehicles", []), "simulation_clock": vehicle_payload.get("simulation_clock"), "signal_edge_objects": signal_payload.get("signal_edge_objects", []), "track_edge_objects": signal_payload.get("track_edge_objects", [])}
            network = self.read_json(self.bridge / "rail-network.json")
            manifest = self.read_json(self.root / "rail-network-manifest.json")
            if manifest.get("save_id") != self.current_save_id():
                return
            previous = self.read_json(self.bridge / "live-rail-state.json")
            network_mtime = self._mtime(self.bridge / "rail-network.json")
            if self.live_index is None or self.live_network_mtime != network_mtime:
                self.live_index = RailSpatialIndex(network)
                self.live_network_mtime = network_mtime
                self.live_control = None
            if self.live_control is None:
                signals = normalize_signals(telemetry, self.live_index)
                blocks, atoms = derive_blocks(network, signals, self.live_index)
                self.live_control = (signals, blocks, atoms)
                confirmed = sum(signal["source_status"] != "TRACK_OBJECT_CANDIDATE" for signal in signals)
                self.write_json(self.bridge / "rail-control-state.json", {"schema_version": 1, "source_status": "ENGINE_OBSERVED_STATIC_CONTROL", "sampled_at": now, "signals": signals, "blocks": blocks, "counts": {"signal_candidates": len(signals), "confirmed_signals": confirmed, "blocks": len(blocks)}})
            value = normalize_live_state(telemetry, network, manifest, previous, now, spatial_index=self.live_index, control=self.live_control)
            frame = {key: item for key, item in value.items() if key not in {"signals", "blocks"}}
            self.write_json(self.bridge / "live-rail-state.json", frame)
            self.station_events.record_frame(frame, manifest, self.current_save_id())
            self.live_error = None
        except (BridgeError, OSError, ValueError, KeyError, TypeError) as exc:
            self.live_error = str(exc)
        finally:
            self.last_live_poll = now
            self.live_lock.release()

    def refresh_save_scope(self) -> None:
        """Detect an in-game save switch and refresh all save-bound static data."""
        now = time.time()
        if now - self.last_snapshot_poll < self.snapshot_poll_seconds or not self.live_lock.acquire(blocking=False):
            return
        try:
            heartbeat = self.read_json(self.bridge / "heartbeat.json")
            age = now - float(heartbeat.get("last_update", 0)) if heartbeat else 999
            if not heartbeat.get("bridge_ready") or age >= 10:
                return
            # state.json is the mod's continuously refreshed save snapshot.  Save
            # detection must stay file-only: issuing get_game_state every three
            # seconds monopolizes the single Bridge mailbox and starves live vehicle
            # sampling on large saves.
            snapshot = self.read_json(self.bridge / "state.json")
            if not snapshot:
                return
            save_id = snapshot_save_id(snapshot)
            manifest = self.read_json(self.root / "rail-network-manifest.json")
            # A web-server restart must not request and rebuild the entire railway
            # network when the on-disk manifest already belongs to this save.  The
            # old condition also required active_save_id, which is necessarily None
            # after restart and could hold live polling behind a very expensive
            # get_rail_network call for minutes.
            if manifest.get("save_id") == save_id:
                self.active_save_id = save_id
                self.save_switch_error = None
                return
            self.active_save_id = save_id
            self.live_index = None
            self.live_control = None
            self.live_network_mtime = 0
            self.last_signal_poll = 0
            self.write_json(self.bridge / "live-rail-state.json", {
                "schema_version": 2, "save_id": save_id, "source_status": "SAVE_TRANSITION", "sampled_at": now,
                "simulation": snapshot.get("simulation"), "vehicles": [], "counts": {"rail_vehicles": 0},
            })
            self.write_json(self.bridge / "rail-control-state.json", {
                "schema_version": 2, "save_id": save_id, "source_status": "SAVE_TRANSITION",
                "sampled_at": now, "signals": [], "blocks": [], "counts": {"signals": 0, "blocks": 0},
            })
            client = BridgeClient(self.bridge, timeout_seconds=30, poll_seconds=.04)
            client.call("get_rail_network", {})
            self.save_switch_error = None
        except (BridgeError, OSError, ValueError, KeyError, TypeError) as exc:
            self.save_switch_error = str(exc)
        finally:
            self.last_snapshot_poll = now
            self.live_lock.release()

    def regenerate_if_changed(self) -> None:
        source = self.bridge / "rail-network.json"
        current = self._mtime(source)
        if not current or current == self.last_bridge_network_mtime:
            return
        with self.generation_lock:
            current = self._mtime(source)
            if current == self.last_bridge_network_mtime:
                return
            completed = subprocess.run(
                [sys.executable, str(self.exporter), "--input", str(source), "--output-directory", str(self.root),
                 "--save-id", self.current_save_id()],
                cwd=self.exporter.parents[1], capture_output=True, text=True, timeout=180,
            )
            if completed.returncode == 0:
                self.last_bridge_network_mtime = current

    def watch(self) -> None:
        while not self.stop.wait(1.0):
            self.refresh_save_scope()
            self.regenerate_if_changed()
            self.refresh_live()


def handler_factory(app: RailMapState):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app.root), **kwargs)

        def log_message(self, format_string: str, *args) -> None:
            sys.stdout.write("[rail-map] " + format_string % args + "\n")
            sys.stdout.flush()

        def end_headers(self) -> None:
            static_path = urlparse(self.path).path
            if static_path.startswith("/templates/") or static_path.startswith("/station-previews/") or static_path in {
                "/", "/index.html", "/timetable.html", "/network.css", "/timetable.css",
                "/network-page.js", "/timetable-page.js", "/rail-network-manifest.js",
                "/template-runtime.js", "/network-app.js", "/timetable.js", "/app.js",
            }:
                self.send_header("Cache-Control", "no-store, max-age=0")
            super().end_headers()

        def send_json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/status":
                self.send_json(app.status())
                return
            if path == "/api/rail/manifest":
                self.send_json(app.read_json(app.root / "rail-network-manifest.json"))
                return
            if path == "/api/telemetry":
                value = app.read_json(app.bridge / "operational-telemetry.json")
                self.send_json(value, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return
            if path == "/api/live":
                value = app.read_json(app.bridge / "live-rail-state.json")
                self.send_json(value, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return
            if path == "/api/control":
                value = app.read_json(app.bridge / "rail-control-state.json")
                self.send_json(value, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return
            if path == "/api/timetable-plan":
                value = app.read_json(app._plan_path())
                self.send_json(value, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return
            if path == "/api/ai-suggestions":
                self.send_json(app.ai_suggestions())
                return
            if path == "/api/mcp-work-log":
                raw_limit = parse_qs(parsed.query).get("limit", ["30"])[0]
                if raw_limit.lower() == "all":
                    limit = None
                else:
                    try:
                        limit = int(raw_limit)
                    except ValueError:
                        self.send_json({"error": "invalid limit"}, HTTPStatus.BAD_REQUEST)
                        return
                self.send_json(app.mcp_work_logs(limit))
                return
            if path == "/api/operations-context":
                value = app.operations_context()
                self.send_json(value, HTTPStatus.OK if value.get("lines") else HTTPStatus.NOT_FOUND)
                return
            if path.startswith("/api/vehicle-detail/"):
                raw_id = path.rsplit("/", 1)[-1]
                if not raw_id.isdigit():
                    self.send_json({"error": "invalid vehicle id"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    value = app.vehicle_detail(int(raw_id))
                except (BridgeError, ValueError) as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self.send_json(value, HTTPStatus.OK if "error" not in value else HTTPStatus.NOT_FOUND)
                return
            if path.startswith("/api/station-logs/"):
                raw_id = path.rsplit("/", 1)[-1]
                if not raw_id.isdigit():
                    self.send_json({"error": "invalid station id"}, HTTPStatus.BAD_REQUEST)
                    return
                raw_limit = parse_qs(parsed.query).get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self.send_json({"error": "invalid limit"}, HTTPStatus.BAD_REQUEST)
                    return
                save_id = app.current_save_id()
                rows = app.station_events.query(int(raw_id), save_id, limit)
                self.send_json({"save_id": save_id, "station_id": int(raw_id), "events": rows, "count": len(rows)})
                return
            if path.startswith("/api/rail/tile/"):
                key = path.rsplit("/", 1)[-1]
                if not TILE_KEY.fullmatch(key):
                    self.send_json({"error": "invalid tile key"}, HTTPStatus.BAD_REQUEST)
                    return
                value = app.read_json(app.root / "rail-network-tiles" / f"tile-{key}.json")
                self.send_json(value, HTTPStatus.OK if value else HTTPStatus.NOT_FOUND)
                return
            if path == "/api/events":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last = None
                try:
                    while not app.stop.is_set():
                        current = app.status()
                        if current != last:
                            payload = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
                            self.wfile.write(f"event: status\ndata: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            last = current
                        time.sleep(1)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            super().do_GET()

    return Handler


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ui-directory", type=Path, default=repository / "ui" / "rail-map")
    parser.add_argument("--bridge-directory", type=Path, default=bridge_dir())
    parser.add_argument("--live-poll-seconds", type=float, default=1.5)
    args = parser.parse_args()
    app = RailMapState(args.ui_directory.resolve(), args.bridge_directory.resolve(), repository / "tools" / "export-rail-network-map.py", args.live_poll_seconds)
    watcher = threading.Thread(target=app.watch, name="rail-map-watcher", daemon=True)
    watcher.start()
    server = ThreadingHTTPServer((args.host, args.port), handler_factory(app))
    print(f"TPF2 rail map: http://{args.host}:{args.port}/?view=network", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
