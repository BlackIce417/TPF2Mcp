"""Detect grade-separated rail crossings from engine-observed XYZ geometry."""
from __future__ import annotations

import math
from collections import defaultdict


def _position(value: dict | None) -> dict | None:
    if not value:
        return None
    return value.get("position", value)


def _distance_xy(left: dict, right: dict) -> float:
    return math.hypot(float(left.get("x", 0)) - float(right.get("x", 0)),
                      float(left.get("y", 0)) - float(right.get("y", 0)))


def _canonical_direction(x: float, y: float) -> dict:
    length = math.hypot(x, y)
    if length <= 1e-9:
        return {"x": 1.0, "y": 0.0}
    x, y = x / length, y / length
    if x < 0 or (abs(x) <= 1e-9 and y < 0):
        x, y = -x, -y
    return {"x": x, "y": y}


def _cubic_point(edge: dict, left: dict, right: dict, ratio: float) -> dict:
    fallback = {key: float(right.get(key, 0)) - float(left.get(key, 0)) for key in ("x", "y", "z")}
    tangent0 = edge.get("tangent0") or fallback
    tangent1 = edge.get("tangent1") or fallback
    h00 = 2 * ratio ** 3 - 3 * ratio ** 2 + 1
    h10 = ratio ** 3 - 2 * ratio ** 2 + ratio
    h01 = -2 * ratio ** 3 + 3 * ratio ** 2
    h11 = ratio ** 3 - ratio ** 2
    return {
        key: (h00 * float(left.get(key, 0)) + h10 * float(tangent0.get(key, 0))
              + h01 * float(right.get(key, 0)) + h11 * float(tangent1.get(key, 0)))
        for key in ("x", "y", "z")
    }


