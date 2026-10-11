from __future__ import annotations

from typing import Any

from .snapshot import SnapshotIndex


def _vehicle_count(bucket: dict[str, Any], vehicle_id: int) -> int:
    value = (bucket.get("vehicles") or {}).get(str(vehicle_id), 0)
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def _nonempty_errors(demand: dict[str, Any]) -> dict[str, Any]:
    errors = demand.get("errors") or {}
    return {str(key): value for key, value in errors.items() if value} if isinstance(errors, dict) else {"collector": errors}


def _bucket_available(bucket: Any) -> bool:
    return isinstance(bucket, dict) and bucket.get("status") != "UNAVAILABLE"


def _bucket_complete(bucket: Any) -> bool:
    return _bucket_available(bucket) and bucket.get("truncated") is not True


def _count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def station_waiting_state(index: SnapshotIndex, station_id: int,
                          line_demands: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate line-assigned waiting entities whose observed OD starts here.

    TPF2 exposes demand per line, not per station.  This join is exact only when
    every connected line probe is available, untruncated, and has no waiting
    entities without a LINE_STOP_OD journey.
    """
    if station_id not in index.station_by_id:
        raise ValueError(f"ENTITY_NOT_FOUND: station {station_id}")
    cargo_names = {item.get("cargo_id"): item.get("display_name") for item in index.cargo_registry.list()}
    passenger_waiting = cargo_waiting = 0
    passenger_unmapped = cargo_unmapped = 0
    cargo_type_unknown = 0
    cargo_totals: dict[int, int] = {}
    rows: list[dict[str, Any]] = []
    errors: dict[str, Any] = {}
    truncated_lines: list[int] = []
    unavailable_lines: list[int] = []
    unavailable_passenger_lines: list[int] = []
    unavailable_cargo_lines: list[int] = []

    seen_line_ids: set[int] = set()
    for line in index.lines_by_station.get(station_id, []):
        line_id = line.get("entity_id")
        if not isinstance(line_id, int) or line_id in seen_line_ids:
            continue
        seen_line_ids.add(line_id)
        stops = line.get("stops") or []
        stop_indices = sorted({item.get("index", offset) for offset, item in enumerate(stops)
                               if item.get("station_id") == station_id and isinstance(item.get("index", offset), int)})
        demand = line_demands.get(line_id) or {}
        row_errors = _nonempty_errors(demand)
        passenger_bucket, cargo_bucket = demand.get("passengers"), demand.get("cargo")
        shared_error = any(key not in {"persons", "cargo"} for key in row_errors)
        passengers_available = not shared_error and "persons" not in row_errors and _bucket_available(passenger_bucket)
        cargo_available = not shared_error and "cargo" not in row_errors and _bucket_available(cargo_bucket)
        available = passengers_available and cargo_available
        truncated = any(isinstance(bucket, dict) and bucket.get("truncated") is True
                        for bucket in (passenger_bucket, cargo_bucket))
        if row_errors:
            errors[str(line_id)] = row_errors
        if truncated:
            truncated_lines.append(line_id)
        if not available:
            unavailable_lines.append(line_id)
        if not passengers_available:
            unavailable_passenger_lines.append(line_id)
        if not cargo_available:
            unavailable_cargo_lines.append(line_id)

        line_passengers = line_cargo = 0
        line_cargo_types: dict[int, int] = {}
        for journey in (passenger_bucket or {}).get("by_journey") or []:
            if journey.get("line_stop_0") in stop_indices:
                line_passengers += _count(journey.get("waiting"))
        for journey in (cargo_bucket or {}).get("by_journey") or []:
            if journey.get("line_stop_0") not in stop_indices:
                continue
            line_cargo += _count(journey.get("waiting"))
            for cargo in journey.get("by_cargo") or []:
                cargo_id = cargo.get("cargo_id")
                if isinstance(cargo_id, int):
                    line_cargo_types[cargo_id] = line_cargo_types.get(cargo_id, 0) + _count(cargo.get("waiting"))

        known_passenger_waiting = sum(_count(item.get("waiting")) for item in (passenger_bucket or {}).get("by_journey") or [])
        known_cargo_waiting = sum(_count(item.get("waiting")) for item in (cargo_bucket or {}).get("by_journey") or [])
        row_passenger_unmapped = max(0, _count((passenger_bucket or {}).get("waiting")) - known_passenger_waiting)
        row_cargo_unmapped = max(0, _count((cargo_bucket or {}).get("waiting")) - known_cargo_waiting)
        cargo_type_unknown += _count((cargo_bucket or {}).get("cargo_type_unknown"))
        if passengers_available:
            passenger_waiting += line_passengers
        if cargo_available:
            cargo_waiting += line_cargo
        passenger_unmapped += row_passenger_unmapped
        cargo_unmapped += row_cargo_unmapped
        if cargo_available:
            for cargo_id, amount in line_cargo_types.items():
                cargo_totals[cargo_id] = cargo_totals.get(cargo_id, 0) + amount
        rows.append({
            "line_id": line_id, "line_name": line.get("name"), "line_stop_indices": stop_indices,
            "passengers_waiting": line_passengers if passengers_available else None,
            "cargo_waiting": line_cargo if cargo_available else None,
            "unmapped_waiting": {"passengers": row_passenger_unmapped, "cargo": row_cargo_unmapped},
            "complete": available and not truncated and row_passenger_unmapped == 0 and row_cargo_unmapped == 0,
        })

    complete = bool(line_demands) and not unavailable_lines and not truncated_lines and passenger_unmapped == 0 and cargo_unmapped == 0
    return {
        "source_status": "ENGINE_COMPONENT_CLASSIFIED_AGGREGATE" if line_demands else "UNAVAILABLE",
        "scope": "LINE_ASSIGNED_WAITING_WITH_OBSERVED_ORIGIN_AT_STATION",
        "passengers": {"waiting": passenger_waiting if not unavailable_passenger_lines else None},
        "cargo": {
            "waiting": cargo_waiting if not unavailable_cargo_lines else None,
            "by_cargo": ([{"cargo_id": cargo_id, "cargo_name": cargo_names.get(cargo_id), "waiting": amount}
                          for cargo_id, amount in sorted(cargo_totals.items())]
                         if not unavailable_cargo_lines else None),
        },
        "lines": rows,
        "quality": {
            "complete": complete, "truncated_line_ids": truncated_lines, "unavailable_line_ids": unavailable_lines,
            "unavailable_by_kind": {"passengers": unavailable_passenger_lines, "cargo": unavailable_cargo_lines},
            "errors": errors, "unmapped_waiting": {"passengers": passenger_unmapped, "cargo": cargo_unmapped},
            "cargo_type_unknown_entities": cargo_type_unknown,
        },
        "limitations": [
            "Counts cover entities assigned to connected lines and mapped to this station as LINE_STOP_OD origin.",
            "Unassigned entities and entities whose journey is unavailable cannot be attributed to a station.",
        ],
    }


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
    errors = _nonempty_errors(demand)
    passenger_bucket, cargo_bucket = demand.get("passengers"), demand.get("cargo")
    load_available = not errors and _bucket_available(passenger_bucket) and _bucket_available(cargo_bucket)
    load_complete = load_available and _bucket_complete(passenger_bucket) and _bucket_complete(cargo_bucket)
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
            "occupancy_ratio": round(load_total / capacity, 4) if load_complete and capacity_known and capacity else None,
            "cargo_by_type": cargo_by_type,
        },
        "availability": {"live_motion": bool(live) and not live.get("_live_unavailable", False), "load": load_available,
                         "complete_load": load_complete, "capacity": capacity_known,
                         "cargo_type_breakdown": bool(cargo_by_type)},
        "quality": {"source_status": demand.get("source_status", demand.get("source", "UNKNOWN")),
                    "truncated": {"passengers": isinstance(passenger_bucket, dict) and passenger_bucket.get("truncated") is True,
                                  "cargo": isinstance(cargo_bucket, dict) and cargo_bucket.get("truncated") is True},
                    "errors": errors},
    }


def agent_operations_guide() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rule": "Use MCP tools only; never create ad-hoc bridge-file scripts.",
        "read_workflow": ["get_dispatch_overview", "get_line_dispatch_state", "get_station_dispatch_state", "get_vehicle_dispatch_state"],
        "write_workflow": ["get_operation_capabilities", "propose_operation", "validate_operation", "create_task", "plan_task", "approve_task_step", "continue_task", "get_task"],
        "safety": {"direct_execute_operation_exposed": False, "default_write_policy": "MANUAL", "one_mutation_per_continue": True},
    }
