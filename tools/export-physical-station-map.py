"""Normalize engine-observed rail geometry for the standalone SVG viewer."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.config import bridge_dir  # noqa: E402


def curve_length(edge: dict, nodes: dict[int, dict], steps: int = 64) -> float:
    a, b = nodes[edge["node0"]], nodes[edge["node1"]]
    t0 = edge.get("tangent0") or {key: b[key] - a[key] for key in ("x", "y", "z")}
    t1 = edge.get("tangent1") or t0
    previous = (a["x"], a["y"], a["z"])
    total = 0.0
    for index in range(1, steps + 1):
        u = index / steps
        h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
        h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
        current = tuple(h00*a[key] + h10*t0[key] + h01*b[key] + h11*t1[key] for key in ("x", "y", "z"))
        total += math.dist(previous, current)
        previous = current
    return total


def platform_span_inside_bounds(node_id: int, track_type: int, edges: list[dict], nodes: dict[int, dict], bounds: dict) -> float | None:
    adjacency: dict[int, list[dict]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["node0"]].append(edge)
        adjacency[edge["node1"]].append(edge)
    if len(adjacency[node_id]) != 2:
        return None
    minimum, maximum = bounds["min"], bounds["max"]
    def inside(point: tuple[float, float, float]) -> bool:
        return minimum["x"] <= point[0] <= maximum["x"] and minimum["y"] <= point[1] <= maximum["y"] and minimum["z"] - 5 <= point[2] <= maximum["z"] + 5
    def clipped_length(edge: dict, steps: int = 256) -> float:
        a, b = nodes[edge["node0"]], nodes[edge["node1"]]
        t0 = edge.get("tangent0") or {key: b[key] - a[key] for key in ("x", "y", "z")}
        t1 = edge.get("tangent1") or t0
        points = []
        for index in range(steps + 1):
            u = index / steps
            h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
            h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
            points.append(tuple(h00*a[key] + h10*t0[key] + h01*b[key] + h11*t1[key] for key in ("x", "y", "z")))
        return sum(math.dist(p0, p1) for p0, p1 in zip(points, points[1:]) if inside(p0) and inside(p1))
    visited: set[int] = set()
    total = 0.0
    for first in adjacency[node_id]:
        current_node, edge = node_id, first
        while edge["entity_id"] not in visited and edge.get("track_type") == track_type:
            visited.add(edge["entity_id"])
            total += clipped_length(edge)
            other = edge["node1"] if edge["node0"] == current_node else edge["node0"]
            if len(adjacency[other]) != 2:
                break
            onward = [item for item in adjacency[other] if item["entity_id"] not in visited and item.get("track_type") == track_type]
            if len(onward) != 1:
                break
            current_node, edge = other, onward[0]
    return round(total, 1)


def platform_chain_length(node_id: int, track_type: int, edges: list[dict], nodes: dict[int, dict], construction_ids: set[int]) -> float | None:
    owned = [edge for edge in edges if edge.get("construction_entity_id") in construction_ids and edge.get("track_type") == track_type]
    adjacency: dict[int, list[dict]] = defaultdict(list)
    for edge in owned:
        adjacency[edge["node0"]].append(edge)
        adjacency[edge["node1"]].append(edge)
    if len(adjacency[node_id]) != 2:
        return None
    visited: set[int] = set()
    total = 0.0
    for first in adjacency[node_id]:
        current_node, edge = node_id, first
        while edge["entity_id"] not in visited:
            visited.add(edge["entity_id"])
            total += curve_length(edge, nodes)
            other = edge["node1"] if edge["node0"] == current_node else edge["node0"]
            onward = [item for item in adjacency[other] if item["entity_id"] not in visited]
            if len(onward) != 1:
                break
            current_node, edge = other, onward[0]
    return round(total, 1)


def terminal_curve_to_throat_length(node_id: int, track_type: int, edges: list[dict], nodes: dict[int, dict]) -> float | None:
    adjacency: dict[int, list[dict]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["node0"]].append(edge)
        adjacency[edge["node1"]].append(edge)
    if len(adjacency[node_id]) != 2:
        return None
    visited: set[int] = set()
    total = 0.0
    for first in adjacency[node_id]:
        current_node, edge = node_id, first
        while edge["entity_id"] not in visited and edge.get("track_type") == track_type:
            other = edge["node1"] if edge["node0"] == current_node else edge["node0"]
            if len(adjacency[other]) != 2:
                break
            visited.add(edge["entity_id"])
            total += curve_length(edge, nodes)
            onward = [item for item in adjacency[other] if item["entity_id"] not in visited and item.get("track_type") == track_type]
            if len(onward) != 1:
                break
            current_node, edge = other, onward[0]
    return round(total, 1) if total > 0 else None


def main() -> None:
    default_input = bridge_dir() / "station-geometry.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=default_input)
    parser.add_argument("--output-directory", type=Path, default=Path("ui/rail-map"))
    parser.add_argument("--display-radius", type=float, default=500.0)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    if source.get("status") != "OK" or source.get("source_status") != "ENGINE_OBSERVED":
        raise SystemExit(f"geometry source is not engine-observed: {source.get('status')}")

    center = source["center"]
    all_nodes = {item["entity_id"]: item["position"] for item in source["track_nodes"]}
    candidates = []
    for edge in source["track_edges"]:
        endpoints = [all_nodes.get(edge["node0"]), all_nodes.get(edge["node1"])]
        if any(point is None for point in endpoints):
            continue
        nearest = min(math.hypot(point["x"] - center["x"], point["y"] - center["y"]) for point in endpoints)
        if nearest <= args.display_radius:
            candidates.append(edge)

    adjacency: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, edge in enumerate(candidates):
        adjacency[edge["node0"]].append((index, edge["node1"]))
        adjacency[edge["node1"]].append((index, edge["node0"]))
    terminal_nodes = {item["vehicle_node"]["entity"] for item in source["terminals"]}
    queue = deque(terminal_nodes)
    connected_nodes = set(terminal_nodes)
    connected_edges: set[int] = set()
    while queue:
        node = queue.popleft()
        for edge_index, other in adjacency[node]:
            connected_edges.add(edge_index)
            if other not in connected_nodes:
                connected_nodes.add(other)
                queue.append(other)

    edges = [dict(edge, terminal_connected=index in connected_edges) for index, edge in enumerate(candidates)]
    referenced = {edge[key] for edge in edges for key in ("node0", "node1")}
    nodes = [
        {"entity_id": node_id, "position": all_nodes[node_id], "degree": len(adjacency[node_id])}
        for node_id in sorted(referenced)
    ]
    station_construction_ids = {
        item.get("construction_entity_id") for item in source["child_stations"]
        if isinstance(item.get("construction_entity_id"), int) and item.get("construction_entity_id") >= 0
    }
    terminals = []
    station_bounds = source["child_stations"][0].get("bounds")
    for item in source["terminals"]:
        node_id = item["vehicle_node"]["entity"]
        adjacent_types = [edge["track_type"] for edge in source["track_edges"] if node_id in (edge["node0"], edge["node1"])]
        track_type = adjacent_types[0] if adjacent_types else None
        direct_length = item.get("direct_platform_length_m")
        if not isinstance(direct_length, (int, float)) or direct_length <= 0:
            direct_length = None
        owned_length = platform_chain_length(node_id, track_type, source["track_edges"], all_nodes, station_construction_ids) if track_type is not None else None
        throat_length = terminal_curve_to_throat_length(node_id, track_type, source["track_edges"], all_nodes) if track_type is not None else None
        geometric_span = platform_span_inside_bounds(node_id, track_type, source["track_edges"], all_nodes, station_bounds) if track_type is not None and station_bounds else None
        if direct_length is not None:
            platform_length, length_source, confidence = round(float(direct_length), 1), "SYSTEM_DIRECT", "HIGH"
        elif owned_length is not None:
            platform_length, length_source, confidence = owned_length, "STATION_CONSTRUCTION_OWNED_TRACK_CURVE", "HIGH"
        else:
            platform_length, length_source, confidence = throat_length, "TERMINAL_CURVE_TO_PRE_SWITCH_NODES", "MEDIUM"
        terminals.append({
            "station_index": item["station_index"],
            "terminal_index": item["terminal_index"],
            "tag": item.get("tag"),
            "node_id": node_id,
            "position": all_nodes.get(node_id),
            "service_class": "HIGH_SPEED" if item["terminal_index"] < 2 else "CONVENTIONAL",
            "usage": "PASSENGER",
            "platform_length_m": platform_length,
            "geometric_station_bounds_span_m": geometric_span,
            "length_source": length_source,
            "length_confidence": confidence,
            "direct_length_field": item.get("direct_platform_length_field"),
        })
    result = {
        "schema_version": 1,
        "diagram_type": "ENGINE_OBSERVED_PHYSICAL_TRACK_GRAPH",
        "source_status": "ENGINE_OBSERVED",
        "station_group_id": source["station_group_id"],
        "station_entity_id": source["child_stations"][0]["entity_id"],
        "station_construction_ids": sorted(station_construction_ids),
        "center": center,
        "station_bounds": source["child_stations"][0].get("bounds"),
        "display_radius_m": args.display_radius,
        "terminals": terminals,
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "terminals": len(terminals),
            "nodes": len(nodes),
            "edges": len(edges),
            "switch_nodes": sum(item["degree"] >= 3 for item in nodes),
        },
        "track_type_evidence": {
            "54": "used by user-confirmed high-speed terminals 0 and 1",
            "148": "used by user-confirmed conventional terminals 2 and 3",
            "117": "engine-observed nearby track type; semantic label unknown",
            "1": "engine-observed additional track type; semantic label unknown",
        },
        "limitations": [
            "Terminal service classes are user-confirmed; coordinates and topology are engine-observed.",
            "All engine-observed track edges inside the display radius are included; terminal_connected marks station-platform reachability within this window.",
            "Signals are not included in this static version.",
        ],
    }
    args.output_directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    (args.output_directory / "physical-track-data.json").write_text(encoded + "\n", encoding="utf-8")
    (args.output_directory / "physical-track-data.js").write_text("window.PHYSICAL_TRACK_DATA=" + encoded + ";\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
