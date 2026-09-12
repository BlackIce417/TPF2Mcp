from __future__ import annotations
from typing import Any
from .base import OperationHandler
from ...lines import LineRouteRequest, LineStopResolver

class SetLineStopsHandler(OperationHandler):
    operation_type = "SET_LINE_STOPS"
    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        if not isinstance(target.get("line_id"), int): return "SET_LINE_STOPS requires target.line_id."
        if not isinstance(parameters.get("start_station_id"), int) or not isinstance(parameters.get("end_station_id"), int): return "SET_LINE_STOPS requires start_station_id and end_station_id."
        via = parameters.get("via_station_ids", [])
        if not isinstance(via, list) or not all(isinstance(value, int) for value in via): return "via_station_ids must be an integer list."
        route = [parameters["start_station_id"], *via, parameters["end_station_id"]]
        if len(set(route)) != len(route): return "SET_LINE_STOPS rejects repeated stations; TPF2 lines loop automatically and duplicate stops can hang the engine."
        return None
    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        route = LineRouteRequest(parameters["start_station_id"], parameters["end_station_id"], tuple(parameters.get("via_station_ids", [])))
        resolver, selectors = LineStopResolver(index), parameters.get("terminal_selectors", {})
        stops = [resolver.resolve_station_stop(value, terminal_selector=selectors.get(str(value), selectors.get(value))) for value in route.normalized_stop_sequence()]
        return {"normalized_route": route.normalized_stop_sequence(), "resolved_stops": stops, "resolution_error": next((item for item in stops if item.get("resolution_status") != "RESOLVED"), None)}
    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        line = index.line_by_id.get(operation["target"]["line_id"])
        observed = [item.get("station_id") for item in line.get("stops", [])] if line else []
        return {"status": "POSTCONDITION_VERIFIED" if observed == operation["expected_effect"]["normalized_route"] else "POSTCONDITION_NOT_MET", "observed_route": observed}
