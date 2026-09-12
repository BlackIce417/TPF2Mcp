import unittest
from tpf2_mcp.lines import LineRouteRequest, LineStopResolver
from tpf2_mcp.operations.handlers import get as handler_for
from tpf2_mcp.tasks.goals import goal_capability, planned_steps, scope_for


class _Index:
    station_by_id = {1: {}, 2: {}, 3: {}, 4: {}}
    line_by_id = {10: {"raw_stops": [{"station_id": 1, "station_index": 0, "terminal_id": 0}, {"station_id": 2, "station_index": 0, "terminal_id": 1}]}, 11: {"raw_stops": [{"station_id": 3, "station_index": 0, "terminal_id": 0}, {"station_id": 3, "station_index": 0, "terminal_id": 1}]}}


class LineRouteTests(unittest.TestCase):
    def test_order_is_preserved(self):
        self.assertEqual([1, 2, 3, 4], LineRouteRequest(1, 4, (2, 3)).normalized_stop_sequence())
        self.assertNotEqual([1, 2, 3, 4], LineRouteRequest(1, 4, (3, 2)).normalized_stop_sequence())

    def test_resolver_refuses_ambiguous_terminal(self):
        resolver = LineStopResolver(_Index())
        self.assertEqual("RESOLVED", resolver.resolve_station_stop(1)["resolution_status"])
        self.assertEqual("AMBIGUOUS_TERMINAL", resolver.resolve_station_stop(3)["resolution_status"])

    def test_create_line_handler_uses_business_route_not_source_line(self):
        handler = handler_for("CREATE_LINE")
        parameters = {"name": "A-B", "start_station_id": 1, "end_station_id": 2, "via_station_ids": []}
        self.assertIsNone(handler.validate_parameters({}, parameters))
        effect = handler.expected_effect(_Index(), {}, parameters)
        self.assertEqual([1, 2], effect["normalized_route"])
        self.assertIsNone(effect["resolution_error"])
        self.assertNotIn("source_line_id", parameters)

    def test_create_line_handler_rejects_repeated_station(self):
        handler = handler_for("CREATE_LINE")
        parameters = {"name": "unsafe-loop", "start_station_id": 1, "end_station_id": 1, "via_station_ids": [2]}
        self.assertIn("repeated stations", handler.validate_parameters({}, parameters))

    def test_set_line_stops_handler_rejects_repeated_station(self):
        handler = handler_for("SET_LINE_STOPS")
        parameters = {"start_station_id": 1, "end_station_id": 1, "via_station_ids": [2]}
        self.assertIn("repeated stations", handler.validate_parameters({"line_id": 10}, parameters))

    def test_create_line_goal_is_scoped_to_requested_stations(self):
        goal = {"name": "A-B-C", "start_station_id": 1, "via_station_ids": [2], "end_station_id": 3}
        self.assertEqual("CREATE_LINE", goal_capability("CREATE_LINE_GOAL")["operation_type"])
        self.assertEqual([1, 2, 3], scope_for("CREATE_LINE_GOAL", goal)["station_ids"])
        step = planned_steps("CREATE_LINE_GOAL", goal, {})[0]
        self.assertEqual("CREATE_LINE", step["operation_type"])
        self.assertNotIn("source_line_id", step["parameters"])

    def test_explicit_terminal_resolves_an_ambiguous_station(self):
        handler = handler_for("CREATE_LINE")
        parameters = {"name": "A-B", "start_station_id": 1, "end_station_id": 3, "via_station_ids": [], "terminal_selectors": {"3": 1}}
        effect = handler.expected_effect(_Index(), {}, parameters)
        self.assertIsNone(effect["resolution_error"])
        self.assertEqual(1, effect["resolved_stops"][1]["terminal"])
