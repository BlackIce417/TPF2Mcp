import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient, _atomic_json_write


class BridgeTests(unittest.TestCase):
    def test_atomic_write_creates_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "command.json"
            _atomic_json_write(path, {"ok": True})
            self.assertEqual({"ok": True}, json.loads(path.read_text(encoding="utf-8")))

    def test_missing_heartbeat_is_disconnected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(BridgeClient(Path(directory)).status()["connected"])

    def test_request_specific_ready_marked_response(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge_dir = Path(directory)
            responses = bridge_dir / "responses"
            responses.mkdir()

            def respond() -> None:
                command_path = bridge_dir / "command.json"
                while not command_path.exists():
                    time.sleep(0.005)
                command = json.loads(command_path.read_text(encoding="utf-8"))
                response = {"schema_version": 1, "request_id": command["request_id"], "ok": True,
                            "result": {"message": "pong"}, "error": None, "timestamp": 0}
                response_path = responses / f"{command['request_id']}.json"
                response_path.write_text(json.dumps(response), encoding="utf-8")
                (responses / f"{command['request_id']}.ready").write_text("ready\n", encoding="utf-8")

            worker = threading.Thread(target=respond)
            worker.start()
            self.assertEqual("pong", BridgeClient(bridge_dir, timeout_seconds=1).ping()["message"])
            worker.join(timeout=1)

    def test_full_rail_network_uses_explicit_one_shot_command(self):
        class RecordingBridge(BridgeClient):
            def call(self, command, params=None):
                return {"command": command, "params": params}

        result = RecordingBridge(Path("unused")).export_rail_network()
        self.assertEqual("get_rail_network", result["command"])
        self.assertEqual({}, result["params"])

    def test_operational_telemetry_uses_unified_explicit_command(self):
        class RecordingBridge(BridgeClient):
            def call(self, command, params=None):
                return {"command": command, "params": params}

        result = RecordingBridge(Path("unused")).operational_telemetry()
        self.assertEqual("get_operational_telemetry", result["command"])
        self.assertEqual({"section": "inventory"}, result["params"])

        result = RecordingBridge(Path("unused")).operational_telemetry("signals")
        self.assertEqual({"section": "signals"}, result["params"])

    def test_vehicle_dispatch_state_uses_explicit_bridge_command(self):
        class RecordingBridge(BridgeClient):
            def call(self, command, params=None):
                return {"command": command, "params": params}

        result = RecordingBridge(Path("unused")).vehicle_dispatch_state(42, 1234)
        self.assertEqual("get_vehicle_dispatch_state", result["command"])
        self.assertEqual({"vehicle_id": 42, "maximum_entities": 1234}, result["params"])
