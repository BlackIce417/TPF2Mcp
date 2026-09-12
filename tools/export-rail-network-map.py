"""Prepare the one-shot engine rail export for the browser dispatch map."""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path


def curve_length(edge: dict, nodes: dict[int, dict], steps: int = 12) -> float:
    a, b = nodes[edge["node0"]], nodes[edge["node1"]]
    t0 = edge.get("tangent0") or {key: b[key] - a[key] for key in ("x", "y", "z")}
    t1 = edge.get("tangent1") or t0
    previous = (a["x"], a["y"], a.get("z", 0))
    total = 0.0
    for index in range(1, steps + 1):
        u = index / steps
        h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
        h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
        current = tuple(h00*a.get(key, 0) + h10*t0.get(key, 0) + h01*b.get(key, 0) + h11*t1.get(key, 0) for key in ("x", "y", "z"))
        total += math.dist(previous, current)
        previous = current
    return total


def shortest_edge_path(start: int, goal: int, adjacency: dict[int, list[tuple[int, int, float]]]) -> list[int] | None:
    if start == goal:
        return []
    queue = [(0.0, start)]
    distances = {start: 0.0}
    previous: dict[int, tuple[int, int]] = {}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node == goal:
            break
        for other, edge_id, weight in adjacency.get(node, []):
            candidate = distance + weight
            if candidate < distances.get(other, math.inf):
                distances[other] = candidate
                previous[other] = (node, edge_id)
                heapq.heappush(queue, (candidate, other))
    if goal not in previous:
        return None
    result, current = [], goal
    while current != start:
        current, edge_id = previous[current]
        result.append(edge_id)
    result.reverse()
    return result


def ordered_route_points(start: int, edge_ids: list[int], edges: dict[int, dict], nodes: dict[int, dict]) -> list[list[float]]:
    current = start
    result = [[nodes[current]["x"], nodes[current]["y"]]]
    for edge_id in edge_ids:
        edge = edges[edge_id]
        current = edge["node1"] if edge["node0"] == current else edge["node0"]
        result.append([nodes[current]["x"], nodes[current]["y"]])
    return result


def sampled_edge_path(start: int, edge_ids: list[int], edges: dict[int, dict], nodes: dict[int, dict], steps: int = 12) -> list[list[float]]:
    """Sample the engine Hermite curves in path order instead of replacing them with chords."""
    current = start
    result = [[nodes[current]["x"], nodes[current]["y"]]]
    for edge_id in edge_ids:
        edge = edges[edge_id]
        a, b = nodes[edge["node0"]], nodes[edge["node1"]]
        t0 = edge.get("tangent0") or {key: b[key] - a[key] for key in ("x", "y", "z")}
        t1 = edge.get("tangent1") or t0
        samples = []
        for index in range(steps + 1):
            u = index / steps
            h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
            h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
            samples.append([
                h00*a["x"] + h10*t0.get("x", 0) + h01*b["x"] + h11*t1.get("x", 0),
                h00*a["y"] + h10*t0.get("y", 0) + h01*b["y"] + h11*t1.get("y", 0),
            ])
        if current == edge["node1"]:
            samples.reverse()
            current = edge["node0"]
        else:
            current = edge["node1"]
        result.extend(samples[1:])
    return result


def simplify(points: list[list[float]], tolerance: float = 80.0) -> list[list[float]]:
    if len(points) <= 2:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    furthest_index, furthest_distance = 0, -1.0
    for index, (x, y) in enumerate(points[1:-1], 1):
        if denominator == 0:
            distance = math.hypot(x - ax, y - ay)
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / denominator))
            distance = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if distance > furthest_distance:
            furthest_index, furthest_distance = index, distance
    if furthest_distance <= tolerance:
        return [points[0], points[-1]]
    left = simplify(points[:furthest_index + 1], tolerance)
    right = simplify(points[furthest_index:], tolerance)
    return left[:-1] + right


