from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _round_15(value: float) -> int:
    return int(max(15, round(value / 15) * 15))


def _station_and_platform_index(manifest: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    stations = {int(item["entity_id"]): item for item in manifest.get("stations", [])}
    platforms: dict[int, dict[str, Any]] = {}
    for station in stations.values():
        for terminal in station.get("terminals", []):
            detail = {
                "station_group_id": int(station["entity_id"]),
                "station_name": station.get("name"),
                "station_index": terminal.get("station_index"),
                "terminal_index": terminal.get("terminal_index"),
                "cargo": bool(terminal.get("cargo")),
            }
            for edge_id in terminal.get("platform_edge_ids") or []:
                platforms[int(edge_id)] = detail
    return stations, platforms


def _line_stop_kind(line: dict[str, Any], stop: dict[str, Any], stations: dict[int, dict[str, Any]]) -> str:
    station = stations.get(int(stop.get("station_group_id", -1)))
    if not station:
        return "UNKNOWN"
    station_index, terminal_index = stop.get("station_index"), stop.get("terminal_index")
    terminal = next((item for item in station.get("terminals", []) if item.get("station_index") == station_index and item.get("terminal_index") == terminal_index), None)
    if terminal is None:
        return "UNKNOWN"
    return "CARGO" if terminal.get("cargo") else "PASSENGER"


def optimize_dwell_times(frames: list[dict[str, Any]], manifest: dict[str, Any], snapshot: dict[str, Any], *, minimum_observation_seconds: float = 60.0) -> dict[str, Any]:
    """Build a conservative, reversible stop-policy plan from live movement frames."""
    raw_frames = sorted((frame for frame in frames if isinstance(frame.get("sampled_at"), (int, float))), key=lambda item: item["sampled_at"])
    frames = [frame for frame in raw_frames if (frame.get("simulation") or {}).get("analysis_allowed") is True]
    if not frames:
        statuses = sorted({(frame.get("simulation") or {}).get("status", "UNKNOWN") for frame in raw_frames})
        return {
            "schema_version": 1, "source_status": "ANALYSIS_BLOCKED_SIMULATION_INACTIVE",
            "observation": {"frame_count": 0, "duration_seconds": 0.0, "minimum_required_seconds": minimum_observation_seconds, "simulation_statuses": statuses},
            "safety": {"signal_changes": False, "load_modes_preserved": True, "cargo_full_load_policies_preserved": True, "rollback_values_included": True, "automatic_apply": False},
            "counts": {"lines_analyzed": 0, "recommendations": 0, "apply_ready": 0}, "recommendations": [], "line_reports": [],
            "limitations": ["Dwell analysis is disabled while simulation is paused, stalled, or not yet confirmed running."],
        }
    stations, platform_edges = _station_and_platform_index(manifest)
    manifest_lines = {int(line["entity_id"]): line for line in manifest.get("lines", [])}
    snapshot_lines = {int(line["entity_id"]): line for line in snapshot.get("lines", [])}
    line_samples: dict[int, dict[str, Any]] = defaultdict(lambda: {"speeds": [], "sample_seconds": 0.0, "moving_seconds": 0.0, "platform_stop_seconds": 0.0, "outside_wait_seconds": 0.0, "stop_seconds": defaultdict(float), "outside_stop_seconds": defaultdict(float), "vehicles": set()})

    observation_seconds = 0.0
    for frame_index, frame in enumerate(raw_frames):
        if (frame.get("simulation") or {}).get("analysis_allowed") is not True:
            continue
        next_frame = raw_frames[frame_index + 1] if frame_index + 1 < len(raw_frames) else None
        continuous = next_frame is not None and (next_frame.get("simulation") or {}).get("analysis_allowed") is True
        wall_dt = max(0.0, min(5.0, float(next_frame["sampled_at"]) - float(frame["sampled_at"]))) if continuous else 0.0
        multiplier = (frame.get("simulation") or {}).get("speed_multiplier")
        dt = wall_dt * float(multiplier) if isinstance(multiplier, (int, float)) and multiplier > 0 else wall_dt
        observation_seconds += dt
        for vehicle in frame.get("vehicles", []):
            line_id = vehicle.get("line_id")
            if line_id not in manifest_lines:
                continue
            sample = line_samples[int(line_id)]
            sample["vehicles"].add(int(vehicle["entity_id"]))
            sample["sample_seconds"] += dt
            speed = vehicle.get("speed_kmh")
            if isinstance(speed, (int, float)):
                sample["speeds"].append(float(speed))
            stopped = isinstance(speed, (int, float)) and speed <= 1.0
            at_platform = int(vehicle.get("edge_id", -1)) in platform_edges
            if not stopped:
                sample["moving_seconds"] += dt
            elif at_platform:
                sample["platform_stop_seconds"] += dt
                stop_index = vehicle.get("stop_index")
                if isinstance(stop_index, int):
                    sample["stop_seconds"][stop_index] += dt
            elif vehicle.get("approaching_station") is True:
                sample["outside_wait_seconds"] += dt
                stop_index = vehicle.get("stop_index")
                if isinstance(stop_index, int):
                    sample["outside_stop_seconds"][stop_index] += dt

    recommendations, line_reports = [], []
    for line_id, line in manifest_lines.items():
        observed = line_samples[line_id]
        total = observed["sample_seconds"]
        current_line = snapshot_lines.get(line_id, {})
        current_stops = {int(stop.get("index", index)): stop for index, stop in enumerate(current_line.get("stops", []))}
        diagnostic = next((item for item in (frames[-1].get("line_diagnostics", []) if frames else []) if item.get("line_id") == line_id), {})
        outside_ratio = observed["outside_wait_seconds"] / total if total else 0.0
        platform_ratio = observed["platform_stop_seconds"] / total if total else 0.0
        moving_speeds = [value for value in observed["speeds"] if value > 1.0]
        line_report = {
            "line_id": line_id,
            "name": line.get("name"),
            "vehicle_count_observed": len(observed["vehicles"]),
            "median_moving_speed_kmh": round(statistics.median(moving_speeds), 1) if moving_speeds else None,
            "p10_moving_speed_kmh": round(_percentile(moving_speeds, .1), 1) if moving_speeds else None,
            "p90_moving_speed_kmh": round(_percentile(moving_speeds, .9), 1) if moving_speeds else None,
            "platform_stop_ratio": round(platform_ratio, 4),
            "outside_approach_wait_ratio": round(outside_ratio, 4),
            "spacing_diagnosis": diagnostic.get("diagnosis"),
            "minimum_spacing_m": diagnostic.get("minimum_spacing_m"),
            "target_spacing_m": diagnostic.get("target_spacing_m"),
            "frequency_seconds": current_line.get("frequency_seconds"),
            "throughput": current_line.get("throughput"),
        }
        line_reports.append(line_report)

        headway = current_line.get("frequency_seconds")
        if not isinstance(headway, (int, float)) or headway <= 0:
            continue
        base_passenger_max = _round_15(max(30.0, min(120.0, headway * .18)))
        congestion = outside_ratio >= .03 or diagnostic.get("diagnosis") == "POSSIBLE_BUNCHING"
        if congestion:
            base_passenger_max = _round_15(max(30.0, base_passenger_max * .75))
        if isinstance(current_line.get("throughput"), (int, float)) and current_line["throughput"] >= 500:
            base_passenger_max = min(base_passenger_max, 60)

        for stop in line.get("stops", []):
            stop_index = int(stop.get("sequence_index", 0))
            current = (current_stops.get(stop_index) or {}).get("policy") or {}
            stop_kind = _line_stop_kind(line, stop, stations)
            load_mode = current.get("load_mode")
            current_min, current_max = current.get("min_waiting_time"), current.get("max_waiting_time")
            if stop_kind != "PASSENGER" or load_mode != 0 or not isinstance(current_max, (int, float)) or current_max < 0:
                continue
            recommended = {"load_mode": load_mode, "min_waiting_time": 0, "max_waiting_time": base_passenger_max}
            if current_min == recommended["min_waiting_time"] and current_max == recommended["max_waiting_time"]:
                continue
            evidence_seconds = observed["stop_seconds"].get(stop_index, 0.0)
            outside_stop_seconds = observed["outside_stop_seconds"].get(stop_index, 0.0)
            enough_observation = observation_seconds >= minimum_observation_seconds
            confidence = "MEDIUM" if enough_observation and (evidence_seconds >= 10 or outside_stop_seconds >= 10) else "LOW"
            # Normal platform dwell alone does not prove that the configured
            # maximum hurts traffic. Require a queue outside this exact stop
            # before declaring a policy change safe to execute.
            apply_ready = enough_observation and outside_stop_seconds >= 10
            recommendations.append({
                "line_id": line_id,
                "line_name": line.get("name"),
                "stop_index": stop_index,
                "station_group_id": stop.get("station_group_id"),
                "station_name": stations.get(int(stop.get("station_group_id", -1)), {}).get("name"),
                "stop_kind": stop_kind,
                "current_policy": {"load_mode": load_mode, "min_waiting_time": current_min, "max_waiting_time": current_max},
                "recommended_policy": recommended,
                "confidence": confidence,
                "apply_ready": apply_ready,
                "reason": {
                    "headway_seconds": round(headway, 1),
                    "outside_approach_wait_ratio": round(outside_ratio, 4),
                    "platform_stop_seconds_at_stop": round(evidence_seconds, 1),
                    "outside_wait_seconds_for_stop": round(outside_stop_seconds, 1),
                    "spacing_diagnosis": diagnostic.get("diagnosis"),
                    "rule": "cap ordinary passenger dwell to 18% of observed headway; tighten for bunching/approach waiting/high throughput",
                },
            })

    recommendations.sort(key=lambda item: (not item["apply_ready"], -item["reason"]["outside_approach_wait_ratio"], item["line_id"], item["stop_index"]))
    return {
        "schema_version": 1,
        "source_status": "DERIVED_CONSERVATIVE",
        "observation": {"frame_count": len(frames), "duration_seconds": round(observation_seconds, 1), "minimum_required_seconds": minimum_observation_seconds},
        "safety": {
            "signal_changes": False,
            "load_modes_preserved": True,
            "cargo_full_load_policies_preserved": True,
            "rollback_values_included": True,
            "automatic_apply": False,
        },
        "counts": {"lines_analyzed": len(manifest_lines), "recommendations": len(recommendations), "apply_ready": sum(item["apply_ready"] for item in recommendations)},
        "recommendations": recommendations,
        "line_reports": sorted(line_reports, key=lambda item: (-item["outside_approach_wait_ratio"], item["line_id"])),
        "limitations": [
            "Signal aspects and reservations are unavailable.",
            "Station demand/load is unavailable; cargo/full-load policies are therefore preserved.",
            "Fixed stop policies can reduce dwell-induced bunching but cannot provide active timetable holding or priority dispatch.",
        ],
    }
