from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..operations.capabilities import capability


def _goal_status(operation_type: str) -> tuple[str, str | None]:
    item = capability(operation_type)
    if not item or not item.get("engine_verified"):
        return "ENGINE_ONLY", "No engine-verified operation exists."
    if not item.get("controller_supported"):
        return "CONTROLLER_READY", "Engine command is verified but Controller support is unavailable."
    if not item.get("task_supported"):
        return "TASK_READY", "Controller support exists but Task support is unavailable."
    if not item.get("runtime_enabled"):
        return "EXECUTABLE_BUT_DISABLED", "Product path is ready but the Lua runtime write kill switch is disabled."
    return "EXECUTABLE", None


def goal_capabilities() -> list[dict[str, Any]]:
    line = capability("RENAME_LINE")
    buy = capability("BUY_VEHICLE")
    assign = capability("ASSIGN_VEHICLE_TO_LINE")
    create = capability("CREATE_LINE")
    return [
        {"goal_type": "RENAME_LINE_GOAL", "status": _goal_status("RENAME_LINE")[0], "operation_type": "RENAME_LINE", "reason": _goal_status("RENAME_LINE")[1]},
        {"goal_type": "RESTORE_LINE_NAME_GOAL", "status": _goal_status("RENAME_LINE")[0], "operation_type": "RENAME_LINE", "reason": _goal_status("RENAME_LINE")[1]},
        {"goal_type": "INSPECT_NETWORK_GOAL", "status": "PLAN_ONLY", "reason": "Read-only network intelligence is available."},
        {"goal_type": "IMPROVE_CONNECTIVITY_GOAL", "status": "PLAN_ONLY", "reason": "No verified infrastructure construction operation exists."},
        {"goal_type": "REDUCE_STRUCTURAL_ISOLATION_GOAL", "status": "PLAN_ONLY", "reason": "No verified infrastructure construction operation exists."},
        {"goal_type": "BUY_VEHICLE_GOAL", "status": _goal_status("BUY_VEHICLE")[0], "operation_type": "BUY_VEHICLE", "reason": _goal_status("BUY_VEHICLE")[1]},
        {"goal_type": "ASSIGN_VEHICLE_TO_LINE_GOAL", "status": _goal_status("ASSIGN_VEHICLE_TO_LINE")[0], "operation_type": "ASSIGN_VEHICLE_TO_LINE", "reason": _goal_status("ASSIGN_VEHICLE_TO_LINE")[1]},
        {"goal_type": "EXPAND_LINE_WITH_VEHICLE_GOAL", "status": "EXECUTABLE_BUT_DISABLED" if _goal_status("BUY_VEHICLE")[0] == _goal_status("ASSIGN_VEHICLE_TO_LINE")[0] == "EXECUTABLE_BUT_DISABLED" else "BLOCKED", "operation_type": "BUY_VEHICLE", "reason": "Both required operations must be product-ready."},
        {"goal_type": "BUY_AND_ASSIGN_VEHICLE_GOAL", "status": "EXECUTABLE_BUT_DISABLED" if _goal_status("BUY_VEHICLE")[0] == _goal_status("ASSIGN_VEHICLE_TO_LINE")[0] == "EXECUTABLE_BUT_DISABLED" else "BLOCKED", "operation_type": "BUY_VEHICLE", "reason": "Both required operations must be product-ready."},
        {"goal_type": "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL", "status": _goal_status("CREATE_LINE_FROM_SOURCE_ROUTE")[0], "operation_type": "CREATE_LINE_FROM_SOURCE_ROUTE", "reason": _goal_status("CREATE_LINE_FROM_SOURCE_ROUTE")[1]},
        {"goal_type": "CREATE_LINE_GOAL", "status": _goal_status("CREATE_LINE")[0], "operation_type": "CREATE_LINE", "reason": _goal_status("CREATE_LINE")[1]},
        {"goal_type": "CREATE_AND_STAFF_LINE_GOAL", "status": "EXECUTABLE_BUT_DISABLED" if _goal_status("CREATE_LINE")[0] == _goal_status("BUY_VEHICLE")[0] == _goal_status("ASSIGN_VEHICLE_TO_LINE")[0] == "EXECUTABLE_BUT_DISABLED" else "BLOCKED", "operation_type": "CREATE_LINE", "reason": "Creates a route, then discovers and staffs the new line one mutation at a time."},
        {"goal_type": "CREATE_AND_CONFIGURE_LINE_GOAL", "status": "EXECUTABLE_BUT_DISABLED" if _goal_status("CREATE_LINE")[0] == _goal_status("SET_LINE_STOPS")[0] == _goal_status("BUY_VEHICLE")[0] == _goal_status("ASSIGN_VEHICLE_TO_LINE")[0] == "EXECUTABLE_BUT_DISABLED" else "BLOCKED", "operation_type": "CREATE_LINE", "reason": "Creates, explicitly configures, purchases, and assigns 1–4 vehicles through separately verified mutations."},
        {"goal_type": "SET_LINE_STOPS_GOAL", "status": _goal_status("SET_LINE_STOPS")[0], "operation_type": "SET_LINE_STOPS", "reason": _goal_status("SET_LINE_STOPS")[1]},
        {"goal_type": "SET_LINE_STOP_POLICY_GOAL", "status": _goal_status("SET_LINE_STOP_POLICY")[0], "operation_type": "SET_LINE_STOP_POLICY", "reason": _goal_status("SET_LINE_STOP_POLICY")[1]},
        {"goal_type": "HOLD_VEHICLE_AT_TERMINAL_GOAL", "status": _goal_status("HOLD_VEHICLE_AT_TERMINAL")[0], "operation_type": "HOLD_VEHICLE_AT_TERMINAL", "reason": _goal_status("HOLD_VEHICLE_AT_TERMINAL")[1]},
        {"goal_type": "RELEASE_VEHICLE_FROM_HOLD_GOAL", "status": _goal_status("RELEASE_VEHICLE_FROM_HOLD")[0], "operation_type": "RELEASE_VEHICLE_FROM_HOLD", "reason": _goal_status("RELEASE_VEHICLE_FROM_HOLD")[1]},
        {"goal_type": "SELL_VEHICLE_GOAL", "status": _goal_status("SELL_VEHICLE")[0], "operation_type": "SELL_VEHICLE", "reason": _goal_status("SELL_VEHICLE")[1]},
        {"goal_type": "OPTIMIZE_LINE_GOAL", "status": "PLAN_ONLY", "reason": "Structural evidence is available, but live load, waiting, and profit are unavailable for autonomous mutation."},
    ]


