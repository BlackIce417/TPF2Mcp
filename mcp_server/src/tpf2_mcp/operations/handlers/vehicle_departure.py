from __future__ import annotations

from typing import Any

from .base import OperationHandler


class HoldVehicleAtTerminalHandler(OperationHandler):
    operation_type = "HOLD_VEHICLE_AT_TERMINAL"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        maximum = parameters.get("max_hold_seconds")
        valid = isinstance(target.get("vehicle_id"), int) and isinstance(maximum, (int, float)) and 10 <= maximum <= 600
        return None if valid else "HOLD_VEHICLE_AT_TERMINAL requires vehicle_id and max_hold_seconds 10..600."

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return {"manual_departure": True, "max_hold_seconds": parameters["max_hold_seconds"], "fail_safe_release": True}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
        control = vehicle.get("departure_control") if vehicle else None
        auto_departure = vehicle.get("raw_autoDeparture") if vehicle else None
        verified = bool(control and control.get("manual") is True and control.get("command_confirmed") is True and auto_departure is False)
        return {"status": "POSTCONDITION_VERIFIED" if verified else "POSTCONDITION_NOT_MET", "vehicle_id": operation["target"]["vehicle_id"], "expected_manual_departure": True, "observed_auto_departure": auto_departure, "observed_departure_control": control}


class ReleaseVehicleFromHoldHandler(OperationHandler):
    operation_type = "RELEASE_VEHICLE_FROM_HOLD"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        return None if isinstance(target.get("vehicle_id"), int) else "RELEASE_VEHICLE_FROM_HOLD requires vehicle_id."

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return {"manual_departure": False, "immediate_departure_requested": True}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        vehicle = index.vehicle_by_id.get(operation["target"]["vehicle_id"])
        control = vehicle.get("departure_control") if vehicle else None
        auto_departure = vehicle.get("raw_autoDeparture") if vehicle else None
        verified = bool(control and control.get("manual") is False and control.get("command_confirmed") is True and auto_departure is True)
        return {"status": "POSTCONDITION_VERIFIED" if verified else "POSTCONDITION_NOT_MET", "vehicle_id": operation["target"]["vehicle_id"], "expected_manual_departure": False, "observed_auto_departure": auto_departure, "observed_departure_control": control}
