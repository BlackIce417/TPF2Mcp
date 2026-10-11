"""Line-template cyclic timetable planning over verified snapshot/live fields."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

from .capacity_allocator import allocate_to_available_capacity
from .fleet_policy import evaluate_fleet_adjustment
from .save_scope import snapshot_save_id


def _length(points: list[list[float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _terminal_kind(station: dict[str, Any], stop: dict[str, Any]) -> str:
    terminal = next((item for item in station.get("terminals", [])
                     if item.get("station_index") == stop.get("station_index")
                     and item.get("terminal_index") == stop.get("terminal_index")), None)
    if terminal is None:
        return "UNKNOWN"
    return "FREIGHT" if terminal.get("cargo") else "PASSENGER"


def _platform_fit(station: dict[str, Any], stop: dict[str, Any], train_length_m: float | None) -> dict[str, Any]:
    selectors = [{"station_index": stop.get("station_index"), "terminal_index": stop.get("terminal_index"), "primary": True}]
    selectors.extend({**item, "primary": False} for item in stop.get("alternative_terminals", []) if isinstance(item, dict))
    unique, options = set(), []
    for selector in selectors:
        key = (selector.get("station_index"), selector.get("terminal_index"))
        if key in unique:
            continue
        unique.add(key)
        terminal = next((item for item in station.get("terminals", [])
                         if item.get("station_index") == key[0] and item.get("terminal_index") == key[1]), None)
        length = terminal.get("platform_length_m") if terminal else None
        fits = length >= train_length_m if isinstance(length, (int, float)) and isinstance(train_length_m, (int, float)) else None
        options.append({"station_index": key[0], "terminal_index": key[1], "primary": selector["primary"],
                        "platform_length_m": length, "platform_length_source": terminal.get("platform_length_source") if terminal else "UNKNOWN",
                        "fits_longest_assigned_train": fits})
    known = [item["fits_longest_assigned_train"] for item in options if item["fits_longest_assigned_train"] is not None]
    status = "TOO_SHORT" if False in known else "VERIFIED_FIT" if options and len(known) == len(options) else "UNKNOWN"
    return {"status": status, "train_length_m": round(train_length_m, 1) if train_length_m is not None else None,
            "all_selectable_platforms_fit": status == "VERIFIED_FIT", "options": options}


def _line_kind(line: dict[str, Any], stations: dict[int, dict[str, Any]]) -> str:
    kinds = {_terminal_kind(stations.get(int(stop.get("station_group_id", -1)), {}), stop)
             for stop in line.get("stops", [])}
    kinds.discard("UNKNOWN")
    if len(kinds) == 1:
        return next(iter(kinds))
    return "MIXED" if kinds else "UNKNOWN"


def _leg_weights(line: dict[str, Any]) -> list[float]:
    stop_count = len(line.get("stops", []))
    if stop_count == 0:
        return []
    measured = [_length(segment) for segment in line.get("overview_segments", []) if len(segment) >= 2]
    if len(measured) == stop_count - 1:
        measured.append(measured[-1] if stop_count == 2 else statistics.median(measured))
    if len(measured) != stop_count or not any(value > 0 for value in measured):
        return [1.0] * stop_count
    return [max(1.0, value) for value in measured]


def _round_seconds(value: float) -> int:
    return max(1, int(round(value)))


def _capacity_map(vehicle: dict[str, Any]) -> dict[int, float]:
    return {int(item["cargo_id"]): float(item["capacity"]) for item in vehicle.get("capacity_by_cargo", [])
            if isinstance(item, dict) and isinstance(item.get("cargo_id"), int)
            and isinstance(item.get("capacity"), (int, float))}


def _fleet_demand_profile(line_plan: dict[str, Any], vehicles: list[dict[str, Any]],
                          samples: list[dict[str, Any]], fleet_change_cooldown: bool = False,
                          vehicle_catalog: list[dict[str, Any]] | None = None,
                          reachable_depot: dict[str, Any] | None = None,
                          ) -> tuple[dict[str, Any], dict[str, Any]]:
    service = line_plan["service_class"]
    latest = samples[-1] if samples else {}
    demand_key = "passengers" if service == "PASSENGER" else "cargo" if service == "FREIGHT" else None
    demand = latest.get(demand_key, {}) if demand_key else {}
    demanded_cargo_ids = sorted({int(item["cargo_id"]) for item in demand.get("by_cargo", [])
                                 if isinstance(item, dict) and isinstance(item.get("cargo_id"), int)
                                 and (item.get("total") or 0) > 0})
    effective_capacities, service_compatible = [], []
    for vehicle in vehicles:
        capacities = _capacity_map(vehicle)
        if service == "PASSENGER" and 0 in capacities:
            effective_capacities.append(capacities[0])
            service_compatible.append(True)
        elif service == "FREIGHT" and demanded_cargo_ids:
            effective_capacities.append(sum(capacities.get(cargo_id, 0) for cargo_id in demanded_cargo_ids))
            service_compatible.append(all(capacities.get(cargo_id, 0) > 0 for cargo_id in demanded_cargo_ids))
        elif isinstance(vehicle.get("capacity_total"), (int, float)):
            effective_capacities.append(float(vehicle["capacity_total"]))
            service_compatible.append(service != "FREIGHT")
    capacity_complete = len(effective_capacities) == len(vehicles)
    total_capacity = int(round(sum(effective_capacities))) if capacity_complete else 0
    signatures = sorted({str(vehicle["consist_signature"]) for vehicle in vehicles if vehicle.get("consist_signature")})
    speed_classes = sorted({round(float(vehicle["consist_top_speed_kmh"])) for vehicle in vehicles
                            if isinstance(vehicle.get("consist_top_speed_kmh"), (int, float))})
    compatibility_sets = sorted({tuple(sorted(_capacity_map(vehicle))) for vehicle in vehicles})
    compatible_templates = [(vehicle, capacity) for vehicle, capacity, compatible in zip(vehicles, effective_capacities, service_compatible) if compatible]
    template = max(compatible_templates, key=lambda item: item[1])[0] if capacity_complete and compatible_templates else None
    homogeneous_speed = len(speed_classes) <= 1
    homogeneous_cargo = bool(service_compatible) and all(service_compatible)
    platform_safe = (line_plan.get("platform_feasibility") or {}).get("all_stops_fit") is True
    depot_id = reachable_depot.get("entity_id") if reachable_depot else (template or {}).get("raw_depot")
    template_safe = (template is not None and homogeneous_speed and homogeneous_cargo
                     and bool(template.get("consist_signature")) and platform_safe and isinstance(depot_id, int))
    fleet = evaluate_fleet_adjustment(line_plan, samples, total_capacity)
    latest_metrics = {
        "sample_count": len(samples), "onboard": demand.get("onboard"), "waiting": demand.get("waiting"),
        "average_waiting_seconds": demand.get("average_waiting_seconds"),
        "load_factor": round(demand.get("onboard", 0) / total_capacity, 3) if total_capacity > 0 else None,
        "demanded_cargo_ids": demanded_cargo_ids,
        "truncated": demand.get("truncated"),
        "journey_granularity": demand.get("journey_granularity"),
        "journey_unknown": demand.get("journey_unknown"),
        "by_journey": demand.get("by_journey", []),
    }
    constraint = {
        "policy": "CLONE_EXISTING_LINE_CONSIST_ONLY",
        "allowed_existing_consist_signatures": signatures,
        "speed_classes_kmh": speed_classes,
        "cargo_compatibility_sets": [list(value) for value in compatibility_sets],
        "identical_cargo_capability_sets": len(compatibility_sets) <= 1,
        "required_cargo_ids": [0] if service == "PASSENGER" else demanded_cargo_ids,
        "all_vehicles_support_required_cargo": homogeneous_cargo,
        "homogeneous_speed_class": homogeneous_speed,
        "homogeneous_cargo_compatibility": homogeneous_cargo,
        "all_scheduled_platforms_fit": platform_safe,
        "expansion_template_vehicle_id": template.get("entity_id") if template_safe else None,
        "expansion_depot": reachable_depot if template_safe else None,
        "recovery_depot": reachable_depot,
        "expansion_allowed": template_safe,
        "blocked_reason": None if template_safe else "line must have one verified speed class; every vehicle and the clone template must support the required cargo; an exact consist signature and verified train-length/platform-length fit are required",
        "guarantee": "A purchase copies an existing consist from this line; it cannot introduce another train family or cargo capability.",
    }
    underlying_decision = fleet["decision"]
    execution_eligibility = (
        "COOLDOWN_AFTER_VERIFIED_CHANGE"
        if underlying_decision in {"ADD_ONE_PROPOSAL", "REMOVE_ONE_PROPOSAL"} and fleet_change_cooldown
        else "PROPOSAL_READY" if fleet["decision"] == "ADD_ONE_PROPOSAL" and template_safe
        else "PROPOSAL_READY" if fleet["decision"] == "REMOVE_ONE_PROPOSAL" and len(vehicles) > 1
        else "BLOCKED_BY_CONSIST_CONSTRAINT" if fleet["decision"] == "ADD_ONE_PROPOSAL" and not template_safe
        else "NO_FLEET_CHANGE"
    )
    if execution_eligibility == "COOLDOWN_AFTER_VERIFIED_CHANGE":
        fleet["decision"] = "HOLD_FLEET"
        fleet["underlying_decision"] = underlying_decision
        fleet["hold_reason"] = "RECENT_FLEET_CHANGE_OR_ROLLED_BACK_ATTEMPT"
    fleet.update({"demand": latest_metrics, "effective_capacity_total": total_capacity or None,
                  "consist_constraint": constraint, "automatic_add": False, "automatic_remove": False,
                  "fleet_change_cooldown": fleet_change_cooldown,
                  "execution_eligibility": execution_eligibility})
    action_plan = None
    if execution_eligibility == "PROPOSAL_READY" and underlying_decision == "ADD_ONE_PROPOSAL" and template is not None:
        action_plan = {
            "kind": "ADD_TRAIN",
            "operations": [
                {"operation_type": "BUY_VEHICLE", "target": {"depot_id": template.get("raw_depot")},
                 "parameters": {"source_vehicle_id": template.get("entity_id")}},
                {"operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"line_id": line_plan["line_id"]},
                 "parameters": {"stop_index": 0, "vehicle_id_source": "PREVIOUS_NEW_ENTITY"}},
            ],
            "reason": "sustained overload; clone a compatible verified consist and assign it to the line",
        }
        action_plan["operations"][0]["target"]["depot_id"] = depot_id
        current_smallest = min(vehicles, key=lambda item: item.get("capacity_total") or 0)
        candidates = []
        required = set(constraint["required_cargo_ids"])
        speed = current_smallest.get("consist_top_speed_kmh")
        platform_lengths = [option.get("platform_length_m") for stop in line_plan.get("stops", [])
                            for option in (stop.get("platform_fit") or {}).get("options", [])]
        known_lengths = [float(value) for value in platform_lengths if isinstance(value, (int, float))]
        max_length = min(known_lengths) if known_lengths else None
        for candidate in vehicle_catalog or []:
            capacities = set(_capacity_map(candidate))
            length = candidate.get("consist_length_m")
            if (candidate.get("entity_id") != current_smallest.get("entity_id")
                    and required <= capacities
                    and candidate.get("capacity_total", 0) > current_smallest.get("capacity_total", 0)
                    and candidate.get("consist_top_speed_kmh") == speed
                    and isinstance(length, (int, float)) and max_length is not None and length <= max_length
                    and candidate.get("consist_signature")):
                candidates.append(candidate)
        if candidates:
            candidate = max(candidates, key=lambda item: item.get("capacity_total") or 0)
            action_plan = {
                "kind": "ADD_CARRIAGES_BY_CONFIG_REPLACEMENT",
                "operations": [{"operation_type": "REPLACE_VEHICLE_CONFIG",
                                "target": {"vehicle_id": current_smallest["entity_id"]},
                                "parameters": {"source_vehicle_id": candidate["entity_id"],
                                               "confirmation": f"REPLACE_VEHICLE_CONFIG:{current_smallest['entity_id']}:{candidate['entity_id']}"}}],
                "capacity_before": current_smallest.get("capacity_total"),
                "capacity_after": candidate.get("capacity_total"),
                "parts_before": len(current_smallest.get("consist_parts", [])),
                "parts_after": len(candidate.get("consist_parts", [])),
                "reason": "larger compatible consist fits every selectable platform",
            }
    elif execution_eligibility == "PROPOSAL_READY" and underlying_decision == "REMOVE_ONE_PROPOSAL":
        target = max(vehicles, key=lambda item: item.get("capacity_total") or 0)
        target_capacity = sum(_capacity_map(target).get(cargo_id, 0) for cargo_id in constraint["required_cargo_ids"])
        onboard = int(latest_metrics.get("onboard") or 0)
        minimum_total = math.ceil(onboard * 1.1)
        smaller = []
        for candidate in vehicle_catalog or []:
            candidate_capacity = sum(_capacity_map(candidate).get(cargo_id, 0)
                                     for cargo_id in constraint["required_cargo_ids"])
            target_length, candidate_length = target.get("consist_length_m"), candidate.get("consist_length_m")
            if (candidate.get("entity_id") != target.get("entity_id")
                    and candidate.get("consist_signature") and candidate.get("consist_signature") != target.get("consist_signature")
                    and candidate.get("consist_top_speed_kmh") == target.get("consist_top_speed_kmh")
                    and candidate_capacity > 0 and candidate_capacity < target_capacity
                    and total_capacity - target_capacity + candidate_capacity >= minimum_total
                    and isinstance(target_length, (int, float)) and isinstance(candidate_length, (int, float))
                    and candidate_length < target_length):
                smaller.append((candidate_capacity, candidate))
        if smaller:
            candidate_capacity, candidate = max(smaller, key=lambda item: (item[0], -item[1]["entity_id"]))
            action_plan = {
                "kind": "REMOVE_CARRIAGES_BY_CONFIG_REPLACEMENT",
                "operations": [{"operation_type": "REPLACE_VEHICLE_CONFIG",
                                "target": {"vehicle_id": target["entity_id"]},
                                "parameters": {"source_vehicle_id": candidate["entity_id"],
                                               "confirmation": f"REPLACE_VEHICLE_CONFIG:{target['entity_id']}:{candidate['entity_id']}"}}],
                "capacity_before": target_capacity, "capacity_after": candidate_capacity,
                "parts_before": len(target.get("consist_parts", [])),
                "parts_after": len(candidate.get("consist_parts", [])),
                "aggregate_capacity_after": total_capacity - target_capacity + candidate_capacity,
                "minimum_required_capacity": minimum_total,
                "reason": "sustained low load; shorten one consist while retaining 110% of observed onboard demand",
            }
        else:
            target = min(vehicles, key=lambda item: item.get("capacity_total") or 0)
            action_plan = {"kind": "REMOVE_TRAIN", "operations": [{"operation_type": "SELL_VEHICLE",
                           "target": {"vehicle_id": target["entity_id"]},
                           "parameters": {"confirmation": f"SELL_VEHICLE:{target['entity_id']}"}}],
                           "reason": "six consecutive under-load samples with no material queue"}
    if action_plan and action_plan.get("kind") == "ADD_TRAIN" and not (
            reachable_depot and reachable_depot.get("dispatch_verified") is True):
        action_plan = None
        fleet["execution_eligibility"] = "BLOCKED_BY_UNVERIFIED_DEPOT_DISPATCH"
        constraint["dispatch_path_status"] = "UNKNOWN_ENGINE_VALIDATION_REQUIRED"
        constraint["blocked_reason"] = (
            "the depot and line share track connectivity, but TPF2 has not verified that a newly bought train "
            "can enter this line without a path-finder failure")
    fleet["action_plan"] = action_plan
    return fleet, latest_metrics


def _parallel_service_diagnostics(plans: list[dict[str, Any]], cargo_names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    cargo_names = cargo_names or {}
    def station_pairs(plan: dict[str, Any]) -> set[tuple[int, int]]:
        stations = [int(stop["station_group_id"]) for stop in plan.get("stops", [])
                    if isinstance(stop.get("station_group_id"), int)]
        return {(left, right) for left in stations for right in stations if left != right}

    def cargo_supported(plan: dict[str, Any], cargo_id: int) -> bool:
        if plan.get("service_class") == "PASSENGER":
            return cargo_id == 0
        sets = ((plan.get("fleet_policy") or {}).get("consist_constraint") or {}).get("cargo_compatibility_sets", [])
        return bool(sets) and all(cargo_id in values for values in sets)

    def od_stop_pair(plan: dict[str, Any], value: dict[str, Any], origin: int, destination: int) -> list[int] | None:
        pairs = value.get("stop_pairs", {})
        if pairs:
            return list(max(pairs, key=pairs.get))
        stops = [item.get("station_group_id") for item in plan.get("stops", [])]
        for first, station in enumerate(stops):
            if station != origin:
                continue
            for distance in range(1, len(stops)):
                second = (first + distance) % len(stops)
                if stops[second] == destination:
                    return [first, second]
        return None

    demand_by_line: dict[int, dict[tuple[int, int, int], dict[str, int]]] = {}
    observed_keys: set[tuple[str, int, int, int]] = set()
    complete_lines: set[int] = set()
    for plan in plans:
        line_id, demand = plan["line_id"], plan.get("demand") or {}
        if demand.get("journey_granularity") != "LINE_STOP_OD" or demand.get("truncated") is not False:
            continue
        complete_lines.add(line_id)
        stops = {index: stop.get("station_group_id") for index, stop in enumerate(plan.get("stops", []))}
        line_values: dict[tuple[int, int, int], dict[str, int]] = {}
        for journey in demand.get("by_journey", []):
            left, right = stops.get(journey.get("line_stop_0")), stops.get(journey.get("line_stop_1"))
            if not isinstance(left, int) or not isinstance(right, int) or left == right:
                continue
            origin, destination = left, right
            cargo_values = journey.get("by_cargo", []) if plan["service_class"] == "FREIGHT" else [{
                "cargo_id": 0, "onboard": journey.get("onboard", 0), "waiting": journey.get("waiting", 0), "total": journey.get("total", 0),
            }]
            for cargo in cargo_values:
                cargo_id = cargo.get("cargo_id")
                if not isinstance(cargo_id, int):
                    continue
                key = (origin, destination, cargo_id)
                value = line_values.setdefault(key, {"onboard": 0, "waiting": 0, "total": 0, "stop_pairs": {}})
                for field in ("onboard", "waiting", "total"):
                    value[field] += int(cargo.get(field) or 0)
                pair = (int(journey.get("line_stop_0")), int(journey.get("line_stop_1")))
                value["stop_pairs"][pair] = value["stop_pairs"].get(pair, 0) + int(cargo.get("total") or 0)
                observed_keys.add((plan["service_class"], origin, destination, cargo_id))
        demand_by_line[line_id] = line_values

    result = []
    pairs_by_line = {plan["line_id"]: station_pairs(plan) for plan in plans}
    for service, origin, destination, cargo_id in sorted(observed_keys):
        members = [plan for plan in plans if plan["line_id"] in complete_lines
                   and plan["service_class"] == service
                   and (origin, destination) in pairs_by_line[plan["line_id"]]
                   and cargo_supported(plan, cargo_id)]
        if len(members) < 2:
            continue
        values = [demand_by_line.get(member["line_id"], {}).get((origin, destination, cargo_id), {"onboard": 0, "waiting": 0, "total": 0, "stop_pairs": {}})
                  for member in members]
        totals = [value["total"] for value in values]
        total = sum(totals)
        shares = [value / total if total else 0 for value in totals]
        imbalance = total >= 20 and max(shares) >= .8 and min(shares) <= .2
        waiting_total = sum(value["waiting"] for value in values)
        allocation = allocate_to_available_capacity(waiting_total, [{
            "line_id": member["line_id"],
            "line_name": member.get("line_name") or f"线路 {member['line_id']}",
            "residual_capacity": max(0, int(((member.get("fleet_policy") or {}).get("effective_capacity_total") or 0) - value["onboard"])),
            "departure_in_seconds": member["headway_seconds"],
        } for member, value in zip(members, values)])
        station_names = {}
        for member in members:
            station_names.update({stop.get("station_group_id"): stop.get("station_name") for stop in member.get("stops", [])})
        result.append({
            "service_class": service, "shared_station_pair": [origin, destination],
            "shared_station_names": [station_names.get(origin), station_names.get(destination)],
            "cargo_id": cargo_id, "cargo_name": "乘客" if cargo_id == 0 else cargo_names.get(cargo_id),
            "lines": [{"line_id": member["line_id"], "line_name": member.get("line_name") or f"线路 {member['line_id']}",
                       "demand": value["total"], "onboard": value["onboard"],
                       "waiting": value["waiting"], "demand_share": round(share, 3),
                       "source_stop_pair": od_stop_pair(member, value, origin, destination),
                       "headway_seconds": member["headway_seconds"]} for member, value, share in zip(members, values, shares)],
            "status": "OBSERVED_PARALLEL_OD_IMBALANCE" if imbalance else "BALANCED_OR_INSUFFICIENT_EVIDENCE",
            "direct_reassignment": "NATIVE_OD_REASSIGNMENT_CONTROL_PLANE_READY",
            "application_contract": {
                "mode": "VERSION_LOCKED_NATIVE_HOOK",
                "scope": "EXPLICIT_OD_AND_MAX_COUNT",
                "automatic_decision": True,
                "automatic_application": True,
            },
            "demand_granularity": "ENGINE_COMPONENT_LINE_STOP_OD",
            "observation_only": False,
            "automatic_decision": True,
            "proposed_adjustment": allocation,
        })
    return result


def _event_times(base: float, headway: float, horizon: float) -> list[float]:
    first = base % headway
    return [first + index * headway for index in range(-1, math.ceil(horizon / headway) + 1)]


def _line_block_profiles(plan: dict[str, Any], blocks: list[dict[str, Any]], clearance: int) -> list[dict[str, Any]]:
    """Approximate ordered block occupation from the line's native route edges."""
    route = [edge for edge in plan.get("route_edge_ids", []) if isinstance(edge, int)]
    if not route:
        return []
    running = float((plan.get("speed_basis") or {}).get("scheduled_running_seconds") or plan["cycle_seconds"])
    profiles = []
    for block in blocks:
        edge_ids = {edge for edge in block.get("edge_ids", []) if isinstance(edge, int)}
        indices = [index for index, edge in enumerate(route) if edge in edge_ids]
        if not indices:
            continue
        groups = [[indices[0]]]
        for index in indices[1:]:
            if index != groups[-1][-1] + 1:
                groups.append([])
            groups[-1].append(index)
        for occurrence, group in enumerate(groups):
            profiles.append({
                "block_id": block.get("block_id"), "occurrence": occurrence,
                "entry_offset_seconds": running * group[0] / len(route),
                "occupation_seconds": max(float(clearance), running * len(group) / len(route) + clearance),
                "edge_count": len(group),
                "source_status": "ROUTE_EDGE_ORDER_AND_SIGNAL_BLOCK_DERIVED",
            })
    return profiles


