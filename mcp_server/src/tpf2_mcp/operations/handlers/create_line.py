from __future__ import annotations
from typing import Any
from .base import OperationHandler
from ...lines import LineRouteRequest, LineStopResolver


class ArbitraryCreateLineHandler(OperationHandler):
    """Business-route CREATE_LINE; terminal selection is evidence constrained."""
    operation_type = "CREATE_LINE"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        name = parameters.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            return "CREATE_LINE requires a non-empty parameters.name up to 128 characters."
        if not isinstance(parameters.get("start_station_id"), int) or not isinstance(parameters.get("end_station_id"), int):
            return "CREATE_LINE requires integer start_station_id and end_station_id."
        via = parameters.get("via_station_ids", [])
        if not isinstance(via, list) or not all(isinstance(value, int) for value in via):
            return "CREATE_LINE parameters.via_station_ids must be an integer list."
        route = [parameters["start_station_id"], *via, parameters["end_station_id"]]
        if len(set(route)) != len(route):
            return "CREATE_LINE rejects repeated stations; TPF2 lines loop automatically and duplicate stops can hang the engine."
        selectors = parameters.get("terminal_selectors", {})
        if not isinstance(selectors, dict) or not all(isinstance(value, int) for value in selectors.values()):
            return "CREATE_LINE parameters.terminal_selectors must map station IDs to integer terminals."
        return None

    def resolve(self, index: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        route = LineRouteRequest(parameters["start_station_id"], parameters["end_station_id"], tuple(parameters.get("via_station_ids", [])), parameters.get("transport_mode"))
        resolver = LineStopResolver(index)
        selectors = parameters.get("terminal_selectors", {})
        stops = [resolver.resolve_station_stop(station_id, route.transport_mode, selectors.get(str(station_id), selectors.get(station_id))) for station_id in route.normalized_stop_sequence()]
        failed = [stop for stop in stops if stop.get("resolution_status") != "RESOLVED"]
        return {"normalized_route": route.normalized_stop_sequence(), "stops": stops, "error": failed[0] if failed else None}

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        resolved = self.resolve(index, parameters)
        return {"new_line_count": 1, "normalized_route": resolved["normalized_route"], "resolved_stops": resolved["stops"], "resolution_error": resolved["error"]}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        before = set(operation["expected_entity_state"]["line_ids"])
        created = sorted(set(index.line_by_id) - before)
        if len(created) != 1:
            return {"status": "NEW_ENTITY_NOT_OBSERVED" if not created else "AMBIGUOUS_NEW_ENTITY", "new_entities": [{"entity_type": "LINE", "entity_id": value} for value in created]}
        line = index.line_by_id[created[0]]
        observed = [item.get("station_id") for item in line.get("stops", [])]
        expected = operation["expected_effect"]["normalized_route"]
        ok = line.get("name") == operation["parameters"]["name"] and observed == expected
        return {"status": "POSTCONDITION_VERIFIED" if ok else "POSTCONDITION_NOT_MET", "new_entities": [{"entity_type": "LINE", "entity_id": created[0]}], "observed_route": observed}


class CreateLineHandler(OperationHandler):
    """Creates a temporary line by copying a verified native source route."""
    operation_type = "CREATE_LINE_FROM_SOURCE_ROUTE"

    def validate_parameters(self, target: dict[str, Any], parameters: dict[str, Any]) -> str | None:
        if not isinstance(target.get("source_line_id"), int): return "CREATE_LINE_FROM_SOURCE_ROUTE requires target.source_line_id."
        name = parameters.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128: return "CREATE_LINE requires a non-empty parameters.name up to 128 characters."
        return None

    def expected_effect(self, index: Any, target: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        source = index.line_by_id[target["source_line_id"]]
        return {"new_line_count": 1, "source_line_id": target["source_line_id"], "ordered_stops": [{"station_id": item.get("station_id")} for item in source.get("stops", [])]}

    def verify_postcondition(self, index: Any, operation: dict[str, Any]) -> dict[str, Any]:
        before = set(operation["expected_entity_state"]["line_ids"])
        created = sorted(set(index.line_by_id) - before)
        if len(created) != 1: return {"status": "NEW_ENTITY_NOT_OBSERVED" if not created else "AMBIGUOUS_NEW_ENTITY", "new_entities": [{"entity_type": "LINE", "entity_id": value} for value in created]}
        line = index.line_by_id[created[0]]
        expected = operation["expected_effect"]["ordered_stops"]
        observed = [{"station_id": item.get("station_id")} for item in line.get("stops", [])]
        return {"status": "POSTCONDITION_VERIFIED" if line.get("name") == operation["parameters"]["name"] and observed == expected else "POSTCONDITION_NOT_MET", "new_entities": [{"entity_type": "LINE", "entity_id": created[0]}], "observed_route": observed}
