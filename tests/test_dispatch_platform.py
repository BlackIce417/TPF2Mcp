import tempfile
import time
import unittest
from pathlib import Path

from tpf2_mcp.control_system import EngineeringControlSystem
from tpf2_mcp.dispatch_platform import DispatchControlPlatform


class DispatchPlatformTests(unittest.TestCase):
    def test_status_selects_official_and_native_backends(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = EngineeringControlSystem(root / "bridge", root / "state")
            platform = DispatchControlPlatform(control, root / "state")
            value = platform.view("save", {"sampled_at": time.time(), "vehicles": []},
                                  {"allow_write_operations": True,
                                   "allowed_operations": ["HOLD_VEHICLE_AT_TERMINAL", "RELEASE_VEHICLE_FROM_HOLD",
                                                          "STOP_VEHICLE", "START_VEHICLE"]},
                                  {"state": "ACTIVE", "supervisor_state": "LOADED"})
            self.assertEqual("OFFICIAL_LUA_API", value["capabilities"]["HOLD_TRAIN"]["backend"])
            self.assertEqual("OFFICIAL_LUA_API", value["capabilities"]["PROTECTIVE_STOP"]["backend"])
            self.assertEqual("NATIVE_SPEED_HOOK", value["capabilities"]["SET_SPEED_LIMIT"]["backend"])
            self.assertEqual("AVAILABLE", value["capabilities"]["SET_SPEED_LIMIT"]["status"])

    def test_speed_command_compiles_to_existing_control_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = EngineeringControlSystem(root / "bridge", root / "state")
            platform = DispatchControlPlatform(control, root / "state")
            result = platform.submit({"type": "SET_SPEED_LIMIT", "save_id": "save",
                                      "target": {"vehicle_id": 1, "line_id": 2},
                                      "parameters": {"start_km": 1, "end_km": 2, "speed_kmh": 60}}, "save")
            self.assertEqual("ACCEPTED", result["status"])
            self.assertEqual(60, control.config()["speed_rules"][0]["speed_kmh"])
            self.assertEqual(result["expires_at"], control.config()["speed_rules"][0]["expires_at"])

    def test_explicit_native_commands_are_stored_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = EngineeringControlSystem(root / "bridge", root / "state")
            platform = DispatchControlPlatform(control, root / "state")
            expiry = time.time() + 60
            commands = [
                {"type": "ASSIGN_PLATFORM", "command_id": "platform-1", "save_id": "save",
                 "target": {"vehicle_id": 1, "line_id": 2},
                 "parameters": {"station_group_id": 10, "station_index": 0, "terminal_index": 3},
                 "expires_at": expiry},
                {"type": "SET_PATH_COST", "command_id": "path-1", "save_id": "save",
                 "target": {"vehicle_id": 1}, "parameters": {"edge_ids": [7, 8], "penalty_seconds": 90},
                 "expires_at": expiry},
                {"type": "REASSIGN_OD", "command_id": "od-1", "save_id": "save", "target": {},
                 "parameters": {"source_line": 2, "target_line": 3, "source_stop0": 0, "source_stop1": 1,
                                "target_stop0": 2, "target_stop1": 3, "max_assignments": 4,
                                "entity_kind": "PERSON"}, "expires_at": expiry},
            ]
            for command in commands:
                self.assertEqual("ACCEPTED", platform.submit(command, "save")["status"])
            self.assertEqual("DUPLICATE", platform.submit(commands[0], "save")["status"])
            changed = {**commands[0], "parameters": {**commands[0]["parameters"], "terminal_index": 4}}
            with self.assertRaisesRegex(ValueError, "different content"):
                platform.submit(changed, "save")
            result = platform.submit({"type": "CANCEL_COMMAND", "save_id": "save",
                                      "target": {"command_id": "platform-1"}, "parameters": {}}, "save")
            self.assertEqual("CANCELLED", result["status"])
            self.assertEqual([], control.config()["station_rules"])
            self.assertEqual(1, len(control.config()["path_rules"]))
            self.assertEqual(1, len(control.config()["routing_rules"]))

    def test_cargo_reassignment_fails_closed_without_type_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            platform = DispatchControlPlatform(EngineeringControlSystem(root / "bridge", root / "state"), root / "state")
            with self.assertRaisesRegex(ValueError, "cargo-type-specific"):
                platform.submit({"type": "REASSIGN_OD", "save_id": "save", "target": {},
                                 "parameters": {"source_line": 1, "target_line": 2,
                                                "source_stop0": 0, "source_stop1": 1,
                                                "target_stop0": 0, "target_stop1": 1,
                                                "max_assignments": 1, "entity_kind": "CARGO", "cargo_id": 7}}, "save")

    def test_cross_save_and_expired_commands_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            platform = DispatchControlPlatform(EngineeringControlSystem(root / "bridge", root / "state"), root / "state")
            with self.assertRaisesRegex(ValueError, "save_id"):
                platform.submit({"type": "SET_PATH_POLICY", "save_id": "other"}, "save")
            with self.assertRaisesRegex(ValueError, "expires_at"):
                platform.submit({"type": "SET_PATH_POLICY", "save_id": "save", "expires_at": 1}, "save")

    def test_protective_stop_uses_official_user_stop_and_turnout_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = EngineeringControlSystem(root / "bridge", root / "state")
            operations = []
            platform = DispatchControlPlatform(
                control, root / "state", operation_executor=lambda value: operations.append(value) or {"accepted": True},
                speed_profile_provider=lambda: {"turnouts": [{"incident_edge_ids": [9]}]},
            )
            command = {"type": "PROTECTIVE_STOP", "save_id": "save", "target": {"vehicle_id": 1},
                       "parameters": {"edge_ids": [9]}}
            with self.assertRaisesRegex(ValueError, "turnout conflict"):
                platform.submit(command, "save")
            control.configure({"mode": "ARMED"}, "save", "ARM:save")
            command["parameters"]["emergency"] = True
            self.assertEqual("EXECUTED", platform.submit(command, "save")["status"])
            self.assertEqual("STOP_VEHICLE", operations[-1]["operation_type"])
            result = platform.submit({"type": "RESUME_TRAIN", "save_id": "save",
                                      "target": {"vehicle_id": 1}, "parameters": {}}, "save")
            self.assertEqual("EXECUTED", result["status"])
            self.assertEqual("START_VEHICLE", operations[-1]["operation_type"])


if __name__ == "__main__":
    unittest.main()