def goal_capability(goal_type: str) -> dict[str, Any] | None:
    return next((item for item in goal_capabilities() if item["goal_type"] == goal_type), None)


def satisfied(goal_type: str, goal: dict[str, Any], index: Any) -> tuple[bool, dict[str, Any]]:
    if goal_type in {"RENAME_LINE_GOAL", "RESTORE_LINE_NAME_GOAL"}:
        line_id, desired_name = goal.get("line_id"), goal.get("desired_name")
        line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
        return bool(line and line.get("name") == desired_name), {"line_id": line_id, "expected_name": desired_name, "actual_name": line.get("name") if line else None}
    if goal_type == "BUY_VEHICLE_GOAL":
        vehicle_id = goal.get("created_vehicle_id")
        return isinstance(vehicle_id, int) and vehicle_id in index.vehicle_by_id, {"created_vehicle_id": vehicle_id, "exists": vehicle_id in index.vehicle_by_id if isinstance(vehicle_id, int) else False}
    if goal_type == "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL":
        line_id = goal.get("created_line_id")
        line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
        return bool(line and line.get("name") == goal.get("name")), {"created_line_id": line_id, "exists": line is not None, "actual_name": line.get("name") if line else None}
    if goal_type == "CREATE_LINE_GOAL":
        line_id = goal.get("created_line_id")
        line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
        expected = [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")]
        observed = [stop.get("station_id") for stop in line.get("stops", [])] if line else []
        return bool(line and line.get("name") == goal.get("name") and observed == expected), {"created_line_id": line_id, "expected_route": expected, "observed_route": observed}
    if goal_type == "CREATE_AND_STAFF_LINE_GOAL":
        line_id = goal.get("created_line_id")
        line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
        expected = [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")]
        vehicles = goal.get("assigned_vehicle_ids", [])
        route_ok = bool(line and [stop.get("station_id") for stop in line.get("stops", [])] == expected)
        fleet_ok = len(vehicles) == goal.get("vehicle_count") and all(index.vehicle_by_id.get(value, {}).get("line_id") == line_id for value in vehicles)
        return route_ok and fleet_ok, {"created_line_id": line_id, "route_ok": route_ok, "assigned_vehicle_ids": vehicles, "fleet_ok": fleet_ok}
    if goal_type == "CREATE_AND_CONFIGURE_LINE_GOAL":
        line_id = goal.get("created_line_id")
        line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
        expected = [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")]
        observed = [stop.get("station_id") for stop in line.get("stops", [])] if line else []
        vehicle_ids = goal.get("assigned_vehicle_ids", [])
        fleet_ok = len(vehicle_ids) == goal.get("vehicle_count", 1) and all(index.vehicle_by_id.get(vehicle_id, {}).get("line_id") == line_id for vehicle_id in vehicle_ids)
        done = bool(line and observed == expected and fleet_ok)
        return done, {"created_line_id": line_id, "assigned_vehicle_ids": vehicle_ids, "expected_route": expected, "observed_route": observed, "fleet_ok": fleet_ok}
    if goal_type == "SET_LINE_STOPS_GOAL":
        line = index.line_by_id.get(goal.get("line_id"))
        expected = [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")]
        observed = [stop.get("station_id") for stop in line.get("stops", [])] if line else []
        return observed == expected, {"line_id": goal.get("line_id"), "expected_route": expected, "observed_route": observed}
    if goal_type == "SET_LINE_STOP_POLICY_GOAL":
        line, stop_index = index.line_by_id.get(goal.get("line_id")), goal.get("stop_index")
        stop = line.get("stops", [])[stop_index] if line and isinstance(stop_index, int) and stop_index < len(line.get("stops", [])) else None
        expected = {"load_mode": goal.get("load_mode"), "min_waiting_time": goal.get("min_waiting_time"), "max_waiting_time": goal.get("max_waiting_time")}
        observed = stop.get("policy") if stop else None
        return observed == expected, {"line_id": goal.get("line_id"), "stop_index": stop_index, "expected_policy": expected, "observed_policy": observed}
    if goal_type in {"HOLD_VEHICLE_AT_TERMINAL_GOAL", "RELEASE_VEHICLE_FROM_HOLD_GOAL"}:
        vehicle = index.vehicle_by_id.get(goal.get("vehicle_id"))
        control = vehicle.get("departure_control") if vehicle else None
        expected_manual = goal_type == "HOLD_VEHICLE_AT_TERMINAL_GOAL"
        expected_auto = not expected_manual
        observed_auto = vehicle.get("raw_autoDeparture") if vehicle else None
        done = bool(control and control.get("manual") is expected_manual and control.get("command_confirmed") is True and observed_auto is expected_auto)
        return done, {"vehicle_id": goal.get("vehicle_id"), "expected_manual_departure": expected_manual, "observed_auto_departure": observed_auto, "observed_departure_control": control}
    if goal_type == "SELL_VEHICLE_GOAL":
        vehicle_id = goal.get("vehicle_id")
        return vehicle_id not in index.vehicle_by_id, {"vehicle_id": vehicle_id, "vehicle_present": vehicle_id in index.vehicle_by_id}
    if goal_type in {"ASSIGN_VEHICLE_TO_LINE_GOAL", "EXPAND_LINE_WITH_VEHICLE_GOAL", "BUY_AND_ASSIGN_VEHICLE_GOAL"}:
        vehicle_id = goal.get("vehicle_id") or goal.get("created_vehicle_id")
        line_id = goal.get("line_id") if goal_type != "BUY_AND_ASSIGN_VEHICLE_GOAL" else goal.get("target_line_id")
        vehicle = index.vehicle_by_id.get(vehicle_id) if isinstance(vehicle_id, int) else None
        return bool(vehicle and vehicle.get("line_id") == line_id), {"vehicle_id": vehicle_id, "expected_line_id": line_id, "actual_line_id": vehicle.get("line_id") if vehicle else None}
    return False, {"reason": "This goal is plan-only and has no executable satisfaction predicate."}


def scope_for(goal_type: str, goal: dict[str, Any]) -> dict[str, Any]:
    if goal_type in {"RENAME_LINE_GOAL", "RESTORE_LINE_NAME_GOAL"} and isinstance(goal.get("line_id"), int):
        return {"line_ids": [goal["line_id"]], "operation_types": ["RENAME_LINE"]}
    if goal_type == "BUY_VEHICLE_GOAL": return {"line_ids": [], "vehicle_ids": [goal.get("source_vehicle_id")], "depot_ids": [goal.get("depot_id")], "operation_types": ["BUY_VEHICLE"]}
    if goal_type == "ASSIGN_VEHICLE_TO_LINE_GOAL": return {"line_ids": [goal.get("line_id")], "vehicle_ids": [goal.get("vehicle_id")], "operation_types": ["ASSIGN_VEHICLE_TO_LINE"]}
    if goal_type == "EXPAND_LINE_WITH_VEHICLE_GOAL": return {"line_ids": [goal.get("line_id")], "vehicle_ids": [goal.get("source_vehicle_id")], "depot_ids": [goal.get("depot_id")], "operation_types": ["BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"]}
    if goal_type == "BUY_AND_ASSIGN_VEHICLE_GOAL": return {"line_ids": [goal.get("target_line_id")], "vehicle_ids": [goal.get("source_vehicle_id")], "depot_ids": [goal.get("depot_id")], "operation_types": ["BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"]}
    if goal_type == "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL": return {"line_ids": [goal.get("source_line_id")], "operation_types": ["CREATE_LINE_FROM_SOURCE_ROUTE"]}
    if goal_type == "CREATE_LINE_GOAL": return {"station_ids": [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")], "line_ids": [], "operation_types": ["CREATE_LINE"], "max_new_lines": 1}
    if goal_type == "CREATE_AND_STAFF_LINE_GOAL": return {"station_ids": [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")], "line_ids": [], "vehicle_ids": [goal.get("source_vehicle_id")], "depot_ids": [goal.get("depot_id")], "operation_types": ["CREATE_LINE", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"], "max_new_lines": 1}
    if goal_type == "CREATE_AND_CONFIGURE_LINE_GOAL": return {"station_ids": [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")], "line_ids": [], "vehicle_ids": [goal.get("source_vehicle_id")], "depot_ids": [goal.get("depot_id")], "operation_types": ["CREATE_LINE", "SET_LINE_STOPS", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"], "max_new_lines": 1}
    if goal_type == "SET_LINE_STOPS_GOAL": return {"station_ids": [goal.get("start_station_id"), *goal.get("via_station_ids", []), goal.get("end_station_id")], "line_ids": [goal.get("line_id")], "operation_types": ["SET_LINE_STOPS"]}
    if goal_type == "SET_LINE_STOP_POLICY_GOAL": return {"line_ids": [goal.get("line_id")], "operation_types": ["SET_LINE_STOP_POLICY"]}
    if goal_type == "HOLD_VEHICLE_AT_TERMINAL_GOAL": return {"line_ids": [], "vehicle_ids": [goal.get("vehicle_id")], "operation_types": ["HOLD_VEHICLE_AT_TERMINAL"]}
    if goal_type == "RELEASE_VEHICLE_FROM_HOLD_GOAL": return {"line_ids": [], "vehicle_ids": [goal.get("vehicle_id")], "operation_types": ["RELEASE_VEHICLE_FROM_HOLD"]}
    if goal_type == "SELL_VEHICLE_GOAL": return {"line_ids": [], "vehicle_ids": [goal.get("vehicle_id")], "operation_types": ["SELL_VEHICLE"]}
    return {"line_ids": [], "vehicle_ids": [], "depot_ids": [], "operation_types": []}


def planned_steps(goal_type: str, goal: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if goal_type in {"RENAME_LINE_GOAL", "RESTORE_LINE_NAME_GOAL"}:
        return [{"step_type": "GAME_OPERATION", "operation_type": "RENAME_LINE", "target": {"line_id": goal["line_id"]}, "parameters": {"name": goal["desired_name"]}, "reason": evidence}]
    if goal_type == "BUY_VEHICLE_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "BUY_VEHICLE", "target": {"depot_id": goal["depot_id"]}, "parameters": {"source_vehicle_id": goal["source_vehicle_id"]}, "reason": evidence}]
    if goal_type == "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "CREATE_LINE_FROM_SOURCE_ROUTE", "target": {"source_line_id": goal["source_line_id"]}, "parameters": {"name": goal["name"]}, "reason": evidence}]
    if goal_type == "CREATE_LINE_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "CREATE_LINE", "target": {}, "parameters": {"name": goal["name"], "start_station_id": goal["start_station_id"], "via_station_ids": goal.get("via_station_ids", []), "end_station_id": goal["end_station_id"], "transport_mode": goal.get("transport_mode")}, "reason": evidence}]
    if goal_type == "CREATE_AND_STAFF_LINE_GOAL":
        steps = [{"step_type": "GAME_OPERATION", "operation_type": "CREATE_LINE", "target": {}, "parameters": {"name": goal["name"], "start_station_id": goal["start_station_id"], "via_station_ids": goal.get("via_station_ids", []), "end_station_id": goal["end_station_id"], "transport_mode": goal.get("transport_mode"), "terminal_selectors": goal.get("terminal_selectors", {})}, "reason": evidence}]
        for _ in range(goal["vehicle_count"]):
            steps.extend([{"step_type": "GAME_OPERATION", "operation_type": "BUY_VEHICLE", "target": {"depot_id": goal["depot_id"]}, "parameters": {"source_vehicle_id": goal["source_vehicle_id"]}, "reason": "Buy deterministic template vehicle."}, {"step_type": "GAME_OPERATION", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": None, "line_id": None}, "parameters": {"stop_index": 0}, "reason": "Assign the newly verified purchase."}])
        return steps
    if goal_type == "CREATE_AND_CONFIGURE_LINE_GOAL":
        route = {"start_station_id": goal["start_station_id"], "via_station_ids": goal.get("via_station_ids", []), "end_station_id": goal["end_station_id"], "transport_mode": goal.get("transport_mode"), "terminal_selectors": goal.get("terminal_selectors", {})}
        steps = [
            {"step_type": "GAME_OPERATION", "operation_type": "CREATE_LINE", "target": {}, "parameters": {"name": goal["name"], **route}, "reason": evidence},
            {"step_type": "GAME_OPERATION", "operation_type": "SET_LINE_STOPS", "target": {"line_id": None}, "parameters": route, "reason": "Apply and independently verify the requested route."},
        ]
        for _ in range(goal.get("vehicle_count", 1)):
            steps.extend([
                {"step_type": "GAME_OPERATION", "operation_type": "BUY_VEHICLE", "target": {"depot_id": goal["depot_id"]}, "parameters": {"source_vehicle_id": goal["source_vehicle_id"]}, "reason": "Buy one deterministic template vehicle."},
                {"step_type": "GAME_OPERATION", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": None, "line_id": None}, "parameters": {"stop_index": goal.get("stop_index", 0)}, "reason": "Assign the verified purchase to the verified configured line."},
            ])
        return steps
    if goal_type == "SET_LINE_STOPS_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "SET_LINE_STOPS", "target": {"line_id": goal["line_id"]}, "parameters": {"start_station_id": goal["start_station_id"], "via_station_ids": goal.get("via_station_ids", []), "end_station_id": goal["end_station_id"], "transport_mode": goal.get("transport_mode"), "terminal_selectors": goal.get("terminal_selectors", {})}, "reason": evidence}]
    if goal_type == "SET_LINE_STOP_POLICY_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "SET_LINE_STOP_POLICY", "target": {"line_id": goal["line_id"]}, "parameters": {"stop_index": goal["stop_index"], "load_mode": goal["load_mode"], "min_waiting_time": goal["min_waiting_time"], "max_waiting_time": goal["max_waiting_time"]}, "reason": evidence}]
    if goal_type == "HOLD_VEHICLE_AT_TERMINAL_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "HOLD_VEHICLE_AT_TERMINAL", "target": {"vehicle_id": goal["vehicle_id"]}, "parameters": {"max_hold_seconds": goal["max_hold_seconds"]}, "reason": evidence}]
    if goal_type == "RELEASE_VEHICLE_FROM_HOLD_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "RELEASE_VEHICLE_FROM_HOLD", "target": {"vehicle_id": goal["vehicle_id"]}, "parameters": {}, "reason": evidence}]
    if goal_type == "SELL_VEHICLE_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "SELL_VEHICLE", "target": {"vehicle_id": goal["vehicle_id"]}, "parameters": {"confirmation": goal["confirmation"]}, "reason": evidence}]
    if goal_type == "ASSIGN_VEHICLE_TO_LINE_GOAL":
        return [{"step_type": "GAME_OPERATION", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": goal["vehicle_id"], "line_id": goal["line_id"]}, "parameters": {"stop_index": goal.get("stop_index", 0)}, "reason": evidence}]
    if goal_type == "EXPAND_LINE_WITH_VEHICLE_GOAL":
        return [
            {"step_type": "GAME_OPERATION", "operation_type": "BUY_VEHICLE", "target": {"depot_id": goal["depot_id"]}, "parameters": {"source_vehicle_id": goal["source_vehicle_id"]}, "reason": evidence},
            {"step_type": "GAME_OPERATION", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": None, "line_id": goal["line_id"]}, "parameters": {"stop_index": goal.get("stop_index", 0)}, "reason": "Assign the newly verified purchase."},
        ]
    if goal_type == "BUY_AND_ASSIGN_VEHICLE_GOAL":
        return [
            {"step_type": "GAME_OPERATION", "operation_type": "BUY_VEHICLE", "target": {"depot_id": goal["depot_id"]}, "parameters": {"source_vehicle_id": goal["source_vehicle_id"]}, "reason": evidence},
            {"step_type": "GAME_OPERATION", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": None, "line_id": goal["target_line_id"]}, "parameters": {"stop_index": goal.get("stop_index", 0)}, "reason": "Assign the newly verified purchase."},
        ]
    return []