def _cross(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _segment_intersection(left: dict, right: dict, minimum_angle_sin: float) -> dict | None:
    left_vector = (left["b"]["x"] - left["a"]["x"], left["b"]["y"] - left["a"]["y"])
    right_vector = (right["b"]["x"] - right["a"]["x"], right["b"]["y"] - right["a"]["y"])
    denominator = _cross(left_vector, right_vector)
    lengths = math.hypot(*left_vector) * math.hypot(*right_vector)
    if lengths <= 1e-9 or abs(denominator) / lengths <= max(minimum_angle_sin, 1e-9):
        return None
    delta = (right["a"]["x"] - left["a"]["x"], right["a"]["y"] - left["a"]["y"])
    left_ratio = _cross(delta, right_vector) / denominator
    right_ratio = _cross(delta, left_vector) / denominator
    epsilon = 1e-7
    if not (-epsilon <= left_ratio <= 1 + epsilon and -epsilon <= right_ratio <= 1 + epsilon):
        return None
    left_ratio = max(0.0, min(1.0, left_ratio))
    right_ratio = max(0.0, min(1.0, right_ratio))
    return {
        "x": left["a"]["x"] + left_vector[0] * left_ratio,
        "y": left["a"]["y"] + left_vector[1] * left_ratio,
        "left_z": left["a"]["z"] + (left["b"]["z"] - left["a"]["z"]) * left_ratio,
        "right_z": right["a"]["z"] + (right["b"]["z"] - right["a"]["z"]) * right_ratio,
        "left_direction": _canonical_direction(*left_vector),
        "right_direction": _canonical_direction(*right_vector),
    }


def detect_grade_separated_crossings(
    edges: list[dict],
    nodes: dict[int, dict] | list[dict],
    *,
    cell_size_m: float = 20.0,
    samples: int = 8,
    maximum_samples: int = 24,
    minimum_clearance_m: float = .75,
    minimum_endpoint_distance_m: float = .25,
    minimum_angle_degrees: float = 0.0,
) -> list[dict]:
    """Return disconnected XY crossings whose engine Z values prove vertical separation."""
    if isinstance(nodes, list):
        node_by_id = {int(item["entity_id"]): _position(item) for item in nodes}
    else:
        node_by_id = {int(node_id): _position(value) for node_id, value in nodes.items()}
    minimum_angle_sin = math.sin(math.radians(minimum_angle_degrees))
    buckets: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    crossings: dict[tuple[int, int], dict] = {}
    segment_index = 0

    for edge in edges:
        endpoint0 = node_by_id.get(int(edge["node0"]))
        endpoint1 = node_by_id.get(int(edge["node1"]))
        if not endpoint0 or not endpoint1:
            continue
        chord_length = _distance_xy(endpoint0, endpoint1)
        sample_count = min(maximum_samples, max(samples, math.ceil(chord_length / 25)))
        previous = _cubic_point(edge, endpoint0, endpoint1, 0.0)
        for sample_index in range(1, sample_count + 1):
            current = _cubic_point(edge, endpoint0, endpoint1, sample_index / sample_count)
            if _distance_xy(previous, current) <= 1e-6:
                previous = current
                continue
            segment = {
                "index": segment_index, "edge": edge, "a": previous, "b": current,
                "endpoint0": endpoint0, "endpoint1": endpoint1,
            }
            segment_index += 1
            min_cell_x = math.floor(min(previous["x"], current["x"]) / cell_size_m)
            max_cell_x = math.floor(max(previous["x"], current["x"]) / cell_size_m)
            min_cell_y = math.floor(min(previous["y"], current["y"]) / cell_size_m)
            max_cell_y = math.floor(max(previous["y"], current["y"]) / cell_size_m)
            compared: set[int] = set()
            occupied_cells = [
                (cell_x, cell_y)
                for cell_x in range(min_cell_x, max_cell_x + 1)
                for cell_y in range(min_cell_y, max_cell_y + 1)
            ]
            for cell in occupied_cells:
                for other in buckets[cell]:
                    if other["index"] in compared:
                        continue
                    compared.add(other["index"])
                    left_id, right_id = int(edge["entity_id"]), int(other["edge"]["entity_id"])
                    if left_id == right_id:
                        continue
                    edge_nodes = {edge["node0"], edge["node1"]}
                    if edge_nodes.intersection((other["edge"]["node0"], other["edge"]["node1"])):
                        continue
                    pair = tuple(sorted((left_id, right_id)))
                    if pair in crossings:
                        continue
                    hit = _segment_intersection(segment, other, minimum_angle_sin)
                    if not hit:
                        continue
                    if min(_distance_xy(hit, endpoint) for endpoint in (
                        endpoint0, endpoint1, other["endpoint0"], other["endpoint1"],
                    )) < minimum_endpoint_distance_m:
                        continue
                    clearance = abs(hit["left_z"] - hit["right_z"])
                    if clearance < minimum_clearance_m:
                        continue
                    left_is_upper = hit["left_z"] > hit["right_z"]
                    crossings[pair] = {
                        "position": {"x": hit["x"], "y": hit["y"]},
                        "upper_z": hit["left_z"] if left_is_upper else hit["right_z"],
                        "lower_z": hit["right_z"] if left_is_upper else hit["left_z"],
                        "clearance_m": clearance,
                        "upper_edge_id": left_id if left_is_upper else right_id,
                        "lower_edge_id": right_id if left_is_upper else left_id,
                        "upper_node_ids": (
                            [int(edge["node0"]), int(edge["node1"])] if left_is_upper
                            else [int(other["edge"]["node0"]), int(other["edge"]["node1"])]
                        ),
                        "lower_node_ids": (
                            [int(other["edge"]["node0"]), int(other["edge"]["node1"])] if left_is_upper
                            else [int(edge["node0"]), int(edge["node1"])]
                        ),
                        "upper_direction": hit["left_direction"] if left_is_upper else hit["right_direction"],
                        "lower_direction": hit["right_direction"] if left_is_upper else hit["left_direction"],
                        "source": "ENGINE_XYZ_TOPOLOGY_DERIVED",
                    }
            for cell in occupied_cells:
                buckets[cell].append(segment)
            previous = current

    return sorted(crossings.values(), key=lambda item: (item["position"]["x"], item["position"]["y"]))