def _clip_segment_to_bounds(a: list[float], b: list[float], bounds: dict) -> tuple[list[float], list[float]] | None:
    """Liang-Barsky clip of one track chord to an observed station AABB."""
    minimum, maximum = bounds.get("min") or {}, bounds.get("max") or {}
    if not all(isinstance(value, (int, float)) for value in (minimum.get("x"), minimum.get("y"), maximum.get("x"), maximum.get("y"))):
        return a, b
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - minimum["x"]), (dx, maximum["x"] - a[0]), (-dy, a[1] - minimum["y"]), (dy, maximum["y"] - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return None
    return [a[0] + dx * low, a[1] + dy * low], [a[0] + dx * high, a[1] + dy * high]


def clip_polyline_to_bounds(points: list[list[float]], bounds: dict | None, anchor: dict | None = None) -> list[list[float]]:
    if len(points) < 2 or not bounds:
        return points
    chains: list[list[list[float]]] = []
    current: list[list[float]] = []
    for a, b in zip(points, points[1:]):
        clipped = _clip_segment_to_bounds(a, b, bounds)
        if clipped is None:
            if len(current) >= 2:
                chains.append(current)
            current = []
            continue
        left, right = clipped
        if current and math.dist(current[-1], left) <= .05:
            if math.dist(current[-1], right) > .001:
                current.append(right)
        else:
            if len(current) >= 2:
                chains.append(current)
            current = [left, right]
    if len(current) >= 2:
        chains.append(current)
    if not chains:
        return []
    if anchor and isinstance(anchor.get("x"), (int, float)) and isinstance(anchor.get("y"), (int, float)):
        return min(chains, key=lambda chain: min(math.hypot(point[0] - anchor["x"], point[1] - anchor["y"]) for point in chain))
    return max(chains, key=lambda chain: sum(math.dist(a, b) for a, b in zip(chain, chain[1:])))


def platform_chain(node_id: int, adjacency: dict[int, list[tuple[int, int, float]]], edges: dict[int, dict]) -> tuple[list[int], float, list[int]]:
    adjacent = adjacency.get(node_id, [])
    if len(adjacent) != 2:
        return [], 0.0, []
    track_type = edges[adjacent[0][1]].get("track_type")
    visited: set[int] = set()
    branches: list[tuple[list[int], list[int]]] = []
    total = 0.0
    for _, first_edge_id, _ in adjacent:
        current, edge_id = node_id, first_edge_id
        branch_edges: list[int] = []
        branch_nodes: list[int] = []
        while edge_id not in visited and edges[edge_id].get("track_type") == track_type:
            edge = edges[edge_id]
            other = edge["node1"] if edge["node0"] == current else edge["node0"]
            # The edge entering a switch is part of the throat, not the usable
            # platform span. Stop immediately before that edge.
            if len(adjacency.get(other, [])) != 2:
                break
            visited.add(edge_id)
            branch_edges.append(edge_id)
            branch_nodes.append(other)
            weight = next(weight for target, candidate, weight in adjacency[current] if candidate == edge_id and target == other)
            total += weight
            onward = [candidate for candidate in adjacency[other] if candidate[1] not in visited and edges[candidate[1]].get("track_type") == track_type]
            if len(onward) != 1:
                break
            current, edge_id = other, onward[0][1]
        branches.append((branch_edges, branch_nodes))
    left_edges, left_nodes = branches[0] if branches else ([], [])
    right_edges, right_nodes = branches[1] if len(branches) > 1 else ([], [])
    ordered_edges = list(reversed(left_edges)) + right_edges
    ordered_nodes = list(reversed(left_nodes)) + [node_id] + right_nodes
    return ordered_edges, round(total, 1), ordered_nodes


def classify_terminal_station_model(evidence_edges: list[dict], edge_count: int, chain_length: float,
                                    construction_file: str | None = None) -> tuple[str, str]:
    normalized_construction = construction_file.lower().replace("\\", "/") if isinstance(construction_file, str) else ""
    if normalized_construction:
        if normalized_construction == "station/rail/lollo_freestyle_train_station/station.con":
            return "FREESTYLE_STATION", "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED"
        return "OTHER", "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED"
    identified_edges = [edge for edge in evidence_edges if edge.get("track_resource_file")]
    if identified_edges:
        if any(edge.get("freestyle_station_track") for edge in identified_edges):
            return "FREESTYLE_STATION", "TRACK_TYPE_RESOURCE_FILE_ENGINE_OBSERVED"
        return "OTHER", "TRACK_TYPE_RESOURCE_FILE_ENGINE_OBSERVED"
    # Short edge chains and invisible platform tracks are also produced by
    # vanilla/modular stations. Geometry can use them, but they do not identify
    # which construction mod owns the station.
    return "UNKNOWN", "UNKNOWN"


def infer_platform_model_track_types(source: dict, nodes: dict[int, dict], stations: list[dict], used_edge_ids: set[int]) -> set[int]:
    """Find platform-model track types without inferring a station's construction mod."""
    stats: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for edge in source["edges"]:
        a, b = nodes[edge["node0"]], nodes[edge["node1"]]
        x, y = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        inside_station = any(
            station.get("bounds")
            and station["bounds"]["min"]["x"] <= x <= station["bounds"]["max"]["x"]
            and station["bounds"]["min"]["y"] <= y <= station["bounds"]["max"]["y"]
            for station in stations
        )
        row = stats[edge.get("track_type")]
        row[0] += 1
        row[1] += edge["entity_id"] in used_edge_ids
        row[2] += inside_station
    return {
        track_type for track_type, (total, line_used, inside) in stats.items()
        # Some Freestyle platform resources occur at only one small station.
        # Construction-file evidence decides whether these chains may be used,
        # so a low global count is safe here and avoids dropping rare variants.
        if track_type is not None and total >= 3 and line_used == 0 and inside / total >= .9
    }


def platform_model_chains(station: dict, source_edges: list[dict], nodes: dict[int, dict], marker_track_types: set[int],
                          bounds_margin_m: float = 30.0) -> list[dict]:
    """Recover Freestyle platform-track components near a station.

    The station construction AABB is derived from rendered construction models,
    while Freestyle's invisible platform tracks can sit a few metres outside it.
    Filtering by the exact AABB can therefore remove a connector edge and split
    one platform into two apparent half-platforms.  Use the same 30 m capture
    radius as terminal-to-model assignment, then clip the final geometry back to
    the observed station bounds.
    """
    bounds = station.get("bounds")
    if not bounds or not marker_track_types:
        return []
    model_bounds = {
        "min": {
            "x": bounds["min"]["x"] - bounds_margin_m,
            "y": bounds["min"]["y"] - bounds_margin_m,
        },
        "max": {
            "x": bounds["max"]["x"] + bounds_margin_m,
            "y": bounds["max"]["y"] + bounds_margin_m,
        },
    }
    candidates = {}
    for edge in source_edges:
        if edge.get("track_type") not in marker_track_types:
            continue
        a, b = nodes[edge["node0"]], nodes[edge["node1"]]
        x, y = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        if (bounds["min"]["x"] - bounds_margin_m <= x <= bounds["max"]["x"] + bounds_margin_m
                and bounds["min"]["y"] - bounds_margin_m <= y <= bounds["max"]["y"] + bounds_margin_m):
            candidates[edge["entity_id"]] = edge
    adjacency: dict[int, list[int]] = defaultdict(list)
    for edge_id, edge in candidates.items():
        adjacency[edge["node0"]].append(edge_id)
        adjacency[edge["node1"]].append(edge_id)
    remaining, chains = set(candidates), []
    while remaining:
        seed = next(iter(remaining))
        component_edges, frontier = set(), [seed]
        while frontier:
            edge_id = frontier.pop()
            if edge_id in component_edges:
                continue
            component_edges.add(edge_id)
            edge = candidates[edge_id]
            for node_id in (edge["node0"], edge["node1"]):
                frontier.extend(other for other in adjacency[node_id] if other not in component_edges)
        remaining -= component_edges
        component_nodes = {candidates[edge_id][key] for edge_id in component_edges for key in ("node0", "node1")}
        if any(sum(edge_id in component_edges for edge_id in adjacency[node_id]) > 2 for node_id in component_nodes):
            continue
        ends = [node_id for node_id in component_nodes if sum(edge_id in component_edges for edge_id in adjacency[node_id]) == 1]
        start = ends[0] if ends else candidates[seed]["node0"]
        ordered, current, previous_edge = [], start, None
        while True:
            onward = [edge_id for edge_id in adjacency[current] if edge_id in component_edges and edge_id != previous_edge]
            if not onward:
                break
            edge_id = onward[0]
            ordered.append(edge_id)
            edge = candidates[edge_id]
            current = edge["node1"] if edge["node0"] == current else edge["node0"]
            previous_edge = edge_id
            if len(ordered) >= len(component_edges):
                break
        points = sampled_edge_path(start, ordered, candidates, nodes)
        # Clip to the capture bounds, not the construction's exact AABB.  The
        # latter describes visible construction models and can cut longitudinal
        # platform geometry merely because its invisible track sits 1–2 m to
        # the outside of the model footprint.
        points = clip_polyline_to_bounds(points, model_bounds)
        if len(points) >= 2:
            chains.append({
                "edge_ids": ordered,
                "centerline": simplify(points, tolerance=.2),
                "length_m": sum(math.dist(a, b) for a, b in zip(points, points[1:])),
                "track_type": candidates[ordered[0]].get("track_type"),
            })
    return chains


def point_polyline_distance(point: dict, line: list[list[float]]) -> float:
    best = math.inf
    for a, b in zip(line, line[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point["x"] - a[0]) * dx + (point["y"] - a[1]) * dy) / length2))
        best = min(best, math.hypot(point["x"] - (a[0] + dx * t), point["y"] - (a[1] + dy * t)))
    return best


