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

    def test_generated_bootstrap_scripts_are_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui"; bridge = Path(directory) / "bridge"
            root.mkdir(); bridge.mkdir()
            (root / "rail-network-manifest.js").write_text("window.RAIL_NETWORK_DATA={};", encoding="utf-8")
            (root / "templates").mkdir()
            (root / "templates" / "sidebar.html").write_text("<template></template>", encoding="utf-8")
            (root / "station-previews").mkdir()
            (root / "station-previews" / "station-20.json").write_text("{}", encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")
            server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.handler_factory(app))
            import threading
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/rail-network-manifest.js", timeout=2) as response:
                    self.assertIn("no-store", response.headers.get("Cache-Control", ""))
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/templates/sidebar.html", timeout=2) as response:
                    self.assertIn("no-store", response.headers.get("Cache-Control", ""))
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/station-previews/station-20.json", timeout=2) as response:
                    self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_refresh_after_server_restart_reuses_matching_save_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui"; bridge = Path(directory) / "bridge"
            root.mkdir(); bridge.mkdir()
            state = {"game": {"player_entity": "1"}, "towns": [{"entity_id": 10}]}
            save_id = MODULE.snapshot_save_id(state)
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (bridge / "heartbeat.json").write_text(
                json.dumps({"bridge_ready": True, "last_update": time.time()}), encoding="utf-8",
            )
            (root / "rail-network-manifest.json").write_text(
                json.dumps({"save_id": save_id}), encoding="utf-8",
            )
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            app.refresh_save_scope()

            self.assertEqual(save_id, app.active_save_id)
            self.assertFalse((bridge / "rail-control-state.json").exists())

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
            state = {"sequence": 8, "game": {"player_entity": "1"}, "towns": [{"entity_id": 10}], "lines": [{
                "entity_id": 91, "name": "线路 91", "frequency_seconds": 329,
                "raw_stops": [{"sequence_index": 2, "station_id": 12, "station_index": 0, "terminal_id": 1,
                               "alternative_terminals": [{"station_index": 0, "terminal_id": 2}],
                               "policy": {"min_waiting_time": 0, "max_waiting_time": 180}}],
            }], "vehicles": [
                {"entity_id": 1, "line_id": 91, "raw_state": 1, "supported_cargo_ids": [0], "consist_top_speed_kmh": 250},
                {"entity_id": 2, "line_id": 91, "raw_state": 2, "capacity_by_cargo": [{"cargo_id": 0, "capacity": 80}], "consist_top_speed_kmh": 160},
                {"entity_id": 3, "line_id": 91, "raw_state": 1, "supported_cargo_ids": [0]},
                {"entity_id": 4, "line_id": 91, "raw_state": 0, "supported_cargo_ids": [0], "consist_top_speed_kmh": 300},
                {"entity_id": 5, "line_id": 91, "raw_state": 1, "supported_cargo_ids": [1], "consist_top_speed_kmh": 300},
            ]}
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps({"save_id": MODULE.snapshot_save_id(state), "lines": [{
                "line_id": 91, "vehicle_count": 2, "headway_seconds": 329,
                "stops": [{"stop_index": 2, "scheduled_dwell_seconds": 10,
                           "arrival_offset_seconds": 50, "departure_offset_seconds": 60}],
            }]}), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            value = app.operations_context()

            self.assertEqual(value["snapshot_sequence"], 8)
            self.assertEqual(value["lines"][0]["stops"][0]["scheduled_dwell_seconds"], 10)
            self.assertEqual(value["lines"][0]["stops"][0]["policy"]["max_waiting_time"], 180)
            self.assertEqual(value["lines"][0]["stops"][0]["station_index"], 0)
            self.assertEqual(value["lines"][0]["stops"][0]["alternative_terminals"][0]["terminal_id"], 2)
            self.assertEqual(value["lines"][0]["active_passenger_vehicles"], {
                "total": 3, "high_speed": 1, "conventional": 1, "unknown_speed": 1, "threshold_kmh": 250.0,
            })

    def test_ai_advice_separates_unresolved_work_from_verified_work_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            state_dir = Path(directory) / "tpf2_mcp_state"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True); state_dir.mkdir()
            state = {"game": {"player_entity": "1"}, "towns": [{"entity_id": 10}]}
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            plan = {"save_id": MODULE.snapshot_save_id(state), "counts": {"planned_lines": 1}, "global_conflict_plan": {"conflicts_removed": 2}, "lines": [{
                "line_id": 91, "line_name": "线路 91", "demand": {"waiting": 500, "sample_count": 3},
                "fleet_policy": {"decision": "ADD_ONE_PROPOSAL", "execution_eligibility": "PROPOSAL_READY"},
                "platform_feasibility": {"status": "VERIFIED_FIT"},
            }], "parallel_service_diagnostics": []}
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            completed = {"task_id": "t1", "save_id": MODULE.snapshot_save_id(state), "status": "COMPLETED", "goal": {"target_line_id": 91},
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

    def test_full_work_log_merges_latest_blocked_pending_and_cancelled_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            state_dir = Path(directory) / "tpf2_mcp_state"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True); state_dir.mkdir()
            state = {"game": {"player_entity": "1"}, "towns": [{"entity_id": 10}]}
            save_id = MODULE.snapshot_save_id(state)
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            tasks = [
                {"task_id": "blocked", "save_id": save_id, "status": "READY", "goal": {"vehicle_id": 7},
                 "next_step": {"operation_type": "HOLD_VEHICLE_AT_TERMINAL", "target": {"vehicle_id": 7}},
                 "timeline": [{"at": "2026-01-01T00:00:00+00:00"}]},
                {"task_id": "blocked", "save_id": save_id, "status": "FAILED", "goal": {"vehicle_id": 7},
                 "steps": [{"operation_type": "HOLD_VEHICLE_AT_TERMINAL", "status": "EXECUTION_FAILED"}],
                 "next_step": {"operation_type": "HOLD_VEHICLE_AT_TERMINAL", "target": {"vehicle_id": 7}},
                 "result": {"reason": "EXECUTION_FAILED"}, "timeline": [{"at": "2026-01-01T00:01:00+00:00"}]},
                {"task_id": "pending", "save_id": save_id, "status": "WAITING_FOR_APPROVAL", "goal": {"line_id": 9},
                 "next_step": {"operation_type": "SET_LINE_STOP_POLICY", "target": {"line_id": 9}},
                 "timeline": [{"at": "2026-01-01T00:02:00+00:00"}]},
                {"task_id": "cancelled", "save_id": save_id, "status": "CANCELLED", "goal": {"vehicle_id": 8},
                 "next_step": {"operation_type": "RELEASE_VEHICLE", "target": {"vehicle_id": 8}},
                 "timeline": [{"at": "2026-01-01T00:03:00+00:00"}]},
            ]
            (state_dir / "tasks.jsonl").write_text("\n".join(json.dumps(item) for item in tasks), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            value = app.mcp_work_logs(None)

            by_task = {item.get("task_id"): item for item in value["entries"] if item.get("task_id")}
            self.assertEqual(set(by_task), {"blocked", "pending", "cancelled"})
            self.assertEqual(by_task["blocked"]["category"], "BLOCKED")
            self.assertEqual(by_task["blocked"]["reason"], "EXECUTION_FAILED")
            self.assertEqual(by_task["pending"]["category"], "PENDING")
            self.assertEqual(by_task["cancelled"]["category"], "CANCELLED")
            self.assertEqual(value["status_counts"]["BLOCKED"], 1)

    def test_parallel_flow_advice_is_observation_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True)
            state = {"game": {"player_entity": "1"}, "towns": [{"entity_id": 10}]}
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            plan = {"save_id": MODULE.snapshot_save_id(state), "lines": [], "parallel_service_diagnostics": [{
                "status": "OBSERVED_PARALLEL_OD_IMBALANCE", "shared_station_pair": [10, 11], "cargo_id": 0,
                "lines": [{"line_id": 1, "demand_share": .9}, {"line_id": 2, "demand_share": .1}],
                "observation_only": True,
            }]}
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")

            item = app.ai_suggestions()["suggestions"][0]

            self.assertEqual("PARALLEL_LINE_IMBALANCE", item["template"])
            self.assertEqual("OBSERVATION_ONLY", item["automation_status"])
            self.assertTrue(item["observation_only"])
            self.assertIn("当前不生成或执行", item["required_action"])

    def test_recent_verified_fleet_change_suppresses_repeated_add_advice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ui" / "rail-map"; bridge = Path(directory) / "bridge"
            diagnostics = Path(directory) / "diagnostics" / "rail-operations"
            root.mkdir(parents=True); bridge.mkdir(); diagnostics.mkdir(parents=True)
            state = {"game": {"player_entity": "1"}, "towns": [{"entity_id": 10}]}
            save_id = MODULE.snapshot_save_id(state)
            (bridge / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (diagnostics / "line-timetable-plan.json").write_text(json.dumps({
                "save_id": save_id,
                "lines": [{
                    "line_id": 91, "line_name": "线路 91", "demand": {"waiting": 500, "sample_count": 4},
                    "fleet_policy": {"decision": "ADD_ONE_PROPOSAL", "execution_eligibility": "PROPOSAL_READY"},
                    "platform_feasibility": {"status": "VERIFIED_FIT"},
                }],
                "parallel_service_diagnostics": [],
            }), encoding="utf-8")
            app = MODULE.RailMapState(root, bridge, Path(directory) / "exporter.py")
            app.work_log.record_verified_action(
                save_id, "expand:91", "EXPAND_LINE_WITH_VEHICLE", "加车并验证", line_id=91,
            )

            advice = app.ai_suggestions()

            self.assertFalse(any(item.get("template") == "ADD_TRAIN" for item in advice["suggestions"]))


if __name__ == "__main__":
    unittest.main()
