from __future__ import annotations
from typing import Any
from .base import OperationHandler

class BuyVehicleHandler(OperationHandler):
    operation_type = "BUY_VEHICLE"
    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        return None if isinstance(target.get("depot_id"), int) and isinstance(parameters.get("source_vehicle_id"), int) else "BUY_VEHICLE requires target.depot_id and parameters.source_vehicle_id."
    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return {"new_vehicle_count": 1, "baseline_vehicle_ids": sorted(index.vehicle_by_id)}
    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        before = set(operation["expected_entity_state"]["vehicle_ids"]); created = sorted(set(index.vehicle_by_id) - before)
        return {"status": "POSTCONDITION_VERIFIED" if len(created) == 1 else "NEW_ENTITY_NOT_OBSERVED" if not created else "AMBIGUOUS_NEW_ENTITY", "new_entities": [{"entity_type": "VEHICLE", "entity_id": value} for value in created]}