def offset_polyline_away_from_center(line: list[list[float]], anchor: dict, center: dict, distance: float) -> list[list[float]]:
    """Offset a terminal track toward the station exterior while following its curve."""
    if len(line) < 2 or distance <= 0:
        return line
    dx, dy = line[-1][0] - line[0][0], line[-1][1] - line[0][1]
    length = math.hypot(dx, dy)
    if length == 0:
        return line
    reference_normal = [-dy / length, dx / length]
    outward = [anchor["x"] - center["x"], anchor["y"] - center["y"]]
    if reference_normal[0] * outward[0] + reference_normal[1] * outward[1] < 0:
        reference_normal[0] *= -1
        reference_normal[1] *= -1
    result = []
    for index, point in enumerate(line):
        before = line[max(0, index - 1)]
        after = line[min(len(line) - 1, index + 1)]
        local_dx, local_dy = after[0] - before[0], after[1] - before[1]
        local_length = math.hypot(local_dx, local_dy)
        normal = reference_normal if local_length == 0 else [-local_dy / local_length, local_dx / local_length]
        if normal[0] * reference_normal[0] + normal[1] * reference_normal[1] < 0:
            normal = [-normal[0], -normal[1]]
        result.append([point[0] + normal[0] * distance, point[1] + normal[1] * distance])
    return result


def offset_polyline_by_vector(line: list[list[float]], vector: list[float], distance: float) -> list[list[float]]:
    """Translate a platform curve laterally without changing its shape."""
    length = math.hypot(vector[0], vector[1])
    if len(line) < 2 or length == 0 or distance <= 0:
        return line
    dx, dy = vector[0] / length * distance, vector[1] / length * distance
    return [[point[0] + dx, point[1] + dy] for point in line]


def modular_station_lateral_vector(terminals: list[dict]) -> list[float] | None:
    """Recover the construction's increasing module-axis from terminal tags.

    Vanilla and CRST modular stations encode a track module index in tag // 2;
    even tags put the platform on the lower-index (left) side and odd tags on
    the higher-index (right) side. Regressing observed track positions against
    that index makes the rule independent of station rotation.
    """
    tagged = [terminal for terminal in terminals if isinstance(terminal.get("tag"), (int, float))]
    indices = [math.floor(int(terminal["tag"]) / 2) for terminal in tagged]
    if len(set(indices)) < 2:
        return None
    mean_index = sum(indices) / len(indices)
    mean_x = sum(terminal["position"]["x"] for terminal in tagged) / len(tagged)
    mean_y = sum(terminal["position"]["y"] for terminal in tagged) / len(tagged)
    covariance = [
        sum((index - mean_index) * (terminal["position"]["x"] - mean_x) for index, terminal in zip(indices, tagged)),
        sum((index - mean_index) * (terminal["position"]["y"] - mean_y) for index, terminal in zip(indices, tagged)),
    ]
    return covariance if math.hypot(*covariance) > 1e-6 else None


