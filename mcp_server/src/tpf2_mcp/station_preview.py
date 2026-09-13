"""Generate one reusable, save-scoped physical rail preview per station."""
from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from pathlib import Path


DEFAULT_MARGIN_M = 50.0
MINIMUM_SPAN_M = 0.0
THROAT_SEARCH_M = 300.0
ISLAND_TRACK_GAP_MIN_M = 8.0
ISLAND_TRACK_GAP_MAX_M = 22.0
UNPAIRED_PLATFORM_OFFSET_M = 5.0


def _xy(value: dict | None, fallback: dict | None = None) -> tuple[float, float]:
    point = value or fallback or {}
    return float(point.get("x", 0.0)), float(point.get("y", 0.0))


def _station_track_points(station: dict, groups: list[dict], platforms: list[dict]) -> list[list[float]]:
    lines = [platform.get("platform_centerline") or [] for platform in platforms]
    lines.extend(
        _operating_track_centerline(terminal)
        for group in groups
        for terminal in group.get("terminals", [])
    )
    points = [list(map(float, point[:2])) for line in lines for point in line]
    if points:
        return points
    source = station.get("bounds") or {}
    if source:
        min_x, min_y = _xy(source.get("min"), station.get("center"))
        max_x, max_y = _xy(source.get("max"), station.get("center"))
        return [[min_x, min_y], [min_x, max_y], [max_x, min_y], [max_x, max_y]]
    return [list(_xy(station.get("center")))]


def _station_direction(station: dict, groups: list[dict], platforms: list[dict]) -> tuple[float, float]:
    lines = [platform.get("platform_centerline") or [] for platform in platforms]
    lines.extend(
        _operating_track_centerline(terminal)
        for group in groups
        for terminal in group.get("terminals", [])
    )
    segments = [
        (float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))
        for line in lines for left, right in zip(line, line[1:])
        if math.dist(left[:2], right[:2]) > 1e-6
    ]
    if segments:
        reference = max(segments, key=lambda value: math.hypot(*value))
        aligned = [value if value[0] * reference[0] + value[1] * reference[1] >= 0
                   else (-value[0], -value[1]) for value in segments]
        direction = (sum(value[0] for value in aligned), sum(value[1] for value in aligned))
    else:
        source = station.get("bounds") or {}
        min_x, min_y = _xy(source.get("min"), station.get("center"))
        max_x, max_y = _xy(source.get("max"), station.get("center"))
        direction = (1.0, 0.0) if max_x - min_x >= max_y - min_y else (0.0, 1.0)
    length = math.hypot(*direction)
    if length <= 1e-9:
        return 1.0, 0.0
    result = (direction[0] / length, direction[1] / length)
    return (-result[0], -result[1]) if result[0] < 0 or (abs(result[0]) <= 1e-9 and result[1] < 0) else result


def _project_frame(point: tuple[float, float] | list[float], origin: tuple[float, float],
                   direction: tuple[float, float], normal: tuple[float, float]) -> tuple[float, float]:
    delta = (float(point[0]) - origin[0], float(point[1]) - origin[1])
    return delta[0] * direction[0] + delta[1] * direction[1], delta[0] * normal[0] + delta[1] * normal[1]


def _edge_samples(edge: dict, nodes: dict[int, dict]) -> list[tuple[float, float]]:
    a = nodes.get(int(edge.get("node0", -1)), {}).get("position")
    b = nodes.get(int(edge.get("node1", -1)), {}).get("position")
    if not a or not b:
        return []
    fallback = {axis: float(b.get(axis, 0)) - float(a.get(axis, 0)) for axis in ("x", "y")}
    tangent0 = edge.get("tangent0") or fallback
    tangent1 = edge.get("tangent1") or fallback
    count = min(24, max(8, math.ceil(math.dist(_xy(a), _xy(b)) / 25)))
    result = []
    for index in range(count + 1):
        ratio = index / count
        h00 = 2 * ratio ** 3 - 3 * ratio ** 2 + 1
        h10 = ratio ** 3 - 2 * ratio ** 2 + ratio
        h01 = -2 * ratio ** 3 + 3 * ratio ** 2
        h11 = ratio ** 3 - ratio ** 2
        result.append((
            h00 * float(a.get("x", 0)) + h10 * float(tangent0.get("x", 0))
            + h01 * float(b.get("x", 0)) + h11 * float(tangent1.get("x", 0)),
            h00 * float(a.get("y", 0)) + h10 * float(tangent0.get("y", 0))
            + h01 * float(b.get("y", 0)) + h11 * float(tangent1.get("y", 0)),
        ))
    return result


