"""State aggregation for the local FastAPI railway-map service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .bridge import BridgeClient, BridgeError
from .control_system import EngineeringControlSystem
from .congestion_advisor import CongestionAdvisor
from .dispatch_platform import DispatchControlPlatform
from .infrastructure_speed import build_infrastructure_speed_profile
from .demand_history import DemandHistoryStore
from .dispatch import vehicle_dispatch_state
from .operations import OperationController
from .native_supervisor import NativeSupervisor
from .rail_live import RailSpatialIndex, derive_blocks, normalize_live_state, normalize_signals
from .save_scope import snapshot_save_id
from .snapshot import SnapshotIndex
from .station_log import StationEventStore
from .work_log import McpWorkLogStore
from .timetable_planner import plan_line_timetables
from .timetable_prediction import TimetablePredictor, project_prediction_to_wall
from .tasks import TaskOrchestrator
from .vehicle_length import VehicleModelLengthResolver
from .web_store import WebMutationStore


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
    def __init__(self, root: Path, bridge: Path, exporter: Path, live_poll_seconds: float = 0.2):
        self.root = root
        self.bridge = bridge
        self.exporter = exporter
        self.stop = threading.Event()
        self.generation_lock = threading.Lock()
        self.live_lock = threading.Lock()
        self.full_vehicle_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.status_cache: dict = {}
        self.status_cached_at = 0.0
        self.live_poll_seconds = max(0.1, live_poll_seconds)
        self.last_live_poll = 0.0
        self.last_full_vehicle_poll = 0.0
        self.last_signal_poll = 0.0
        self.last_snapshot_poll = 0.0
        self.snapshot_poll_seconds = 3.0
        self.active_save_id: str | None = None
        self.save_switch_error: str | None = None
        self.live_error: str | None = None
        self.live_index: RailSpatialIndex | None = None
        self.live_network_mtime = 0
        self.live_control = None
        self.block_line_membership: dict[str, list[int]] = {}
        self.line_block_totals: dict[int, int] = {}
        self.last_bridge_network_mtime = self._mtime(bridge / "rail-network.json")
        self.station_events = StationEventStore(bridge / "station-events.sqlite3")
        state_directory = bridge.parent / "tpf2_mcp_state"
        self.state_directory = state_directory
        self.work_log = McpWorkLogStore(state_directory / "mcp-work-log.sqlite3")
        self.task_journal = state_directory / "tasks.jsonl"
        self.timetable_lock = threading.Lock()
        self.timetable_cache = None
        self.timetable_controls = {}
        self.timetable_predictor = TimetablePredictor(state_path=state_directory / "timetable-bindings.json")
        self.demand_history = DemandHistoryStore(state_directory / "line-demand.sqlite3")
        self.vehicle_length_resolver = VehicleModelLengthResolver(bridge.parent.parents[1])
        self.demand_queue: list[int] = []
        self.last_demand_sweep = 0.0
        self.last_demand_item = 0.0
        self.control_system = EngineeringControlSystem(
            bridge, state_directory,
            timetable_executor=self._execute_timetable,
            timetable_clearer=self._clear_timetable,
            fleet_executor=self._execute_fleet_action,
        )
        self.congestion_advisor = CongestionAdvisor()
        self.infrastructure_speed_profile: dict = {}
        self.infrastructure_speed_profile_mtime = 0.0
        self.dispatch_platform = DispatchControlPlatform(
            self.control_system, state_directory, operation_executor=self._execute_platform_operation,
            speed_profile_provider=self.speed_profile,
        )
        self.native_supervisor = NativeSupervisor(bridge.parent)
        self.native_supervisor_status: dict = {}
        self.web_store = WebMutationStore(bridge / "dispatch" / "web.sqlite3")

    def control_status(self) -> dict:
        value = self.control_system.view()
        value["runtime"] = {
            "demand_pending_lines": len(self.demand_queue),
            "last_demand_sweep_at": self.last_demand_sweep or None,
            "last_demand_sample_at": self.last_demand_item or None,
            "native_supervisor": self.native_supervisor_status,
        }
        return value

    def _execute_platform_operation(self, envelope: dict) -> dict:
        return BridgeClient(self.bridge, timeout_seconds=20, poll_seconds=.04).call("execute_operation", envelope)

    def speed_profile(self) -> dict:
        source = self.root / "rail-network-data.json"
        modified = self._mtime(source)
        if not self.infrastructure_speed_profile or modified != self.infrastructure_speed_profile_mtime:
            network = self.read_json(source)
            policy = self.control_system.config().get("infrastructure_speed_policy") or {}
            self.infrastructure_speed_profile = build_infrastructure_speed_profile(
                network, policy.get("overrides"), float(policy.get("default_side_kmh") or 45),
                float(policy.get("platform_kmh") or 45),
            )
            self.infrastructure_speed_profile_mtime = modified
        return self.infrastructure_speed_profile

    def dispatch_platform_status(self) -> dict:
        return self.dispatch_platform.view(
            self.current_save_id(), self.read_json(self.bridge / "live-rail-state.json"),
            self.read_json(self.bridge / "heartbeat.json"),
            {**self.read_json(self.bridge / "native-control-status.json"), **self.native_supervisor_status},
            self.speed_profile(),
        )

    def _execute_timetable(self, line: dict) -> dict:
        parameters = {
            "enabled": True, "cycle_seconds": line["cycle_seconds"],
            "epoch_game_time_ms": line["epoch_game_time_ms"],
            "control_lease_expires_at": line.get("control_lease_expires_at"),
            "late_release_seconds": line["late_release_seconds"], "priority": line["priority"],
            "stops": [{key: stop[key] for key in ("stop_index", "departure_offsets_seconds", "max_hold_seconds")}
                      for stop in line["stops"]],
        }
        envelope = {"protocol_version": 1, "operation_id": f"auto-timetable-{line['line_id']}-{int(time.time())}",
                    "operation_type": "APPLY_LINE_TIMETABLE", "target": {"line_id": line["line_id"]},
                    "parameters": parameters}
        return BridgeClient(self.bridge, timeout_seconds=20, poll_seconds=.04).call("execute_operation", envelope)

    def _clear_timetable(self, line_id: int) -> dict:
        envelope = {"protocol_version": 1, "operation_id": f"auto-clear-timetable-{line_id}-{int(time.time())}",
                    "operation_type": "CLEAR_LINE_TIMETABLE", "target": {"line_id": line_id}, "parameters": {}}
        return BridgeClient(self.bridge, timeout_seconds=20, poll_seconds=.04).call("execute_operation", envelope)

    def _execute_fleet_action(self, action: dict, line: dict) -> dict:
        bridge = BridgeClient(self.bridge, timeout_seconds=45, poll_seconds=.04)
        current = SnapshotIndex(bridge.game_state(force_refresh=True))

        def snapshot(force: bool) -> SnapshotIndex:
            nonlocal current
            if force:
                current = SnapshotIndex(bridge.game_state(force_refresh=True))
            return current

        operations = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope),
                                         journal_path=self.state_directory / "operations.jsonl")
        tasks = TaskOrchestrator(snapshot, operations, journal_path=self.state_directory / "tasks.jsonl")
        kind = action.get("kind")
        if kind == "ADD_TRAIN":
            first = (action.get("operations") or [{}])[0]
            depot_id = (first.get("target") or {}).get("depot_id")
            source_id = (first.get("parameters") or {}).get("source_vehicle_id")
            if not isinstance(depot_id, int) or not isinstance(source_id, int):
                return {"status": "BLOCKED", "reason": "VERIFIED_DEPOT_OR_TEMPLATE_UNAVAILABLE"}
            task = tasks.create("EXPAND_LINE_WITH_VEHICLE_GOAL", {"line_id": line["line_id"],
                                "source_vehicle_id": source_id, "depot_id": depot_id, "stop_index": 0},
                                policy="AUTO_SAFE", max_steps=2, max_write_operations=2)
        elif kind == "REMOVE_TRAIN":
            operation = (action.get("operations") or [{}])[0]
            vehicle_id = (operation.get("target") or {}).get("vehicle_id")
            target_vehicle = current.vehicle_by_id.get(vehicle_id)
            rollback_source = next((item for item in current.state.get("vehicles", [])
                                    if item.get("entity_id") != vehicle_id
                                    and item.get("consist_signature") == (target_vehicle or {}).get("consist_signature")), None)
            recovery_depot = (((line.get("fleet_policy") or {}).get("consist_constraint") or {})
                              .get("recovery_depot") or {}).get("entity_id")
            if not target_vehicle or not rollback_source or not isinstance(recovery_depot, int):
                return {"status": "BLOCKED", "reason": "REMOVAL_REQUIRES_EXECUTABLE_REPLACEMENT_ROLLBACK"}
            task = tasks.create("SELL_VEHICLE_GOAL", {"vehicle_id": vehicle_id,
                                "confirmation": f"SELL_VEHICLE:{vehicle_id}"},
                                policy="AUTO_SAFE", max_steps=1, max_write_operations=1)
            rollback = {"kind": "BUY_AND_ASSIGN_REPLACEMENT", "line_id": line["line_id"],
                        "source_vehicle_id": rollback_source["entity_id"], "depot_id": recovery_depot,
                        "consist_signature": target_vehicle.get("consist_signature")}
        elif kind in {"ADD_CARRIAGES_BY_CONFIG_REPLACEMENT", "REMOVE_CARRIAGES_BY_CONFIG_REPLACEMENT"}:
            operation = (action.get("operations") or [{}])[0]
            target_id = (operation.get("target") or {}).get("vehicle_id")
            before = current.vehicle_by_id.get(target_id)
            rollback_source = next((item for item in current.state.get("vehicles", [])
                                    if item.get("entity_id") != target_id
                                    and item.get("consist_signature") == (before or {}).get("consist_signature")), None)
            if not before or not rollback_source:
                return {"status": "BLOCKED", "reason": "CONFIG_REPLACEMENT_REQUIRES_OBSERVED_ROLLBACK_TEMPLATE"}
            proposal = operations.propose(operation["operation_type"], operation["target"], operation["parameters"])
            execution = operations.execute(proposal.get("operation_id", ""), dry_run=False)
            verification = operations.verify(proposal.get("operation_id", "")) if execution.get("command_sent") else None
            return {"status": (verification or execution).get("status"), "proposal": proposal,
                    "execution": execution, "verification": verification,
                    "rollback": {"operation_type": "REPLACE_VEHICLE_CONFIG", "target": {"vehicle_id": target_id},
                                 "parameters": {"source_vehicle_id": rollback_source["entity_id"],
                                                "confirmation": f"REPLACE_VEHICLE_CONFIG:{target_id}:{rollback_source['entity_id']}"}}}
        else:
            return {"status": "BLOCKED", "reason": f"UNSUPPORTED_FLEET_ACTION:{kind}"}
        task = tasks.plan(task["task_id"], fresh=False)
        if task.get("status") == "WAITING_FOR_APPROVAL":
            task = tasks.approve(task["task_id"])
        while task.get("status") == "READY":
            task = tasks.continue_task(task["task_id"])
        if kind == "ADD_TRAIN":
            created = (task.get("goal") or {}).get("created_vehicle_id")
            rollback = {"operation_type": "SELL_VEHICLE", "target": {"vehicle_id": created},
                        "parameters": {"confirmation": f"SELL_VEHICLE:{created}"}}
            if task.get("status") == "COMPLETED":
                task = {**task, "rollback": rollback}
            elif isinstance(created, int) and snapshot(True).vehicle_by_id.get(created):
                proposal = operations.propose(rollback["operation_type"], rollback["target"], rollback["parameters"])
                execution = operations.execute(proposal.get("operation_id", ""), dry_run=False)
                verification = operations.verify(proposal.get("operation_id", "")) if execution.get("command_sent") else None
                compensated = (verification or {}).get("status") == "POSTCONDITION_VERIFIED"
                task = {**task, "status": "COMPENSATED_FAIL_CLOSED" if compensated else task.get("status"),
                        "compensation": {"reason": "ASSIGNMENT_POSTCONDITION_NOT_MET",
                                         "proposal": proposal, "execution": execution,
                                         "verification": verification, "vehicle_id": created}}
        elif kind == "REMOVE_TRAIN":
            task = {**task, "rollback": rollback}
        return task

    def _plan_path(self) -> Path:
        return self.root.parents[1] / "diagnostics" / "rail-operations" / "line-timetable-plan.json"

    def _runtime_plan_path(self, save_id: str) -> Path:
        return self.state_directory / f"timetable-plan-{save_id}.json"

    @staticmethod
    def _write_json_atomic(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)

    def current_save_id(self) -> str:
        return snapshot_save_id(self.read_json(self.bridge / "state.json"))

    def timetable_plan(self) -> dict:
        """Return only a current-save plan; build a read-only preview if absent.

        Generated previews stay in memory. Never apply a plan from this endpoint.
        Old schema-v2 files have wrapped/partially shifted template times.
        """
        snapshot = self.read_json(self.bridge / "state.json")
        if not snapshot:
            return {"error": "SNAPSHOT_UNAVAILABLE"}
        length_resolution = self.vehicle_length_resolver.enrich_snapshot(snapshot)
        save_id = snapshot_save_id(snapshot)
        stored = self.read_json(self._plan_path())
        if (self.control_system.config().get("mode") == "DISABLED"
                and stored.get("save_id") == save_id and stored.get("schema_version", 0) >= 4):
            return {**stored, "plan_source": "SAVED_PLAN"}
        runtime_path = self._runtime_plan_path(save_id)
        previous_plan = self.read_json(runtime_path)
        now = time.time()
        network_mtime = self._mtime(self.root / "rail-network-data.json")
        cache_seconds = float(self.control_system.config().get("plan_interval_seconds") or 60)
        if (previous_plan.get("save_id") == save_id and previous_plan.get("schema_version", 0) >= 4
                and previous_plan.get("network_mtime") == network_mtime
                and now - float(previous_plan.get("generated_at") or 0) < cache_seconds):
            return {**previous_plan, "plan_source": "PERSISTED_RUNTIME_PLAN"}
        with self.timetable_lock:
            now = time.time()
            key = (save_id, network_mtime)
            if self.timetable_cache and self.timetable_cache[0] == key and now - self.timetable_cache[1] < cache_seconds:
                return self.timetable_cache[2]
            network = self.read_json(self.root / "rail-network-data.json")
            if network.get("save_id") != save_id:
                return {"error": "NETWORK_SAVE_MISMATCH", "save_id": save_id}
            live = self.read_json(self.bridge / "live-rail-state.json")
            frames = [live] if live.get("save_id") == save_id and 0 <= now - live.get("sampled_at", 0) < 10 else []
            control = self.read_json(self.bridge / "rail-control-state.json")
            if control.get("save_id") not in (None, save_id):
                control = {}
            line_ids = [int(item["entity_id"]) for item in network.get("lines", []) if isinstance(item.get("entity_id"), int)]
            histories = self.demand_history.histories(line_ids, save_id, 12)
            recent = {int(item["line_id"]) for item in self.work_log.query(save_id, 500)
                      if item.get("applied") and isinstance(item.get("line_id"), int)
                      and now - float(item.get("occurred_at") or 0) < FLEET_CHANGE_STABILIZATION_SECONDS}
            plan = plan_line_timetables(snapshot, network, frames, histories, recent, control)
            # Refreshing evidence must not slide every departure slot forward.
            # Keep this session's origin until a save switch or clock rewind.
            baseline = self.timetable_cache[2] if self.timetable_cache and self.timetable_cache[0][0] == save_id else previous_plan
            if baseline.get("save_id") == save_id and isinstance(baseline.get("epoch_game_time_ms"), (int, float)):
                origin = baseline["epoch_game_time_ms"]
                if not frames or plan["epoch_game_time_ms"] >= origin:
                    plan["epoch_game_time_ms"] = origin
                    for line in plan["lines"]:
                        line["epoch_game_time_ms"] = origin
            plan.update(plan_source="READ_ONLY_PREVIEW", generated_at=now, network_mtime=network_mtime,
                        snapshot_sequence=snapshot.get("sequence"), vehicle_length_resolution=length_resolution)
            self._write_json_atomic(runtime_path, plan)
            plan["plan_source"] = "PERSISTED_RUNTIME_PLAN"
            self.timetable_cache = (key, now, plan)
            return plan

    def timetable_live(self, line_id: int) -> dict:
        status = self.status()
        live = self.read_json(self.bridge / "live-rail-state.json")
        valid = (status["bridge_connected"] and live.get("save_id") == status["save_id"]
                 and 0 <= time.time() - live.get("sampled_at", 0) < 10)
        controller = {"state": "UNKNOWN"}
        vehicles = [item for item in live.get("vehicles", []) if item.get("line_id") == line_id] if valid else []
        if valid:
            plan = self.timetable_plan()
            line = next((item for item in plan.get("lines", []) if item.get("line_id") == line_id), None)
            if line:
                with self.timetable_lock:
                    predictions = self.timetable_predictor.predictions(status["save_id"], line, live, vehicles)
                vehicles = [{**item, "timetable": project_prediction_to_wall(predictions.get(item.get("entity_id"), {}), live)}
                            for item in vehicles]
        if valid:
            key = (status["save_id"], line_id)
            with self.timetable_lock:
                cached = self.timetable_controls.get(key)
                if cached is None or time.time() - cached[0] >= 10:
                    try:
                        value = BridgeClient(self.bridge, timeout_seconds=3).timetable_status(line_id)
                        controller = {**value, "state": "ENABLED" if value.get("enabled") else "DISABLED"}
                    except (BridgeError, OSError, ValueError):
                        controller = {"state": "UNKNOWN"}
                    self.timetable_controls = {key: (time.time(), controller)}
                else:
                    controller = cached[1]
        return {"save_id": status["save_id"], "fresh": bool(valid), "controller": controller,
                "sampled_at": live.get("sampled_at") if valid else None,
                "simulation": live.get("simulation", {}) if valid else {},
                "vehicles": vehicles}

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
        now = time.time()
        with self.status_lock:
            if self.status_cache and now - self.status_cached_at < 0.5:
                return self.status_cache
            heartbeat = self.read_json(self.bridge / "heartbeat.json")
            state = self.read_json(self.bridge / "state.json")
            manifest = self.read_json(self.root / "rail-network-manifest.json")
            save_id = snapshot_save_id(state)
            telemetry = self.read_json(self.bridge / "operational-telemetry.json")
            live = self.read_json(self.bridge / "live-rail-state.json")
            age = max(0.0, now - float(heartbeat.get("last_update", 0))) if heartbeat else None
            self.status_cache = {
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
            self.status_cached_at = now
            return self.status_cache

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
        result = vehicle_dispatch_state(index, vehicle_id, live, demand)
        save_id = snapshot_save_id(state)
        valid_live = (live_frame.get("save_id") == save_id and isinstance(live_frame.get("sampled_at"), (int, float))
                      and 0 <= time.time() - live_frame["sampled_at"] < 10 and live is not None)
        if valid_live and isinstance(line_id, int):
            plan = self.timetable_plan()
            line = next((item for item in plan.get("lines", []) if item.get("line_id") == line_id), None)
            if line:
                with self.timetable_lock:
                    prediction = self.timetable_predictor.predictions(save_id, line, live_frame, [live])[vehicle_id]
                result["timetable"] = project_prediction_to_wall(prediction, live_frame)
        result.setdefault("timetable", {"binding_state": "UNBOUND", "punctuality": "LATE_UNDETERMINED",
                                        "prediction_source": "LIVE_TIMETABLE_UNAVAILABLE"})
        return result

    def ai_suggestions(self) -> dict:
        """Render bounded, evidence-backed templates only for work MCP cannot finish autonomously."""
        plan_path = self._plan_path()
        plan = self.read_json(plan_path)
        save_id = self.current_save_id()
        if plan.get("save_id") != save_id:
            live = self.read_json(self.bridge / "live-rail-state.json")
            network = self.read_json(self.root / "rail-network-data.json")
            congestion = (self.congestion_advisor.sample(network, live, self.speed_profile())
                          if live.get("save_id") == save_id else [])
            return {
                "schema_version": 2, "save_id": save_id, "policy": "Observation only; stale plans from another save are hidden.",
                "generated_at": time.time(), "suggestions": congestion, "total": len(congestion), "stale_plan_hidden": bool(plan),
                "templates": {"PARALLEL_LINE_IMBALANCE": "并行线路分配失衡",
                              "SECTION_CONGESTION": "区间拥堵", "STATION_THROAT_CONGESTION": "站场咽喉拥堵",
                              "PLATFORM_SATURATION": "站台能力饱和", "TURNOUT_SPEED_BOTTLENECK": "低速道岔瓶颈"},
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
            control_config = self.control_system.config()
            routing_enabled = (control_config.get("features") or {}).get("routing") is True
            routing_mode = control_config.get("mode")
            automation_status = "AUTOMATED" if routing_enabled and routing_mode == "ARMED" else "SHADOW" if routing_enabled and routing_mode == "SHADOW" else "CONTROL_DISABLED"
            suggestions.append({
                "created_at": generated_at,
                "template": "PARALLEL_LINE_IMBALANCE", "template_label": "分配失衡", "severity": "REVIEW", "title": f"{corridor} · {demand_kind}分配失衡",
                "reason": labels, "required_action": "控制平面将按目标线路剩余运力生成有界 OD 分流租约" if routing_enabled else "在控制系统中启用运力分流",
                "automation_status": automation_status, "station_pair": group.get("shared_station_pair"),
                "cargo_id": group.get("cargo_id"), "observation_only": False,
            })
        live = self.read_json(self.bridge / "live-rail-state.json")
        network = self.read_json(self.root / "rail-network-data.json")
        if live.get("save_id") == save_id:
            suggestions.extend(self.congestion_advisor.sample(network, live, self.speed_profile(), now))
        rank = {"BLOCKED": 0, "ACTION": 1, "REVIEW": 2, "DATA": 3}
        suggestions.sort(key=lambda item: (-float(item.get("created_at") or 0), rank.get(item.get("severity"), 9), -(next((line.get("demand", {}).get("waiting", 0) for line in plan.get("lines", []) if line.get("line_id") == item.get("line_id")), 0))))
        return {
            "schema_version": 2, "save_id": save_id,
            "policy": "Only unresolved, approval-gated, infrastructure, or unavailable-capability work appears here. Completed verified actions appear in MCP work log.",
            "templates": {
                "ADD_TRAIN": "线路建议加车", "PLATFORM_TOO_SHORT": "站台长度不足",
                "PLATFORM_LENGTH_UNKNOWN": "长度数据待验证", "PARALLEL_LINE_IMBALANCE": "并行线路分配失衡",
                "SECTION_CONGESTION": "区间拥堵", "STATION_THROAT_CONGESTION": "站场咽喉拥堵",
                "PLATFORM_SATURATION": "站台能力饱和", "TURNOUT_SPEED_BOTTLENECK": "低速道岔瓶颈",
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

    def refresh_full_vehicle_telemetry(self) -> None:
        if not self.full_vehicle_lock.acquire(blocking=False):
            return
        try:
            BridgeClient(self.bridge, timeout_seconds=8, poll_seconds=.04).operational_telemetry("vehicles_live")
        except (BridgeError, OSError, ValueError):
            pass
        finally:
            self.last_full_vehicle_poll = time.time()
            self.full_vehicle_lock.release()

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
            vehicle_path = self.bridge / "operational-telemetry-vehicles_live.json"
            position_path = self.bridge / "operational-telemetry-vehicle_positions.json"
            vehicle_payload = self.read_json(vehicle_path)
            position_payload = self.read_json(position_path)
            periodic_fresh = (position_payload.get("report_mode") == "PERIODIC"
                              and now - self._mtime(position_path) < max(1.0, self.live_poll_seconds * 3))
            if not periodic_fresh:
                # Compatibility path for the currently loaded/older Lua runtime.
                # After the next game restart Lua publishes this file itself.
                client.operational_telemetry("vehicles_live")
                vehicle_payload = self.read_json(vehicle_path)
                self.last_full_vehicle_poll = now
            else:
                control_config = self.control_system.config()
                path_sensitive = (control_config.get("mode") in {"SHADOW", "ARMED"}
                                  and any((control_config.get("features") or {}).get(name)
                                          for name in ("routing", "speed", "station", "path")))
                full_interval = 5.0 if path_sensitive else 30.0
                if now - self.last_full_vehicle_poll >= full_interval or not vehicle_payload:
                    self.last_full_vehicle_poll = now
                    threading.Thread(target=self.refresh_full_vehicle_telemetry,
                                     name="rail-map-full-vehicle-refresh", daemon=True).start()
                full_by_id = {item.get("entity_id"): item for item in vehicle_payload.get("vehicles", [])}
                vehicle_payload = {
                    **vehicle_payload,
                    "vehicles": [{**full_by_id.get(item.get("entity_id"), {}), **item}
                                 for item in position_payload.get("vehicles", [])],
                    "simulation_clock": position_payload.get("simulation_clock"),
                }
            signal_payload = self.read_json(self.bridge / "operational-telemetry-signals.json")
            if signal_payload.get('session_id') != vehicle_payload.get('session_id'):
                signal_payload = {}
            signal_revision = (signal_payload.get('session_id'), signal_payload.get('generated_at'))
            if getattr(self, 'live_signal_revision', None) != signal_revision:
                self.live_control = None
                self.live_signal_revision = signal_revision
            footprint_payload = self.read_json(self.bridge / "operational-telemetry-train_footprints.json")
            footprint_fresh = (footprint_payload.get("session_id") == vehicle_payload.get("session_id")
                               and isinstance(footprint_payload.get("generated_at"), (int, float))
                               and 0 <= now - float(footprint_payload["generated_at"]) <= 5)
            footprint_by_id = ({item.get("entity_id"): item for item in footprint_payload.get("vehicles", [])}
                               if footprint_fresh else {})
            if footprint_by_id:
                vehicle_payload["vehicles"] = [
                    {**item, **footprint_by_id.get(item.get("entity_id"), {}),
                     "footprint_sampled_at": footprint_payload.get("generated_at")}
                    for item in vehicle_payload.get("vehicles", [])
                ]
            telemetry = {"vehicles": vehicle_payload.get("vehicles", []), "simulation_clock": vehicle_payload.get("simulation_clock"), "signal_edge_objects": signal_payload.get("signal_edge_objects", []), "track_edge_objects": signal_payload.get("track_edge_objects", [])}
            telemetry.update(session_id=vehicle_payload.get('session_id'),
                             signal_inventory_generated_at=signal_payload.get('generated_at'),
                             signal_state_payload=self.read_json(self.bridge / 'operational-telemetry-signal_states.json'))
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
                detail = self.read_json(self.root / "rail-network-data.json")
                edge_lines: dict[int, set[int]] = {}
                for line in detail.get("lines", []):
                    line_id = line.get("entity_id")
                    if not isinstance(line_id, int):
                        continue
                    for edge_id in line.get("route_edge_ids", []):
                        if isinstance(edge_id, int):
                            edge_lines.setdefault(edge_id, set()).add(line_id)
                self.block_line_membership = {}
                self.line_block_totals = {}
                for block in blocks:
                    members = sorted({line_id for edge_id in block.get("edge_ids", [])
                                      for line_id in edge_lines.get(edge_id, set())})
                    self.block_line_membership[str(block.get("block_id"))] = members
                    for line_id in members:
                        self.line_block_totals[line_id] = self.line_block_totals.get(line_id, 0) + 1
                confirmed = sum(signal["source_status"] != "TRACK_OBJECT_CANDIDATE" for signal in signals)
                self.write_json(self.bridge / "rail-control-state.json", {"schema_version": 1, "source_status": "ENGINE_OBSERVED_STATIC_CONTROL", "sampled_at": now, "signals": signals, "blocks": blocks, "counts": {"signal_candidates": len(signals), "confirmed_signals": confirmed, "blocks": len(blocks)}})
            value = normalize_live_state(telemetry, network, manifest, previous, now, spatial_index=self.live_index, control=self.live_control)
            frame = {key: item for key, item in value.items() if key not in {"signals", "blocks"}}
            # Dynamic observations must never be frozen in the static control cache.
            frame['signal_observations'] = [{key: signal.get(key) for key in (
                'entity_id', 'edge_id', 'edge_param', 'directions', 'direction_bindings',
                'direction_status', 'state_entries', 'state_sampled_at', 'state_source',
                'state_status', 'aspect')} for signal in value.get('signals', [])]
            frame["path_blocks"] = [
                {"block_id": block.get("block_id"), "edge_ids": block.get("edge_ids", []),
                 "occupied_vehicle_ids": block.get("occupied_vehicle_ids", [])}
                for block in value.get("blocks", []) if block.get("occupied_vehicle_ids")
            ]
            occupied_by_line: dict[int, int] = {}
            for block in frame["path_blocks"]:
                for line_id in self.block_line_membership.get(str(block.get("block_id")), []):
                    occupied_by_line[line_id] = occupied_by_line.get(line_id, 0) + 1
            frame["line_block_occupancy"] = [
                {"line_id": line_id, "occupied_blocks": occupied_by_line.get(line_id, 0),
                 "total_blocks": total,
                 "occupancy_ratio": round(occupied_by_line.get(line_id, 0) / total, 4) if total else 0.0}
                for line_id, total in sorted(self.line_block_totals.items())
            ]
            frame["save_id"] = manifest.get("save_id")
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
            self.block_line_membership = {}
            self.line_block_totals = {}
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

    def sample_demand_if_due(self) -> None:
        config = self.control_system.config()
        if config.get("mode") not in {"SHADOW", "ARMED"}:
            self.demand_queue = []
            return
        now = time.time()
        if not self.demand_queue:
            if now - self.last_demand_sweep < float(config["demand_sample_interval_seconds"]):
                return
            network = self.read_json(self.root / "rail-network-data.json")
            self.demand_queue = [int(item["entity_id"]) for item in network.get("lines", [])
                                 if isinstance(item.get("entity_id"), int)]
            if not self.demand_queue:
                return
        line_id = self.demand_queue.pop(0)
        self.last_demand_item = now
        try:
            sample = BridgeClient(self.bridge, timeout_seconds=15, poll_seconds=.04).line_demand(line_id, 50000)
            self.demand_history.record(sample, self.current_save_id(), now)
            # Demand evidence changes fleet and routing decisions even when the
            # rail geometry is unchanged.
            with self.timetable_lock:
                self.timetable_cache = None
        except (BridgeError, OSError, ValueError):
            self.demand_queue.append(line_id)
        if not self.demand_queue:
            self.last_demand_sweep = now

    def run_control_cycle(self) -> None:
        if not self.control_system.due():
            return
        snapshot = self.read_json(self.bridge / "state.json")
        manifest = self.read_json(self.root / "rail-network-data.json")
        if not snapshot:
            return
        # Planning can resolve hundreds of vehicle resources on the first run.
        # Read the safety telemetry afterwards so plan computation never makes
        # an otherwise healthy frame look stale at the execution boundary.
        plan = self.timetable_plan()
        self.refresh_live()
        live = self.read_json(self.bridge / "live-rail-state.json")
        heartbeat = self.read_json(self.bridge / "heartbeat.json")
        native_status = self.read_json(self.bridge / "native-control-status.json")
        control_config = self.control_system.config()
        native_requested = (control_config.get("mode") == "ARMED"
                            and any((control_config.get("features") or {}).get(name) for name in ("routing", "speed", "station", "path")))
        self.native_supervisor_status = self.native_supervisor.reconcile(allow_inject=native_requested)
        native_status.update(self.native_supervisor_status)
        self.control_system.cycle(snapshot, manifest, manifest, live, heartbeat, native_status, plan)

    def watch(self) -> None:
        while not self.stop.wait(min(0.1, self.live_poll_seconds)):
            self.refresh_save_scope()
            self.regenerate_if_changed()
            self.refresh_live()
            self.sample_demand_if_due()
            self.run_control_cycle()