def offset_modular_station_platforms(station: dict, distance: float = 5.0) -> None:
    """Separate vanilla/CRST modular platforms from their operating rails."""
    terminals = station.get("terminals", [])
    lateral = modular_station_lateral_vector(terminals)
    for terminal in terminals:
        line = terminal.get("platform_centerline") or []
        tag = terminal.get("tag")
        if len(line) < 2 or not isinstance(tag, (int, float)):
            continue
        side = -1 if int(tag) % 2 == 0 else 1
        vector = lateral
        source = "MODULAR_TERMINAL_TAG_SIDE_DERIVED"
        if vector is None:
            # A one-track station cannot reveal the construction's module-axis.
            # Its bounding-volume centre still identifies the occupied platform
            # side after projection onto the terminal track's local normal.
            dx, dy = line[-1][0] - line[0][0], line[-1][1] - line[0][1]
            vector = [-dy, dx]
            toward_center = [station["center"]["x"] - terminal["position"]["x"], station["center"]["y"] - terminal["position"]["y"]]
            if vector[0] * toward_center[0] + vector[1] * toward_center[1] < 0:
                vector = [-vector[0], -vector[1]]
            side = 1
            source = "SINGLE_TERMINAL_BOUNDING_CENTER_SIDE_DERIVED"
        terminal["operating_track_centerline"] = line
        terminal["platform_centerline"] = offset_polyline_by_vector(line, [vector[0] * side, vector[1] * side], distance)
        terminal["platform_geometry_source"] = source
        terminal["platform_offset_m"] = distance


def normalize_modular_station_platform_spans(station: dict) -> None:
    """Give every platform in one modular construction its shared longitudinal span.

    A switch inserted inside the construction can terminate one terminal's
    degree-2 operating-edge chain before the physical platform end.  Modular
    stations still have one construction-wide longitudinal footprint, so use
    the union of the observed platform endpoints for rendering and the longest
    observed terminal length for the common displayed platform length.
    """
    terminals = [terminal for terminal in station.get("terminals", []) if len(terminal.get("platform_centerline") or []) >= 2]
    if len(terminals) < 2:
        return
    reference = max(terminals, key=lambda terminal: math.dist(terminal["platform_centerline"][0], terminal["platform_centerline"][-1]))
    reference_line = reference["platform_centerline"]
    dx, dy = reference_line[-1][0] - reference_line[0][0], reference_line[-1][1] - reference_line[0][1]
    axis_length = math.hypot(dx, dy)
    if axis_length <= 1e-6:
        return
    axis = [dx / axis_length, dy / axis_length]
    oriented: list[tuple[dict, list[list[float]], float, float]] = []
    for terminal in terminals:
        line = [list(point) for point in terminal["platform_centerline"]]
        start_projection = line[0][0] * axis[0] + line[0][1] * axis[1]
        end_projection = line[-1][0] * axis[0] + line[-1][1] * axis[1]
        if start_projection > end_projection:
            line.reverse()
            start_projection, end_projection = end_projection, start_projection
        oriented.append((terminal, line, start_projection, end_projection))
    shared_start = min(item[2] for item in oriented)
    shared_end = max(item[3] for item in oriented)
    observed_lengths = [terminal.get("platform_length_m") for terminal in terminals if isinstance(terminal.get("platform_length_m"), (int, float))]
    common_length = round(max(observed_lengths), 1) if observed_lengths else round(shared_end - shared_start, 1)
    for terminal, line, start_projection, end_projection in oriented:
        if start_projection > shared_start + .01:
            delta = start_projection - shared_start
            line.insert(0, [line[0][0] - axis[0] * delta, line[0][1] - axis[1] * delta])
        if end_projection < shared_end - .01:
            delta = shared_end - end_projection
            line.append([line[-1][0] + axis[0] * delta, line[-1][1] + axis[1] * delta])
        terminal["platform_centerline"] = line
        terminal["platform_length_original_m"] = terminal.get("platform_length_m")
        terminal["platform_length_original_source"] = terminal.get("platform_length_source")
        terminal["platform_length_m"] = common_length
        terminal["platform_length_source"] = "MODULAR_STATION_SHARED_SPAN_DERIVED"


