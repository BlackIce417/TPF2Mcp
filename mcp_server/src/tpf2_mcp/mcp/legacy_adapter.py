"""Historical file-bridge handlers, loaded only for explicit MockBridge calls.
Production MCP never imports this adapter or exposes its tools.
"""
from __future__ import annotations
import json
import time
from tpf2_mcp.transport.bridge import BridgeError
from tpf2_mcp.common.config import snapshot_cache_seconds, state_dir
from tpf2_mcp.repositories.snapshot import SnapshotIndex
from tpf2_mcp.algorithms.analytics import NetworkIntelligenceIndex
from tpf2_mcp.algorithms.planning import DecisionSupport
from tpf2_mcp.services.operations import OperationController, capabilities as operation_capabilities
from tpf2_mcp.services.tasks import TaskOrchestrator, goal_capabilities
from tpf2_mcp.services.dispatch import agent_operations_guide, station_waiting_state, vehicle_dispatch_state
from tpf2_mcp.mcp.server import _tool_result, _error
_index_cache = {}
_intelligence_cache = {}
_planning_cache = {}
_operation_controllers = {}
_task_orchestrators = {}
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


def call(name, params, bridge, request_id):
    if name == "probe_vehicle_speed_control":
        if params.get("arguments", {}):
            return _error(-32602, "probe_vehicle_speed_control accepts no arguments or write options", request_id)
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(bridge.probe_vehicle_speed_control())}
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
        arguments = params.get("arguments", {}); station_id = arguments.get("station_id"); maximum = arguments.get("maximum_entities", 20000)
        if not isinstance(station_id, int): return _error(-32602, "station_id must be an integer", request_id)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 100 <= maximum <= 50000: return _error(-32602, "maximum_entities must be an integer from 100 to 50000", request_id)
        index = _index(bridge); station = index.station_operating_state(station_id); connectivity = index.station_connectivity(station_id)
        if station is None: return _error(-32001, f"ENTITY_NOT_FOUND: station {station_id}", request_id)
        line_ids = sorted({line["entity_id"] for line in index.lines_by_station.get(station_id, []) if isinstance(line.get("entity_id"), int)})
        lines = [index.line_summary(line_id) for line_id in line_ids]
        demands = {}
        for line_id in line_ids:
            try:
                demands[line_id] = bridge.line_demand(line_id, maximum)
            except BridgeError as exc:
                demands[line_id] = {"line_id": line_id, "passengers": {"status": "UNAVAILABLE"},
                                    "cargo": {"status": "UNAVAILABLE"}, "errors": {"bridge": str(exc)}}
        waiting = station_waiting_state(index, station_id, demands)
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"schema_version": 1, "station": station, "connectivity": connectivity, "lines": lines, "waiting": waiting})}
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


def resource(params, bridge, request_id):
    uri = params.get("uri")
    index = _index(bridge)
    resource_values = {"tpf2://game": index.overview(), "tpf2://network": index.network_summary(), "tpf2://network/lines": [_index(bridge)._line(x) for x in index.line_by_id.values()], "tpf2://network/stations": [_index(bridge)._station(x) for x in index.station_by_id.values()], "tpf2://network/vehicles": [_index(bridge)._vehicle(x) for x in index.vehicle_by_id.values()], "tpf2://cargo-types": index.cargo_types(), "tpf2://capabilities": index.capabilities(), "tpf2://agent-operations": agent_operations_guide()}
    if uri in resource_values:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(resource_values[uri], ensure_ascii=False)}]}}
    return _error(-32602, "unknown resource", request_id)
