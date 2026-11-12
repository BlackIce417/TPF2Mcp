"""Map line chainage limits onto the ordered native track-edge path."""
from __future__ import annotations

import math
from typing import Any


def _edge_length(edge: dict[str, Any], nodes: dict[int, dict[str, Any]]) -> float:
    a, b = nodes.get(int(edge["node0"])), nodes.get(int(edge["node1"]))
    if not a or not b:
        return 0.0
    pa, pb = a["position"], b["position"]
    return math.dist(tuple(float(pa.get(axis, 0)) for axis in ("x", "y", "z")),
                     tuple(float(pb.get(axis, 0)) for axis in ("x", "y", "z")))


def map_chainage_zone(network: dict[str, Any], line_id: int, start_km: float, end_km: float,
                       speed_kmh: float, vehicle_id: int, direction: str = "FORWARD") -> dict[str, Any]:
    if not 0 <= start_km < end_km or speed_kmh <= 0:
        raise ValueError("start_km < end_km and a positive speed_kmh are required")
    line = next((item for item in network.get("lines", []) if item.get("entity_id") == line_id), None)
    if line is None:
        raise ValueError(f"line {line_id} not found")
    nodes = {int(item["entity_id"]): item for item in network.get("nodes", [])}
    edges = {int(item["entity_id"]): item for item in network.get("edges", [])}
    route = list(line.get("route_edge_ids", []))
    if direction == "REVERSE":
        route.reverse()
    elif direction != "FORWARD":
        raise ValueError("direction must be FORWARD or REVERSE")
    start_m, end_m, cursor = start_km * 1000, end_km * 1000, 0.0
    selected = []
    for route_index, edge_id in enumerate(route):
        edge = edges.get(int(edge_id))
        length = _edge_length(edge, nodes) if edge else 0.0
        edge_start, edge_end = cursor, cursor + length
        if length > 0 and edge_end > start_m and edge_start < end_m:
            selected.append({"edge_id": int(edge_id), "route_index": route_index,
                             "from_param": round(max(0.0, (start_m - edge_start) / length), 6),
                             "to_param": round(min(1.0, (end_m - edge_start) / length), 6),
                             "chainage_start_m": round(edge_start, 3), "chainage_end_m": round(edge_end, 3)})
        cursor = edge_end
    if end_m > cursor:
        raise ValueError(f"zone end {end_m:.1f}m exceeds measured route length {cursor:.1f}m")
    return {"schema_version": 1, "vehicle_id": vehicle_id, "line_id": line_id, "direction": direction,
            "start_km": start_km, "end_km": end_km, "speed_kmh": speed_kmh,
            "speed_mps": round(speed_kmh / 3.6, 6), "route_length_m": round(cursor, 3),
            "edge_ids": list(dict.fromkeys(item["edge_id"] for item in selected)), "segments": selected,
            "activation": "NATIVE_SPEED_PREVIEW_EDGE_INTERSECTION",
            "release": "AFTER_TRAIN_SPEED_PREVIEW_NO_LONGER_INTERSECTS_ZONE"}
