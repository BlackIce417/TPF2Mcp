"""Minimal dependency-free MCP server over stdio (JSON-RPC, one message per line)."""
from __future__ import annotations

import json
import sys
import time
from typing import Any

from .bridge import BridgeClient, BridgeError, MockBridge
from .config import snapshot_cache_seconds, state_dir
from .snapshot import SnapshotIndex
from .analytics import NetworkIntelligenceIndex
from .planning import DecisionSupport
from .operations import OperationController, capabilities as operation_capabilities
from .tasks import TaskOrchestrator, goal_capabilities
from .dispatch import agent_operations_guide, vehicle_dispatch_state


def _bridge() -> BridgeClient | MockBridge:
    # MockBridge requires a caller-provided fixture and is therefore only used
    # by unit tests.  A process configured for real use always uses the bridge.
    return BridgeClient()


def _tool_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "structuredContent": value}


def _error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


_index_cache: dict[int, tuple[float, SnapshotIndex]] = {}
_intelligence_cache: dict[int, tuple[int | None, NetworkIntelligenceIndex]] = {}
_planning_cache: dict[int, tuple[int | None, DecisionSupport]] = {}
_operation_controllers: dict[int, OperationController] = {}
_task_orchestrators: dict[int, TaskOrchestrator] = {}


def _index(bridge: BridgeClient | MockBridge, force_refresh: bool = False) -> SnapshotIndex:
    """Use one bridge snapshot for a read-only MCP interaction window.

    Lua independently refreshes its source snapshot at a short interval.  The
    longer Python window prevents a tool sequence (line -> stations -> vehicles)
    from repeatedly asking the game to scan the entire world.
    """
    now, cache_key = time.monotonic(), id(bridge)
    cached = _index_cache.get(cache_key)
    if not force_refresh and cached and now - cached[0] < snapshot_cache_seconds():
        return cached[1]
    index = SnapshotIndex(bridge.game_state(force_refresh=force_refresh))
    _index_cache[cache_key] = (now, index)
    return index


def _collection(bridge: BridgeClient | MockBridge, key: str) -> list[dict[str, Any]]:
    index = _index(bridge)
    if key == "lines": return [index._line(item) for item in index.line_by_id.values()]
    if key == "stations": return [index._station(item) for item in index.station_by_id.values()]
    if key == "vehicles": return [index._vehicle(item) for item in index.vehicle_by_id.values()]
    return index.collection(key)


def _intelligence(bridge: BridgeClient | MockBridge) -> NetworkIntelligenceIndex:
    snapshot = _index(bridge)
    cache_key, sequence = id(bridge), snapshot.state.get("sequence")
    cached = _intelligence_cache.get(cache_key)
    if cached and cached[0] == sequence:
        return cached[1]
    intelligence = NetworkIntelligenceIndex(snapshot)
    _intelligence_cache[cache_key] = (sequence, intelligence)
    return intelligence


def _planning(bridge: BridgeClient | MockBridge) -> DecisionSupport:
    intelligence = _intelligence(bridge)
    cache_key, sequence = id(bridge), intelligence.snapshot_sequence
    cached = _planning_cache.get(cache_key)
    if cached and cached[0] == sequence:
        return cached[1]
    planning = DecisionSupport(intelligence)
    _planning_cache[cache_key] = (sequence, planning)
    return planning


def _operations(bridge: BridgeClient | MockBridge) -> OperationController:
    """One in-memory journal per bridge with a mediated bridge executor."""
    controller = _operation_controllers.get(id(bridge))
    if controller is None:
        controller = OperationController(lambda force_refresh: _index(bridge, force_refresh), lambda envelope: bridge.call("execute_operation", envelope), journal_path=state_dir() / "operations.jsonl")
        _operation_controllers[id(bridge)] = controller
    return controller


def _tasks(bridge: BridgeClient | MockBridge) -> TaskOrchestrator:
    orchestrator = _task_orchestrators.get(id(bridge))
    if orchestrator is None:
        orchestrator = TaskOrchestrator(lambda force_refresh: _index(bridge, force_refresh), _operations(bridge), journal_path=state_dir() / "tasks.jsonl")
        _task_orchestrators[id(bridge)] = orchestrator
    return orchestrator


def _entity(bridge: BridgeClient | MockBridge, key: str, entity_id: int) -> dict[str, Any]:
    item = _index(bridge).entity(key, entity_id)
    if item is not None:
        index = _index(bridge)
        if key == "lines": return index._line(item)
        if key == "stations": return index._station(item)
        if key == "vehicles": return index._vehicle(item)
        return item
    raise BridgeError(f"ENTITY_NOT_FOUND: {key} {entity_id} not found")


