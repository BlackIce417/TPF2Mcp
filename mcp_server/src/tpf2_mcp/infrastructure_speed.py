"""Derive conservative operating speeds from the physical rail graph.

The game exposes track speed limits and topology, but not Chinese turnout frog
numbers.  This module therefore keeps observed facts separate from inferred
operating policy and allows explicit node/edge overrides.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


TURNOUT_PROFILES = {
    "9": {"passenger_kmh": 30.0, "freight_kmh": 30.0, "radius_m": 185.0},
    "12-330": {"passenger_kmh": 45.0, "freight_kmh": 45.0, "radius_m": 330.0},
    "12-350": {"passenger_kmh": 50.0, "freight_kmh": 45.0, "radius_m": 350.0},
    "18-800": {"passenger_kmh": 75.0, "freight_kmh": 75.0, "radius_m": 800.0},
    "18-860": {"passenger_kmh": 80.0, "freight_kmh": 80.0, "radius_m": 860.0},
    "30": {"passenger_kmh": 140.0, "freight_kmh": 90.0, "radius_m": 2700.0},
}


def _position(node: dict[str, Any]) -> tuple[float, float] | None:
    value = node.get("position") or node
    if not isinstance(value, dict):
        return None
    x, y = value.get("x"), value.get("y")
    return (float(x), float(y)) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None


def _outward_vector(node_id: int, edge: dict[str, Any], nodes: dict[int, dict[str, Any]]) -> tuple[float, float] | None:
    other_id = int(edge["node1"] if int(edge["node0"]) == node_id else edge["node0"])
    origin, other = _position(nodes.get(node_id, {})), _position(nodes.get(other_id, {}))
    if not origin or not other:
        return None
    dx, dy = other[0] - origin[0], other[1] - origin[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > .01 else None


def _straight_pair(node_id: int, incident: list[dict[str, Any]], nodes: dict[int, dict[str, Any]]) -> set[int]:
    """Return the two edges whose outward vectors are closest to opposite."""
    best: tuple[float, int, int] | None = None
    for index, left in enumerate(incident):
        a = _outward_vector(node_id, left, nodes)
        if not a:
            continue
        for right in incident[index + 1:]:
            b = _outward_vector(node_id, right, nodes)
            if not b:
                continue
            dot = a[0] * b[0] + a[1] * b[1]
            candidate = (dot, int(left["entity_id"]), int(right["entity_id"]))
            if best is None or candidate < best:
                best = candidate
    return set(best[1:]) if best else set()


def _nearest_station(node_id: int, nodes: dict[int, dict[str, Any]], stations: list[dict[str, Any]], maximum_m: float = 1200.0) -> dict[str, Any] | None:
    point = _position(nodes.get(node_id, {}))
    if not point:
        return None
    best = None
    for station in stations:
        center = _position(station.get("center") or {})
        if center:
            distance = math.dist(point, center)
            if distance <= maximum_m and (best is None or distance < best[0]):
                best = (distance, station)
    return best[1] if best else None


def build_infrastructure_speed_profile(network: dict[str, Any], overrides: dict[str, Any] | None = None,
                                       default_side_kmh: float = 45.0,
                                       platform_kmh: float = 45.0) -> dict[str, Any]:
    """Classify switch branches and platform tracks into an auditable profile."""
    overrides = overrides or {}
    nodes = {int(item["entity_id"]): item for item in network.get("nodes", []) if isinstance(item.get("entity_id"), int)}
    edges = {int(item["entity_id"]): item for item in network.get("edges", []) if isinstance(item.get("entity_id"), int)}
    stations = list(network.get("stations", []))
    adjacency: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges.values():
        for key in ("node0", "node1"):
            if isinstance(edge.get(key), int):
                adjacency[int(edge[key])].append(edge)

    edge_limits: dict[int, dict[str, Any]] = {}
    platform_edges: dict[int, str] = {}
    for station in stations:
        name = str(station.get("name") or f"车站 {station.get('entity_id')}")
        for terminal in station.get("terminals", []):
            for edge_id in terminal.get("platform_edge_ids", []):
                if isinstance(edge_id, int) and edge_id in edges:
                    platform_edges[edge_id] = name
                    edge_limits[edge_id] = {"edge_id": edge_id, "speed_kmh": float(platform_kmh),
                                            "kind": "PLATFORM_TRACK", "station_name": name,
                                            "evidence": "ENGINE_PLATFORM_EDGE_PLUS_CONSERVATIVE_POLICY"}

    node_overrides = {int(key): value for key, value in (overrides.get("turnout_nodes") or {}).items()}
    edge_overrides = {int(key): value for key, value in (overrides.get("edges") or {}).items()}
    turnouts = []
    for node_id, incident in adjacency.items():
        if len(incident) < 3:
            continue
        straight = _straight_pair(node_id, incident, nodes)
        lateral = sorted(int(edge["entity_id"]) for edge in incident if int(edge["entity_id"]) not in straight)
        override = node_overrides.get(node_id) or {}
        profile_name = str(override.get("profile") or "")
        profile = TURNOUT_PROFILES.get(profile_name)
        side_speed = float(override.get("speed_kmh") or (profile or {}).get("passenger_kmh") or default_side_kmh)
        station = _nearest_station(node_id, nodes, stations)
        station_name = (station or {}).get("name")
        evidence = "USER_TURNOUT_PROFILE" if override else "TOPOLOGY_INFERRED_CONSERVATIVE_POLICY"
        for edge_id in lateral:
            existing = edge_limits.get(edge_id)
            if existing is None or side_speed < float(existing["speed_kmh"]):
                edge_limits[edge_id] = {"edge_id": edge_id, "speed_kmh": side_speed,
                                        "kind": "TURNOUT_LATERAL", "station_name": station_name,
                                        "turnout_node_id": node_id, "profile": profile_name or None,
                                        "evidence": evidence}
        turnouts.append({"node_id": node_id, "degree": len(incident),
                         "incident_edge_ids": sorted(int(edge["entity_id"]) for edge in incident),
                         "straight_edge_ids": sorted(straight), "lateral_edge_ids": lateral,
                         "side_speed_kmh": side_speed, "profile": profile_name or None,
                         "station_name": station_name, "evidence": evidence})

    for edge_id, override in edge_overrides.items():
        if edge_id not in edges:
            continue
        speed = float(override["speed_kmh"] if isinstance(override, dict) else override)
        edge_limits[edge_id] = {"edge_id": edge_id, "speed_kmh": speed, "kind": "EDGE_OVERRIDE",
                                "station_name": (override.get("station_name") if isinstance(override, dict) else None),
                                "evidence": "USER_EDGE_OVERRIDE"}

    for edge_id, limit in list(edge_limits.items()):
        infrastructure = edges[edge_id].get("speed_limit_mps")
        if isinstance(infrastructure, (int, float)):
            limit["infrastructure_kmh"] = round(float(infrastructure) * 3.6, 1)
            limit["speed_kmh"] = min(float(limit["speed_kmh"]), limit["infrastructure_kmh"])
    return {"schema_version": 1, "source_status": "ENGINE_TOPOLOGY_WITH_AUDITABLE_POLICY",
            "turnout_profiles": TURNOUT_PROFILES, "turnouts": turnouts,
            "edge_limits": sorted(edge_limits.values(), key=lambda item: item["edge_id"]),
            "counts": {"turnouts": len(turnouts), "platform_edges": len(platform_edges),
                       "limited_edges": len(edge_limits)},
            "limitations": ["TURNOUT_FROG_NUMBER_NOT_EXPOSED_BY_GAME",
                            "STRAIGHT_AND_LATERAL_EDGES_ARE_GEOMETRY_INFERENCES_UNLESS_OVERRIDDEN"]}


def compile_vehicle_speed_leases(profile: dict[str, Any], network: dict[str, Any], live: dict[str, Any],
                                 expires_at: float, maximum: int = 64) -> list[dict[str, Any]]:
    """Compile one conservative native lease per train from its line route."""
    limits = {int(item["edge_id"]): item for item in profile.get("edge_limits", [])}
    routes = {int(line["entity_id"]): [int(edge) for edge in line.get("route_edge_ids", [])]
              for line in network.get("lines", []) if isinstance(line.get("entity_id"), int)}
    candidates = []
    for vehicle in live.get("vehicles", []):
        vehicle_id, line_id = vehicle.get("entity_id"), vehicle.get("line_id")
        if not isinstance(vehicle_id, int) or not isinstance(line_id, int):
            continue
        affected = [edge_id for edge_id in routes.get(line_id, []) if edge_id in limits]
        if not affected:
            continue
        cap = min(float(limits[edge_id]["speed_kmh"]) for edge_id in affected)
        candidates.append({"kind": "speed", "lease_id": f"infrastructure:{vehicle_id}",
                           "vehicle_id": vehicle_id, "line_id": line_id, "speed_kmh": cap,
                           "speed_mps": round(cap / 3.6, 6), "edge_ids": list(dict.fromkeys(affected)),
                           "expires_at": expires_at, "reason": "INFRASTRUCTURE_OPERATING_SPEED_ENVELOPE",
                           "policy_evidence": sorted({limits[edge_id]["evidence"] for edge_id in affected})})
    candidates.sort(key=lambda item: (next((v.get("approaching_station") is not True for v in live.get("vehicles", [])
                                             if v.get("entity_id") == item["vehicle_id"]), True), item["vehicle_id"]))
    return candidates[:max(0, maximum)]
