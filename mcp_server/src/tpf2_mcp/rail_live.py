from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _field(fields: dict[str, Any] | None, name: str) -> Any:
    detail = (fields or {}).get(name) or {}
    return detail.get("value")


def _project(point: dict[str, float], a: dict[str, float], b: dict[str, float]) -> tuple[float, float, dict[str, float]]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point["x"] - a["x"]) * dx + (point["y"] - a["y"]) * dy) / length2))
    q = {"x": a["x"] + dx * t, "y": a["y"] + dy * t, "z": a.get("z", 0.0) + (b.get("z", 0.0) - a.get("z", 0.0)) * t}
    return math.hypot(point["x"] - q["x"], point["y"] - q["y"]), t, q


def _edge_position(edge: dict[str, Any], nodes: dict[int, dict[str, float]], param: float) -> dict[str, float] | None:
    """Evaluate the same cubic Hermite curve used by the static rail renderer."""
    a, b = nodes.get(int(edge["node0"])), nodes.get(int(edge["node1"]))
    if not a or not b:
        return None
    u = max(0.0, min(1.0, float(param)))
    fallback = {axis: b.get(axis, 0.0) - a.get(axis, 0.0) for axis in ("x", "y", "z")}
    t0, t1 = edge.get("tangent0") or fallback, edge.get("tangent1") or fallback
    h00, h10 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u
    h01, h11 = -2*u**3 + 3*u**2, u**3 - u**2
    return {axis: h00*a.get(axis, 0.0) + h10*t0.get(axis, 0.0) + h01*b.get(axis, 0.0) + h11*t1.get(axis, 0.0) for axis in ("x", "y", "z")}


def _edge_param_from_position(edge: dict[str, Any], nodes: dict[int, dict[str, float]], point: dict[str, float]) -> float | None:
    """Find the nearest parameter on one known rail edge's Hermite curve."""
    def distance2(param: float) -> float:
        candidate = _edge_position(edge, nodes, param)
        if not candidate:
            return math.inf
        return sum((candidate.get(axis, 0.0) - point.get(axis, 0.0)) ** 2 for axis in ("x", "y", "z"))

    steps = 24
    samples = [(distance2(index / steps), index / steps) for index in range(steps + 1)]
    _, best = min(samples)
    low, high = max(0.0, best - 1 / steps), min(1.0, best + 1 / steps)
    for _ in range(16):
        left, right = (2 * low + high) / 3, (low + 2 * high) / 3
        if distance2(left) <= distance2(right):
            high = right
        else:
            low = left
    return (low + high) / 2


class RailSpatialIndex:
    def __init__(self, network: dict[str, Any], cell_size: float = 400.0):
        self.cell_size = cell_size
        self.nodes = {int(node["entity_id"]): node["position"] for node in network.get("nodes", [])}
        self.edges = {int(edge["entity_id"]): edge for edge in network.get("edges", [])}
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for edge_id, edge in self.edges.items():
            a, b = self.nodes.get(int(edge["node0"])), self.nodes.get(int(edge["node1"]))
            if not a or not b:
                continue
            min_x, max_x = sorted((a["x"], b["x"]))
            min_y, max_y = sorted((a["y"], b["y"]))
            for x in range(math.floor(min_x / cell_size), math.floor(max_x / cell_size) + 1):
                for y in range(math.floor(min_y / cell_size), math.floor(max_y / cell_size) + 1):
                    self.grid[(x, y)].append(edge_id)

    def snap(self, point: dict[str, float], search_cells: int = 1) -> dict[str, Any] | None:
        cx, cy = math.floor(point["x"] / self.cell_size), math.floor(point["y"] / self.cell_size)
        candidates: set[int] = set()
        for x in range(cx - search_cells, cx + search_cells + 1):
            for y in range(cy - search_cells, cy + search_cells + 1):
                candidates.update(self.grid.get((x, y), ()))
        best = None
        for edge_id in candidates:
            edge = self.edges[edge_id]
            a, b = self.nodes[int(edge["node0"])], self.nodes[int(edge["node1"])]
            distance, param, snapped = _project(point, a, b)
            if best is None or distance < best["distance_m"]:
                best = {"edge_id": edge_id, "edge_param": param, "distance_m": distance, "position": snapped}
        return best


def _object_position(item: dict[str, Any], index: RailSpatialIndex) -> dict[str, float] | None:
    if item.get("position"):
        return item["position"]
    edge = index.edges.get(int(item.get("edge_entity_id", -1)))
    param = item.get("edge_param")
    if not edge or not isinstance(param, (int, float)):
        return None
    if param > 1.0:
        param = param / 65535.0 if param <= 65535 else 0.5
    a, b = index.nodes[int(edge["node0"])], index.nodes[int(edge["node1"])]
    return {axis: a.get(axis, 0.0) + (b.get(axis, 0.0) - a.get(axis, 0.0)) * param for axis in ("x", "y", "z")}


