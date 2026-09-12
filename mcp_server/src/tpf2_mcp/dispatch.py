from __future__ import annotations

from typing import Any

from .snapshot import SnapshotIndex


def _vehicle_count(bucket: dict[str, Any], vehicle_id: int) -> int:
    value = (bucket.get("vehicles") or {}).get(str(vehicle_id), 0)
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def vehicle_dispatch_state(index: SnapshotIndex, vehicle_id: int, live: dict[str, Any] | None,
                           demand: dict[str, Any] | None) -> dict[str, Any]:
    """Join snapshot identity/capacity with live motion and Bridge-classified load."""
    vehicle = index.vehicle_by_id.get(vehicle_id)
    if vehicle is None:
        raise ValueError(f"ENTITY_NOT_FOUND: vehicle {vehicle_id}")
    live = live or {}
    demand = demand or {}
    line_id = live.get("line_id") if isinstance(live.get("line_id"), int) else vehicle.get("line_id")
    line = index.line_by_id.get(line_id) if isinstance(line_id, int) else None
    stop_index = live.get("stop_index")
    stops = (line or {}).get("stops") or []
    next_stop = next((item for item in stops if item.get("index") == stop_index), None)
    if next_stop is None and isinstance(stop_index, int) and 0 <= stop_index < len(stops):
        next_stop = stops[stop_index]
    station = index.station_by_id.get((next_stop or {}).get("station_id"))

    passengers = _vehicle_count(demand.get("passengers") or {}, vehicle_id)
    cargo = _vehicle_count(demand.get("cargo") or {}, vehicle_id)
    cargo_by_type = []
    for item in (demand.get("cargo") or {}).get("by_cargo") or []:
        amount = _vehicle_count(item, vehicle_id)
        if amount:
            cargo_type = next((value for value in index.cargo_registry.list() if value.get("cargo_id") == item.get("cargo_id")), None)
            cargo_by_type.append({"cargo_id": item.get("cargo_id"), "cargo_name": (cargo_type or {}).get("display_name"), "amount": amount})
    capacity = vehicle.get("capacity_total")
    load_total = passengers + cargo
    capacity_known = isinstance(capacity, (int, float)) and capacity >= 0
    load_available = bool(demand) and ("passengers" in demand or "cargo" in demand)
    speed_mps = live.get("speed_mps")
    speed_kmh = live.get("speed_kmh")
    if speed_kmh is None and isinstance(speed_mps, (int, float)):
        speed_kmh = round(speed_mps * 3.6, 1)
    return {
        "schema_version": 1,
        "source_status": "ENGINE_COMPONENT_CLASSIFIED",
        "vehicle": {
            "entity_id": vehicle_id, "name": vehicle.get("name"), "line_id": line_id,
            "line_name": (line or {}).get("name"), "capacity": capacity if capacity_known else None,
            "supported_cargo_ids": vehicle.get("supported_cargo_ids") or [],
            "consist_top_speed_kmh": vehicle.get("consist_top_speed_kmh"),
            "consist_length_m": vehicle.get("consist_length_m"),
        },
        "motion": {
            "speed_kmh": speed_kmh, "speed_mps": speed_mps,
            "raw_state": live.get("raw_state", vehicle.get("raw_state")), "status": live.get("status"),
            "edge_id": live.get("edge_id"), "block_id": live.get("block_id"),
            "position_stale": bool(live.get("position_stale")),
        },
        "next_stop": {
            "stop_index": stop_index, "station_id": (next_stop or {}).get("station_id"),
            "station_name": (station or {}).get("name"),
        },
        "load": {
            "passengers": passengers if load_available else None,
            "cargo": cargo if load_available else None,
            "total": load_total if load_available else None,
            "capacity": capacity if capacity_known else None,
            "occupancy_ratio": round(load_total / capacity, 4) if load_available and capacity_known and capacity else None,
            "cargo_by_type": cargo_by_type,
        },
        "availability": {"live_motion": bool(live) and not live.get("_live_unavailable", False), "load": load_available, "capacity": capacity_known,
                         "cargo_type_breakdown": bool(cargo_by_type)},
    }


def agent_operations_guide() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rule": "Use MCP tools only; never create ad-hoc bridge-file scripts.",
        "read_workflow": ["get_dispatch_overview", "get_line_dispatch_state", "get_station_dispatch_state", "get_vehicle_dispatch_state"],
        "write_workflow": ["get_operation_capabilities", "propose_operation", "validate_operation", "create_task", "plan_task", "approve_task_step", "continue_task", "get_task"],
        "safety": {"direct_execute_operation_exposed": False, "default_write_policy": "MANUAL", "one_mutation_per_continue": True},
    }