def _coordinate_station_phases(plans: list[dict[str, Any]], blocks: list[dict[str, Any]] | None = None,
                               horizon: int = 3600, clearance: int = 30) -> dict[str, Any]:
    """Shift lower-priority templates against station and signal-block reservations."""
    reserved: dict[int, list[float]] = defaultdict(list)
    platform_reserved: dict[tuple[int, int, int], list[tuple[float, float]]] = defaultdict(list)
    block_reserved: dict[str, list[tuple[float, float]]] = defaultdict(list)
    initial_conflicts = final_conflicts = initial_block_conflicts = final_block_conflicts = 0
    initial_platform_conflicts = final_platform_conflicts = 0
    blocks = blocks or []
    for plan in plans:
        headway = float(plan["headway_seconds"])
        profiles = _line_block_profiles(plan, blocks, clearance)
        plan["block_occupation_profiles"] = profiles
        step = max(1, min(5, int(headway // 12) or 1))
        candidates = list(range(0, max(1, int(headway)), step))

        def score(shift: float) -> tuple[int, int, int]:
            station_collisions = platform_collisions = block_collisions = 0
            for stop in plan["stops"]:
                station_id = stop.get("station_group_id")
                if not isinstance(station_id, int):
                    continue
                for event in _event_times(stop["departure_offset_seconds"] + shift, headway, horizon):
                    station_collisions += sum(abs(event - other) < clearance for other in reserved[station_id])
                station_index, terminal_index = stop.get("station_index"), stop.get("terminal_index")
                if isinstance(station_index, int) and isinstance(terminal_index, int):
                    key = (station_id, station_index, terminal_index)
                    duration = max(float(clearance), float(stop["departure_offset_seconds"] - stop["arrival_offset_seconds"]) + clearance)
                    for event in _event_times(stop["arrival_offset_seconds"] + shift, headway, horizon):
                        platform_collisions += sum(event < end and start < event + duration
                                                   for start, end in platform_reserved[key])
            for profile in profiles:
                duration = profile["occupation_seconds"]
                for event in _event_times(profile["entry_offset_seconds"] + shift, headway, horizon):
                    block_collisions += sum(event < end and start < event + duration
                                            for start, end in block_reserved[str(profile["block_id"])])
            return station_collisions, platform_collisions, block_collisions

        baseline_station, baseline_platform, baseline_block = score(0)
        scored = [(*score(candidate), candidate) for candidate in candidates]
        best_station, best_platform, best_block, shift = min(
            scored, key=lambda item: (item[0] + item[1] + item[2], item[2], item[1], item[0], item[3]))
        initial_conflicts += baseline_station
        final_conflicts += best_station
        initial_platform_conflicts += baseline_platform
        final_platform_conflicts += best_platform
        initial_block_conflicts += baseline_block
        final_block_conflicts += best_block
        plan["global_phase_shift_seconds"] = shift
        plan["station_conflicts_before_shift"] = baseline_station
        plan["station_conflicts_after_shift"] = best_station
        plan["platform_conflicts_before_shift"] = baseline_platform
        plan["platform_conflicts_after_shift"] = best_platform
        plan["block_conflicts_before_shift"] = baseline_block
        plan["block_conflicts_after_shift"] = best_block
        for stop in plan["stops"]:
            # Keep template times unwrapped: arrival <= departure <= next arrival,
            # including across the cycle boundary. Only controller slots wrap.
            stop["arrival_offset_seconds"] = round(stop["arrival_offset_seconds"] + shift, 1)
            stop["departure_offset_seconds"] = round(stop["departure_offset_seconds"] + shift, 1)
            stop["departure_offsets_seconds"] = sorted(round((value + shift) % plan["cycle_seconds"], 1) for value in stop["departure_offsets_seconds"])
            station_id = stop.get("station_group_id")
            if isinstance(station_id, int):
                reserved[station_id].extend(_event_times(stop["departure_offset_seconds"], headway, horizon))
                station_index, terminal_index = stop.get("station_index"), stop.get("terminal_index")
                if isinstance(station_index, int) and isinstance(terminal_index, int):
                    key = (station_id, station_index, terminal_index)
                    duration = max(float(clearance), float(stop["departure_offset_seconds"] - stop["arrival_offset_seconds"]) + clearance)
                    for event in _event_times(stop["arrival_offset_seconds"], headway, horizon):
                        platform_reserved[key].append((event, event + duration))
        for profile in profiles:
            duration = profile["occupation_seconds"]
            for event in _event_times(profile["entry_offset_seconds"] + shift, headway, horizon):
                block_reserved[str(profile["block_id"])].append((event, event + duration))
    return {"horizon_seconds": horizon, "clearance_seconds": clearance, "conflicts_before_shift": initial_conflicts,
            "conflicts_after_shift": final_conflicts, "conflicts_removed": initial_conflicts - final_conflicts,
            "block_conflicts_before_shift": initial_block_conflicts,
            "block_conflicts_after_shift": final_block_conflicts,
            "block_conflicts_removed": initial_block_conflicts - final_block_conflicts,
            "platform_conflicts_before_shift": initial_platform_conflicts,
            "platform_conflicts_after_shift": final_platform_conflicts,
            "platform_conflicts_removed": initial_platform_conflicts - final_platform_conflicts,
            "block_direction_policy": "BOTH_DIRECTIONS_MUTUALLY_EXCLUSIVE",
            "throat_policy": "STATION_GROUP_DEPARTURE_CLEARANCE",
            "constraint_source": "SIGNAL_BLOCK_PLATFORM_AND_THROAT" if blocks else "PLATFORM_AND_THROAT"}


def plan_line_timetables(snapshot: dict[str, Any], manifest: dict[str, Any],
                         frames: list[dict[str, Any]] | None = None,
                         demand_samples_by_line: dict[int, list[dict[str, Any]]] | None = None,
                         recent_fleet_change_line_ids: set[int] | None = None,
                         control: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create one repeating template per line; vehicles occupy evenly spaced phases."""
    frames = frames or []
    demand_samples_by_line = demand_samples_by_line or {}
    recent_fleet_change_line_ids = recent_fleet_change_line_ids or set()
    snapshot_lines = {int(item["entity_id"]): item for item in snapshot.get("lines", [])}
    manifest_lines = {int(item["entity_id"]): item for item in manifest.get("lines", [])}
    stations = {int(item["entity_id"]): item for item in manifest.get("stations", [])}
    edge_by_id = {int(edge["entity_id"]): edge for edge in manifest.get("edges", [])}
    node_by_id = {int(node["entity_id"]): node for node in manifest.get("nodes", [])}
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for edge in edge_by_id.values():
        if isinstance(edge.get("node0"), int) and isinstance(edge.get("node1"), int):
            union(int(edge["node0"]), int(edge["node1"]))

    def reachable_depot(line: dict[str, Any]) -> dict[str, Any] | None:
        route_edges = [edge_by_id[value] for value in line.get("route_edge_ids", []) if value in edge_by_id]
        route_nodes = {int(edge[key]) for edge in route_edges for key in ("node0", "node1")
                       if isinstance(edge.get(key), int)}
        if not route_nodes:
            return None
        route_roots = {find(node) for node in route_nodes}
        candidates = []
        for depot in manifest.get("depots", []):
            depot_edge = edge_by_id.get(depot.get("nearest_edge_id"))
            if not depot_edge or not all(isinstance(depot_edge.get(key), int) for key in ("node0", "node1")):
                continue
            depot_nodes = [int(depot_edge[key]) for key in ("node0", "node1")]
            if not any(find(node) in route_roots for node in depot_nodes):
                continue
            position = depot.get("track_connection_position") or depot.get("center") or {}
            x, y = position.get("x"), position.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            distances = []
            for node in route_nodes:
                node_position = node_by_id.get(node, {}).get("position", {})
                if isinstance(node_position.get("x"), (int, float)) and isinstance(node_position.get("y"), (int, float)):
                    distances.append(math.hypot(float(x) - float(node_position["x"]), float(y) - float(node_position["y"])))
            if distances and isinstance(depot.get("entity_id"), int):
                candidates.append((min(distances), depot))
        if not candidates:
            return None
        distance, depot = min(candidates, key=lambda item: (item[0], item[1]["entity_id"]))
        return {"entity_id": int(depot["entity_id"]), "name": depot.get("name"),
                "route_distance_m": round(distance, 1), "evidence": "SAME_RAIL_COMPONENT_NEAREST_ROUTE_NODE",
                "dispatch_verified": depot.get("dispatch_verified") is True}
    vehicles_by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for vehicle in snapshot.get("vehicles", []):
        if isinstance(vehicle.get("line_id"), int):
            vehicles_by_line[int(vehicle["line_id"])].append(vehicle)

    current_frame = max((frame for frame in frames if isinstance(frame.get("sampled_at"), (int, float))),
                        key=lambda frame: frame["sampled_at"], default=None)
    if current_frame is not None and current_frame.get("vehicles"):
        live_assignments: dict[int, list[dict[str, Any]]] = defaultdict(list)
        snapshot_vehicle_by_id = {int(item["entity_id"]): item for item in snapshot.get("vehicles", [])}
        for vehicle in current_frame["vehicles"]:
            if isinstance(vehicle.get("line_id"), int):
                merged = {**snapshot_vehicle_by_id.get(int(vehicle["entity_id"]), {}), **vehicle}
                live_assignments[int(vehicle["line_id"])].append(merged)
        for line_id, live_vehicles in live_assignments.items():
            # Live telemetry can transiently omit a train at a tunnel/path
            # boundary. Update matching entities without replacing the
            # complete snapshot-bound line fleet.
            merged_by_id = {int(item["entity_id"]): item for item in vehicles_by_line.get(line_id, [])}
            for live_vehicle in live_vehicles:
                merged_by_id[int(live_vehicle["entity_id"])] = live_vehicle
            vehicles_by_line[line_id] = list(merged_by_id.values())

    speeds: dict[int, list[float]] = defaultdict(list)
    for frame in frames:
        active = (frame.get("simulation") or {}).get("analysis_allowed") is True or frame.get("source_status") == "ENGINE_OBSERVED_DYNAMIC"
        if not active:
            continue
        for vehicle in frame.get("vehicles", []):
            speed = vehicle.get("speed_kmh")
            if isinstance(vehicle.get("line_id"), int) and isinstance(speed, (int, float)) and speed > 1:
                speeds[int(vehicle["line_id"])].append(float(speed))

    clock = (current_frame.get("simulation") or {}).get("clock", {}) if current_frame else {}
    epoch_ms = clock.get("game_time") if isinstance(clock.get("game_time"), (int, float)) else 0
    plans, excluded = [], []
    for line_id, line in sorted(manifest_lines.items()):
        observed = snapshot_lines.get(line_id, {})
        assigned = vehicles_by_line.get(line_id, [])
        frequency = observed.get("frequency_seconds")
        if len(line.get("stops", [])) < 2 or not assigned or not isinstance(frequency, (int, float)) or frequency <= 0:
            excluded.append({"line_id": line_id, "reason": "NEEDS_TWO_STOPS_ASSIGNED_VEHICLES_AND_FREQUENCY"})
            continue

        vehicle_count = len(assigned)
        consist_lengths = [float(vehicle["consist_length_m"]) for vehicle in assigned
                           if isinstance(vehicle.get("consist_length_m"), (int, float)) and vehicle["consist_length_m"] > 0]
        longest_train = max(consist_lengths) if len(consist_lengths) == len(assigned) else None
        cycle = max(60, _round_seconds(float(frequency) * vehicle_count))
        service = _line_kind(line, stations)
        stop_count = len(line["stops"])
        raw_sections = [vehicle.get("raw_sectionTimes") for vehicle in assigned]
        raw_sections = [values for values in raw_sections if isinstance(values, list) and len(values) == stop_count
                        and all(isinstance(value, (int, float)) and value > 0 for value in values)]
        if raw_sections:
            run_times = [_round_seconds(statistics.median(values[index] for values in raw_sections)) for index in range(stop_count)]
            minimum_dwell = 10 if service == "PASSENGER" else 20
            if sum(run_times) + minimum_dwell * stop_count > cycle:
                cycle = sum(run_times) + minimum_dwell * stop_count
            remaining = cycle - sum(run_times)
            dwell_times = [max(minimum_dwell, remaining // stop_count)] * stop_count
            dwell_times[-1] += cycle - sum(run_times) - sum(dwell_times)
            running_source = "ENGINE_RAW_SECTION_TIMES_MEDIAN"
        else:
            dwell = 30 if service == "PASSENGER" else 60 if service == "FREIGHT" else 45
            if dwell * stop_count >= cycle * .6:
                dwell = max(10, int(cycle * .4 / stop_count))
            dwell_times = [dwell] * stop_count
            running_budget = max(stop_count, cycle - sum(dwell_times))
            weights = _leg_weights(line)
            weight_total = sum(weights)
            run_times = [_round_seconds(running_budget * weight / weight_total) for weight in weights]
            run_times[-1] += cycle - (sum(run_times) + sum(dwell_times))
            running_source = "PROVISIONAL_DISTRIBUTION_WITHIN_OBSERVED_CYCLE"

        headway = cycle / vehicle_count
        phase_offsets = [round(index * headway, 1) for index in range(vehicle_count)]
        cumulative, stops = 0, []
        platform_checks = []
        for index, stop in enumerate(line["stops"]):
            dwell = dwell_times[index]
            arrival = cumulative
            departure = cumulative + dwell
            platform_fit = _platform_fit(stations.get(int(stop.get("station_group_id", -1)), {}), stop, longest_train)
            platform_checks.append(platform_fit)
            stops.append({
                "stop_index": index,
                "station_group_id": stop.get("station_group_id"),
                "station_index": stop.get("station_index"),
                "terminal_index": stop.get("terminal_index"),
                "alternative_terminals": stop.get("alternative_terminals", []),
                "station_name": stations.get(int(stop.get("station_group_id", -1)), {}).get("name"),
                "service_kind": _terminal_kind(stations.get(int(stop.get("station_group_id", -1)), {}), stop),
                "arrival_offset_seconds": arrival,
                "departure_offset_seconds": departure,
                "scheduled_dwell_seconds": dwell,
                "departure_offsets_seconds": sorted(round((departure + phase) % cycle, 1) for phase in phase_offsets),
                "max_hold_seconds": min(600, max(60, _round_seconds(headway * 1.1))),
                "next_leg_running_seconds": run_times[index],
                "platform_fit": platform_fit,
            })
            cumulative += dwell + run_times[index]

        speed = _percentile(speeds.get(line_id, []), .9)
        observed_speed_class = round(speed / 10) * 10 if speed is not None else None
        consist_limits = [vehicle.get("consist_top_speed_kmh") for vehicle in assigned if isinstance(vehicle.get("consist_top_speed_kmh"), (int, float))]
        consist_limit = round(min(consist_limits), 1) if consist_limits else None
        route_limits = [edge_by_id[edge_id].get("speed_limit_mps") for edge_id in line.get("route_edge_ids", [])
                        if edge_id in edge_by_id and isinstance(edge_by_id[edge_id].get("speed_limit_mps"), (int, float))]
        infrastructure_limit = round(min(route_limits) * 3.6, 1) if route_limits else None
        measured_distance = sum(_length(segment) for segment in line.get("overview_segments", []) if len(segment) >= 2)
        scheduled_running = sum(run_times)
        scheduled_speed = round(measured_distance / scheduled_running * 3.6, 1) if measured_distance > 0 and scheduled_running > 0 else None
        priority_speed = scheduled_speed if scheduled_speed is not None else observed_speed_class
        base_priority = {"PASSENGER": 300, "MIXED": 200, "FREIGHT": 100}.get(service, 0)
        plan = {
            "line_id": line_id, "line_name": line.get("name"), "enabled": False,
            "service_class": service, "speed_class_kmh": priority_speed,
            "speed_basis": {"consist_top_speed_kmh": consist_limit, "infrastructure_min_speed_limit_kmh": infrastructure_limit,
                            "observed_p90_speed_kmh": observed_speed_class, "scheduled_running_speed_kmh": scheduled_speed,
                            "scheduled_running_seconds": scheduled_running, "measured_route_distance_m": round(measured_distance, 1),
                            "rule": "section timetable uses observed sectionTimes; rolling-stock and infrastructure limits are feasibility ceilings"},
            "priority": {"base": base_priority, "speed_tiebreak_kmh": priority_speed,
                         "rule": "PASSENGER > MIXED > FREIGHT; within class, shorter scheduled time on the shared section first; aging prevents starvation"},
            "vehicle_count": vehicle_count, "headway_seconds": round(headway, 1), "cycle_seconds": cycle,
            "epoch_game_time_ms": epoch_ms, "late_release_seconds": min(60, max(10, _round_seconds(headway * .2))),
            "phase_offsets_seconds": phase_offsets, "stops": stops,
            "route_edge_ids": [int(edge) for edge in line.get("route_edge_ids", []) if isinstance(edge, int)],
            "platform_feasibility": {
                "longest_assigned_train_m": round(longest_train, 1) if longest_train is not None else None,
                "vehicle_lengths_complete": longest_train is not None,
                "all_stops_fit": bool(platform_checks) and all(item["status"] == "VERIFIED_FIT" for item in platform_checks),
                "status": "TOO_SHORT" if any(item["status"] == "TOO_SHORT" for item in platform_checks) else "VERIFIED_FIT" if platform_checks and all(item["status"] == "VERIFIED_FIT" for item in platform_checks) else "UNKNOWN",
                "rule": "every primary and selectable alternative platform must be at least as long as the longest assigned consist",
            },
            "source_status": {
                "cycle": "DERIVED_FROM_UI_CROSS_VERIFIED_FREQUENCY_X_ASSIGNED_VEHICLES",
                "running_times": running_source,
                "speed_class": "SECTION_TIMETABLE_DERIVED" if scheduled_speed is not None else "ENGINE_OBSERVED_P90" if speed is not None else "UNAVAILABLE",
                "demand": "UNAVAILABLE",
            },
        }
        samples = demand_samples_by_line.get(line_id) or demand_samples_by_line.get(str(line_id)) or []
        plan["fleet_policy"], plan["demand"] = _fleet_demand_profile(
            plan, assigned, samples, line_id in recent_fleet_change_line_ids, snapshot.get("vehicles", []),
            reachable_depot(line),
        )
        plan["source_status"]["demand"] = "ENGINE_COMPONENT_CLASSIFIED_HISTORY" if samples else "UNAVAILABLE"
        plans.append(plan)

    plans.sort(key=lambda item: (-item["priority"]["base"], -(item["speed_class_kmh"] or 0), item["line_id"]))
    verified_blocks = [block for block in (control or {}).get("blocks", [])
                       if isinstance(block, dict) and block.get("edge_ids")]
    conflict_plan = _coordinate_station_phases(plans, verified_blocks)
    edges_by_line = {int(item["entity_id"]): set(item.get("route_edge_ids", [])) for item in manifest.get("lines", [])}
    unresolved_shared_track = []
    for index, left in enumerate(plans):
        left_stations = {stop.get("station_group_id") for stop in left["stops"]}
        for right in plans[index + 1:]:
            shared_edges = edges_by_line.get(left["line_id"], set()) & edges_by_line.get(right["line_id"], set())
            if not shared_edges:
                continue
            right_stations = {stop.get("station_group_id") for stop in right["stops"]}
            unresolved_shared_track.append({
                "higher_priority_line_id": left["line_id"], "lower_priority_line_id": right["line_id"],
                "shared_edge_count": len(shared_edges), "shared_station_count": len(left_stations & right_stations),
                "status": "SIGNAL_BLOCK_PHASE_COORDINATED" if verified_blocks else "SECTION_OCCUPANCY_PENDING",
            })
    return {
        "schema_version": 4, "save_id": snapshot_save_id(snapshot),
        "plan_kind": "LINE_TEMPLATE_CYCLIC_TIMETABLE", "automatic_apply": False,
        "epoch_game_time_ms": epoch_ms, "counts": {"planned_lines": len(plans), "excluded_lines": len(excluded)},
        "lines": plans, "excluded": excluded, "global_conflict_plan": conflict_plan,
        "shared_track_conflicts": unresolved_shared_track,
        "parallel_service_diagnostics": _parallel_service_diagnostics(
            plans,
            {int(item["cargo_id"]): str(item.get("display_name") or item.get("cargo_key") or item["cargo_id"])
             for item in snapshot.get("cargo_types", []) if isinstance(item.get("cargo_id"), int)},
        ),
            "execution_contract": {
            "unit": "one timetable template per line; assigned vehicles use evenly spaced phases",
            "early_ready": "hold that vehicle at the terminal until its line slot",
            "late": "release without schedule hold, then recover at a later timing point",
            "conflicts": "plan slots by service priority; hold at the previous station, never intentionally on open line",
            "convergence": "one vehicle may claim each departure slot; bunched vehicles take successive slots and normally converge within one or two cycles",
        },
        "limitations": [
            "Demand-aware fleet changes require three overload or six underload samples and execute only through an ARMED control plane with write permissions.",
            "Direct passenger/cargo reassignment uses a version-locked native OD lease and fails closed when the game binary signature changes.",
            "Initial leg times are provisional until raw sectionTimes/lineStopDepartures are live-verified over multiple trips.",
            "Signal-block occupation uses route-edge order and scheduled running time; exact entry/exit times still need multi-trip live calibration.",
            "The planner never writes directly; the control plane applies plans only after health, permission, idempotency and action-budget checks.",
            "Unknown or insufficient platform length blocks automatic consist expansion; train length must not exceed any selectable platform length.",
        ],
    }
