import unittest
import json
from pathlib import Path

from tpf2_mcp.bridge import MockBridge
from tpf2_mcp.dispatch import station_waiting_state, vehicle_dispatch_state
from tpf2_mcp.server import handle
from tpf2_mcp.snapshot import SnapshotIndex


class ServerTests(unittest.TestCase):
    @staticmethod
    def bridge() -> MockBridge:
        return MockBridge(Path(__file__).parent / "fixtures" / "world_snapshot_001.json")

    def test_lists_tools(self):
        response = handle({"id": 1, "method": "tools/list"}, self.bridge())
        self.assertEqual("get_game_state", response["result"]["tools"][1]["name"])

    def test_reads_game_state(self):
        response = handle({"id": 2, "method": "tools/call", "params": {"name": "get_game_state"}}, self.bridge())
        self.assertEqual("mock", response["result"]["structuredContent"]["game"]["status"])

    def test_game_state_accepts_force_refresh(self):
        response = handle({"id": 12, "method": "tools/call", "params": {"name": "get_game_state", "arguments": {"force_refresh": True}}}, self.bridge())
        self.assertEqual(1, response["result"]["structuredContent"]["snapshot_sequence"])

    def test_lists_town_tools(self):
        response = handle({"id": 3, "method": "tools/list"}, self.bridge())
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("get_towns", names)
        self.assertIn("get_town", names)

    def test_mcp_structured_content_preserves_utf8(self):
        response = handle({"id": 4, "method": "tools/call", "params": {"name": "get_industries"}}, self.bridge())
        result = response["result"]
        self.assertEqual("铁矿", result["structuredContent"][0]["name"])
        self.assertIn("机械厂", result["content"][0]["text"])

    def test_line_summary_tool(self):
        response = handle({"id": 5, "method": "tools/call", "params": {"name": "get_line_summary", "arguments": {"line_id": 40}}}, self.bridge())
        self.assertEqual([50, 51], response["result"]["structuredContent"]["line"]["vehicle_ids"])

    def test_line_demand_tool_uses_bridge_protocol(self):
        bridge = self.bridge()
        tools = handle({"id": 51, "method": "tools/list"}, bridge)
        response = handle({"id": 52, "method": "tools/call", "params": {"name": "get_line_demand", "arguments": {"line_id": 40, "maximum_entities": 1234}}}, bridge)
        self.assertIn("get_line_demand", [item["name"] for item in tools["result"]["tools"]])
        self.assertEqual(40, response["result"]["structuredContent"]["line_id"])
        self.assertEqual(1234, response["result"]["structuredContent"]["maximum_entities"])

    def test_line_demand_validates_probe_bound(self):
        response = handle({"id": 53, "method": "tools/call", "params": {"name": "get_line_demand", "arguments": {"line_id": 40, "maximum_entities": 0}}}, self.bridge())
        self.assertEqual(-32602, response["error"]["code"])

    def test_agent_dispatch_tools_are_fixed_mcp_interfaces(self):
        bridge = self.bridge()
        listed = handle({"id": 54, "method": "tools/list"}, bridge)
        names = {item["name"] for item in listed["result"]["tools"]}
        self.assertTrue({"get_dispatch_overview", "get_station_dispatch_state", "get_line_dispatch_state",
                         "get_vehicle_dispatch_state", "get_agent_operations_guide"}.issubset(names))
        vehicle = handle({"id": 55, "method": "tools/call", "params": {
            "name": "get_vehicle_dispatch_state", "arguments": {"vehicle_id": 50}}}, bridge)
        self.assertEqual(50, vehicle["result"]["structuredContent"]["vehicle"]["entity_id"])
        self.assertEqual(0, vehicle["result"]["structuredContent"]["load"]["passengers"])
        guide = handle({"id": 56, "method": "resources/read", "params": {"uri": "tpf2://agent-operations"}}, bridge)
        self.assertIn("get_vehicle_dispatch_state", guide["result"]["contents"][0]["text"])

    def test_station_dispatch_aggregates_directional_waiting_demand(self):
        class DemandBridge(MockBridge):
            def line_demand(self, line_id: int, maximum_entities: int = 20000):
                value = super().line_demand(line_id, maximum_entities)
                if line_id != 40:
                    return value
                value.update(source_status="ENGINE_COMPONENT_CLASSIFIED", errors={})
                value["passengers"] = {
                    "waiting": 15, "truncated": False, "journey_granularity": "LINE_STOP_OD",
                    "by_journey": [
                        {"line_stop_0": 0, "line_stop_1": 1, "waiting": 5},
                        {"line_stop_0": 1, "line_stop_1": 2, "waiting": 7},
                        {"line_stop_0": 2, "line_stop_1": 1, "waiting": 3},
                    ],
                }
                value["cargo"] = {
                    "waiting": 10, "truncated": False, "journey_granularity": "LINE_STOP_OD",
                    "by_journey": [
                        {"line_stop_0": 0, "line_stop_1": 1, "waiting": 4,
                         "by_cargo": [{"cargo_id": 1, "waiting": 4}]},
                        {"line_stop_0": 1, "line_stop_1": 2, "waiting": 6,
                         "by_cargo": [{"cargo_id": 1, "waiting": 6}]},
                    ],
                }
                return value

        bridge = DemandBridge(Path(__file__).parent / "fixtures" / "world_snapshot_001.json")
        response = handle({"id": 57, "method": "tools/call", "params": {
            "name": "get_station_dispatch_state", "arguments": {"station_id": 30, "maximum_entities": 1000}}}, bridge)
        waiting = response["result"]["structuredContent"]["waiting"]
        self.assertEqual(8, waiting["passengers"]["waiting"])
        self.assertEqual(4, waiting["cargo"]["waiting"])
        self.assertEqual(4, waiting["cargo"]["by_cargo"][0]["waiting"])
        self.assertEqual([0, 2], waiting["lines"][0]["line_stop_indices"])
        self.assertTrue(waiting["quality"]["complete"])

    def test_vehicle_dispatch_marks_truncated_or_failed_load_incomplete(self):
        fixture = Path(__file__).parent / "fixtures" / "world_snapshot_001.json"
        index = SnapshotIndex(json.loads(fixture.read_text(encoding="utf-8")))
        truncated = vehicle_dispatch_state(index, 50, {"line_id": 40}, {
            "source_status": "ENGINE_COMPONENT_CLASSIFIED", "errors": {},
            "passengers": {"vehicles": {"50": 12}, "truncated": True},
            "cargo": {"vehicles": {}, "truncated": False, "by_cargo": []},
        })
        self.assertTrue(truncated["availability"]["load"])
        self.assertFalse(truncated["availability"]["complete_load"])
        self.assertIsNone(truncated["load"]["occupancy_ratio"])
        failed = vehicle_dispatch_state(index, 50, {"line_id": 40}, {
            "errors": {"persons": "probe failed"}, "passengers": {"vehicles": {}}, "cargo": {"vehicles": {}}})
        self.assertFalse(failed["availability"]["load"])
        self.assertIsNone(failed["load"]["passengers"])

    def test_station_waiting_preserves_available_kind_when_other_probe_fails(self):
        fixture = Path(__file__).parent / "fixtures" / "world_snapshot_001.json"
        index = SnapshotIndex(json.loads(fixture.read_text(encoding="utf-8")))
        waiting = station_waiting_state(index, 30, {40: {
            "errors": {"cargo": "probe failed"},
            "passengers": {"waiting": 5, "truncated": False,
                           "by_journey": [{"line_stop_0": 0, "line_stop_1": 1, "waiting": 5}]},
            "cargo": {"status": "UNAVAILABLE"},
        }})
        self.assertEqual(5, waiting["passengers"]["waiting"])
        self.assertIsNone(waiting["cargo"]["waiting"])
        self.assertEqual([40], waiting["quality"]["unavailable_by_kind"]["cargo"])
        self.assertEqual([], waiting["quality"]["unavailable_by_kind"]["passengers"])

    def test_network_summary_tool(self):
        response = handle({"id": 6, "method": "tools/call", "params": {"name": "get_transport_network_summary", "arguments": {}}}, self.bridge())
        self.assertEqual(2, response["result"]["structuredContent"]["line_count"])

    def test_network_resource(self):
        response = handle({"id": 7, "method": "resources/read", "params": {"uri": "tpf2://network"}}, self.bridge())
        self.assertIn('"line_count": 2', response["result"]["contents"][0]["text"])

    def test_vehicle_operating_tool_has_availability(self):
        response = handle({"id": 8, "method": "tools/call", "params": {"name": "get_vehicle_operating_state", "arguments": {"vehicle_id": 50}}}, self.bridge())
        self.assertFalse(response["result"]["structuredContent"]["availability"]["capacity"])

    def test_town_query_uses_snapshot_index(self):
        response = handle({"id": 9, "method": "tools/call", "params": {"name": "get_town", "arguments": {"entity_id": 10}}}, self.bridge())
        self.assertEqual("北京", response["result"]["structuredContent"]["name"])

    def test_cargo_types_tool(self):
        response = handle({"id": 10, "method": "tools/call", "params": {"name": "get_cargo_types", "arguments": {}}}, self.bridge())
        self.assertEqual("IRON_ORE", response["result"]["structuredContent"][1]["cargo_key"])

    def test_cargo_types_resource(self):
        response = handle({"id": 11, "method": "resources/read", "params": {"uri": "tpf2://cargo-types"}}, self.bridge())
        self.assertIn('"PASSENGERS"', response["result"]["contents"][0]["text"])

    def test_phase8_tools_and_capabilities_resource(self):
        capabilities = handle({"id": 12, "method": "resources/read", "params": {"uri": "tpf2://capabilities"}}, self.bridge())
        scorecard = handle({"id": 13, "method": "tools/call", "params": {"name": "get_line_scorecard", "arguments": {"line_id": 40}}}, self.bridge())
        route = handle({"id": 14, "method": "tools/call", "params": {"name": "find_station_route", "arguments": {"source_station_id": 30, "target_station_id": 32}}}, self.bridge())
        self.assertIn('"vehicle_load": {"status": "UNAVAILABLE"', capabilities["result"]["contents"][0]["text"])
        self.assertEqual(3, scorecard["result"]["structuredContent"]["network"]["stop_count"])
        self.assertEqual([30, 31, 32], route["result"]["structuredContent"]["station_ids"])

    def test_direct_operation_execution_is_not_exposed(self):
        bridge = self.bridge()
        capabilities = handle({"id": 15, "method": "tools/call", "params": {"name": "get_operation_capabilities", "arguments": {}}}, bridge)
        proposal = handle({"id": 16, "method": "tools/call", "params": {"name": "propose_operation", "arguments": {"operation_type": "RENAME_LINE", "target": {"line_id": 40}, "parameters": {"name": "Safe name"}}}}, bridge)
        tools = handle({"id": 17, "method": "tools/list", "params": {}}, bridge)
        execution = handle({"id": 18, "method": "tools/call", "params": {"name": "execute_operation", "arguments": {"operation_id": proposal["result"]["structuredContent"]["operation_id"], "dry_run": True}}}, bridge)
        self.assertTrue(capabilities["result"]["structuredContent"]["capabilities"][0]["verified"])
        self.assertNotIn("execute_operation", [item["name"] for item in tools["result"]["tools"]])
        self.assertIn("DIRECT_OPERATION_EXECUTION_DISABLED", execution["error"]["message"])

    def test_new_line_candidate_planner_is_exposed_and_read_only(self):
        bridge = self.bridge()
        before = bridge.game_state()
        tools = handle({"id": 19, "method": "tools/list", "params": {}}, bridge)
        result = handle({"id": 20, "method": "tools/call", "params": {"name": "plan_new_line_candidates", "arguments": {"limit": 5}}}, bridge)
        self.assertIn("plan_new_line_candidates", [item["name"] for item in tools["result"]["tools"]])
        candidate = result["result"]["structuredContent"]["candidates"][0]
        self.assertEqual("CREATE_LINE_GOAL", candidate["task_goal_candidate"]["goal_type"])
        self.assertEqual(before, bridge.game_state())
