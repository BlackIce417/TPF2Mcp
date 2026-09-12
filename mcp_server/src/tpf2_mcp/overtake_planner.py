from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


def _cyclic_contains_in_order(route: list[int], first: int, second: int) -> bool:
    if first not in route or second not in route or first == second:
        return False
    size = len(route)
    return any(route[(start + offset) % size] == second for start, value in enumerate(route) if value == first for offset in range(1, size))


def plan_overtakes(frames: list[dict[str, Any]], manifest: dict[str, Any], *, network_detail: dict[str, Any] | None = None, minimum_speed_advantage_kmh: float = 25.0) -> dict[str, Any]:
    """Find structural overtaking candidates; never authorizes a hold itself."""
    frames = [frame for frame in frames if (frame.get("simulation") or {}).get("analysis_allowed") is True]
    if not frames:
        return {"schema_version": 1, "source_status": "ANALYSIS_BLOCKED_SIMULATION_INACTIVE", "automatic_apply": False, "counts": {"candidates": 0, "apply_ready": 0}, "candidates": [], "required_before_hold": ["simulation must be confirmed running"]}
    stations = {int(item["entity_id"]): item for item in manifest.get("stations", [])}
    lines = {int(item["entity_id"]): item for item in manifest.get("lines", [])}
    speeds: dict[int, list[float]] = defaultdict(list)
    vehicle_ids: dict[int, set[int]] = defaultdict(set)
    for frame in frames:
        for vehicle in frame.get("vehicles", []):
            line_id, speed = vehicle.get("line_id"), vehicle.get("speed_kmh")
            if line_id in lines and isinstance(speed, (int, float)) and speed > 1:
                speeds[int(line_id)].append(float(speed))
                vehicle_ids[int(line_id)].add(int(vehicle["entity_id"]))
    median_speed = {line_id: statistics.median(values) for line_id, values in speeds.items() if values}
    detailed_lines = {int(item["entity_id"]): item for item in (network_detail or {}).get("lines", [])}
    candidates = []
    for slow_id, slow in lines.items():
        slow_stops = slow.get("stops", [])
        slow_route = [int(stop["station_group_id"]) for stop in slow_stops]
        if len(slow_route) < 3 or slow_id not in median_speed:
            continue
        for index, stop in enumerate(slow_stops):
            station_id = int(stop["station_group_id"])
            station = stations.get(station_id, {})
            passenger_terminals = [item for item in station.get("terminals", []) if not item.get("cargo")]
            if len(passenger_terminals) < 2:
                continue
            before, after = slow_route[index - 1], slow_route[(index + 1) % len(slow_route)]
            for fast_id, fast in lines.items():
                if fast_id == slow_id or fast_id not in median_speed:
                    continue
                fast_route = [int(item["station_group_id"]) for item in fast.get("stops", [])]
                advantage = median_speed[fast_id] - median_speed[slow_id]
                if station_id in fast_route or advantage < minimum_speed_advantage_kmh or median_speed[fast_id] < median_speed[slow_id] * 1.2:
                    continue
                if not _cyclic_contains_in_order(fast_route, before, after):
                    continue
                slow_edges = set(detailed_lines.get(slow_id, {}).get("route_edge_ids", []))
                fast_edges = set(detailed_lines.get(fast_id, {}).get("route_edge_ids", []))
                platform_edges = {int(edge) for terminal in passenger_terminals for edge in terminal.get("platform_edge_ids", [])}
                bypass_verified = bool(slow_edges & platform_edges) and bool(fast_edges) and not bool(fast_edges & platform_edges)
                candidates.append({
                    "hold_station_id": station_id, "hold_station_name": station.get("name"),
                    "slow_line_id": slow_id, "slow_line_name": slow.get("name"), "slow_stop_index": index,
                    "fast_line_id": fast_id, "fast_line_name": fast.get("name"),
                    "shared_boundary_station_ids": [before, after],
                    "slow_median_speed_kmh": round(median_speed[slow_id], 1), "fast_median_speed_kmh": round(median_speed[fast_id], 1),
                    "speed_advantage_kmh": round(advantage, 1), "passenger_terminal_count": len(passenger_terminals),
                    "bypass_path_verified": bypass_verified,
                    "slow_vehicle_ids_observed": sorted(vehicle_ids[slow_id]), "fast_vehicle_ids_observed": sorted(vehicle_ids[fast_id]),
                    "apply_ready": False,
                    "blocking_reason": "FAST_TRAIN_DIRECTION_AND_ETA_NOT_YET_VERIFIED" if bypass_verified else "BYPASS_PATH_AND_FAST_TRAIN_ETA_NOT_YET_VERIFIED",
                })
    candidates.sort(key=lambda item: (-item["speed_advantage_kmh"], item["hold_station_id"], item["slow_line_id"]))
    return {
        "schema_version": 1, "source_status": "DERIVED_STRUCTURAL_CANDIDATES", "automatic_apply": False,
        "counts": {"candidates": len(candidates), "apply_ready": 0}, "candidates": candidates,
        "required_before_hold": ["slow vehicle is raw_state=2, speed<=1, and on its exact stop platform", "fast vehicle is behind in the same direction", "fast route bypasses the occupied platform and clears the downstream merge", "predicted saved fast-train delay exceeds slow-train hold cost"],
    }
