import configparser
import json
import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.control_system import EngineeringControlSystem, NativeLeaseWriter
from tpf2_mcp.save_scope import snapshot_save_id


def fixture():
    snapshot = {
        "game": {"world_entity": 0, "player_entity": 1}, "towns": [{"entity_id": 10}],
        "vehicles": [{"entity_id": 100, "line_id": 7, "consist_top_speed_kmh": 120,
                      "capacity_total": 100, "capacity_by_cargo": [{"cargo_id": 0, "capacity": 100}]}],
    }
    save_id = snapshot_save_id(snapshot)
    network = {
        "save_id": save_id,
        "nodes": [{"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                  {"entity_id": 2, "position": {"x": 2000, "y": 0, "z": 0}}],
        "edges": [{"entity_id": 11, "node0": 1, "node1": 2, "speed_limit_mps": 55.5}],
        "lines": [{"entity_id": 7, "route_edge_ids": [11]}],
    }
    live = {"save_id": save_id, "sampled_at": 1000, "simulation": {"analysis_allowed": True},
            "vehicles": [{"entity_id": 100, "line_id": 7, "stop_index": 0,
                          "approaching_station": True, "arrival_station_terminal_locked": False},
                         {"entity_id": 200, "line_id": 8, "stop_index": 1,
                          "approaching_station": False, "arrival_station_terminal_locked": False}],
            "blocks": [{"block_id": "busy", "edge_ids": [21, 22], "occupied_vehicle_ids": [200]},
                       {"block_id": "self", "edge_ids": [11], "occupied_vehicle_ids": [100]}]}
    plan_line = {"line_id": 7, "cycle_seconds": 120, "epoch_game_time_ms": 5000,
                 "late_release_seconds": 20, "priority": {"base": 300},
                 "stops": [{"stop_index": 0, "station_group_id": 10,
                            "departure_offsets_seconds": [10], "max_hold_seconds": 60,
                            "platform_fit": {"options": [
                                {"station_index": 0, "terminal_index": 1, "primary": True,
                                 "fits_longest_assigned_train": True},
                                {"station_index": 0, "terminal_index": 2, "primary": False,
                                 "fits_longest_assigned_train": True},
                            ]}}], "fleet_policy": {"action_plan": None}}
    plan = {"save_id": save_id, "lines": [plan_line], "parallel_service_diagnostics": [{
        "status": "OBSERVED_PARALLEL_OD_IMBALANCE",
        "lines": [{"line_id": 7, "demand_share": .9, "source_stop_pair": [0, 1]},
                  {"line_id": 8, "demand_share": .1, "source_stop_pair": [2, 3]}],
        "proposed_adjustment": {"allocations": [
            {"line_id": 8, "assigned": 12}, {"line_id": 7, "assigned": 0}
        ]},
    }]}
    heartbeat = {"bridge_ready": True, "last_update": 1000, "allow_write_operations": True,
                 "allowed_operations": ["APPLY_LINE_TIMETABLE", "CLEAR_LINE_TIMETABLE"]}
    native = {"state": "ACTIVE", "supervisor_state": "LOADED"}
    return snapshot, network, live, plan, heartbeat, native


class EngineeringControlSystemTests(unittest.TestCase):
    def test_existing_config_is_migrated_with_disabled_path_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            state.mkdir()
            (state / "control-system-config.json").write_text(
                json.dumps({"schema_version": 1, "mode": "DISABLED",
                            "features": {"station": True}, "speed_rules": []}), encoding="utf-8")
            system = EngineeringControlSystem(root / "bridge", state)
            self.assertTrue(system.config()["features"]["station"])
            self.assertFalse(system.config()["features"]["path"])
            self.assertEqual(300, system.config()["path_penalty_seconds"])

    def test_defaults_disabled_and_arming_requires_save_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            self.assertEqual("DISABLED", system.view()["config"]["mode"])
            with self.assertRaisesRegex(ValueError, "ARM"):
                system.configure({"mode": "ARMED"}, "save-1", "wrong")
            result = system.configure({"mode": "ARMED"}, "save-1", "ARM:save-1")
            self.assertEqual("ARMED", result["config"]["mode"])

    def test_shadow_computes_decisions_without_publishing_active_leases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "SHADOW", "features": {"routing": True, "station": True}}, None)
            snapshot, network, live, plan, heartbeat, native = fixture()
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            kinds = {item["kind"] for item in result["state"]["decisions"]}
            self.assertEqual({"routing", "station"}, kinds)
            self.assertEqual([], result["leases"]["leases"])
            self.assertEqual("SHADOW", result["state"]["lifecycle"])

    def test_shadow_spacing_is_computed_but_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            envelope = lambda positions: {"complete": True, "expected_parts": len(positions), "parts": [
                {"position": {"x": x, "y": 0, "z": 0},
                 "bounds": {"min": {"x": x - 5, "y": -2, "z": 0},
                            "max": {"x": x + 5, "y": 2, "z": 3}}} for x in positions]}
            live["vehicles"] = [
                {"entity_id": 100, "line_id": 7, "edge_id": 11, "edge_param": .1,
                 "current_edge_index": 0, "path_edge_ids": [11], "path_edge_directions": [True],
                 "speed_mps": 20, "position_stale": False, "footprint_complete": True,
                 "footprint_sampled_at": 1000, "brake_decel_mps2": .8,
                 "train_envelope": envelope([170, 200])},
                {"entity_id": 200, "line_id": 7, "edge_id": 11, "edge_param": .25,
                 "current_edge_index": 0, "path_edge_ids": [11], "path_edge_directions": [True],
                 "speed_mps": 10, "position_stale": False, "footprint_complete": True,
                 "footprint_sampled_at": 1000, "brake_decel_mps2": .8,
                 "train_envelope": envelope([450, 500])},
            ]
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "SHADOW", "features": {"spacing": True}}, snapshot_save_id(snapshot))
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            decision = next(item for item in result["state"]["decisions"]
                            if item.get("vehicle_id") == 100 and item["kind"] == "spacing_advisory")
            self.assertEqual(200, decision["leader_vehicle_id"])
            self.assertEqual([], result["leases"]["leases"])

    def test_switching_from_armed_to_shadow_immediately_clears_native_leases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"station": True}}, save_id, f"ARM:{save_id}")
            armed = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertTrue(armed["leases"]["leases"])
            shadow = system.configure({"mode": "SHADOW"}, save_id)
            self.assertEqual("SHADOW", shadow["config"]["mode"])
            self.assertEqual([], shadow["leases"]["leases"])

    def test_health_budget_covers_bounded_demand_probe_latency(self):
        snapshot, network, live, plan, heartbeat, native = fixture()
        live["sampled_at"] = 980
        heartbeat["last_update"] = 980
        health = EngineeringControlSystem._health(snapshot, network, live, heartbeat, native, 1000, 45)
        self.assertTrue(health["ready_read"])
        health = EngineeringControlSystem._health(snapshot, network, live, heartbeat, native, 1026, 45)
        self.assertFalse(health["ready_read"])

    def test_armed_publishes_multiple_native_leases_and_timetable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            applied = []
            system = EngineeringControlSystem(root / "bridge", root / "state",
                                              timetable_executor=lambda line: applied.append(line["line_id"]) or {"accepted": True})
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system.configure({"mode": "ARMED", "max_actions_per_cycle": 10,
                              "features": {"routing": True, "station": True, "speed": True, "timetable": True},
                              "speed_rules": [{"vehicle_id": 100, "line_id": 7, "start_km": 0.2,
                                               "end_km": 1.2, "speed_kmh": 60},
                                              {"vehicle_id": 100, "line_id": 7, "start_km": 0.8,
                                               "end_km": 1.8, "speed_kmh": 40}]}, save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual("ARMED", result["state"]["lifecycle"])
            self.assertEqual({"routing", "station", "speed"}, {item["kind"] for item in result["leases"]["leases"]})
            self.assertEqual([7], applied)
            ini = configparser.ConfigParser()
            ini.read(root / "bridge" / "native-control.ini")
            self.assertEqual("2", ini["meta"]["speed_count"])
            self.assertEqual("1", ini["meta"]["station_count"])
            self.assertEqual("1", ini["meta"]["routing_count"])
            self.assertEqual("100", ini["speed_0"]["vehicle_id"])
            self.assertEqual("100", ini["speed_1"]["vehicle_id"])

    def test_routing_lease_records_waiting_distribution_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"routing": True}}, save_id, f"ARM:{save_id}")
            first = system.cycle(snapshot, network, network, live, heartbeat,
                                 {**native, "supervisor_state": "LOADED"}, plan, now=1000)
            self.assertEqual(1, len(first["leases"]["leases"]))
            plan["parallel_service_diagnostics"][0]["lines"][0]["waiting"] = 5
            plan["parallel_service_diagnostics"][0]["lines"][1]["waiting"] = 7
            second = system.cycle(snapshot, network, network, live, heartbeat,
                                  {**native, "supervisor_state": "LOADED", "routing_successes": 1}, plan, now=1011)
            observed = next(item for item in second["state"]["actions"]
                            if item["kind"] == "OD_WAITING_DISTRIBUTION_OBSERVED")
            self.assertEqual(5, observed["source_waiting_delta"])
            self.assertEqual(7, observed["target_waiting_delta"])

    def test_path_controller_penalizes_other_trains_occupied_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"path": True},
                              "path_penalty_seconds": 240}, save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            lease = result["leases"]["leases"][0]
            self.assertEqual("path", lease["kind"])
            self.assertEqual(100, lease["vehicle_id"])
            self.assertEqual([21, 22], lease["edge_ids"])
            self.assertEqual(240.0, lease["penalty_seconds"])
            ini = configparser.ConfigParser()
            ini.read(root / "bridge" / "native-control.ini")
            self.assertEqual("1", ini["meta"]["path_count"])
            self.assertEqual("21,22", ini["path_0"]["edge_ids"])

    def test_path_controller_accepts_compact_live_path_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            live["path_blocks"] = live.pop("blocks")
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "SHADOW", "features": {"path": True}}, save_id)
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            decision = next(item for item in result["state"]["decisions"] if item["kind"] == "path")
            self.assertEqual([21, 22], decision["edge_ids"])

    def test_explicit_rules_are_validated_and_published_without_policy_switches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            plan["lines"].append({"line_id": 8, "stops": [
                {"station_group_id": 10}, {"station_group_id": 20},
            ]})
            plan["lines"][0]["stops"].append({"station_group_id": 20, "platform_fit": {"options": []}})
            network["edges"].append({"entity_id": 12, "node0": 1, "node1": 2, "speed_limit_mps": 55.5})
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED",
                              "station_rules": [{"rule_id": "s", "vehicle_id": 100, "line_id": 7,
                                                 "station_group_id": 10, "station_index": 0, "terminal_index": 1,
                                                 "expires_at": 1060}],
                              "path_rules": [{"rule_id": "p", "vehicle_id": 100, "edge_ids": [12],
                                              "penalty_seconds": 45, "expires_at": 1060}],
                              "routing_rules": [{"rule_id": "r", "source_line": 7, "target_line": 8,
                                                 "source_stop0": 0, "source_stop1": 1,
                                                 "target_stop0": 0, "target_stop1": 1,
                                                 "max_assignments": 3, "entity_kind": "PERSON",
                                                 "expires_at": 1060}]}, save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual({"station", "path", "routing"}, {item["kind"] for item in result["leases"]["leases"]})
            routing = next(item for item in result["leases"]["leases"] if item["kind"] == "routing")
            self.assertEqual("PERSON", routing["entity_kind"])

    def test_explicit_rules_fail_closed_on_direction_and_unknown_platform_fit(self):
        plan = {"lines": [
            {"line_id": 1, "stops": [{"station_group_id": 10, "platform_fit": {"options": [
                {"station_index": 0, "terminal_index": 0, "fits_longest_assigned_train": None}]}}
                                   , {"station_group_id": 20}]},
            {"line_id": 2, "stops": [{"station_group_id": 20}, {"station_group_id": 10}]},
        ]}
        live = {"vehicles": [{"entity_id": 5, "line_id": 1, "stop_index": 0,
                              "approaching_station": True, "arrival_station_terminal_locked": False}]}
        stations = EngineeringControlSystem._explicit_station_decisions(plan, live, [{
            "rule_id": "s", "vehicle_id": 5, "station_group_id": 10, "station_index": 0,
            "terminal_index": 0, "enabled": True, "expires_at": 2000}], 1100, 1000)
        self.assertEqual("PLATFORM_FIT_NOT_VERIFIED", stations[0]["reason"])
        routing = EngineeringControlSystem._explicit_routing_decisions(plan, [{
            "rule_id": "r", "source_line": 1, "target_line": 2,
            "source_stop0": 0, "source_stop1": 1, "target_stop0": 0, "target_stop1": 1,
            "max_assignments": 1, "entity_kind": "PERSON", "enabled": True, "expires_at": 2000,
        }], 1100, 1000)
        self.assertEqual("OD_DIRECTION_OR_STATION_MISMATCH", routing[0]["reason"])

    def test_expired_explicit_rule_is_removed_from_persistent_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "SHADOW", "speed_rules": [{"rule_id": "old", "vehicle_id": 100,
                              "line_id": 7, "start_km": .1, "end_km": .2, "speed_kmh": 30,
                              "expires_at": 999}]}, save_id)
            system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual([], system.config()["speed_rules"])

    def test_health_failure_degrades_and_clears_native_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "failure_trip_count": 2,
                              "features": {"speed": True},
                              "speed_rules": [{"vehicle_id": 100, "line_id": 7, "start_km": .1,
                                               "end_km": .5, "speed_kmh": 60}]}, save_id, f"ARM:{save_id}")
            native["state"] = "DISABLED"
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual("DEGRADED", result["state"]["lifecycle"])
            self.assertEqual(1, result["state"]["consecutive_failures"])
            self.assertEqual([], result["leases"]["leases"])

    def test_compensated_fleet_failure_stays_armed_and_enters_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            plan["lines"][0]["fleet_policy"]["action_plan"] = {"kind": "ADD_TRAIN", "operations": []}
            heartbeat["allowed_operations"] += ["BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE", "SELL_VEHICLE"]
            system = EngineeringControlSystem(
                root / "bridge", root / "state",
                fleet_executor=lambda action, line: {"status": "COMPENSATED_FAIL_CLOSED"})
            system.configure({"mode": "ARMED", "features": {"fleet": True}}, save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual("ARMED", result["state"]["lifecycle"])
            self.assertEqual(4600, result["state"]["cooldowns"]["fleet:7"])
            self.assertEqual("COMPENSATED_FAIL_CLOSED", result["state"]["actions"][0]["result"]["status"])

    def test_pending_native_update_cannot_be_armed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"station": True}}, save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat,
                                  {**native, "native_update_pending": True}, plan, now=1000)
            self.assertEqual("DEGRADED", result["state"]["lifecycle"])
            self.assertIn("not active", result["state"]["trip_reason"])
            self.assertEqual([], result["leases"]["leases"])

    def test_observed_speed_violation_revokes_native_leases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"speed": True},
                              "speed_rules": [{"vehicle_id": 100, "line_id": 7, "start_km": .1,
                                               "end_km": 1.0, "speed_kmh": 60}]}, save_id, f"ARM:{save_id}")
            system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            live["sampled_at"] = 1011
            heartbeat["last_update"] = 1011
            live["vehicles"][0].update(edge_id=11, speed_kmh=70)
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1011)
            self.assertEqual("DEGRADED", result["state"]["lifecycle"])
            self.assertIn("exceeded", result["state"]["trip_reason"])
            self.assertEqual([], result["leases"]["leases"])

    def test_emergency_stop_clears_resident_timetables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cleared = []
            system = EngineeringControlSystem(root / "bridge", root / "state",
                                              timetable_clearer=lambda line_id: cleared.append(line_id) or {"accepted": True})
            system._state["applied_timetables"] = {"7": "hash"}
            result = system.emergency_stop("TEST")
            self.assertEqual([7], cleared)
            self.assertEqual("DISABLED", result["state"]["lifecycle"])
            self.assertEqual([], result["leases"]["leases"])

    def test_native_zero_hold_is_rejected_and_bool_encoding_is_numeric(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, network, live, plan, heartbeat, native = fixture()
            save_id = snapshot_save_id(snapshot)
            system = EngineeringControlSystem(root / "bridge", root / "state")
            system.configure({"mode": "ARMED", "features": {"speed": True},
                              "automatic_infrastructure_speed_limits": False,
                              "edge_speed_rules": [{"vehicle_id": 100, "line_id": 7,
                                                    "edge_ids": [11], "speed_kmh": 0, "hold": True}]},
                             save_id, f"ARM:{save_id}")
            result = system.cycle(snapshot, network, network, live, heartbeat, native, plan, now=1000)
            self.assertEqual([], result["leases"]["leases"])
            self.assertEqual("NATIVE_ZERO_STOP_UNVERIFIED_USE_OFFICIAL_USER_STOP",
                             next(item for item in result["state"]["decisions"]
                                  if item.get("kind") == "speed" and item.get("reason"))["reason"])
            NativeLeaseWriter(root / "bridge").write(7, [{"kind": "speed", "lease_id": "test",
                "vehicle_id": 100, "speed_mps": 1, "hold": True, "edge_ids": [11], "expires_at": 2000}], now=1000)
            ini = configparser.ConfigParser(); ini.read(root / "bridge" / "native-control.ini")
            self.assertEqual("1", ini["speed_0"]["hold"])


if __name__ == "__main__":
    unittest.main()