def offset_crst_hm_platforms(station: dict, distance: float = 5.0) -> None:
    """Reproduce the four fixed platform paths declared by CRST_HM.con."""
    terminals = [terminal for terminal in station.get("terminals", []) if len(terminal.get("platform_centerline") or []) >= 2]
    if not terminals:
        return
    radial = sorted(
        (
            math.hypot(terminal["position"]["x"] - station["center"]["x"], terminal["position"]["y"] - station["center"]["y"]),
            index,
        )
        for index, terminal in enumerate(terminals)
    )
    outer = {index for _, index in radial[len(radial) // 2:]}
    for index, terminal in enumerate(terminals):
        line = terminal["platform_centerline"]
        away = [terminal["position"]["x"] - station["center"]["x"], terminal["position"]["y"] - station["center"]["y"]]
        vector = [-away[0], -away[1]] if index in outer else away
        terminal["operating_track_centerline"] = line
        terminal["platform_centerline"] = offset_polyline_by_vector(line, vector, distance)
        terminal["platform_geometry_source"] = "CRST_HM_FIXED_CONSTRUCTION_GEOMETRY_DERIVED"
        terminal["platform_offset_m"] = distance


def mark_track_loading_terminals(station: dict) -> None:
    """Do not invent a side platform where the construction defines none."""
    for terminal in station.get("terminals", []):
        line = terminal.get("platform_centerline") or []
        if len(line) < 2:
            continue
        terminal["operating_track_centerline"] = line
        terminal["terminal_hit_centerline"] = line
        terminal["platform_centerline"] = []
        terminal["platform_geometry_source"] = "CONSTRUCTION_TERMINAL_LANE_COLOCATED_WITH_TRACK"
        terminal["platform_render_mode"] = "TRACK_LOADING_AREA"


def physical_overview_segments(source: dict, nodes: dict[int, dict], adjacency: dict[int, list[tuple[int, int, float]]],
                               excluded_edge_ids: set[int] | None = None) -> list[list[list[float]]]:
    """Collapse degree-2 chains while preserving every physical rail edge."""
    excluded_edge_ids = excluded_edge_ids or set()
    edge_by_id = {item["entity_id"]: item for item in source["edges"] if item["entity_id"] not in excluded_edge_ids}
    adjacency = defaultdict(list)
    for edge_id, edge in edge_by_id.items():
        adjacency[edge["node0"]].append((edge["node1"], edge_id, 0.0))
        adjacency[edge["node1"]].append((edge["node0"], edge_id, 0.0))
    terminal_nodes = {terminal["node_id"] for station in source.get("stations", []) for terminal in station.get("terminals", [])}
    anchors = {node_id for node_id, links in adjacency.items() if len(links) != 2} | terminal_nodes
    visited: set[int] = set()
    segments: list[list[list[float]]] = []

    def walk(start: int, first_edge_id: int) -> list[list[float]]:
        current, edge_id = start, first_edge_id
        points = [[nodes[start]["x"], nodes[start]["y"]]]
        while edge_id not in visited:
            visited.add(edge_id)
            edge = edge_by_id[edge_id]
            other = edge["node1"] if edge["node0"] == current else edge["node0"]
            points.append([nodes[other]["x"], nodes[other]["y"]])
            if other in anchors:
                break
            onward = [candidate for _, candidate, _ in adjacency[other] if candidate not in visited]
            if not onward:
                break
            current, edge_id = other, onward[0]
        return simplify(points, tolerance=60.0)

    for start in sorted(anchors):
        for _, edge_id, _ in adjacency[start]:
            if edge_id not in visited:
                segments.append(walk(start, edge_id))
    # Closed loops can contain no degree-changing node or terminal.
    for edge in edge_by_id.values():
        if edge["entity_id"] not in visited:
            segments.append(walk(edge["node0"], edge["entity_id"]))
    return [segment for segment in segments if len(segment) >= 2]


def prepare_rail_depots(source: dict, nodes: dict[int, dict], edges: dict[int, dict], maximum_candidate_distance: float = 45.0) -> list[dict]:
    """Attach depot centres to the nearest observed physical rail edge.

    TPF2's VEHICLE_DEPOT component does not expose its connector in the live
    probe.  Construction-file/assigned-rail-vehicle classification is kept as
    engine evidence; proximity is explicitly labelled as derived fallback.
    """
    result = []
    for depot in source.get("depots", []):
        center = depot.get("center")
        if not center:
            continue
        nearest = None
        for edge_id, edge in edges.items():
            a, b = nodes.get(edge["node0"]), nodes.get(edge["node1"])
            if not a or not b:
                continue
            distance, param, position = _project_xy(center, a, b)
            if nearest is None or distance < nearest["distance_m"]:
                nearest = {"edge_id": edge_id, "edge_param": param, "distance_m": distance, "position": position}
        engine_classified = bool(depot.get("rail_candidate"))
        proximity_candidate = nearest is not None and nearest["distance_m"] <= maximum_candidate_distance
        if not engine_classified and not proximity_candidate:
            continue
        classification_source = depot.get("rail_classification_source") if engine_classified else "NEAREST_RAIL_EDGE_PROXIMITY_DERIVED"
        item = {
            "entity_id": depot["entity_id"], "name": depot.get("name") or f"Depot {depot['entity_id']}",
            "center": center, "bounds": depot.get("bounds"), "construction_file": depot.get("construction_file"),
            "rail_classification_source": classification_source,
            "assigned_vehicle_count": len(depot.get("assigned_vehicle_ids") or []),
            "rail_assigned_vehicle_count": len(depot.get("rail_assigned_vehicle_ids") or []),
            "parked_vehicle_count": len(depot.get("parked_vehicle_ids") or []),
            "parked_vehicle_count_source": depot.get("parked_vehicle_count_source") or "UNKNOWN",
        }
        if nearest:
            item.update({
                "nearest_edge_id": nearest["edge_id"], "nearest_edge_param": round(nearest["edge_param"], 6),
                "nearest_edge_distance_m": round(nearest["distance_m"], 1),
                "track_connection_position": nearest["position"],
                "track_connection_source": "NEAREST_PHYSICAL_RAIL_EDGE_DERIVED",
            })
        result.append(item)
    return sorted(result, key=lambda item: item["entity_id"])


def _project_xy(point: dict, a: dict, b: dict) -> tuple[float, float, dict]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length2 = dx * dx + dy * dy
    param = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point["x"] - a["x"]) * dx + (point["y"] - a["y"]) * dy) / length2))
    position = {"x": a["x"] + dx * param, "y": a["y"] + dy * param, "z": a.get("z", 0.0) + (b.get("z", 0.0) - a.get("z", 0.0)) * param}
    return math.hypot(point["x"] - position["x"], point["y"] - position["y"]), param, position


