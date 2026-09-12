import importlib.util
import json
import tempfile
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "serve-rail-map.py"
SPEC = importlib.util.spec_from_file_location("serve_rail_map", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RailMapServerTests(unittest.TestCase):
    def test_status_combines_bridge_and_manifest_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui"
            bridge = Path(directory) / "bridge"
            root.mkdir(); bridge.mkdir()
            (bridge / "heartbeat.json").write_text(json.dumps({"bridge_ready": True, "last_update": time.time(), "snapshot_seq": 4}), encoding="utf-8")
            (root / "rail-network-manifest.json").write_text(json.dumps({"generated_at": 9, "counts": {"lines": 2}}), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            status = app.status()

            self.assertTrue(status["bridge_connected"])
            self.assertEqual(4, status["snapshot_sequence"])
            self.assertEqual(9, status["rail_generation"])

    def test_http_status_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui"
            bridge = Path(directory) / "bridge"
            root.mkdir(); bridge.mkdir()
            (bridge / "heartbeat.json").write_text(json.dumps({"bridge_ready": True, "last_update": time.time()}), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")
            server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.handler_factory(app))
            import threading
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/status", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["bridge_connected"])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_live_endpoint_omits_static_control_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui"; bridge = Path(directory) / "bridge"
            root.mkdir(); bridge.mkdir()
            (bridge / "live-rail-state.json").write_text(json.dumps({"vehicles": [{"entity_id": 1}], "counts": {"rail_vehicles": 1}}), encoding="utf-8")
            (bridge / "rail-control-state.json").write_text(json.dumps({"signals": [{"entity_id": 2}], "blocks": [{"block_id": "B1"}], "counts": {"signals": 1}}), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")
            server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.handler_factory(app))
            import threading
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/live", timeout=2) as response:
                    live = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/control", timeout=2) as response:
                    control = json.loads(response.read().decode("utf-8"))
                self.assertNotIn("signals", live); self.assertNotIn("blocks", live)
                self.assertEqual(2, control["signals"][0]["entity_id"])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_operations_context_exposes_compact_station_dwell_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True)
            (bridge / "state.json").write_text(json.dumps({"sequence": 8, "lines": [{
                "entity_id": 91, "name": "线路 91", "frequency_seconds": 329,
                "raw_stops": [{"sequence_index": 2, "station_id": 12, "terminal_id": 1,
                               "policy": {"min_waiting_time": 0, "max_waiting_time": 180}}],
            }]}), encoding="utf-8")
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps({"lines": [{
                "line_id": 91, "vehicle_count": 2, "headway_seconds": 329,
                "stops": [{"stop_index": 2, "scheduled_dwell_seconds": 10,
                           "arrival_offset_seconds": 50, "departure_offset_seconds": 60}],
            }]}), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            value = app.operations_context()

            self.assertEqual(value["snapshot_sequence"], 8)
            self.assertEqual(value["lines"][0]["stops"][0]["scheduled_dwell_seconds"], 10)
            self.assertEqual(value["lines"][0]["stops"][0]["policy"]["max_waiting_time"], 180)

    def test_ai_advice_separates_unresolved_work_from_verified_work_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            state_dir = Path(directory) / "tpf2_mcp_state"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True); state_dir.mkdir()
            plan = {"counts": {"planned_lines": 1}, "global_conflict_plan": {"conflicts_removed": 2}, "lines": [{
                "line_id": 91, "line_name": "线路 91", "demand": {"waiting": 500, "sample_count": 3},
                "fleet_policy": {"decision": "ADD_ONE_PROPOSAL", "execution_eligibility": "PROPOSAL_READY"},
                "platform_feasibility": {"status": "VERIFIED_FIT"},
            }], "parallel_service_diagnostics": []}
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            completed = {"task_id": "t1", "status": "COMPLETED", "goal": {"target_line_id": 91},
                         "planned_steps": [{"target": {"line_id": 91}}],
                         "steps": [{"step_id": "s1", "sequence": 1, "operation_type": "SET_LINE_STOP_POLICY",
                                    "status": "POSTCONDITION_VERIFIED", "verification": {"status": "POSTCONDITION_VERIFIED"}}]}
            (state_dir / "tasks.jsonl").write_text(json.dumps(completed), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")
            advice, work = app.ai_suggestions(), app.mcp_work_logs()
            self.assertEqual("ADD_TRAIN", advice["suggestions"][0]["template"])
            self.assertEqual("REQUIRES_APPROVAL", advice["suggestions"][0]["automation_status"])
            self.assertIsInstance(advice["suggestions"][0]["created_at"], float)
            self.assertEqual(advice["generated_at"], advice["suggestions"][0]["created_at"])
            self.assertTrue(any(item["applied"] for item in work["entries"]))


if __name__ == "__main__":
    unittest.main()