def _segment_intersects_rectangle(left: tuple[float, float], right: tuple[float, float],
                                  along_min: float, along_max: float,
                                  across_min: float, across_max: float) -> bool:
    delta = (right[0] - left[0], right[1] - left[1])
    lower, upper = 0.0, 1.0
    for start, change, minimum, maximum in (
        (left[0], delta[0], along_min, along_max),
        (left[1], delta[1], across_min, across_max),
    ):
        if abs(change) <= 1e-12:
            if start < minimum or start > maximum:
                return False
            continue
        entry, exit_ = sorted(((minimum - start) / change, (maximum - start) / change))
        lower, upper = max(lower, entry), min(upper, exit_)
        if lower > upper:
            return False
    return True


def _point_in_scope(point: dict | None, scope: dict) -> bool:
    along, across = _project_frame(_xy(point), _xy(scope["origin"]), _xy(scope["direction"]), _xy(scope["normal"]))
    return (scope["along"]["min"] <= along <= scope["along"]["max"]
            and scope["across"]["min"] <= across <= scope["across"]["max"])


def _edge_intersects_scope(edge: dict, nodes: dict[int, dict], scope: dict,
                           samples: list[tuple[float, float]] | None = None) -> bool:
    origin, direction, normal = _xy(scope["origin"]), _xy(scope["direction"]), _xy(scope["normal"])
    points = [_project_frame(point, origin, direction, normal) for point in (samples or _edge_samples(edge, nodes))]
    return any(
        _segment_intersects_rectangle(left, right, scope["along"]["min"], scope["along"]["max"],
                                      scope["across"]["min"], scope["across"]["max"])
        for left, right in zip(points, points[1:])
    )


def _edge_intersects(edge: dict, nodes: dict[int, dict], bounds: dict) -> bool:
    a = nodes.get(edge.get("node0"), {}).get("position")
    b = nodes.get(edge.get("node1"), {}).get("position")
    if not a or not b:
        return False
    # Hermite curves can leave the endpoint rectangle.  Include their Bezier
    # control points so a curved throat is not clipped out of a station preview.
    fallback = {axis: float(b.get(axis, 0)) - float(a.get(axis, 0)) for axis in ("x", "y")}
    tangent0 = edge.get("tangent0") or fallback
    tangent1 = edge.get("tangent1") or fallback
    points = [
        _xy(a),
        (float(a.get("x", 0)) + float(tangent0.get("x", 0)) / 3,
         float(a.get("y", 0)) + float(tangent0.get("y", 0)) / 3),
        (float(b.get("x", 0)) - float(tangent1.get("x", 0)) / 3,
         float(b.get("y", 0)) - float(tangent1.get("y", 0)) / 3),
        _xy(b),
    ]
    edge_min_x = min(point[0] for point in points)
    edge_max_x = max(point[0] for point in points)
    edge_min_y = min(point[1] for point in points)
    edge_max_y = max(point[1] for point in points)
    return not (
        edge_max_x < bounds["min"]["x"] or edge_min_x > bounds["max"]["x"]
        or edge_max_y < bounds["min"]["y"] or edge_min_y > bounds["max"]["y"]
    )