def prepare(source: dict) -> dict:
    if source.get("status") != "OK" or source.get("source_status") != "ENGINE_OBSERVED":
        raise ValueError(f"rail source is not engine-observed: {source.get('status')}")
    nodes = {item["entity_id"]: item["position"] for item in source["nodes"]}
    edge_by_id = {item["entity_id"]: item for item in source["edges"]}
    adjacency: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    for edge in source["edges"]:
        length = curve_length(edge, nodes)
        adjacency[edge["node0"]].append((edge["node1"], edge["entity_id"], length))
        adjacency[edge["node1"]].append((edge["node0"], edge["entity_id"], length))

    disconnected = []
    lines = []
    for line in source["lines"]:
        route_edges, seen = [], set()
        overview_segments = []
        stops = line["stops"]
        for left, right in zip(stops, stops[1:]):
            path = shortest_edge_path(left["node_id"], right["node_id"], adjacency)
            if path is None:
                disconnected.append({"line_id": line["entity_id"], "from": left["node_id"], "to": right["node_id"]})
                continue
            overview_segments.append(simplify(ordered_route_points(left["node_id"], path, edge_by_id, nodes)))
            for edge_id in path:
                if edge_id not in seen:
                    seen.add(edge_id)
                    route_edges.append(edge_id)
        lines.append({**line, "route_edge_ids": route_edges, "overview_segments": overview_segments})

    edge_line_ids: dict[int, list[int]] = defaultdict(list)
    for line in lines:
        for edge_id in line["route_edge_ids"]:
            edge_line_ids[edge_id].append(line["entity_id"])
    used_edge_ids = set(edge_line_ids)
    stations = source["stations"]
    marker_track_types = infer_platform_model_track_types(source, nodes, stations, used_edge_ids)
    for station in stations:
        construction_files = {
            value.lower().replace("\\", "/") for value in station.get("construction_files", []) if isinstance(value, str)
        }
        station_is_freestyle = "station/rail/lollo_freestyle_train_station/station.con" in construction_files
        fixed_terminal_track_geometry = "station/rail/crst_hm.con" in construction_files
        # Invisible/model platform tracks belong to Freestyle Station. Never
        # let this geometric signature leak into a station whose construction
        # is known to be another type. Legacy inputs without construction data
        # retain the older geometry-only fallback.
        model_chains = platform_model_chains(station, source["edges"], nodes, marker_track_types) if station_is_freestyle or not construction_files else []
        assignments, used_chains = {}, set()
        pairs = sorted(
            (point_polyline_distance(terminal["position"], chain["centerline"]), terminal_index, chain_index)
            for terminal_index, terminal in enumerate(station.get("terminals", []))
            for chain_index, chain in enumerate(model_chains)
        )
        for distance, terminal_index, chain_index in pairs:
            if distance <= 30 and terminal_index not in assignments and chain_index not in used_chains:
                assignments[terminal_index] = model_chains[chain_index]
                used_chains.add(chain_index)
        for terminal_index, terminal in enumerate(station.get("terminals", [])):
            edge_ids, length, platform_node_ids = platform_chain(terminal["node_id"], adjacency, edge_by_id)
            adjacent_edge_ids = [edge_id for _, edge_id, _ in adjacency.get(terminal["node_id"], [])]
            evidence_edges = [edge_by_id[edge_id] for edge_id in adjacent_edge_ids if edge_id in edge_by_id]
            terminal_model, terminal_model_source = classify_terminal_station_model(
                evidence_edges, len(edge_ids), length, terminal.get("construction_file")
            )
            station_is_freestyle = station_is_freestyle or terminal_model == "FREESTYLE_STATION"
            terminal["station_model"] = terminal_model
            terminal["station_model_source"] = terminal_model_source
            terminal["platform_mean_edge_length_m"] = round(length / len(edge_ids), 2) if edge_ids else None
            terminal["track_resource_files"] = sorted({edge["track_resource_file"] for edge in evidence_edges if edge.get("track_resource_file")})
            raw_centerline = sampled_edge_path(platform_node_ids[0], edge_ids, edge_by_id, nodes) if edge_ids and platform_node_ids else []
            clipped_centerline = clip_polyline_to_bounds(raw_centerline, station.get("bounds"), terminal.get("position"))
            clipped_length = sum(math.dist(a, b) for a, b in zip(clipped_centerline, clipped_centerline[1:]))
            clipped = clipped_length > 0 and clipped_length + 1 < length
            terminal["platform_edge_ids"] = edge_ids
            use_full_curve = fixed_terminal_track_geometry and length > 0
            terminal["platform_length_m"] = round(length if use_full_curve else clipped_length if clipped_length > 0 else length, 1) or None
            terminal["platform_length_source"] = "FIXED_CONSTRUCTION_TERMINAL_TRACK_CURVE" if use_full_curve else "TERMINAL_TRACK_CLIPPED_TO_STATION_BOUNDS" if clipped else "TERMINAL_CURVE_TO_PRE_SWITCH_NODES" if length else "UNKNOWN"
            display_centerline = raw_centerline if use_full_curve else clipped_centerline
            terminal["platform_centerline"] = simplify(display_centerline, tolerance=.2) if len(display_centerline) >= 2 else []
            model_chain = assignments.get(terminal_index)
            if model_chain:
                terminal["platform_model_edge_ids"] = model_chain["edge_ids"]
                terminal["platform_model_track_type"] = model_chain["track_type"]
                terminal["platform_model_source"] = "INVISIBLE_PLATFORM_TRACK_SIGNATURE_DERIVED"
                terminal["operating_track_centerline"] = terminal["platform_centerline"]
                terminal["platform_centerline"] = model_chain["centerline"]
                terminal["platform_length_m"] = round(model_chain["length_m"], 1)
                terminal["platform_length_source"] = "PLATFORM_MODEL_TRACK_CHAIN_DERIVED"
        terminal_models = {terminal.get("station_model") for terminal in station.get("terminals", [])}
        terminal_model_sources = {terminal.get("station_model_source") for terminal in station.get("terminals", [])}
        observed_model_source = (
            "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED"
            if "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED" in terminal_model_sources
            else "TRACK_TYPE_RESOURCE_FILE_ENGINE_OBSERVED"
        )
        if station_is_freestyle:
            station["station_model"] = "FREESTYLE_STATION"
            station["station_model_source"] = observed_model_source
        elif terminal_models == {"OTHER"}:
            station["station_model"] = "OTHER"
            station["station_model_source"] = observed_model_source
        else:
            station["station_model"] = "UNKNOWN"
            station["station_model_source"] = "UNKNOWN"

        if construction_files & {
            "station/rail/modular_station/modular_station.con",
            "station/rail/modular_station/crst_modular_station.con",
        }:
            offset_modular_station_platforms(station)
        elif "station/rail/crst_hm.con" in construction_files:
            offset_crst_hm_platforms(station)
        elif "station/rail/eat1963_spitzkehre_cargo.con" in construction_files:
            mark_track_loading_terminals(station)

    # A modular construction may expose passenger and cargo terminals as
    # separate station groups. Normalize the physical span by construction so
    # both sides of that one construction use the same endpoints and length.
    modular_terminals_by_construction: dict[int, list[dict]] = defaultdict(list)
    modular_files = {
        "station/rail/modular_station/modular_station.con",
        "station/rail/modular_station/crst_modular_station.con",
    }
    for station in stations:
        for terminal in station.get("terminals", []):
            if str(terminal.get("construction_file") or "").lower() not in modular_files:
                continue
            construction_id = terminal.get("construction_entity_id")
            if isinstance(construction_id, int):
                modular_terminals_by_construction[construction_id].append(terminal)
    for terminals in modular_terminals_by_construction.values():
        normalize_modular_station_platform_spans({"terminals": terminals})

    xs = [point["x"] for point in nodes.values()]
    ys = [point["y"] for point in nodes.values()]
    platform_model_edge_ids = {
        edge_id
        for station in stations
        for terminal in station.get("terminals", [])
        for edge_id in terminal.get("platform_model_edge_ids", [])
    }
    physical_overview = physical_overview_segments(source, nodes, adjacency, platform_model_edge_ids)
    depots = prepare_rail_depots(source, nodes, edge_by_id)
    rendered_edges = [edge for edge in source["edges"] if edge["entity_id"] not in platform_model_edge_ids]
    result = {
        "schema_version": 1,
        "diagram_type": "ENGINE_OBSERVED_GLOBAL_RAIL_GRAPH",
        "source_status": "ENGINE_OBSERVED",
        "bounds": {"min": {"x": min(xs), "y": min(ys)}, "max": {"x": max(xs), "y": max(ys)}},
        "nodes": source["nodes"],
        "edges": [{**edge, "line_used": edge["entity_id"] in used_edge_ids, "line_ids": edge_line_ids.get(edge["entity_id"], [])} for edge in rendered_edges],
        "stations": stations,
        "depots": depots,
        "lines": lines,
        "counts": {**source["counts"], "rendered_rail_edges": len(rendered_edges),
                   "platform_model_edges_excluded_from_rail_render": len(platform_model_edge_ids),
                   "rail_depots": len(depots), "routed_lines": sum(bool(line["route_edge_ids"]) for line in lines), "disconnected_segments": len(disconnected)},
        "routing": {"method": "PHYSICAL_GRAPH_SHORTEST_PATH_DERIVED", "disconnected_segments": disconnected},
        "physical_overview_segments": physical_overview,
        "limitations": [
            "Track, station and terminal coordinates are engine-observed.",
            "Line paths between observed stop terminals are derived by shortest distance on the physical rail graph.",
            "Train positions and block occupancy are not included in this static version.",
        ],
    }
    # Keep only node positions referenced by an edge; malformed orphan nodes are not useful to the renderer.
    referenced = {edge[key] for edge in result["edges"] for key in ("node0", "node1")}
    result["nodes"] = [item for item in result["nodes"] if item["entity_id"] in referenced]
    return result


