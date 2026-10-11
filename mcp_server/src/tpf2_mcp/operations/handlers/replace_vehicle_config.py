from __future__ import annotations

from typing import Any

from .base import OperationHandler


class ReplaceVehicleConfigHandler(OperationHandler):
    operation_type = "REPLACE_VEHICLE_CONFIG"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        if not isinstance(target.get("vehicle_id"), int) or not isinstance(parameters.get("source_vehicle_id"), int):
            return "REPLACE_VEHICLE_CONFIG requires target.vehicle_id and parameters.source_vehicle_id."
        if target["vehicle_id"] == parameters["source_vehicle_id"]:
            return "Target and source vehicles must differ."
        expected = f"REPLACE_VEHICLE_CONFIG:{target['vehicle_id']}:{parameters['source_vehicle_id']}"
        if parameters.get("confirmation") != expected:
            return f"REPLACE_VEHICLE_CONFIG requires parameters.confirmation equal to {expected}."
        return None

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        source = index.vehicle_by_id[parameters["source_vehicle_id"]]
        return {
            "vehicle_id_preserved": target["vehicle_id"],
            "source_vehicle_id": parameters["source_vehicle_id"],
            "consist_signature_after": source.get("consist_signature"),
            "capacity_total_after": source.get("capacity_total"),
            "consist_part_count_after": len(source.get("consist_parts", [])),
        }

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
        expected = operation["expected_effect"]
        verified = bool(vehicle) and vehicle.get("consist_signature") == expected.get("consist_signature_after")
        return {
            "status": "POSTCONDITION_VERIFIED" if verified else "POSTCONDITION_NOT_MET",
            "vehicle_id_preserved": bool(vehicle),
            "observed_consist_signature": vehicle.get("consist_signature") if vehicle else None,
            "expected_consist_signature": expected.get("consist_signature_after"),
            "observed_capacity_total": vehicle.get("capacity_total") if vehicle else None,
        }