def _polyline_length(points: list[list[float]]) -> float:
    return sum(math.dist(left[:2], right[:2]) for left, right in zip(points, points[1:]))


def _sample_polyline(points: list[list[float]], count: int = 9) -> list[list[float]]:
    if len(points) < 2:
        return [list(point[:2]) for point in points]
    lengths = [math.dist(left[:2], right[:2]) for left, right in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 1e-9:
        return [list(points[0][:2]) for _ in range(count)]
    result = []
    for index in range(count):
        target = total * index / (count - 1)
        traversed = 0.0
        for segment_index, length in enumerate(lengths):
            if traversed + length >= target or segment_index == len(lengths) - 1:
                ratio = 0.0 if length <= 1e-9 else (target - traversed) / length
                left, right = points[segment_index], points[segment_index + 1]
                result.append([
                    float(left[0]) + (float(right[0]) - float(left[0])) * ratio,
                    float(left[1]) + (float(right[1]) - float(left[1])) * ratio,
                ])
                break
            traversed += length
    return result


def _aligned_samples(left: list[list[float]], right: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    left_samples = _sample_polyline(left)
    right_samples = _sample_polyline(right)
    direct = math.dist(left_samples[0], right_samples[0]) + math.dist(left_samples[-1], right_samples[-1])
    reverse = math.dist(left_samples[0], right_samples[-1]) + math.dist(left_samples[-1], right_samples[0])
    if reverse < direct:
        right_samples.reverse()
    return left_samples, right_samples


def _operating_track_centerline(terminal: dict) -> list[list[float]]:
    return terminal.get("operating_track_centerline") or terminal.get("platform_centerline") or []


def _polyline_midpoint(points: list[list[float]]) -> list[float]:
    return _sample_polyline(points, 3)[1]


def _island_pair_distance(left: dict, right: dict) -> float | None:
    if bool(left.get("cargo")) != bool(right.get("cargo")):
        return None
    left_points = _operating_track_centerline(left)
    right_points = _operating_track_centerline(right)
    if len(left_points) < 2 or len(right_points) < 2:
        return None
    left_length, right_length = _polyline_length(left_points), _polyline_length(right_points)
    if min(left_length, right_length) <= 1e-9 or max(left_length, right_length) / min(left_length, right_length) > 1.15:
        return None
    left_samples, right_samples = _aligned_samples(left_points, right_points)
    left_vector = (left_samples[-1][0] - left_samples[0][0], left_samples[-1][1] - left_samples[0][1])
    right_vector = (right_samples[-1][0] - right_samples[0][0], right_samples[-1][1] - right_samples[0][1])
    denominator = math.hypot(*left_vector) * math.hypot(*right_vector)
    if denominator <= 1e-9 or abs(sum(a * b for a, b in zip(left_vector, right_vector)) / denominator) < .98:
        return None
    distances = [math.dist(a, b) for a, b in zip(left_samples, right_samples)]
    separation = sum(distances) / len(distances)
    if separation < ISLAND_TRACK_GAP_MIN_M or separation > ISLAND_TRACK_GAP_MAX_M:
        return None
    if max(distances) > ISLAND_TRACK_GAP_MAX_M * 1.25:
        return None
    return separation


def _terminal_lateral_order(terminals: list[dict]) -> tuple[list[int], tuple[float, float]]:
    reference = next((_operating_track_centerline(item) for item in terminals
                      if len(_operating_track_centerline(item)) >= 2), [])
    if len(reference) < 2:
        return list(range(len(terminals))), (0.0, 1.0)
    samples = _sample_polyline(reference, 3)
    direction = (samples[-1][0] - samples[0][0], samples[-1][1] - samples[0][1])
    length = math.hypot(*direction)
    normal = (-direction[1] / length, direction[0] / length)
    lateral = []
    for index, terminal in enumerate(terminals):
        points = _operating_track_centerline(terminal)
        midpoint = _polyline_midpoint(points) if len(points) >= 2 else [0.0, 0.0]
        lateral.append((midpoint[0] * normal[0] + midpoint[1] * normal[1], index))
    return [index for _, index in sorted(lateral)], normal


def _platform_faces_gap(terminal: dict, direction: int, normal: tuple[float, float]) -> bool:
    """Return whether an explicit platform surface lies on the requested rail side."""
    track = _operating_track_centerline(terminal)
    platform = terminal.get("platform_centerline") or []
    if len(track) < 2 or len(platform) < 2 or not terminal.get("platform_geometry_source"):
        return False
    track_midpoint = _polyline_midpoint(track)
    platform_midpoint = _polyline_midpoint(platform)
    offset = ((platform_midpoint[0] - track_midpoint[0]) * normal[0]
              + (platform_midpoint[1] - track_midpoint[1]) * normal[1])
    return offset * direction > 0.5


def _terminal_reference(terminal: dict) -> dict:
    return {
        "station_index": terminal.get("station_index"),
        "terminal_index": terminal.get("terminal_index"),
        "node_id": terminal.get("node_id"),
    }


def _offset_unpaired_centerline(station: dict, terminal: dict) -> list[list[float]]:
    points = [list(point[:2]) for point in (terminal.get("platform_centerline") or [])]
    if len(points) < 2:
        return points
    samples = _sample_polyline(points)
    midpoint = samples[len(samples) // 2]
    direction = (samples[-1][0] - samples[0][0], samples[-1][1] - samples[0][1])
    length = math.hypot(*direction)
    if length <= 1e-9:
        return points
    normal = [-direction[1] / length, direction[0] / length]
    center_x, center_y = _xy(station.get("center"))
    outward = (midpoint[0] - center_x, midpoint[1] - center_y)
    if normal[0] * outward[0] + normal[1] * outward[1] < 0:
        normal[0], normal[1] = -normal[0], -normal[1]
    return [[point[0] + normal[0] * UNPAIRED_PLATFORM_OFFSET_M,
             point[1] + normal[1] * UNPAIRED_PLATFORM_OFFSET_M] for point in points]


def build_station_platforms(station: dict) -> list[dict]:
    """Reconstruct side and island platforms from terminal operating tracks."""
    terminals = station.get("terminals", [])
    order, normal = _terminal_lateral_order(terminals)
    candidates = []
    allow_inferred_islands = len(terminals) >= 3 and station.get("station_model") != "FREESTYLE_STATION"
    for left_index, right_index in zip(order, order[1:]):
        left, right = terminals[left_index], terminals[right_index]
        separation = _island_pair_distance(left, right)
        if separation is None:
            continue
        explicit_inward = (
            _platform_faces_gap(left, 1, normal)
            and _platform_faces_gap(right, -1, normal)
        )
        no_explicit_geometry = not left.get("platform_geometry_source") and not right.get("platform_geometry_source")
        if explicit_inward or (allow_inferred_islands and no_explicit_geometry):
            candidates.append((separation, left_index, right_index))
    used: set[int] = set()
    pairs: dict[int, int] = {}
    for _, left_index, right_index in sorted(candidates):
        if left_index in used or right_index in used:
            continue
        used.update((left_index, right_index))
        pairs[left_index] = right_index

    platforms = []
    for terminal_index in order:
        terminal = terminals[terminal_index]
        if terminal_index in used and terminal_index not in pairs:
            continue
        if terminal_index in pairs:
            other = terminals[pairs[terminal_index]]
            left_samples, right_samples = _aligned_samples(
                _operating_track_centerline(terminal), _operating_track_centerline(other),
            )
            centerline = [[(left[0] + right[0]) / 2, (left[1] + right[1]) / 2]
                          for left, right in zip(left_samples, right_samples)]
            length_values = [value for value in (terminal.get("platform_length_m"), other.get("platform_length_m"))
                             if isinstance(value, (int, float))]
            platforms.append({
                "platform_index": len(platforms),
                "platform_kind": "ISLAND",
                "platform_width_units": 2,
                "cargo": bool(terminal.get("cargo")),
                "terminal_faces": [_terminal_reference(terminal), _terminal_reference(other)],
                "platform_centerline": centerline,
                "platform_length_m": min(length_values) if length_values else None,
                "platform_length_source": "PAIRED_TERMINAL_FACES_MINIMUM_DERIVED",
                "platform_geometry_source": "PAIRED_TERMINAL_FACES_MIDLINE_DERIVED",
            })
            continue
        centerline = terminal.get("platform_centerline") or []
        geometry_source = terminal.get("platform_geometry_source")
        if not geometry_source:
            centerline = _offset_unpaired_centerline(station, terminal)
            geometry_source = "UNPAIRED_TERMINAL_SIDE_OFFSET_DERIVED"
        platforms.append({
            "platform_index": len(platforms),
            "platform_kind": "SIDE_OR_SINGLE_FACE",
            "platform_width_units": 1,
            "cargo": bool(terminal.get("cargo")),
            "terminal_faces": [_terminal_reference(terminal)],
            "platform_centerline": centerline,
            "platform_length_m": terminal.get("platform_length_m"),
            "platform_length_source": terminal.get("platform_length_source"),
            "platform_geometry_source": geometry_source,
        })
    return platforms


def _shared_construction_groups(station: dict, stations: list[dict]) -> list[dict]:
    construction_ids = {
        value for value in station.get("construction_entity_ids", []) if isinstance(value, int)
    }
    if not construction_ids:
        return [station]
    related = [
        item for item in stations
        if construction_ids.intersection(
            value for value in item.get("construction_entity_ids", []) if isinstance(value, int)
        )
    ]
    return related or [station]


def _combined_station_bounds(station: dict, groups: list[dict]) -> dict:
    bounds = [item.get("bounds") for item in groups if item.get("bounds")]
    if not bounds:
        return station
    combined = {
        "min": {
            axis: min(float(item["min"].get(axis, 0)) for item in bounds)
            for axis in ("x", "y")
        },
        "max": {
            axis: max(float(item["max"].get(axis, 0)) for item in bounds)
            for axis in ("x", "y")
        },
    }
    return {**station, "bounds": combined}


def _combined_physical_platforms(groups: list[dict]) -> list[dict]:
    platforms = [
        {**platform, "station_group_id": group.get("entity_id"), "station_group_name": group.get("name")}
        for group in groups
        for platform in group.get("platforms", [])
    ]
    reference = next(
        (item.get("platform_centerline") for item in platforms if len(item.get("platform_centerline") or []) >= 2),
        None,
    )
    if reference:
        samples = _sample_polyline(reference, 3)
        direction = (samples[-1][0] - samples[0][0], samples[-1][1] - samples[0][1])
        length = math.hypot(*direction)
        normal = (-direction[1] / length, direction[0] / length) if length > 1e-9 else (0.0, 1.0)
        platforms.sort(key=lambda item: (
            sum(a * b for a, b in zip(_polyline_midpoint(item.get("platform_centerline") or [[0, 0], [0, 0]]), normal)),
            int(item.get("station_group_id") or 0),
            int(item.get("platform_index") or 0),
        ))
    for index, platform in enumerate(platforms):
        platform["platform_index"] = index
    return platforms


def _station_scope(station: dict, groups: list[dict], platforms: list[dict],
                   edge_by_id: dict[int, dict], adjacency: dict[int, list[tuple[int, int, float]]],
                   edge_samples: dict[int, list[tuple[float, float]]], nodes: dict[int, dict],
                   margin_m: float, minimum_span_m: float) -> dict:
    """Build an oriented platform/siding rectangle bounded by both throats."""
    core_points = _station_track_points(station, groups, platforms)
    origin = (
        sum(point[0] for point in core_points) / len(core_points),
        sum(point[1] for point in core_points) / len(core_points),
    )
    direction = _station_direction(station, groups, platforms)
    normal = (-direction[1], direction[0])
    core_local = [_project_frame(point, origin, direction, normal) for point in core_points]
    core_along_min = min(point[0] for point in core_local)
    core_along_max = max(point[0] for point in core_local)
    core_across_min = min(point[1] for point in core_local)
    core_across_max = max(point[1] for point in core_local)

    platform_edge_ids = {
        int(edge_id)
        for group in groups
        for terminal in group.get("terminals", [])
        for edge_id in terminal.get("platform_edge_ids", [])
        if int(edge_id) in edge_by_id
    }
    seed_nodes = {
        int(node_id)
        for group in groups
        for terminal in group.get("terminals", [])
        for node_id in [terminal.get("node_id")]
        if isinstance(node_id, int) and int(node_id) in nodes
    }
    for edge_id in platform_edge_ids:
        seed_nodes.update((int(edge_by_id[edge_id]["node0"]), int(edge_by_id[edge_id]["node1"])))
    if not seed_nodes and nodes:
        seed_nodes.add(min(nodes, key=lambda node_id: math.dist(_xy(nodes[node_id].get("position")), origin)))

    distances = {node_id: 0.0 for node_id in seed_nodes}
    queue = [(0.0, node_id) for node_id in seed_nodes]
    heapq.heapify(queue)
    reached_edges = set(platform_edge_ids)
    while queue:
        current_distance, node_id = heapq.heappop(queue)
        if current_distance != distances.get(node_id) or current_distance > THROAT_SEARCH_M:
            continue
        for neighbor_id, edge_id, edge_length in adjacency.get(node_id, []):
            next_distance = current_distance + edge_length
            if next_distance > THROAT_SEARCH_M:
                continue
            reached_edges.add(edge_id)
            if next_distance + 1e-9 < distances.get(neighbor_id, math.inf):
                distances[neighbor_id] = next_distance
                heapq.heappush(queue, (next_distance, neighbor_id))

    relevant_switch_along = []
    for node_id in distances:
        links = adjacency.get(node_id, [])
        if len(links) < 3:
            continue
        along, _ = _project_frame(_xy(nodes[node_id].get("position")), origin, direction, normal)
        if core_along_min <= along <= core_along_max:
            relevant_switch_along.append(along)
            continue
        neighbor_along = [
            _project_frame(_xy(nodes[neighbor_id].get("position")), origin, direction, normal)[0]
            for neighbor_id, _, _ in links
        ]
        if along < core_along_min and sum(value > along + .25 for value in neighbor_along) >= 2:
            relevant_switch_along.append(along)
        elif along > core_along_max and sum(value < along - .25 for value in neighbor_along) >= 2:
            relevant_switch_along.append(along)

    throat_along_min = min([core_along_min, *relevant_switch_along])
    throat_along_max = max([core_along_max, *relevant_switch_along])
    siding_points = list(core_local)
    for edge_id in reached_edges:
        for point in edge_samples.get(edge_id, []):
            local = _project_frame(point, origin, direction, normal)
            if throat_along_min <= local[0] <= throat_along_max:
                siding_points.append(local)
    siding_across_min = min([core_across_min, *(point[1] for point in siding_points)])
    siding_across_max = max([core_across_max, *(point[1] for point in siding_points)])

    along_min, along_max = throat_along_min - margin_m, throat_along_max + margin_m
    across_min, across_max = siding_across_min - margin_m, siding_across_max + margin_m
    if minimum_span_m > 0:
        along_center, across_center = (along_min + along_max) / 2, (across_min + across_max) / 2
        half_along = max((along_max - along_min) / 2, minimum_span_m / 2)
        half_across = max((across_max - across_min) / 2, minimum_span_m / 2)
        along_min, along_max = along_center - half_along, along_center + half_along
        across_min, across_max = across_center - half_across, across_center + half_across

    def world(along: float, across: float) -> dict:
        return {
            "x": origin[0] + direction[0] * along + normal[0] * across,
            "y": origin[1] + direction[1] * along + normal[1] * across,
        }

    polygon = [
        world(along_min, across_min), world(along_min, across_max),
        world(along_max, across_max), world(along_max, across_min),
    ]
    return {
        "source": "PLATFORM_SIDING_THROAT_ORIENTED_RECTANGLE_DERIVED",
        "origin": {"x": origin[0], "y": origin[1]},
        "direction": {"x": direction[0], "y": direction[1]},
        "normal": {"x": normal[0], "y": normal[1]},
        "along": {"min": along_min, "max": along_max},
        "across": {"min": across_min, "max": across_max},
        "throat": {"min": throat_along_min, "max": throat_along_max},
        "margin_m": margin_m,
        "relevant_switch_count": len(relevant_switch_along),
        "polygon": polygon,
    }


def _scope_bounds(scope: dict) -> dict:
    return {
        "min": {axis: min(point[axis] for point in scope["polygon"]) for axis in ("x", "y")},
        "max": {axis: max(point[axis] for point in scope["polygon"]) for axis in ("x", "y")},
    }


def build_station_previews(
    network: dict,
    *,
    margin_m: float = DEFAULT_MARGIN_M,
    minimum_span_m: float = MINIMUM_SPAN_M,
    generated_at: int | None = None,
) -> tuple[dict, dict[int, dict]]:
    """Build deterministic preview payloads from a prepared physical network."""
    generated_at = int(time.time()) if generated_at is None else int(generated_at)
    node_by_id = {int(item["entity_id"]): item for item in network.get("nodes", [])}
    edges = network.get("edges", [])
    edge_by_id = {int(edge["entity_id"]): edge for edge in edges}
    degree: dict[int, int] = {}
    adjacency: dict[int, list[tuple[int, int, float]]] = {}
    for edge in edges:
        node0, node1, edge_id = int(edge["node0"]), int(edge["node1"]), int(edge["entity_id"])
        for key in ("node0", "node1"):
            node_id = int(edge[key])
            degree[node_id] = degree.get(node_id, 0) + 1
        if node0 in node_by_id and node1 in node_by_id:
            length = max(1e-6, math.dist(
                _xy(node_by_id[node0].get("position")), _xy(node_by_id[node1].get("position")),
            ))
            adjacency.setdefault(node0, []).append((node1, edge_id, length))
            adjacency.setdefault(node1, []).append((node0, edge_id, length))
    edge_samples = {edge_id: _edge_samples(edge, node_by_id) for edge_id, edge in edge_by_id.items()}
    edge_sample_bounds = {
        edge_id: {
            "min_x": min(point[0] for point in points), "max_x": max(point[0] for point in points),
            "min_y": min(point[1] for point in points), "max_y": max(point[1] for point in points),
        }
        for edge_id, points in edge_samples.items() if points
    }

    previews: dict[int, dict] = {}
    index: list[dict] = []
    stations = [
        station if "platforms" in station else {**station, "platforms": build_station_platforms(station)}
        for station in network.get("stations", [])
    ]
    lines = network.get("lines", [])
    for station in stations:
        station_id = int(station["entity_id"])
        station_groups = _shared_construction_groups(station, stations)
        combined_platforms = _combined_physical_platforms(station_groups)
        group_ids = {int(item["entity_id"]) for item in station_groups}
        scoped_station = _combined_station_bounds(station, station_groups)
        scope = _station_scope(
            scoped_station, station_groups, combined_platforms, edge_by_id, adjacency, edge_samples,
            node_by_id, margin_m, minimum_span_m,
        )
        bounds = _scope_bounds(scope)
        preview_edges = [
            edge for edge in edges
            if (sample_bounds := edge_sample_bounds.get(int(edge["entity_id"])))
            and sample_bounds["max_x"] >= bounds["min"]["x"]
            and sample_bounds["min_x"] <= bounds["max"]["x"]
            and sample_bounds["max_y"] >= bounds["min"]["y"]
            and sample_bounds["min_y"] <= bounds["max"]["y"]
            and _edge_intersects_scope(
                edge, node_by_id, scope, edge_samples.get(int(edge["entity_id"])),
            )
        ]
        preview_crossings = [
            crossing for crossing in network.get("grade_separated_crossings", [])
            if _point_in_scope(crossing.get("position"), scope)
        ]
        referenced = {int(edge[key]) for edge in preview_edges for key in ("node0", "node1")}
        preview_nodes = [
            {**node_by_id[node_id], "degree": degree.get(node_id, 0)}
            for node_id in sorted(referenced)
            if node_id in node_by_id
        ]
        nearby_stations = [
            item for item in stations
            if _point_in_scope(item.get("center"), scope)
        ]
        nearby_depots = [
            item for item in network.get("depots", [])
            if _point_in_scope(item.get("center"), scope)
        ]
        serving_lines = [
            {key: value for key, value in line.items() if key != "route_edge_ids"}
            for line in lines
            if any(stop.get("station_group_id") in group_ids for stop in line.get("stops", []))
        ]
        payload = {
            "schema_version": 1,
            "save_id": network.get("save_id"),
            "generated_at": generated_at,
            "source_status": network.get("source_status"),
            "diagram_type": "ENGINE_OBSERVED_STATION_PHYSICAL_PREVIEW",
            "station": station,
            "station_groups": station_groups,
            "platforms": combined_platforms,
            "bounds": bounds,
            "scope": scope,
            "nodes": preview_nodes,
            "edges": preview_edges,
            "grade_separated_crossings": preview_crossings,
            "nearby_stations": nearby_stations,
            "depots": nearby_depots,
            "lines": serving_lines,
            "margin_m": margin_m,
            "counts": {
                "nodes": len(preview_nodes),
                "edges": len(preview_edges),
                "grade_separated_crossings": len(preview_crossings),
                "switch_nodes": sum(item.get("degree", 0) >= 3 for item in preview_nodes),
                "terminals": sum(len(item.get("terminals", [])) for item in station_groups),
                "platforms": len(combined_platforms),
                "lines": len(serving_lines),
            },
        }
        previews[station_id] = payload
        index.append({
            "station_id": station_id,
            "name": station.get("name"),
            "file": f"station-{station_id}.json",
            "edge_count": len(preview_edges),
            "bounds": bounds,
        })

    index.sort(key=lambda item: item["station_id"])
    manifest = {
        "schema_version": 1,
        "save_id": network.get("save_id"),
        "generated_at": generated_at,
        "source_status": network.get("source_status"),
        "station_count": len(index),
        "stations": index,
    }
    return manifest, previews


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_station_previews(
    network: dict,
    output_directory: Path,
    *,
    margin_m: float = DEFAULT_MARGIN_M,
    minimum_span_m: float = MINIMUM_SPAN_M,
    generated_at: int | None = None,
) -> dict:
    """Write every station payload first and publish the manifest last."""
    manifest, previews = build_station_previews(
        network, margin_m=margin_m, minimum_span_m=minimum_span_m, generated_at=generated_at,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    expected = set()
    for station_id, payload in previews.items():
        filename = f"station-{station_id}.json"
        expected.add(filename)
        _write_json_atomic(output_directory / filename, payload)
    for stale in output_directory.glob("station-*.json"):
        if stale.name not in expected:
            stale.unlink()
    _write_json_atomic(output_directory / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Prepared rail-network-data.json")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_M)
    args = parser.parse_args()
    network = json.loads(args.input.read_text(encoding="utf-8"))
    manifest = write_station_previews(network, args.output_directory, margin_m=args.margin)
    print(json.dumps({"save_id": manifest.get("save_id"), "stations": manifest["station_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