def build_manifest_and_tiles(result: dict, tile_size: float) -> tuple[dict, dict[str, dict]]:
    minimum = result["bounds"]["min"]
    nodes = {item["entity_id"]: item for item in result["nodes"]}
    tile_edges: dict[str, list[dict]] = defaultdict(list)
    tile_coordinates: dict[str, tuple[int, int]] = {}
    for edge in result["edges"]:
        a, b = nodes[edge["node0"]]["position"], nodes[edge["node1"]]["position"]
        ix = math.floor((((a["x"] + b["x"]) / 2) - minimum["x"]) / tile_size)
        iy = math.floor((((a["y"] + b["y"]) / 2) - minimum["y"]) / tile_size)
        key = f"{ix}_{iy}"
        tile_coordinates[key] = (ix, iy)
        tile_edges[key].append(edge)
    tiles, index = {}, []
    for key, edges in tile_edges.items():
        referenced = {edge[field] for edge in edges for field in ("node0", "node1")}
        ix, iy = tile_coordinates[key]
        tile = {
            "key": key,
            "nodes": [nodes[node_id] for node_id in sorted(referenced)],
            "edges": edges,
        }
        tiles[key] = tile
        index.append({
            "key": key, "edge_count": len(edges),
            "min": {"x": minimum["x"] + ix * tile_size, "y": minimum["y"] + iy * tile_size},
            "max": {"x": minimum["x"] + (ix + 1) * tile_size, "y": minimum["y"] + (iy + 1) * tile_size},
        })
    index.sort(key=lambda item: item["key"])
    manifest = {
        "schema_version": 2,
        "diagram_type": result["diagram_type"],
        "source_status": result["source_status"],
        "generated_at": int(time.time()),
        "bounds": result["bounds"],
        "stations": result["stations"],
        "depots": result.get("depots", []),
        "lines": [{key: value for key, value in line.items() if key != "route_edge_ids"} for line in result["lines"]],
        "counts": result["counts"],
        "routing": result["routing"],
        "physical_overview_segments": result.get("physical_overview_segments", []),
        "tile_size_m": tile_size,
        "detail_load_threshold_m": 600,
        "tiles": index,
        "limitations": result["limitations"],
    }
    return manifest, tiles


