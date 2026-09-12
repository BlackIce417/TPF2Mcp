from __future__ import annotations

from typing import Any

from .base import OperationHandler


class SellVehicleHandler(OperationHandler):
    operation_type = "SELL_VEHICLE"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        vehicle_id = target.get("vehicle_id")
        if not isinstance(vehicle_id, int):
            return "SELL_VEHICLE requires target.vehicle_id."
        if parameters.get("confirmation") != f"SELL_VEHICLE:{vehicle_id}":
            return f"SELL_VEHICLE requires parameters.confirmation equal to SELL_VEHICLE:{vehicle_id}."
        return None

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        vehicle = index.vehicle_by_id[target["vehicle_id"]]
        return {"vehicle_removed": True, "previous_line_id": vehicle.get("line_id")}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        vehicle_id = operation["target"]["vehicle_id"]
        removed = vehicle_id not in index.vehicle_by_id
        return {
            "status": "POSTCONDITION_VERIFIED" if removed else "POSTCONDITION_NOT_MET",
            "vehicle_id": vehicle_id,
            "vehicle_present": not removed,
        }
