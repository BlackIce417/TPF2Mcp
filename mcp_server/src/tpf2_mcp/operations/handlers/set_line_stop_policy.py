from __future__ import annotations

from typing import Any

from .base import OperationHandler


class SetLineStopPolicyHandler(OperationHandler):
    operation_type = "SET_LINE_STOP_POLICY"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        stop_index, load_mode = parameters.get("stop_index"), parameters.get("load_mode")
        minimum, maximum = parameters.get("min_waiting_time"), parameters.get("max_waiting_time")
        valid = (
            isinstance(target.get("line_id"), int)
            and isinstance(stop_index, int) and stop_index >= 0
            and isinstance(load_mode, int) and 0 <= load_mode <= 2
            and isinstance(minimum, (int, float)) and minimum >= 0
            and isinstance(maximum, (int, float)) and maximum >= minimum
        )
        return None if valid else "SET_LINE_STOP_POLICY requires line_id, non-negative stop_index, load_mode 0..2, and 0 <= min_waiting_time <= max_waiting_time."

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        return {"stop_index": parameters["stop_index"], "policy": self._policy(parameters)}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        line = index.line_by_id.get(operation["target"]["line_id"])
        stop_index = operation["parameters"]["stop_index"]
        stop = line.get("stops", [])[stop_index] if line and stop_index < len(line.get("stops", [])) else None
        observed = stop.get("policy") if stop else None
        expected = self._policy(operation["parameters"])
        return {"status": "POSTCONDITION_VERIFIED" if observed == expected else "POSTCONDITION_NOT_MET", "stop_index": stop_index, "expected_policy": expected, "observed_policy": observed}

    @staticmethod
    def _policy(parameters: dict[str, Any]) -> dict[str, Any]:
        return {"load_mode": parameters["load_mode"], "min_waiting_time": parameters["min_waiting_time"], "max_waiting_time": parameters["max_waiting_time"]}
