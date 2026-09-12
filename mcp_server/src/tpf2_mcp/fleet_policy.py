"""Conservative fleet-size recommendations from verified line demand samples."""
from __future__ import annotations

from typing import Any


def evaluate_fleet_adjustment(line_plan: dict[str, Any], demand_samples: list[dict[str, Any]], total_capacity: int) -> dict[str, Any]:
    service = line_plan.get("service_class")
    key = "passengers" if service == "PASSENGER" else "cargo" if service == "FREIGHT" else None
    usable = [sample for sample in demand_samples if key and isinstance(sample.get(key), dict)
              and sample[key].get("truncated") is False and sample[key].get("total_for_line") is not None]
    base = {"line_id": line_plan.get("line_id"), "automatic_execute": False, "sample_count": len(usable),
            "vehicle_count": line_plan.get("vehicle_count"), "capacity_total": total_capacity}
    if key is None or total_capacity <= 0 or not usable:
        return {**base, "decision": "INSUFFICIENT_DATA", "reason": "verified non-truncated demand samples and capacity are required"}

    def metrics(sample: dict[str, Any]) -> tuple[float, int, float | None]:
        value = sample[key]
        return value.get("onboard", 0) / total_capacity, int(value.get("waiting", 0)), value.get("average_waiting_seconds")

    values = [metrics(sample) for sample in usable]
    add_window = values[-3:]
    add_ready = len(add_window) == 3 and all(load >= .9 or (waiting >= total_capacity * .5 and isinstance(wait, (int, float)) and wait >= line_plan["headway_seconds"]) for load, waiting, wait in add_window)
    remove_window = values[-6:]
    remove_ready = len(remove_window) == 6 and line_plan.get("vehicle_count", 0) > 1 and all(load <= .35 and waiting <= total_capacity * .1 for load, waiting, _ in remove_window)
    decision = "ADD_ONE_PROPOSAL" if add_ready else "REMOVE_ONE_PROPOSAL" if remove_ready else "HOLD_FLEET"
    return {
        **base, "decision": decision,
        "latest": {"load_factor": round(values[-1][0], 3), "waiting": values[-1][1], "average_waiting_seconds": values[-1][2]},
        "thresholds": {"add_consecutive_samples": 3, "add_load_factor": .9, "add_waiting_capacity_ratio": .5,
                       "add_wait_at_least_headway": True, "remove_consecutive_samples": 6,
                       "remove_load_factor": .35, "remove_waiting_capacity_ratio": .1, "minimum_vehicles": 1},
        "safety": "proposal only; track/platform capacity and purchase/depot feasibility must pass before execution",
    }