def normalize_signals(telemetry: dict[str, Any], index: RailSpatialIndex) -> list[dict[str, Any]]:
    result = []
    confirmed = telemetry.get("signal_edge_objects") or []
    candidates = confirmed or telemetry.get("track_edge_objects") or []
    for item in candidates:
        position = _object_position(item, index)
        if not position:
            continue
        edge_id = item.get("edge_entity_id")
        edge_param = item.get("edge_param")
        if not isinstance(edge_param, (int, float)) and edge_id in index.edges:
            edge_param = _edge_param_from_position(index.edges[int(edge_id)], index.nodes, position)
        names = [model.get("model_name") for model in item.get("models", []) if model.get("model_name")]
        result.append({
            "entity_id": item.get("object_entity_id"),
            "edge_id": edge_id,
            "edge_param": round(edge_param, 6) if isinstance(edge_param, (int, float)) else None,
            "position": position,
            "left": item.get("left"),
            "signal_types": item.get("signal_types") or [],
            "model_names": names,
            "source_status": "SIGNAL_LIST_CLASSIFIED" if item.get("operational_signal_observed") else "MODEL_CLASSIFIED" if item.get("signal_model_observed") else "COMPONENT_CLASSIFIED" if item.get("signal_component_observed") else "TRACK_OBJECT_CANDIDATE",
        })
    return result


def derive_blocks(network: dict[str, Any], signals: list[dict[str, Any]], index: RailSpatialIndex) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signals_by_edge: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        if signal.get("edge_id") in index.edges:
            signals_by_edge[int(signal["edge_id"])].append(signal)
    atoms: list[dict[str, Any]] = []
    adjacency: dict[str, list[int]] = defaultdict(list)
    signal_nodes: set[str] = set()
    for edge_id, edge in index.edges.items():
        points: list[tuple[float, str]] = [(0.0, f"n:{edge['node0']}"), (1.0, f"n:{edge['node1']}")]
        for ordinal, signal in enumerate(sorted(signals_by_edge.get(edge_id, []), key=lambda value: value.get("edge_param") or 0.5)):
            raw = signal.get("edge_param")
            param = float(raw) if isinstance(raw, (int, float)) else 0.5
            if param > 1.0:
                param = param / 65535.0 if param <= 65535 else 0.5
            node = f"s:{signal.get('entity_id')}:{edge_id}:{ordinal}"
            points.append((max(0.0, min(1.0, param)), node))
            signal_nodes.add(node)
        points.sort()
        a, b = index.nodes.get(int(edge["node0"])), index.nodes.get(int(edge["node1"]))
        edge_length = math.dist((a["x"], a["y"], a.get("z", 0)), (b["x"], b["y"], b.get("z", 0))) if a and b else 0.0
        for (p0, n0), (p1, n1) in zip(points, points[1:]):
            atom = {"edge_id": edge_id, "from_param": p0, "to_param": p1, "from": n0, "to": n1, "length_m": edge_length * (p1 - p0)}
            atom_id = len(atoms); atoms.append(atom); adjacency[n0].append(atom_id); adjacency[n1].append(atom_id)
    boundaries = signal_nodes | {node for node, links in adjacency.items() if len(links) != 2}
    visited: set[int] = set()
    blocks: list[dict[str, Any]] = []

    def walk(start_node: str, first_atom: int) -> tuple[list[int], str]:
        chain, node, atom_id = [], start_node, first_atom
        while atom_id not in visited:
            visited.add(atom_id); chain.append(atom_id)
            atom = atoms[atom_id]
            node = atom["to"] if atom["from"] == node else atom["from"]
            if node in boundaries:
                break
            remaining = [candidate for candidate in adjacency[node] if candidate not in visited]
            if not remaining:
                break
            atom_id = remaining[0]
        return chain, node

    for start in sorted(boundaries):
        for atom_id in adjacency[start]:
            if atom_id in visited:
                continue
            chain, end = walk(start, atom_id)
            block_id = f"B{len(blocks) + 1:05d}"
            for member in chain:
                atoms[member]["block_id"] = block_id
            blocks.append({"block_id": block_id, "from": start, "to": end, "length_m": sum(atoms[i]["length_m"] for i in chain), "edge_ids": list(dict.fromkeys(atoms[i]["edge_id"] for i in chain)), "occupied_vehicle_ids": []})
    for atom_id in range(len(atoms)):
        if atom_id in visited:
            continue
        chain, end = walk(atoms[atom_id]["from"], atom_id)
        block_id = f"B{len(blocks) + 1:05d}"
        for member in chain:
            atoms[member]["block_id"] = block_id
        blocks.append({"block_id": block_id, "from": atoms[chain[0]]["from"], "to": end, "length_m": sum(atoms[i]["length_m"] for i in chain), "edge_ids": list(dict.fromkeys(atoms[i]["edge_id"] for i in chain)), "occupied_vehicle_ids": []})
    return blocks, atoms


