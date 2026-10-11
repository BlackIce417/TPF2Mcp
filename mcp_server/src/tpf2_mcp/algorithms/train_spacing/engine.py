"""Fail-closed, route-occurrence aware train spacing control."""
from __future__ import annotations

import math
from typing import Any

from ...dispatch_runtime.geometry import RailGraph


DEFAULT_POLICY = {
    "reaction_seconds": 3.0,
    "fixed_margin_m": 20.0,
    "position_uncertainty_m": 5.0,
    "projection_tolerance_m": 12.0,
    "conservative_deceleration_mps2": 0.35,
    "minimum_limit_kmh": 8.0,
    "hysteresis_kmh": 3.0,
    "max_lookahead_m": 3000.0,
    "maximum_footprint_age_seconds": 2.5,
    "maximum_frame_age_seconds": 2.0,
    "armed_execution": False,
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _route(vehicle: dict[str, Any]) -> dict[str, Any] | None:
    route = vehicle.get("route")
    if isinstance(route, dict):
        if route.get("status") not in (None, "ENGINE_PATH_CURRENT"):
            return None
        edges, directions = route.get("edge_ids"), route.get("directions")
        current = route.get("current_index")
        start_raw = route.get("start_index")
        start = start_raw if isinstance(start_raw, int) and not isinstance(start_raw, bool) else 0
    else:
        window = vehicle.get("route_window")
        if isinstance(window, dict) and window.get("edge_ids"):
            edges, directions = window.get("edge_ids"), window.get("directions")
            current, start_raw = vehicle.get("current_edge_index", window.get("current_index")), window.get("start_index")
            if not isinstance(start_raw, int) or isinstance(start_raw, bool):
                return None
            start = start_raw
            route = window
        else:
            edges, directions = vehicle.get("path_edge_ids"), vehicle.get("path_edge_directions")
            current, start = vehicle.get("current_edge_index"), 0
            route = vehicle
    if not isinstance(edges, list) or not edges or not isinstance(current, int):
        return None
    if not isinstance(directions, list) or len(directions) != len(edges):
        return None
    if not all(isinstance(x, bool) for x in directions):
        return None
    offset = current - start
    if offset < 0 or offset >= len(edges):
        return None
    transports = route.get("transport_indices") or vehicle.get("path_transport_indices") or []
    if not isinstance(transports, list):
        transports = []
    return {"edge_ids": edges, "directions": [bool(x) for x in directions],
            "transport_indices": transports, "start_index": start,
            "current_index": current, "offset": offset}


def _body_samples(vehicle: dict[str, Any]) -> list[dict[str, Any]]:
    samples = vehicle.get("body_samples")
    if isinstance(samples, list):
        if not all(isinstance(x, dict) and isinstance(x.get("position"), dict)
                   and all(_finite(x["position"].get(k)) for k in ("x", "y", "z"))
                   and _finite(x.get("radius_m")) and x["radius_m"] >= 0 for x in samples):
            return []
        return samples
    envelope = vehicle.get("train_envelope") or {}
    if envelope.get("complete") is not True or envelope.get("expected_parts") != len(envelope.get("parts") or []):
        return []
    result = []
    for part in envelope.get("parts") or []:
        position, bounds = part.get("position"), part.get("bounds") or {}
        if not isinstance(position, dict) or not all(_finite(position.get(k)) for k in ("x", "y", "z")):
            return []
        low, high = bounds.get("min") or {}, bounds.get("max") or {}
        if not all(_finite(low.get(k)) and _finite(high.get(k)) and high[k] >= low[k]
                   for k in ("x", "y", "z")):
            return []
        # Circumscribed AABB radius: an estimate, never an observed coupler.
        radius = math.sqrt(sum(max(abs(high[k]-position[k]), abs(low[k]-position[k]))**2
                               for k in ("x", "y", "z")))
        result.append({"position": position, "radius_m": max(0.0, radius)})
    return result


def _prefix(graph: RailGraph, route: dict[str, Any]) -> list[float]:
    values = [0.0]
    previous_end = None
    for edge_id, forward in zip(route["edge_ids"], route["directions"]):
        if edge_id not in graph.lengths:
            raise KeyError(edge_id)
        edge = graph.edges[edge_id]
        start, end = (edge['node0'], edge['node1']) if forward else (edge['node1'], edge['node0'])
        if previous_end is not None and start != previous_end:
            raise ValueError('discontinuous directed path')
        previous_end = end
        values.append(values[-1] + graph.lengths[edge_id])
    return values


def _coordinate(graph: RailGraph, route: dict[str, Any], prefix: list[float], offset: int, param: float) -> float:
    edge_id = route["edge_ids"][offset]
    along = graph.along(edge_id, param)
    if not route["directions"][offset]:
        along = graph.lengths[edge_id] - along
    return prefix[offset] + along


def _project_body(graph: RailGraph, route: dict[str, Any], prefix: list[float], samples: list[dict[str, Any]],
                  lo: int, hi: int, tolerance: float, anchor: float) -> tuple[float, float, float] | None:
    rear, front, worst = math.inf, -math.inf, 0.0
    for sample in samples:
        best = None
        nearby = set(graph.near(tuple(sample['position'][k] for k in ('x', 'y', 'z')), tolerance))
        for offset in range(max(0, lo), min(len(route["edge_ids"]), hi + 1)):
            edge_id = route["edge_ids"][offset]
            if edge_id not in nearby:
                continue
            param, _point, distance = graph.project(edge_id, sample["position"])
            coordinate = _coordinate(graph, route, prefix, offset, param)
            # One physical edge may occur more than once in a cyclic path.
            # Anchor equal-distance projections to the selected occurrence.
            candidate = (distance, abs(coordinate - anchor), coordinate)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[0] > tolerance:
            return None
        radius = float(sample.get("radius_m") or 0.0) if _finite(sample.get("radius_m") or 0.0) else 0.0
        rear, worst = min(rear, best[2] - max(0.0, radius)), max(worst, best[0])
        front = max(front, best[2] + radius)
    return (rear, front, worst) if math.isfinite(rear) else None


def compile_train_spacing(network: dict[str, Any], live: dict[str, Any], expires_at: float,
                          policy: dict[str, Any] | None = None, *, publishable: bool = False,
                          now: float | None = None, graph: RailGraph | None = None) -> list[dict[str, Any]]:
    """Return speed leases or explicit rejection diagnostics for each live train."""
    cfg = {**DEFAULT_POLICY, **(policy or {})}
    for key, default in DEFAULT_POLICY.items():
        if key != 'armed_execution' and (not _finite(cfg[key]) or cfg[key] < 0):
            raise ValueError(f'invalid spacing policy: {key}')
    if cfg['conservative_deceleration_mps2'] <= 0:
        raise ValueError('deceleration must be positive')
    graph = graph or RailGraph(network)
    now = float(live.get("sampled_at") or 0) if now is None else now
    sampled = live.get('sampled_at')
    if not _finite(sampled) or not 0 <= now-sampled <= cfg['maximum_frame_age_seconds']:
        return [{'kind': 'spacing_rejected', 'reason': 'FRAME_STALE'}]
    prepared, rejected = [], []
    for vehicle in live.get("vehicles") or []:
        vehicle_id = vehicle.get("entity_id")
        reason = None
        route = _route(vehicle)
        samples = _body_samples(vehicle)
        if not isinstance(vehicle_id, int) or route is None:
            reason = "ROUTE_OCCURRENCE_UNAVAILABLE"
        elif vehicle.get("position_stale") is True or not _finite(vehicle.get("edge_param")) or not 0 <= vehicle['edge_param'] <= 1:
            reason = "HEAD_POSITION_UNTRUSTED"
        elif route["edge_ids"][route["offset"]] != vehicle.get("edge_id"):
            reason = "ROUTE_HEAD_MISMATCH"
        elif not samples or vehicle.get("footprint_complete") is not True:
            reason = "COMPLETE_TRAIN_FOOTPRINT_UNAVAILABLE"
        elif not _finite(vehicle.get("speed_mps")) or float(vehicle["speed_mps"]) < 0:
            reason = "SPEED_UNAVAILABLE"
        footprint_at = vehicle.get("footprint_sampled_at")
        if reason is None and not _finite(footprint_at):
            reason = "TRAIN_FOOTPRINT_TIMESTAMP_UNAVAILABLE"
        elif reason is None and (now < float(footprint_at)
                                 or now - float(footprint_at) > float(cfg["maximum_footprint_age_seconds"])):
            reason = "TRAIN_FOOTPRINT_STALE"
        if reason:
            if isinstance(vehicle_id, int):
                rejected.append({"kind": "spacing_rejected", "vehicle_id": vehicle_id, "reason": reason})
            continue
        try:
            prefix = _prefix(graph, route)
            reference = _coordinate(graph, route, prefix, route["offset"], float(vehicle["edge_param"]))
            body = _project_body(graph, route, prefix, samples, 0, len(route['edge_ids'])-1,
                                 float(cfg['projection_tolerance_m']), reference)
            if body is None:
                raise ValueError('body off route')
            head = body[1]
        except (KeyError, TypeError, ValueError):
            rejected.append({"kind": "spacing_rejected", "vehicle_id": vehicle_id, "reason": "ROUTE_GEOMETRY_UNAVAILABLE"})
            continue
        prepared.append({"vehicle": vehicle, "route": route, "prefix": prefix, "head": head,
                         "reference": reference, "body": body, "samples": samples})

    results = list(rejected)
    tolerance = float(cfg["projection_tolerance_m"])
    for follower in prepared:
        fv, route, prefix, head = follower["vehicle"], follower["route"], follower["prefix"], follower["head"]
        # Missing observations cannot be interpreted as an empty track.
        if rejected:
            results.append({'kind': 'spacing_rejected', 'vehicle_id': fv['entity_id'],
                            'reason': 'TRAFFIC_OBSERVATION_INCOMPLETE'})
            continue
        best = None
        ambiguous = False
        projection_unresolved = False
        for leader in prepared:
            lv = leader["vehicle"]
            if lv["entity_id"] == fv["entity_id"]:
                continue
            matches = [i for i in range(route["offset"], len(route["edge_ids"]))
                       if route["edge_ids"][i] == lv.get("edge_id")
                       and route["directions"][i] == bool((leader["route"])["directions"][(leader["route"])["offset"]])]
            for match in matches:
                try:
                    leader_head = _coordinate(graph, route, prefix, match, float(lv["edge_param"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if leader_head <= follower['reference'] or leader_head - head > float(cfg["max_lookahead_m"]):
                    continue
                projected = _project_body(graph, route, prefix, leader["samples"], match - 32, match + 4,
                                          tolerance, leader_head)
                if not projected:
                    projection_unresolved = True
                    continue
                leader_rear, _, projection_error = projected
                gap = leader_rear - head
                if len(matches) > 1:
                    ambiguous = True
                    continue
                if best is None or gap < best[0]:
                    best = (gap, leader, match, projection_error)
        if ambiguous or projection_unresolved:
            results.append({'kind': 'spacing_rejected', 'vehicle_id': fv['entity_id'],
                            'reason': 'AMBIGUOUS_PATH_OCCURRENCE' if ambiguous else 'LEADER_BODY_ROUTE_UNRESOLVED'})
            continue
        if best is None:
            results.append({"kind": "spacing_clear", "vehicle_id": fv["entity_id"], "reason": "NO_LEADER_ON_ROUTE"})
            continue
        gap, leader, match, projection_error = best
        if not _finite(fv.get('brake_decel_mps2')) or fv['brake_decel_mps2'] <= 0:
            results.append({'kind': 'spacing_rejected', 'vehicle_id': fv['entity_id'],
                            'reason': 'BRAKING_CAPABILITY_UNAVAILABLE'})
            continue
        observed_brake = float(fv["brake_decel_mps2"])
        braking = min(observed_brake, float(cfg["conservative_deceleration_mps2"]))
        available = gap - float(cfg["fixed_margin_m"]) - float(cfg["position_uncertainty_m"]) - projection_error - follower['body'][2]
        multiplier = (live.get('simulation') or {}).get('speed_multiplier', 1.0)
        if not _finite(multiplier) or multiplier <= 0:
            results.append({'kind': 'spacing_rejected', 'vehicle_id': fv['entity_id'],
                            'reason': 'SIMULATION_SPEED_UNKNOWN'})
            continue
        reaction = (float(cfg["reaction_seconds"]) + now-fv['footprint_sampled_at']) * multiplier
        safe_speed = 0.0 if available <= 0 else -braking * reaction + math.sqrt((braking * reaction) ** 2 + 2 * braking * available)
        speed_kmh = safe_speed * 3.6
        detail = {"vehicle_id": fv["entity_id"], "leader_vehicle_id": leader["vehicle"]["entity_id"],
                  "gap_m": round(gap, 2), "available_braking_distance_m": round(max(0.0, available), 2),
                  "reaction_seconds": reaction, "brake_decel_mps2": braking,
                  "head_chainage_m": head, "leader_tail_chainage_m": head + gap,
                  "endpoint_source": "BODY_BOUNDING_RADIUS_ESTIMATE",
                  "safe_speed_kmh": round(speed_kmh, 1), "path_index_start": route["current_index"],
                  "path_index_end": route["start_index"] + match}
        if speed_kmh < float(cfg["minimum_limit_kmh"]):
            results.append({"kind": "spacing_rejected", **detail, "reason": "NATIVE_STOP_REQUIRED"})
            continue
        # Retain the envelope below the limit too: otherwise reaching the limit
        # would cancel it and cause an accelerate/brake oscillation.
        edge_ids = list(dict.fromkeys(route["edge_ids"][route["offset"]:match + 1]))
        if not publishable or (cfg.get("armed_execution") is True and fv.get("braking_verified") is not True):
            results.append({"kind": "spacing_advisory", **detail, "edge_ids": edge_ids,
                            "reason": "TRAIN_SPACING_ENVELOPE"})
            continue
        results.append({"kind": "speed", "lease_id": f"spacing:{fv['entity_id']}", **detail,
                        "speed_mps": math.floor(safe_speed * 1000) / 1000, "speed_kmh": round(speed_kmh, 1),
                        "edge_ids": edge_ids, "priority": 100, "expires_at": expires_at,
                        "reason": "TRAIN_SPACING_ENVELOPE"})
    return results
