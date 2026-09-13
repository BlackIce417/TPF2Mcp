"""Line-template cyclic timetable planning over verified snapshot/live fields."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

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
                          samples: list[dict[str, Any]], fleet_change_cooldown: bool = False
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
    template_safe = template is not None and homogeneous_speed and homogeneous_cargo and bool(template.get("consist_signature")) and platform_safe
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
        "expansion_allowed": template_safe,
        "blocked_reason": None if template_safe else "line must have one verified speed class; every vehicle and the clone template must support the required cargo; an exact consist signature and verified train-length/platform-length fit are required",
        "guarantee": "A purchase copies an existing consist from this line; it cannot introduce another train family or cargo capability.",
    }
    underlying_decision = fleet["decision"]
    execution_eligibility = (
        "COOLDOWN_AFTER_VERIFIED_CHANGE"
        if underlying_decision in {"ADD_ONE_PROPOSAL", "REMOVE_ONE_PROPOSAL"} and fleet_change_cooldown
        else "PROPOSAL_READY" if fleet["decision"] == "ADD_ONE_PROPOSAL" and template_safe
        else "BLOCKED_BY_CONSIST_CONSTRAINT" if fleet["decision"] in {"ADD_ONE_PROPOSAL", "REMOVE_ONE_PROPOSAL"} and not template_safe
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
    return fleet, latest_metrics


def _parallel_service_diagnostics(plans: list[dict[str, Any]], cargo_names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    cargo_names = cargo_names or {}
    def station_pairs(plan: dict[str, Any]) -> set[tuple[int, int]]:
        stations = sorted({int(stop["station_group_id"]) for stop in plan.get("stops", [])
                           if isinstance(stop.get("station_group_id"), int)})
        return {(left, right) for index, left in enumerate(stations) for right in stations[index + 1:]}

    def cargo_supported(plan: dict[str, Any], cargo_id: int) -> bool:
        if plan.get("service_class") == "PASSENGER":
            return cargo_id == 0
        sets = ((plan.get("fleet_policy") or {}).get("consist_constraint") or {}).get("cargo_compatibility_sets", [])
        return bool(sets) and all(cargo_id in values for values in sets)

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
            origin, destination = sorted((left, right))
            cargo_values = journey.get("by_cargo", []) if plan["service_class"] == "FREIGHT" else [{
                "cargo_id": 0, "onboard": journey.get("onboard", 0), "waiting": journey.get("waiting", 0), "total": journey.get("total", 0),
            }]
            for cargo in cargo_values:
                cargo_id = cargo.get("cargo_id")
                if not isinstance(cargo_id, int):
                    continue
                key = (origin, destination, cargo_id)
                value = line_values.setdefault(key, {"onboard": 0, "waiting": 0, "total": 0})
                for field in value:
                    value[field] += int(cargo.get(field) or 0)
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
        values = [demand_by_line.get(member["line_id"], {}).get((origin, destination, cargo_id), {"onboard": 0, "waiting": 0, "total": 0})
                  for member in members]
        totals = [value["total"] for value in values]
        total = sum(totals)
        shares = [value / total if total else 0 for value in totals]
        imbalance = total >= 20 and max(shares) >= .8 and min(shares) <= .2
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
                       "headway_seconds": member["headway_seconds"]} for member, value, share in zip(members, values, shares)],
            "status": "OBSERVED_PARALLEL_OD_IMBALANCE" if imbalance else "BALANCED_OR_INSUFFICIENT_EVIDENCE",
            "direct_reassignment": "UNAVAILABLE",
            "demand_granularity": "ENGINE_COMPONENT_LINE_STOP_OD",
            "observation_only": True,
            "automatic_decision": False,
            "proposed_adjustment": None,
        })
    return result


def _event_times(base: float, headway: float, horizon: float) -> list[float]:
    first = base % headway
    return [first + index * headway for index in range(-1, math.ceil(horizon / headway) + 1)]


def _coordinate_station_phases(plans: list[dict[str, Any]], horizon: int = 3600, clearance: int = 30) -> dict[str, Any]:
    """Shift lower-priority line templates to reduce station/throat slot collisions."""
    reserved: dict[int, list[float]] = defaultdict(list)
    initial_conflicts = final_conflicts = 0
    for plan in plans:
        headway = float(plan["headway_seconds"])
        step = max(1, min(5, int(headway // 12) or 1))
        candidates = list(range(0, max(1, int(headway)), step))

        def score(shift: float) -> int:
            collisions = 0
            for stop in plan["stops"]:
                station_id = stop.get("station_group_id")
                if not isinstance(station_id, int):
                    continue
                for event in _event_times(stop["departure_offset_seconds"] + shift, headway, horizon):
                    collisions += sum(abs(event - other) < clearance for other in reserved[station_id])
            return collisions

        baseline = score(0)
        scored = [(score(candidate), candidate) for candidate in candidates]
        best_score, shift = min(scored, key=lambda item: (item[0], item[1]))
        initial_conflicts += baseline
        final_conflicts += best_score
        plan["global_phase_shift_seconds"] = shift
        plan["station_conflicts_before_shift"] = baseline
        plan["station_conflicts_after_shift"] = best_score
        for stop in plan["stops"]:
            stop["departure_offset_seconds"] = round((stop["departure_offset_seconds"] + shift) % plan["cycle_seconds"], 1)
            stop["departure_offsets_seconds"] = sorted(round((value + shift) % plan["cycle_seconds"], 1) for value in stop["departure_offsets_seconds"])
            station_id = stop.get("station_group_id")
            if isinstance(station_id, int):
                reserved[station_id].extend(_event_times(stop["departure_offset_seconds"], headway, horizon))
    return {"horizon_seconds": horizon, "clearance_seconds": clearance, "conflicts_before_shift": initial_conflicts,
            "conflicts_after_shift": final_conflicts, "conflicts_removed": initial_conflicts - final_conflicts}


def plan_line_timetables(snapshot: dict[str, Any], manifest: dict[str, Any],
                         frames: list[dict[str, Any]] | None = None,
                         demand_samples_by_line: dict[int, list[dict[str, Any]]] | None = None,
                         recent_fleet_change_line_ids: set[int] | None = None) -> dict[str, Any]:
    """Create one repeating template per line; vehicles occupy evenly spaced phases."""
    frames = frames or []
    demand_samples_by_line = demand_samples_by_line or {}
    recent_fleet_change_line_ids = recent_fleet_change_line_ids or set()
    snapshot_lines = {int(item["entity_id"]): item for item in snapshot.get("lines", [])}
    manifest_lines = {int(item["entity_id"]): item for item in manifest.get("lines", [])}
    stations = {int(item["entity_id"]): item for item in manifest.get("stations", [])}
    edge_by_id = {int(edge["entity_id"]): edge for edge in manifest.get("edges", [])}
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
            plan, assigned, samples, line_id in recent_fleet_change_line_ids
        )
        plan["source_status"]["demand"] = "ENGINE_COMPONENT_CLASSIFIED_HISTORY" if samples else "UNAVAILABLE"
        plans.append(plan)

    plans.sort(key=lambda item: (-item["priority"]["base"], -(item["speed_class_kmh"] or 0), item["line_id"]))
    conflict_plan = _coordinate_station_phases(plans)
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
                "status": "STATION_PHASE_COORDINATED_SECTION_OCCUPANCY_PENDING",
            })
    return {
        "schema_version": 2, "save_id": snapshot_save_id(snapshot),
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
            "Demand-aware fleet changes require three overload or six underload samples and remain proposal-only.",
            "Direct passenger/cargo reassignment between parallel lines is unavailable; only frequency/travel-time influence is supported.",
            "Initial leg times are provisional until raw sectionTimes/lineStopDepartures are live-verified over multiple trips.",
            "Station/throat phases are coordinated now; exact shared-block occupation still needs live-verified section running times.",
            "Plans are emitted disabled and require explicit application after conflict and feasibility checks.",
            "Unknown or insufficient platform length blocks automatic consist expansion; train length must not exceed any selectable platform length.",
        ],
    }