def _line_progress(position: dict[str, float], line: dict[str, Any]) -> tuple[float | None, float, float]:
    best_distance, best_progress, total, offset = math.inf, None, 0.0, 0.0
    for polyline in line.get("overview_segments", []):
        for raw_a, raw_b in zip(polyline, polyline[1:]):
            a, b = {"x": raw_a[0], "y": raw_a[1]}, {"x": raw_b[0], "y": raw_b[1]}
            length = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            distance, param, _ = _project(position, a, b)
            if distance < best_distance:
                best_distance, best_progress = distance, offset + length * param
            offset += length
        total = offset
    return best_progress, total, best_distance


def line_diagnostics(lines: list[dict[str, Any]], vehicles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for vehicle in vehicles:
        if isinstance(vehicle.get("line_id"), int):
            by_line[vehicle["line_id"]].append(vehicle)
    result = []
    for line in lines:
        line_id = int(line["entity_id"]); members = by_line.get(line_id, [])
        progress, route_length = [], 0.0
        for vehicle in members:
            value, length, distance = _line_progress(vehicle["position"], line)
            route_length = max(route_length, length)
            if value is not None and distance < 250:
                progress.append(value)
        progress.sort(); gaps: list[float] = []
        if len(progress) >= 2 and route_length > 0:
            gaps = [b - a for a, b in zip(progress, progress[1:])] + [route_length - progress[-1] + progress[0]]
        target = route_length / len(progress) if progress else None
        cv = (math.sqrt(sum((gap - target) ** 2 for gap in gaps) / len(gaps)) / target) if gaps and target else None
        if len(progress) < 2:
            diagnosis = "INSUFFICIENT_TRAINS"
        elif min(gaps) < max(250.0, target * 0.25):
            diagnosis = "POSSIBLE_BUNCHING"
        elif cv is not None and cv > 0.5:
            diagnosis = "UNEVEN_SPACING"
        else:
            diagnosis = "BALANCED"
        result.append({"line_id": line_id, "name": line.get("name"), "vehicle_count": len(members), "located_vehicle_count": len(progress), "route_length_m": round(route_length, 1), "target_spacing_m": round(target, 1) if target else None, "minimum_spacing_m": round(min(gaps), 1) if gaps else None, "spacing_cv": round(cv, 3) if cv is not None else None, "diagnosis": diagnosis, "demand_status": "UNKNOWN"})
    return result


def _simulation_state(telemetry: dict[str, Any], previous: dict[str, Any] | None, sampled_at: float, vehicles: list[dict[str, Any]]) -> dict[str, Any]:
    clock = telemetry.get("simulation_clock") or {}
    prior_clock = ((previous or {}).get("simulation") or {}).get("clock") or {}
    speedup = clock.get("speedup")
    update_count, prior_update_count = clock.get("update_count"), prior_clock.get("update_count")
    game_time, prior_game_time = clock.get("game_time"), prior_clock.get("game_time")
    update_delta = update_count - prior_update_count if isinstance(update_count, (int, float)) and isinstance(prior_update_count, (int, float)) else None
    game_time_delta = game_time - prior_game_time if isinstance(game_time, (int, float)) and isinstance(prior_game_time, (int, float)) else None
    prior_by_id = {item["entity_id"]: item for item in (previous or {}).get("vehicles", [])}
    compared, moved = 0, 0
    for vehicle in vehicles:
        prior = prior_by_id.get(vehicle["entity_id"])
        if not prior or not vehicle.get("position") or not prior.get("position"):
            continue
        compared += 1
        if math.dist(tuple(vehicle["position"].get(axis, 0.0) for axis in ("x", "y", "z")), tuple(prior["position"].get(axis, 0.0) for axis in ("x", "y", "z"))) > .5:
            moved += 1
    wall_delta = sampled_at - float((previous or {}).get("sampled_at") or sampled_at)
    if isinstance(speedup, (int, float)) and speedup == 0:
        status, allowed, reason = "PAUSED", False, "GAME_SPEED.speedup is 0"
    elif isinstance(update_delta, (int, float)) and wall_delta >= .5 and update_delta <= 0:
        status, allowed, reason = "PAUSED_OR_STALLED", False, "GAME_TIME.updateCount did not advance"
    elif isinstance(speedup, (int, float)) and speedup > 0 and isinstance(update_delta, (int, float)) and update_delta > 0:
        status, allowed, reason = "RUNNING", True, "positive speedup and advancing updateCount"
    elif moved > 0:
        status, allowed, reason = "RUNNING_INFERRED", True, "multiple-frame coordinate displacement observed"
    else:
        status, allowed, reason = "UNKNOWN", False, "awaiting a second clock/position sample"
    return {"status": status, "analysis_allowed": allowed, "speed_multiplier": float(speedup) if isinstance(speedup, (int, float)) else None, "reason": reason, "clock": clock, "deltas": {"update_count": update_delta, "game_time": game_time_delta, "wall_seconds": round(wall_delta, 3)}, "movement_cross_check": {"vehicles_compared": compared, "vehicles_moved_over_0_5m": moved}}


def normalize_live_state(telemetry: dict[str, Any], network: dict[str, Any], manifest: dict[str, Any], previous: dict[str, Any] | None = None, sampled_at: float = 0.0, *, spatial_index: RailSpatialIndex | None = None, control: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    index = spatial_index or RailSpatialIndex(network)
    previous_by_id = {item["entity_id"]: item for item in (previous or {}).get("vehicles", [])}
    previous_time = float((previous or {}).get("sampled_at") or 0.0)
    dt = sampled_at - previous_time
    vehicles = []
    position_fallback_vehicles = 0
    position_fallback_max_seconds = 30.0
    rail_line_ids = {int(line["entity_id"]) for line in manifest.get("lines", [])}
    for raw in telemetry.get("vehicles") or []:
        line_id = raw.get("line_id") if isinstance(raw.get("line_id"), int) else _field(raw.get("component"), "line")
        if line_id not in rail_line_ids:
            continue
        position = raw.get("position")
        snap = index.snap(position) if position else None
        position_source = "BOUNDING_VOLUME" if position else None
        live_edge_id, live_param = raw.get("current_edge_id"), raw.get("current_edge_param")
        if isinstance(live_edge_id, int) and isinstance(live_param, (int, float)) and live_edge_id in index.edges:
            position = _edge_position(index.edges[live_edge_id], index.nodes, float(live_param))
            if position:
                snap = {"edge_id": live_edge_id, "edge_param": float(live_param), "distance_m": 0.0, "position": position}
                position_source = "MOVE_PATH_DYN"
        if snap is None:
            path_items = (raw.get("path_edges") or {}).get("items") or []
            current_edge = next((index.edges.get(int(item["edge_id"])) for item in path_items if isinstance(item.get("edge_id"), int) and int(item["edge_id"]) in index.edges), None)
            if current_edge:
                a, b = index.nodes[int(current_edge["node0"])], index.nodes[int(current_edge["node1"])]
                position = {axis: (a.get(axis, 0.0) + b.get(axis, 0.0)) / 2 for axis in ("x", "y", "z")}
                snap = {"edge_id": int(current_edge["entity_id"]), "edge_param": .5, "distance_m": 0.0, "position": position}
                position_source = "MOVE_PATH_EDGE_APPROXIMATION"
        entity_id = int(raw["entity_id"])
        prior = previous_by_id.get(entity_id)
        position_stale = False
        position_age_seconds = 0.0
        position_observed_at = sampled_at
        if not snap or snap["distance_m"] > 35.0:
            # MOVE_PATH can briefly expose an internal/non-BASE_EDGE_TRACK edge
            # while a train traverses a tunnel, station throat or path boundary.
            # The compact engine frame has no BOUNDING_VOLUME fallback, so retain
            # the last graph-valid position while this *same raw vehicle* is still
            # observed.  Never extrapolate it and expire the hold after 30 s.
            prior_observed_at = (prior or {}).get("position_observed_at")
            if not isinstance(prior_observed_at, (int, float)):
                prior_age = (prior or {}).get("position_age_seconds")
                prior_observed_at = previous_time - float(prior_age or 0.0)
            age = sampled_at - float(prior_observed_at) if prior else math.inf
            if prior and prior.get("position") and prior.get("snapped_position") and age <= position_fallback_max_seconds:
                position = prior["position"]
                snap = {
                    "edge_id": prior["edge_id"],
                    "edge_param": prior["edge_param"],
                    "distance_m": prior.get("rail_distance_m", 0.0),
                    "position": prior["snapped_position"],
                }
                position_source = "LAST_VALID_TRACK_POSITION"
                position_stale = True
                position_age_seconds = max(0.0, age)
                position_observed_at = float(prior_observed_at)
                position_fallback_vehicles += 1
            else:
                continue
        speed = None
        if prior and dt > 0 and not position_stale:
            speed = math.dist((position["x"], position["y"], position.get("z", 0)), (prior["position"]["x"], prior["position"]["y"], prior["position"].get("z", 0))) / dt
            if speed > 150:
                speed = None
        observed_speed = raw.get("speed_mps") if isinstance(raw.get("speed_mps"), (int, float)) else next((_field(raw.get(source), "speed") for source in ("move_info", "info", "move_path_detail") if isinstance(_field(raw.get(source), "speed"), (int, float))), None)
        if observed_speed is not None:
            speed = float(observed_speed)
        vehicles.append({"entity_id": entity_id, "name": raw.get("name"), "line_id": line_id, "stop_index": raw.get("stop_index") if isinstance(raw.get("stop_index"), int) else _field(raw.get("component"), "stopIndex"), "raw_state": raw.get("raw_state") if isinstance(raw.get("raw_state"), int) else _field(raw.get("component"), "state"), "position": position, "snapped_position": snap["position"], "edge_id": snap["edge_id"], "edge_param": round(snap["edge_param"], 5), "rail_distance_m": round(snap["distance_m"], 2), "position_source": position_source or "UNKNOWN", "position_stale": position_stale, "position_age_seconds": round(position_age_seconds, 2), "position_observed_at": position_observed_at, "speed_mps": round(speed, 2) if speed is not None else None, "speed_kmh": round(speed * 3.6, 1) if speed is not None else None, "acceleration_mps2": raw.get("acceleration_mps2"), "approaching_station": raw.get("approaching_station"), "auto_departure": raw.get("auto_departure"), "doors_open": raw.get("doors_open"), "time_until_load": raw.get("time_until_load"), "time_until_close_doors": raw.get("time_until_close_doors"), "time_until_departure": raw.get("time_until_departure")})
    if control is None:
        signals = normalize_signals(telemetry, index)
        blocks, atoms = derive_blocks(network, signals, index)
    else:
        signals, block_templates, atoms = control
        blocks = [{**block, "occupied_vehicle_ids": []} for block in block_templates]
    block_by_id = {block["block_id"]: block for block in blocks}
    atoms_by_edge: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for atom in atoms:
        atoms_by_edge[atom["edge_id"]].append(atom)
    for vehicle in vehicles:
        if vehicle.get("position_stale"):
            continue
        for atom in atoms_by_edge.get(vehicle["edge_id"], []):
            if atom["from_param"] - 1e-6 <= vehicle["edge_param"] <= atom["to_param"] + 1e-6:
                vehicle["block_id"] = atom["block_id"]
                block_by_id[atom["block_id"]]["occupied_vehicle_ids"].append(vehicle["entity_id"])
                break
    diagnostics = line_diagnostics(manifest.get("lines", []), [vehicle for vehicle in vehicles if not vehicle.get("position_stale")])
    confirmed_signals = sum(signal["source_status"] != "TRACK_OBJECT_CANDIDATE" for signal in signals)
    simulation = _simulation_state(telemetry, previous, sampled_at, vehicles)
    return {"schema_version": 1, "source_status": "ENGINE_OBSERVED_DYNAMIC" if simulation["analysis_allowed"] else "ENGINE_OBSERVED_SIMULATION_INACTIVE", "sampled_at": sampled_at, "simulation": simulation, "vehicles": vehicles, "signals": signals, "blocks": blocks, "line_diagnostics": diagnostics, "counts": {"rail_vehicles": len(vehicles), "position_fallback_vehicles": position_fallback_vehicles, "signal_candidates": len(signals), "confirmed_signals": confirmed_signals, "blocks": len(blocks), "occupied_blocks": sum(bool(block["occupied_vehicle_ids"]) for block in blocks)}, "limitations": {"speed": "MOVE_PATH.dyn.speed is never treated as motion while simulation is paused", "position_fallback": "A raw rail vehicle with a transiently unresolved edge retains its last graph-valid position for at most 30 seconds; it is excluded from occupancy and spacing analysis while stale", "block_model": "track objects conservatively delimit sections; SIGNAL_LIST confirmation remains UNKNOWN", "signal_aspect": "UNKNOWN", "demand": "UNKNOWN: unsafe station UI sampling disabled"}}