def handle(message: dict[str, Any], bridge: BridgeClient | MockBridge) -> dict[str, Any] | None:
    method, request_id, params = message.get("method"), message.get("id"), message.get("params", {})
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "tpf2-mcp", "version": "0.1.0"}, "capabilities": {"tools": {}, "resources": {}}}}
    if method == "tools/list":
        tools = [
            {"name": "get_bridge_status", "description": "Return TPF2 bridge liveness and probe state.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_game_state", "description": "Return normalized world metadata, game, company, counts, and snapshot age. Set force_refresh to bypass bridge and MCP snapshot caches.", "inputSchema": {"type": "object", "properties": {"force_refresh": {"type": "boolean"}}, "additionalProperties": False}},
            {"name": "get_world_snapshot", "description": "Return the complete latest normalized world snapshot. Set force_refresh to bypass bridge and MCP snapshot caches.", "inputSchema": {"type": "object", "properties": {"force_refresh": {"type": "boolean"}}, "additionalProperties": False}},
            {"name": "get_cargo_types", "description": "Return dynamically enumerated cargo types from TPF2's cargo repository.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_towns", "description": "Return towns from the latest normalized world snapshot.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_town", "description": "Return one town by its TPF2 entity ID.", "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "integer"}}, "required": ["entity_id"], "additionalProperties": False}},
            *[{"name": f"get_{plural}", "description": f"Return {plural} from the latest normalized world snapshot.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}} for plural in ("industries", "stations", "lines", "vehicles")],
            *[{"name": f"get_{singular}", "description": f"Return one {singular} by TPF2 entity ID.", "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "integer"}}, "required": ["entity_id"], "additionalProperties": False}} for singular in ("industry", "station", "line", "vehicle")],
            {"name": "get_line_summary", "description": "Return a line with its resolved station groups and assigned vehicles.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "get_dispatch_overview", "description": "Agent-oriented compact operating entry point: game state, network counts, capabilities, and safe control workflow.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_station_dispatch_state", "description": "Return one station's identity, connected lines, neighboring stations, and verified operating availability for dispatch decisions.", "inputSchema": {"type": "object", "properties": {"station_id": {"type": "integer"}}, "required": ["station_id"], "additionalProperties": False}},
            {"name": "get_line_dispatch_state", "description": "Return one line's topology, fleet, structural diagnosis, and live Bridge-classified passenger/cargo demand.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}, "maximum_entities": {"type": "integer", "minimum": 1, "maximum": 100000}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "get_vehicle_dispatch_state", "description": "Return one vehicle's current speed/state, next stop, capacity, and Bridge-classified onboard passenger/cargo counts.", "inputSchema": {"type": "object", "properties": {"vehicle_id": {"type": "integer"}, "maximum_entities": {"type": "integer", "minimum": 1, "maximum": 100000}}, "required": ["vehicle_id"], "additionalProperties": False}},
            {"name": "get_agent_operations_guide", "description": "Return the canonical MCP-only read, proposal, approval, execution, and verification workflow for an operating agent.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_line_demand", "description": "Collect live passenger and freight demand assigned to one line through the Bridge, including onboard, waiting, average wait, and observed cargo types. This is a bounded live probe, not cached snapshot data.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}, "maximum_entities": {"type": "integer", "minimum": 1, "maximum": 100000}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "get_transport_network_summary", "description": "Return deterministic transport-network counts and relationship summaries.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "find_lines_without_vehicles", "description": "List lines whose verified assigned-vehicle count is zero.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "find_unassigned_vehicles", "description": "List vehicles with no line and vehicles whose line reference is broken.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "find_suspicious_lines", "description": "Apply deterministic stop/vehicle-count rules; not a profitability claim.", "inputSchema": {"type": "object", "properties": {"vehicle_threshold": {"type": "integer", "minimum": 1}}, "additionalProperties": False}},
            {"name": "get_vehicle_operating_state", "description": "Return verified vehicle operating metrics and availability metadata.", "inputSchema": {"type": "object", "properties": {"vehicle_id": {"type": "integer"}}, "required": ["vehicle_id"], "additionalProperties": False}},
            {"name": "get_station_operating_state", "description": "Return verified station-group waiting metrics and availability metadata.", "inputSchema": {"type": "object", "properties": {"station_id": {"type": "integer"}}, "required": ["station_id"], "additionalProperties": False}},
            {"name": "get_line_operating_summary", "description": "Return line topology plus verified operational/finance availability.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "get_line_scorecard", "description": "Return verified line topology, frequency/throughput, and derived static fleet-capacity metrics; not load or profitability.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "diagnose_line_structure", "description": "Return explainable structural warnings based only on stops, assigned vehicles, verified headway, throughput, and static fleet capacity.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}, "long_headway_seconds": {"type": "number", "exclusiveMinimum": 0}, "short_headway_seconds": {"type": "number", "exclusiveMinimum": 0}, "high_vehicle_count": {"type": "integer", "minimum": 1}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "diagnose_transport_network", "description": "Return evidence-backed network structural diagnostics; it does not infer profitability, congestion, load, or waiting.", "inputSchema": {"type": "object", "properties": {"long_headway_seconds": {"type": "number", "exclusiveMinimum": 0}, "short_headway_seconds": {"type": "number", "exclusiveMinimum": 0}, "high_vehicle_count": {"type": "integer", "minimum": 1}}, "additionalProperties": False}},
            {"name": "compare_lines", "description": "Compare verified and derived structural metrics for selected lines.", "inputSchema": {"type": "object", "properties": {"line_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 100}}, "required": ["line_ids"], "additionalProperties": False}},
            {"name": "rank_lines", "description": "Rank lines by a whitelisted verified or derived structural metric.", "inputSchema": {"type": "object", "properties": {"metric": {"type": "string", "enum": ["frequency_seconds", "throughput", "vehicle_count", "fleet_capacity_total"]}, "order": {"type": "string", "enum": ["asc", "desc"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["metric"], "additionalProperties": False}},
            {"name": "get_station_connectivity", "description": "Return station-group line connections and derived neighboring station groups; not passenger traffic.", "inputSchema": {"type": "object", "properties": {"station_id": {"type": "integer"}}, "required": ["station_id"], "additionalProperties": False}},
            {"name": "rank_transfer_stations", "description": "Rank station groups by line connectivity, not traffic or waiting volume.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "find_station_route", "description": "Find a route through the existing station/line connectivity graph. This is not physical track, road, or map navigation.", "inputSchema": {"type": "object", "properties": {"source_station_id": {"type": "integer"}, "target_station_id": {"type": "integer"}}, "required": ["source_station_id", "target_station_id"], "additionalProperties": False}},
            {"name": "get_fleet_summary", "description": "Return assigned/unassigned counts and verified static capacity distribution; not current load.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_fleet_profile", "description": "Return snapshot-bound fleet assignment, raw depot/state, and capacity profile.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_line_fleet_profile", "description": "Return one line's assigned vehicle IDs and verified/derived fleet metrics.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "rank_vehicles_by_capacity", "description": "Rank vehicles by verified configured capacity, not live load.", "inputSchema": {"type": "object", "properties": {"order": {"type": "string", "enum": ["asc", "desc"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "get_line_profile", "description": "Return a compact snapshot-bound structural line profile using verified and derived metrics only.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "classify_lines", "description": "Classify lines by explicit structural heuristics, not profitability or demand.", "inputSchema": {"type": "object", "properties": {"low_fleet_threshold": {"type": "integer", "minimum": 0}, "long_route_stop_threshold": {"type": "integer", "minimum": 1}, "high_frequency_seconds": {"type": "number", "exclusiveMinimum": 0}, "high_capacity_threshold": {"type": "number", "minimum": 0}}, "additionalProperties": False}},
            {"name": "find_line_outliers", "description": "Find statistical line-metric outliers; results are not operating-health conclusions.", "inputSchema": {"type": "object", "properties": {"metric": {"type": "string", "enum": ["frequency_seconds", "vehicle_count", "fleet_capacity_total", "stop_count", "throughput", "vehicles_per_stop", "capacity_per_stop"]}, "method": {"type": "string", "enum": ["iqr", "percentile"]}, "percentile": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 0.5}}, "required": ["metric"], "additionalProperties": False}},
            {"name": "find_similar_lines", "description": "Find structurally similar lines using z-score normalized verified/derived features; not demand or profitability similarity.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "get_station_profile", "description": "Return topology-only station-group hub/connectivity metrics, not passenger traffic.", "inputSchema": {"type": "object", "properties": {"station_id": {"type": "integer"}}, "required": ["station_id"], "additionalProperties": False}},
            {"name": "rank_station_hubs", "description": "Rank station groups by a topology hub metric, not traffic or waiting volume.", "inputSchema": {"type": "object", "properties": {"metric": {"type": "string", "enum": ["line_count", "graph_degree", "reachable_station_count"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "analyze_network_reachability", "description": "Return line/station graph connected components; not physical-map connectivity.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "find_isolated_station_clusters", "description": "Find small disconnected line/station graph components; not physical-map isolation.", "inputSchema": {"type": "object", "properties": {"max_station_count": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "get_network_recommendations", "description": "Return conservative, rule-based, evidence-backed checks. It never recommends edits or claims profit, load, or waiting.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "analyze_network", "description": "Return a compact snapshot-bound intelligence summary with topology, outliers, hubs, recommendations, and limitations.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "detect_network_problems", "description": "Convert deterministic network recommendations into evidence-backed planning problems.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "analyze_problem_impact", "description": "Return verified topology/fleet relations for a planning problem; not demand or financial impact.", "inputSchema": {"type": "object", "properties": {"problem_id": {"type": "string"}}, "required": ["problem_id"], "additionalProperties": False}},
            {"name": "find_alternative_routes", "description": "Return up to five minimum-hop station/line topology routes, not fastest or physical routes.", "inputSchema": {"type": "object", "properties": {"source_station_id": {"type": "integer"}, "target_station_id": {"type": "integer"}, "max_routes": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["source_station_id", "target_station_id"], "additionalProperties": False}},
            {"name": "find_articulation_stations", "description": "List topology articulation stations derived by Tarjan analysis; not congestion points.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "find_bridge_connections", "description": "List topology bridge connections derived by Tarjan analysis; not service bottlenecks.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "analyze_network_resilience", "description": "Return topology-only resilience metrics and single-point dependencies.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "simulate_station_connection", "description": "Simulate an in-memory virtual connection between existing stations. Never modifies the game.", "inputSchema": {"type": "object", "properties": {"station_a": {"type": "integer"}, "station_b": {"type": "integer"}}, "required": ["station_a", "station_b"], "additionalProperties": False}},
            {"name": "simulate_line_failure", "description": "Simulate removal of one line from the in-memory topology. Never modifies the game.", "inputSchema": {"type": "object", "properties": {"line_id": {"type": "integer"}}, "required": ["line_id"], "additionalProperties": False}},
            {"name": "simulate_station_failure", "description": "Simulate removal of one station from the in-memory topology. Never modifies the game.", "inputSchema": {"type": "object", "properties": {"station_id": {"type": "integer"}}, "required": ["station_id"], "additionalProperties": False}},
            {"name": "simulate_network_scenario", "description": "Apply whitelisted virtual mutations only to an in-memory planning model. Never modifies the game.", "inputSchema": {"type": "object", "properties": {"mutations": {"type": "array", "maxItems": 20}}, "required": ["mutations"], "additionalProperties": False}},
            {"name": "get_planning_options", "description": "Return conservative hypothetical options generated from detected topology problems; not game commands.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "plan_new_line_candidates", "description": "Rank unserved station-pair topology gaps using observed entities only. Returns read-only Task goal candidates and explicit terminal/physical-route limitations.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
            {"name": "compare_network_scenarios", "description": "Compare 2–10 in-memory hypothetical scenarios on topology dimensions; cost, demand, and profit remain unavailable.", "inputSchema": {"type": "object", "properties": {"scenarios": {"type": "array", "minItems": 2, "maxItems": 10}}, "required": ["scenarios"], "additionalProperties": False}},
            {"name": "analyze_and_plan_network", "description": "Return a compact decision-support summary: problems, topology dependencies, planning options, and limitations. It never executes changes.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "get_operation_capabilities", "description": "Return the conservative controlled-write registry. Unverified entries cannot execute.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "propose_operation", "description": "Create a non-mutating controlled-operation proposal; it never writes the game.", "inputSchema": {"type": "object", "properties": {"operation_type": {"type": "string"}, "target": {"type": "object"}, "parameters": {"type": "object"}}, "required": ["operation_type", "target", "parameters"], "additionalProperties": False}},
            {"name": "validate_operation", "description": "Recheck proposal snapshot/entity/capability preconditions without writing.", "inputSchema": {"type": "object", "properties": {"operation_id": {"type": "string"}, "force_refresh": {"type": "boolean"}}, "required": ["operation_id"], "additionalProperties": False}},
            {"name": "get_operation", "description": "Return one operation lifecycle record.", "inputSchema": {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"], "additionalProperties": False}},
            {"name": "list_recent_operations", "description": "Return up to 50 in-memory operation journal records.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "additionalProperties": False}},
            {"name": "create_rollback_operation", "description": "Create a non-mutating compensating proposal for a reversible operation.", "inputSchema": {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"], "additionalProperties": False}},
            {"name": "get_task_capabilities", "description": "List goal types and whether each is executable or plan-only.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"name": "create_task", "description": "Create a bounded task; this never executes a game mutation.", "inputSchema": {"type": "object", "properties": {"goal_type": {"type": "string"}, "goal": {"type": "object"}, "policy": {"type": "string", "enum": ["MANUAL", "AUTO_SAFE", "PLAN_ONLY"]}, "max_steps": {"type": "integer", "minimum": 1, "maximum": 10}, "max_replans": {"type": "integer", "minimum": 1, "maximum": 3}, "max_write_operations": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["goal_type", "goal"], "additionalProperties": False}},
            {"name": "plan_task", "description": "Observe and plan one logical next step without writing.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "get_task", "description": "Return one task journal and state.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "list_tasks", "description": "Return up to 50 recent in-memory tasks.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "additionalProperties": False}},
            {"name": "get_next_task_step", "description": "Return the current logical next step without executing it.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "approve_task_step", "description": "Approve a MANUAL task's single planned write step.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "continue_task", "description": "Re-observe and execute at most one approved/AUTO_SAFE operation, then verify it. Never loops.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "cancel_task", "description": "Cancel an uncompleted task; it cannot undo a completed mutation.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "explain_task", "description": "Return decision evidence, current state, remaining budget, and next permitted action.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False}},
            {"name": "find_low_load_vehicles", "description": "Returns low-load vehicles only when current-load telemetry is available; otherwise explicitly reports metric unavailability.", "inputSchema": {"type": "object", "properties": {"occupancy_threshold": {"type": "number", "minimum": 0, "maximum": 1}}, "additionalProperties": False}},
            {"name": "find_high_waiting_stations", "description": "Returns high-waiting stations only when waiting telemetry is available; otherwise explicitly reports metric unavailability.", "inputSchema": {"type": "object", "properties": {"waiting_threshold": {"type": "integer", "minimum": 0}}, "additionalProperties": False}},
            {"name": "find_stations_without_lines", "description": "List station groups with no resolved line stops.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        ]
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": [
            {"uri": "tpf2://game", "name": "TPF2 game overview", "mimeType": "application/json"},
            {"uri": "tpf2://network", "name": "TPF2 transport network", "mimeType": "application/json"},
            {"uri": "tpf2://network/lines", "name": "TPF2 lines", "mimeType": "application/json"},
            {"uri": "tpf2://network/stations", "name": "TPF2 station groups", "mimeType": "application/json"},
            {"uri": "tpf2://network/vehicles", "name": "TPF2 vehicles", "mimeType": "application/json"},
            {"uri": "tpf2://cargo-types", "name": "TPF2 cargo types", "mimeType": "application/json"},
            {"uri": "tpf2://agent-operations", "name": "TPF2 agent operations workflow", "mimeType": "application/json"},
            {"uri": "tpf2://capabilities", "name": "TPF2 metric capabilities", "mimeType": "application/json"}]}}
    try:
        if method == "tools/call":
            name = params.get("name")
            if name == "get_bridge_status":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(bridge.status())}
            if name == "get_game_state":
                force_refresh = params.get("arguments", {}).get("force_refresh", False)
                if not isinstance(force_refresh, bool): return _error(-32602, "force_refresh must be a boolean", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge, force_refresh).overview())}
            if name == "get_world_snapshot":
                force_refresh = params.get("arguments", {}).get("force_refresh", False)
                if not isinstance(force_refresh, bool): return _error(-32602, "force_refresh must be a boolean", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge, force_refresh).world_snapshot())}
            if name == "get_cargo_types":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).cargo_types())}
            if name == "get_towns":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_collection(bridge, "towns"))}
            if name == "get_town":
                entity_id = params.get("arguments", {}).get("entity_id")
                if not isinstance(entity_id, int):
                    return _error(-32602, "entity_id must be an integer", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_entity(bridge, "towns", entity_id))}
            plural_tools = {"get_industries": "industries", "get_stations": "stations", "get_lines": "lines", "get_vehicles": "vehicles"}
            if name in plural_tools:
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_collection(bridge, plural_tools[name]))}
            singular_tools = {"get_industry": "industries", "get_station": "stations", "get_line": "lines", "get_vehicle": "vehicles"}
            if name in singular_tools:
                entity_id = params.get("arguments", {}).get("entity_id")
                if not isinstance(entity_id, int): return _error(-32602, "entity_id must be an integer", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_entity(bridge, singular_tools[name], entity_id))}
            if name == "get_line_summary":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                summary = _index(bridge).line_summary(line_id)
                if summary is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(summary)}
            if name == "get_agent_operations_guide":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(agent_operations_guide())}
            if name == "get_dispatch_overview":
                index = _index(bridge)
                result = {"schema_version": 1, "game": index.overview(), "network": index.network_summary(),
                          "data_capabilities": index.capabilities(), "agent_workflow": agent_operations_guide()}
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_station_dispatch_state":
                station_id = params.get("arguments", {}).get("station_id")
                if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
                index = _index(bridge); station = index.station_operating_state(station_id); connectivity = index.station_connectivity(station_id)
                if station is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
                lines = [index.line_summary(line_id) for line_id in index._station(index.station_by_id[station_id]).get("line_ids", [])]
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"schema_version": 1, "station": station, "connectivity": connectivity, "lines": lines})}
            if name == "get_line_dispatch_state":
                arguments = params.get("arguments", {}); line_id = arguments.get("line_id"); maximum = arguments.get("maximum_entities", 20000)
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 100000: return _error(-32602, "maximum_entities must be an integer from 1 to 100000", request_id)
                index = _index(bridge); summary = index.line_summary(line_id)
                if summary is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                result = {"schema_version": 1, "summary": summary, "scorecard": index.line_scorecard(line_id),
                          "diagnosis": index.diagnose_line_structure(line_id), "demand": bridge.line_demand(line_id, maximum)}
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_vehicle_dispatch_state":
                arguments = params.get("arguments", {}); vehicle_id = arguments.get("vehicle_id"); maximum = arguments.get("maximum_entities", 20000)
                if not isinstance(vehicle_id, int): return _error(-32602, "vehicle_id must be an integer", request_id)
                if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 100000: return _error(-32602, "maximum_entities must be an integer from 1 to 100000", request_id)
                try:
                    probe = bridge.vehicle_dispatch_state(vehicle_id, maximum)
                except BridgeError as exc:
                    # An already-open save still runs the previous Lua module
                    # until its next reload. Keep the stable MCP tool usable
                    # through older verified Bridge calls, with motion marked
                    # unavailable instead of reading Bridge files directly.
                    if "UNKNOWN_COMMAND" not in str(exc): raise
                    static_vehicle = _index(bridge).vehicle_by_id.get(vehicle_id)
                    if static_vehicle is None: return _error(-32001, f"ENTITY_NOT_FOUND: vehicle {vehicle_id}", request_id)
                    line_id = static_vehicle.get("line_id")
                    probe = {"vehicle": {"entity_id": vehicle_id, "name": static_vehicle.get("name"), "line_id": line_id,
                                         "raw_state": static_vehicle.get("raw_state"), "_live_unavailable": True},
                             "demand": bridge.line_demand(line_id, maximum) if isinstance(line_id, int) else {}}
                try: result = vehicle_dispatch_state(_index(bridge), vehicle_id, probe.get("vehicle"), probe.get("demand"))
                except ValueError as exc: return _error(-32001, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_line_demand":
                arguments = params.get("arguments", {})
                line_id = arguments.get("line_id")
                maximum_entities = arguments.get("maximum_entities", 20000)
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                if not isinstance(maximum_entities, int) or isinstance(maximum_entities, bool) or not 1 <= maximum_entities <= 100000:
                    return _error(-32602, "maximum_entities must be an integer from 1 to 100000", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(bridge.line_demand(line_id, maximum_entities))}
            if name == "get_transport_network_summary":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).network_summary())}
            if name == "find_lines_without_vehicles":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).lines_without_vehicles())}
            if name == "find_unassigned_vehicles":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).unassigned_vehicles())}
            if name == "find_suspicious_lines":
                threshold = params.get("arguments", {}).get("vehicle_threshold", 20)
                if not isinstance(threshold, int) or threshold < 1: return _error(-32602, "vehicle_threshold must be a positive integer", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).suspicious_lines(threshold))}
            if name == "get_vehicle_operating_state":
                vehicle_id = params.get("arguments", {}).get("vehicle_id")
                if not isinstance(vehicle_id, int): return _error(-32602, "vehicle_id must be an integer", request_id)
                result = _index(bridge).vehicle_operating_state(vehicle_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: vehicle {vehicle_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_station_operating_state":
                station_id = params.get("arguments", {}).get("station_id")
                if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
                result = _index(bridge).station_operating_state(station_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_line_operating_summary":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                result = _index(bridge).line_operating_summary(line_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_line_scorecard":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                result = _index(bridge).line_scorecard(line_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name in {"diagnose_line_structure", "diagnose_transport_network"}:
                arguments = params.get("arguments", {})
                long_headway, short_headway, high_vehicles = arguments.get("long_headway_seconds", 600), arguments.get("short_headway_seconds", 120), arguments.get("high_vehicle_count", 10)
                if not isinstance(long_headway, (int, float)) or isinstance(long_headway, bool) or long_headway <= 0: return _error(-32602, "long_headway_seconds must be positive", request_id)
                if not isinstance(short_headway, (int, float)) or isinstance(short_headway, bool) or short_headway <= 0: return _error(-32602, "short_headway_seconds must be positive", request_id)
                if not isinstance(high_vehicles, int) or high_vehicles < 1: return _error(-32602, "high_vehicle_count must be a positive integer", request_id)
                index = _index(bridge)
                if name == "diagnose_line_structure":
                    line_id = arguments.get("line_id")
                    if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                    result = index.diagnose_line_structure(line_id, long_headway, short_headway, high_vehicles)
                    if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                else:
                    result = index.diagnose_transport_network(long_headway, short_headway, high_vehicles)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "compare_lines":
                line_ids = params.get("arguments", {}).get("line_ids")
                if not isinstance(line_ids, list) or not line_ids or len(line_ids) > 100 or not all(isinstance(line_id, int) for line_id in line_ids): return _error(-32602, "line_ids must be a non-empty list of up to 100 integers", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).compare_lines(line_ids))}
            if name == "rank_lines":
                arguments = params.get("arguments", {})
                metric, order, limit = arguments.get("metric"), arguments.get("order", "desc"), arguments.get("limit", 20)
                if order not in {"asc", "desc"}: return _error(-32602, "order must be asc or desc", request_id)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                try: result = _index(bridge).rank_lines(metric, order, limit)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_station_connectivity":
                station_id = params.get("arguments", {}).get("station_id")
                if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
                result = _index(bridge).station_connectivity(station_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name in {"rank_transfer_stations", "rank_vehicles_by_capacity"}:
                arguments = params.get("arguments", {})
                limit, order = arguments.get("limit", 20), arguments.get("order", "desc")
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                if order not in {"asc", "desc"}: return _error(-32602, "order must be asc or desc", request_id)
                result = _index(bridge).rank_transfer_stations(limit) if name == "rank_transfer_stations" else _index(bridge).rank_vehicles_by_capacity(order, limit)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "find_station_route":
                arguments = params.get("arguments", {})
                source, target = arguments.get("source_station_id"), arguments.get("target_station_id")
                if not isinstance(source, int) or not isinstance(target, int): return _error(-32602, "source_station_id and target_station_id must be integers", request_id)
                result = _index(bridge).find_station_route(source, target)
                if result is None: return _error(-32001, "ENTITY_NOT_FOUND: source or target station not found", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_fleet_summary":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).fleet_summary())}
            if name == "get_fleet_profile":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).fleet_profile())}
            if name == "get_line_fleet_profile":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                result = _index(bridge).line_fleet_profile(line_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_line_profile":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                result = _intelligence(bridge).line_profile(line_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "classify_lines":
                arguments = params.get("arguments", {})
                values = {key: arguments.get(key, default) for key, default in {"low_fleet_threshold": 1, "long_route_stop_threshold": 6, "high_frequency_seconds": 180, "high_capacity_threshold": 500}.items()}
                if not isinstance(values["low_fleet_threshold"], int) or values["low_fleet_threshold"] < 0: return _error(-32602, "low_fleet_threshold must be a non-negative integer", request_id)
                if not isinstance(values["long_route_stop_threshold"], int) or values["long_route_stop_threshold"] < 1: return _error(-32602, "long_route_stop_threshold must be a positive integer", request_id)
                if not isinstance(values["high_frequency_seconds"], (int, float)) or values["high_frequency_seconds"] <= 0: return _error(-32602, "high_frequency_seconds must be positive", request_id)
                if not isinstance(values["high_capacity_threshold"], (int, float)) or values["high_capacity_threshold"] < 0: return _error(-32602, "high_capacity_threshold must be non-negative", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_intelligence(bridge).classify_lines(**values))}
            if name == "find_line_outliers":
                arguments = params.get("arguments", {})
                metric, method, percentile = arguments.get("metric"), arguments.get("method", "iqr"), arguments.get("percentile", .05)
                if not isinstance(percentile, (int, float)) or isinstance(percentile, bool): return _error(-32602, "percentile must be numeric", request_id)
                try: result = _intelligence(bridge).line_outliers(metric, method, float(percentile))
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "find_similar_lines":
                arguments = params.get("arguments", {})
                line_id, limit = arguments.get("line_id"), arguments.get("limit", 10)
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                result = _intelligence(bridge).similar_lines(line_id, limit)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: line {line_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_station_profile":
                station_id = params.get("arguments", {}).get("station_id")
                if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
                result = _intelligence(bridge).station_profile(station_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "rank_station_hubs":
                arguments = params.get("arguments", {})
                metric, limit = arguments.get("metric", "line_count"), arguments.get("limit", 20)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                try: result = _intelligence(bridge).rank_station_hubs(metric, limit)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "analyze_network_reachability":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_intelligence(bridge).reachability())}
            if name == "find_isolated_station_clusters":
                limit = params.get("arguments", {}).get("max_station_count", 10)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "max_station_count must be an integer from 1 to 100", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_intelligence(bridge).isolated_clusters(limit))}
            if name == "get_network_recommendations":
                limit = params.get("arguments", {}).get("limit", 20)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_intelligence(bridge).recommendations(limit))}
            if name == "analyze_network":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_intelligence(bridge).analyze())}
            if name == "detect_network_problems":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_planning(bridge).detect_problems())}
            if name == "analyze_problem_impact":
                problem_id = params.get("arguments", {}).get("problem_id")
                if not isinstance(problem_id, str) or not problem_id: return _error(-32602, "problem_id must be a non-empty string", request_id)
                result = _planning(bridge).problem_impact(problem_id)
                if result is None: return _error(-32001, f"PROBLEM_NOT_FOUND_OR_UNSUPPORTED: {problem_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "find_alternative_routes":
                arguments = params.get("arguments", {}); source, target, maximum = arguments.get("source_station_id"), arguments.get("target_station_id"), arguments.get("max_routes", 3)
                if not isinstance(source, int) or not isinstance(target, int): return _error(-32602, "source_station_id and target_station_id must be integers", request_id)
                if not isinstance(maximum, int) or not 1 <= maximum <= 5: return _error(-32602, "max_routes must be an integer from 1 to 5", request_id)
                result = _planning(bridge).route(source, target, max_routes=maximum)
                if result is None: return _error(-32001, "ENTITY_NOT_FOUND: source or target station not found", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name in {"find_articulation_stations", "find_bridge_connections", "analyze_network_resilience"}:
                resilience = _planning(bridge).resilience()
                result = resilience["articulation_stations"] if name == "find_articulation_stations" else resilience["bridge_connections"] if name == "find_bridge_connections" else resilience
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"snapshot_sequence": resilience["snapshot_sequence"], "source_status": "DERIVED", "results": result} if isinstance(result, list) else result)}
            if name == "simulate_station_connection":
                arguments = params.get("arguments", {}); source, target = arguments.get("station_a"), arguments.get("station_b")
                if not isinstance(source, int) or not isinstance(target, int): return _error(-32602, "station_a and station_b must be integers", request_id)
                try: result = _planning(bridge).simulate_connection(source, target)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "simulate_line_failure":
                line_id = params.get("arguments", {}).get("line_id")
                if not isinstance(line_id, int): return _error(-32602, "line_id must be an integer", request_id)
                try: result = _planning(bridge).simulate_line_failure(line_id)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "simulate_station_failure":
                station_id = params.get("arguments", {}).get("station_id")
                if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
                result = _planning(bridge).simulate_station_failure(station_id)
                if result is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "simulate_network_scenario":
                mutations = params.get("arguments", {}).get("mutations")
                if not isinstance(mutations, list) or len(mutations) > 20: return _error(-32602, "mutations must be an array of up to 20 items", request_id)
                try: result = _planning(bridge).simulate(mutations)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "get_planning_options":
                limit = params.get("arguments", {}).get("limit", 20)
                if not isinstance(limit, int) or not 1 <= limit <= 100: return _error(-32602, "limit must be an integer from 1 to 100", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_planning(bridge).planning_options(limit))}
            if name == "plan_new_line_candidates":
                limit = params.get("arguments", {}).get("limit", 10)
                try: result = _planning(bridge).new_line_candidates(limit)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "compare_network_scenarios":
                scenarios = params.get("arguments", {}).get("scenarios")
                try: result = _planning(bridge).compare_scenarios(scenarios)
                except ValueError as exc: return _error(-32602, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "analyze_and_plan_network":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_planning(bridge).analyze_and_plan())}
            if name == "get_operation_capabilities":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"capabilities": operation_capabilities(), "global_write_default": False, "live_write_enabled": False})}
            if name == "propose_operation":
                arguments = params.get("arguments", {})
                operation_type, target, operation_parameters = arguments.get("operation_type"), arguments.get("target"), arguments.get("parameters")
                if not isinstance(operation_type, str) or not isinstance(target, dict) or not isinstance(operation_parameters, dict): return _error(-32602, "operation_type must be a string and target/parameters must be objects", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_operations(bridge).propose(operation_type, target, operation_parameters))}
            if name == "validate_operation":
                arguments = params.get("arguments", {}); operation_id = arguments.get("operation_id"); force_refresh = arguments.get("force_refresh", False)
                if not isinstance(operation_id, str) or not operation_id or not isinstance(force_refresh, bool): return _error(-32602, "operation_id must be non-empty and force_refresh must be a boolean", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_operations(bridge).validate(operation_id, force_refresh))}
            if name == "execute_operation":
                return _error(-32601, "DIRECT_OPERATION_EXECUTION_DISABLED: create, plan, approve, and continue a Task instead", request_id)
            if name == "get_operation":
                operation_id = params.get("arguments", {}).get("operation_id")
                if not isinstance(operation_id, str) or not operation_id: return _error(-32602, "operation_id must be a non-empty string", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_operations(bridge).get(operation_id))}
            if name == "list_recent_operations":
                limit = params.get("arguments", {}).get("limit", 20)
                if not isinstance(limit, int) or not 1 <= limit <= 50: return _error(-32602, "limit must be an integer from 1 to 50", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_operations(bridge).recent(limit))}
            if name == "create_rollback_operation":
                operation_id = params.get("arguments", {}).get("operation_id")
                if not isinstance(operation_id, str) or not operation_id: return _error(-32602, "operation_id must be a non-empty string", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_operations(bridge).rollback(operation_id))}
            if name == "get_task_capabilities":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"goals": goal_capabilities(), "one_mutation_per_continue": True, "default_policy": "MANUAL"})}
            if name == "create_task":
                arguments = params.get("arguments", {}); goal_type, goal = arguments.get("goal_type"), arguments.get("goal")
                if not isinstance(goal_type, str) or not isinstance(goal, dict): return _error(-32602, "goal_type must be a string and goal must be an object", request_id)
                result = _tasks(bridge).create(goal_type, goal, arguments.get("policy", "MANUAL"), arguments.get("max_steps", 1), arguments.get("max_replans", 3), arguments.get("max_write_operations", 1))
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name in {"plan_task", "get_task", "get_next_task_step", "approve_task_step", "continue_task", "cancel_task", "explain_task"}:
                task_id = params.get("arguments", {}).get("task_id")
                if not isinstance(task_id, str) or not task_id: return _error(-32602, "task_id must be a non-empty string", request_id)
                tasks = _tasks(bridge)
                result = tasks.plan(task_id) if name == "plan_task" else tasks.get(task_id) if name == "get_task" else {"task_id": task_id, "status": tasks.get(task_id).get("status"), "next_step": tasks.get(task_id).get("next_step")} if name == "get_next_task_step" else tasks.approve(task_id) if name == "approve_task_step" else tasks.continue_task(task_id) if name == "continue_task" else tasks.cancel(task_id) if name == "cancel_task" else tasks.explain(task_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
            if name == "list_tasks":
                limit = params.get("arguments", {}).get("limit", 20)
                if not isinstance(limit, int) or not 1 <= limit <= 50: return _error(-32602, "limit must be an integer from 1 to 50", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_tasks(bridge).recent(limit))}
            if name == "find_low_load_vehicles":
                threshold = params.get("arguments", {}).get("occupancy_threshold", 0.2)
                if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1: return _error(-32602, "occupancy_threshold must be between 0 and 1", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).low_load_vehicles(float(threshold)))}
            if name == "find_high_waiting_stations":
                threshold = params.get("arguments", {}).get("waiting_threshold", 100)
                if not isinstance(threshold, int) or threshold < 0: return _error(-32602, "waiting_threshold must be a non-negative integer", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).high_waiting_stations(threshold))}
            if name == "find_stations_without_lines":
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(_index(bridge).stations_without_lines())}
            return _error(-32602, f"unknown tool: {name}", request_id)
        if method == "resources/read":
            uri = params.get("uri")
            index = _index(bridge)
            resource_values = {"tpf2://game": index.overview(), "tpf2://network": index.network_summary(), "tpf2://network/lines": [_index(bridge)._line(x) for x in index.line_by_id.values()], "tpf2://network/stations": [_index(bridge)._station(x) for x in index.station_by_id.values()], "tpf2://network/vehicles": [_index(bridge)._vehicle(x) for x in index.vehicle_by_id.values()], "tpf2://cargo-types": index.cargo_types(), "tpf2://capabilities": index.capabilities(), "tpf2://agent-operations": agent_operations_guide()}
            if uri in resource_values:
                return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(resource_values[uri], ensure_ascii=False)}]}}
            return _error(-32602, "unknown resource", request_id)
    except BridgeError as exc:
        return _error(-32001, str(exc), request_id)
    return _error(-32601, f"method not found: {method}", request_id)


def main() -> int:
    # Windows console code pages otherwise leak into redirected stdio and can
    # corrupt valid UTF-8 game names in JSON-RPC captures.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    bridge = _bridge()
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle(message, bridge)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        except json.JSONDecodeError as exc:
            print(json.dumps(_error(-32700, f"parse error: {exc.msg}")), flush=True)
        except Exception as exc:  # Keep stdio protocol alive after unexpected failures.
            print(json.dumps(_error(-32603, f"internal error: {exc}")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
