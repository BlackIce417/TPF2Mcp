import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tpf2_mcp.bridge import BridgeClient, MockBridge
from tpf2_mcp.server import handle
from tpf2_mcp.speed_control_probe import classify_speed_control


def inventories(extra=None):
    commands = {"probe_kind": "READ_ONLY_API_COMMAND_INVENTORY", "api_cmd_make": {"value_type": "table", "items": [
        {"name": name, "value_type": "table"} for name in
        ("setGameSpeed", "setCalendarSpeed", "setAnimalState", "setUserStopped", "setVehicleManualDeparture", "setVehicleShouldDepart")
    ] + (extra or [])}}
    interface = {"game_interface": {"readable": True, "members": [{"key": "setGameSpeed", "value_type": "function"}]}}
    return commands, interface


class SpeedControlProbeTests(unittest.TestCase):
    def test_global_speed_and_stop_start_are_not_single_train_limits(self):
        result = classify_speed_control(*inventories(), fresh=True)
        self.assertEqual("NO_EXPOSED_SETTER_FOUND", result["status"])
        self.assertEqual([], result["candidates"])
        self.assertFalse(result["control_verified"])
        self.assertFalse(result["write_command_sent"])

    def test_callable_table_candidate_is_discovered_but_never_verified(self):
        result = classify_speed_control(*inventories([{"name": "setVehicleSpeed", "value_type": "table", "signature": "(Entity, Number) -> Command"}]), fresh=True)
        self.assertEqual("CANDIDATE_REQUIRES_VALIDATION", result["status"])
        self.assertEqual("setVehicleSpeed", result["candidates"][0]["name"])
        self.assertFalse(result["control_verified"])

    def test_incomplete_stale_or_capped_inventory_stays_unknown(self):
        self.assertEqual("UNKNOWN", classify_speed_control(*inventories(), fresh=False)["status"])
        self.assertEqual("UNKNOWN", classify_speed_control({}, {}, fresh=True)["status"])
        commands, interface = inventories()
        interface["game_interface"]["members"] *= 200
        self.assertEqual("UNKNOWN", classify_speed_control(commands, interface, fresh=True)["status"])

    def test_bridge_refreshes_sidecars_without_sending_write_command(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = BridgeClient(Path(directory))
            def respond(command, params=None):
                self.assertEqual("get_game_state", command)
                self.assertEqual({"force_refresh": True}, params)
                for name, value in zip(("api-command-inventory.json", "vehicle-write-api-probe.json"), inventories()):
                    (bridge.directory / name).write_text(json.dumps(value), encoding="utf-8")
                return {"sequence": 42}
            with patch.object(bridge, "call", side_effect=respond) as call:
                result = bridge.probe_vehicle_speed_control()
                self.assertEqual("NO_EXPOSED_SETTER_FOUND", result["status"])
                self.assertEqual(42, result["snapshot_sequence"])
                call.assert_called_once()
            with patch.object(bridge, "call", return_value={"sequence": 43}):
                self.assertEqual("UNKNOWN", bridge.probe_vehicle_speed_control()["status"])

    def test_mcp_entry_and_mock_cannot_claim_live_verification(self):
        bridge = MockBridge(Path(__file__).parent / "fixtures" / "world_snapshot_001.json")
        tools = handle({"id": 1, "method": "tools/list"}, bridge)["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "probe_vehicle_speed_control")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        request = {"id": 2, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}}
        result = handle(request, bridge)["result"]["structuredContent"]
        self.assertEqual("UNKNOWN", result["status"])
        self.assertTrue(result["mock"])
        request["params"]["arguments"] = {"execute": True}
        self.assertEqual(-32602, handle(request, bridge)["error"]["code"])