def apply_station_model_ground_truth(result: dict, ground_truth: dict) -> None:
    """Apply save-specific user observations without presenting them as engine API data."""
    allowed = {"FREESTYLE_STATION", "OTHER"}
    stations = {station["entity_id"]: station for station in result.get("stations", [])}
    for observation in ground_truth.get("stations", []):
        station = stations.get(observation.get("entity_id"))
        model = observation.get("station_model")
        if not station or model not in allowed:
            continue
        engine_identified = station.get("station_model_source") == "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED"
        if engine_identified:
            station["station_model_ground_truth_match"] = station.get("station_model") == model
            station["station_model_ground_truth_note"] = observation.get("note")
        else:
            station["station_model"] = model
            station["station_model_source"] = "USER_GROUND_TRUTH"
            station["station_model_ground_truth_note"] = observation.get("note")
        for terminal in station.get("terminals", []):
            if not engine_identified:
                terminal["station_model"] = model
                terminal["station_model_source"] = "USER_GROUND_TRUTH"
            if observation.get("platform_layout") == "OUTER_SIDE_OF_TERMINAL_TRACKS" and terminal.get("platform_centerline"):
                if terminal.get("platform_geometry_source"):
                    terminal["platform_geometry_ground_truth_match"] = terminal.get("platform_offset_m") == float(observation.get("platform_offset_m", 5.0))
                    continue
                offset = float(observation.get("platform_offset_m", 5.0))
                terminal["operating_track_centerline"] = terminal["platform_centerline"]
                terminal["platform_centerline"] = offset_polyline_away_from_center(
                    terminal["operating_track_centerline"], terminal["position"], station["center"], offset
                )
                terminal["platform_geometry_source"] = "OUTER_SIDE_OF_TERMINAL_TRACK_DERIVED"
                terminal["platform_offset_m"] = offset


def main() -> None:
    default_input = Path(os.environ["APPDATA"]) / "Transport Fever 2" / "tpf2_mcp_bridge" / "rail-network.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=default_input)
    parser.add_argument("--output-directory", type=Path, default=Path("ui/rail-map"))
    parser.add_argument("--tile-size", type=float, default=2000.0)
    parser.add_argument("--station-model-ground-truth", type=Path, default=Path("ui/rail-map/station-model-ground-truth.json"))
    args = parser.parse_args()
    result = prepare(json.loads(args.input.read_text(encoding="utf-8")))
    if args.station_model_ground_truth.is_file():
        apply_station_model_ground_truth(result, json.loads(args.station_model_ground_truth.read_text(encoding="utf-8")))
    args.output_directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    (args.output_directory / "rail-network-data.json").write_text(encoded + "\n", encoding="utf-8")
    (args.output_directory / "rail-network-data.js").write_text("window.RAIL_NETWORK_DATA=" + encoded + ";\n", encoding="utf-8")
    manifest, tiles = build_manifest_and_tiles(result, args.tile_size)
    manifest_encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    (args.output_directory / "rail-network-manifest.json").write_text(manifest_encoded + "\n", encoding="utf-8")
    (args.output_directory / "rail-network-manifest.js").write_text("window.RAIL_NETWORK_DATA=" + manifest_encoded + ";\n", encoding="utf-8")
    tile_directory = args.output_directory / "rail-network-tiles"
    tile_directory.mkdir(parents=True, exist_ok=True)
    for key, tile in tiles.items():
        tile_encoded = json.dumps(tile, ensure_ascii=False, separators=(",", ":"))
        (tile_directory / f"tile-{key}.json").write_text(tile_encoded + "\n", encoding="utf-8")
        script = f"window.RAIL_NETWORK_TILES=window.RAIL_NETWORK_TILES||{{}};window.RAIL_NETWORK_TILES[{json.dumps(key)}]={tile_encoded};window.dispatchEvent(new CustomEvent('rail-network-tile',{{detail:{json.dumps(key)}}}));\n"
        (tile_directory / f"tile-{key}.js").write_text(script, encoding="utf-8")
    print(json.dumps({**result["counts"], "tiles": len(tiles)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
