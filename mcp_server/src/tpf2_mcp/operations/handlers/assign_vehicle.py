from __future__ import annotations
from typing import Any
from .base import OperationHandler

class AssignVehicleHandler(OperationHandler):
    operation_type = "ASSIGN_VEHICLE_TO_LINE"
    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        return None if isinstance(target.get("vehicle_id"), int) and isinstance(target.get("line_id"), int) and isinstance(parameters.get("stop_index", 0), int) else "ASSIGN_VEHICLE_TO_LINE requires vehicle_id, line_id, and integer stop_index."
    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return {"line_id": target["line_id"]}
    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        vehicle_id, line_id = operation["target"]["vehicle_id"], operation["target"]["line_id"]
        vehicle, line = index.vehicle_by_id.get(vehicle_id), index.line_by_id.get(line_id)
        assigned = vehicle and vehicle.get("line_id") == line_id
        reciprocal = vehicle_id in [item["entity_id"] for item in index.vehicles_by_line.get(line_id, [])] if line else False
        return {"status": "POSTCONDITION_VERIFIED" if assigned and reciprocal else "POSTCONDITION_CONFLICT" if assigned else "POSTCONDITION_NOT_MET"}
