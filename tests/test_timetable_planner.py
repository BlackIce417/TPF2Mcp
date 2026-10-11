import unittest

from tpf2_mcp.timetable_planner import plan_line_timetables, _coordinate_station_phases, _parallel_service_diagnostics


def fixture():
    snapshot = {
        "lines": [{"entity_id": 7, "frequency_seconds": 120, "throughput": 200}],
        "vehicles": [{"entity_id": 1, "line_id": 7}, {"entity_id": 2, "line_id": 7}],
    }
    manifest = {
        "stations": [
            {"entity_id": 10, "name": "A", "terminals": [{"station_index": 0, "terminal_index": 0, "cargo": False, "platform_length_m": 200}]},
            {"entity_id": 11, "name": "B", "terminals": [{"station_index": 0, "terminal_index": 0, "cargo": False, "platform_length_m": 200}]},
        ],
        "lines": [{"entity_id": 7, "name": "P1", "stops": [
            {"station_group_id": 10, "station_index": 0, "terminal_index": 0},
            {"station_group_id": 11, "station_index": 0, "terminal_index": 0},
        ], "overview_segments": [[[0, 0], [1000, 0]]]}],
    }
    frames = [{"simulation": {"analysis_allowed": True, "clock": {"game_time": 500000}}, "vehicles": [
        {"entity_id": 1, "line_id": 7, "speed_kmh": 158}, {"entity_id": 2, "line_id": 7, "speed_kmh": 160},
    ]}]
    return snapshot, manifest, frames


class TimetablePlannerTests(unittest.TestCase):
    def test_phase_shift_preserves_dwell_and_unwrapped_cycle_boundary(self):
        def template():
            return {"headway_seconds": 120, "cycle_seconds": 120, "stops": [
                {"station_group_id": 10, "arrival_offset_seconds": 0,
                 "departure_offset_seconds": 10, "departure_offsets_seconds": [10]},
                {"station_group_id": 11, "arrival_offset_seconds": 90,
                 "departure_offset_seconds": 110, "departure_offsets_seconds": [110]},
            ]}
        plans = [template(), template()]
        _coordinate_station_phases(plans)
        shifted = plans[1]
        self.assertGreater(shifted["global_phase_shift_seconds"], 0)
        first, last = shifted["stops"]
        self.assertEqual(10, first["departure_offset_seconds"] - first["arrival_offset_seconds"])
        self.assertEqual(20, last["departure_offset_seconds"] - last["arrival_offset_seconds"])
        self.assertGreater(last["departure_offset_seconds"], shifted["cycle_seconds"])
        self.assertEqual(last["departure_offset_seconds"] % 120, last["departure_offsets_seconds"][0])
        self.assertEqual(10, 120 + first["arrival_offset_seconds"] - last["departure_offset_seconds"])

    def test_plans_one_template_with_vehicle_phases(self):
        result = plan_line_timetables(*fixture())
        line = result["lines"][0]
        self.assertEqual(result["counts"], {"planned_lines": 1, "excluded_lines": 0})
        self.assertEqual(line["cycle_seconds"], 240)
        self.assertEqual(line["phase_offsets_seconds"], [0.0, 120.0])
        self.assertEqual(line["service_class"], "PASSENGER")
        self.assertIsNotNone(line["speed_class_kmh"])
        self.assertEqual(line["speed_basis"]["observed_p90_speed_kmh"], 160)
        self.assertFalse(line["enabled"])
        self.assertTrue(all(len(stop["departure_offsets_seconds"]) == 2 for stop in line["stops"]))

    def test_cycle_is_accounted_for_exactly(self):
        result = plan_line_timetables(*fixture())
        line = result["lines"][0]
        self.assertEqual(sum(stop["scheduled_dwell_seconds"] + stop["next_leg_running_seconds"] for stop in line["stops"]), line["cycle_seconds"])

    def test_demand_does_not_auto_mutate_fleet(self):
        result = plan_line_timetables(*fixture())
        policy = result["lines"][0]["fleet_policy"]
        self.assertFalse(policy["automatic_add"])
        self.assertFalse(policy["automatic_remove"])

    def test_lower_priority_phase_is_coordinated_after_passenger(self):
        snapshot, manifest, frames = fixture()
        snapshot["lines"].append({"entity_id": 8, "frequency_seconds": 120, "throughput": 200})
        snapshot["vehicles"].append({"entity_id": 3, "line_id": 8})
        freight = dict(manifest["lines"][0])
        freight.update(entity_id=8, name="F1")
        manifest["lines"].append(freight)
        for station in manifest["stations"]:
            station["terminals"][0]["cargo"] = True
        result = plan_line_timetables(snapshot, manifest, frames)
        self.assertIn("global_conflict_plan", result)
        self.assertGreaterEqual(result["global_conflict_plan"]["conflicts_removed"], 0)

    def test_shared_signal_block_occupation_shifts_lower_priority_line(self):
        def plan(line_id):
            return {"line_id": line_id, "headway_seconds": 120, "cycle_seconds": 240,
                    "route_edge_ids": [1, 2, 3, 4],
                    "speed_basis": {"scheduled_running_seconds": 40},
                    "stops": [{"station_group_id": line_id, "arrival_offset_seconds": 0,
                               "departure_offset_seconds": 10, "departure_offsets_seconds": [10, 130]}]}
        plans = [plan(7), plan(8)]
        result = _coordinate_station_phases(plans, [{"block_id": "b1", "edge_ids": [2, 3]}])
        self.assertEqual("SIGNAL_BLOCK_PLATFORM_AND_THROAT", result["constraint_source"])
        self.assertGreater(result["block_conflicts_before_shift"], 0)
        self.assertGreater(plans[1]["global_phase_shift_seconds"], 0)
        self.assertLess(result["block_conflicts_after_shift"], result["block_conflicts_before_shift"])
        self.assertEqual("b1", plans[0]["block_occupation_profiles"][0]["block_id"])
        self.assertEqual("BOTH_DIRECTIONS_MUTUALLY_EXCLUSIVE", result["block_direction_policy"])

    def test_speed_basis_keeps_consist_route_and_actual_schedule_separate(self):
        snapshot, manifest, frames = fixture()
        snapshot["vehicles"][0]["consist_top_speed_kmh"] = 200
        snapshot["vehicles"][1]["consist_top_speed_kmh"] = 160
        manifest["edges"] = [{"entity_id": 21, "speed_limit_mps": 33.333333}]
        manifest["lines"][0]["route_edge_ids"] = [21]
        result = plan_line_timetables(snapshot, manifest, frames)
        line = result["lines"][0]
        self.assertEqual(line["speed_basis"]["consist_top_speed_kmh"], 160)
        self.assertEqual(line["speed_basis"]["infrastructure_min_speed_limit_kmh"], 120)
        # Priority uses the line's scheduled performance. The two limits are
        # feasibility ceilings, not substitutes for an observed timetable.
        self.assertEqual(line["priority"]["speed_tiebreak_kmh"], line["speed_basis"]["scheduled_running_speed_kmh"])

    def test_real_demand_and_exact_consist_constraint_feed_fleet_policy(self):
        snapshot, manifest, frames = fixture()
        manifest["nodes"] = [{"entity_id": 100, "position": {"x": 0, "y": 0}},
                             {"entity_id": 101, "position": {"x": 1000, "y": 0}}]
        manifest["edges"] = [{"entity_id": 21, "node0": 100, "node1": 101, "speed_limit_mps": 55.5}]
        manifest["lines"][0]["route_edge_ids"] = [21]
        manifest["depots"] = [{"entity_id": 50, "name": "Test depot", "nearest_edge_id": 21,
                               "track_connection_position": {"x": 10, "y": 5}, "dispatch_verified": True}]
        for index, vehicle in enumerate(snapshot["vehicles"], 1):
            vehicle.update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                           supported_cargo_ids=[0], consist_signature="91:92", consist_top_speed_kmh=250,
                           consist_length_m=150, consist_parts=[{"model_id": 91, "model_name": "CRH2"}])
        samples = [{"passengers": {"truncated": False, "total_for_line": 390, "onboard": 190,
                                    "waiting": 200, "average_waiting_seconds": 300}}] * 3

        line = plan_line_timetables(snapshot, manifest, frames, {7: samples})["lines"][0]

        self.assertEqual("ENGINE_COMPONENT_CLASSIFIED_HISTORY", line["source_status"]["demand"])
        self.assertEqual("ADD_ONE_PROPOSAL", line["fleet_policy"]["decision"])
        self.assertEqual(200, line["fleet_policy"]["effective_capacity_total"])
        self.assertTrue(line["fleet_policy"]["consist_constraint"]["expansion_allowed"])
        self.assertIn(line["fleet_policy"]["consist_constraint"]["expansion_template_vehicle_id"], {1, 2})
        self.assertEqual(50, line["fleet_policy"]["action_plan"]["operations"][0]["target"]["depot_id"])

    def test_recent_verified_fleet_change_blocks_repeat_proposal_during_settlement(self):
        snapshot, manifest, frames = fixture()
        for vehicle in snapshot["vehicles"]:
            vehicle.update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                           consist_signature="91:92", consist_top_speed_kmh=250, consist_length_m=150)
        samples = [{"passengers": {"truncated": False, "total_for_line": 390, "onboard": 190,
                                    "waiting": 200, "average_waiting_seconds": 300}}] * 3

        line = plan_line_timetables(snapshot, manifest, frames, {7: samples}, {7})["lines"][0]

        self.assertEqual("HOLD_FLEET", line["fleet_policy"]["decision"])
        self.assertEqual("ADD_ONE_PROPOSAL", line["fleet_policy"]["underlying_decision"])
        self.assertTrue(line["fleet_policy"]["fleet_change_cooldown"])
        self.assertEqual("COOLDOWN_AFTER_VERIFIED_CHANGE", line["fleet_policy"]["execution_eligibility"])

    def test_sustained_low_load_prefers_a_shorter_compatible_consist(self):
        snapshot, manifest, frames = fixture()
        for vehicle in snapshot["vehicles"]:
            vehicle.update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                           consist_signature="long", consist_top_speed_kmh=160, consist_length_m=150,
                           consist_parts=[{"model_id": 1}, {"model_id": 2}])
        snapshot["vehicles"].append({"entity_id": 3, "line_id": 8, "capacity_total": 60,
                                     "capacity_by_cargo": [{"cargo_id": 0, "capacity": 60}],
                                     "consist_signature": "short", "consist_top_speed_kmh": 160,
                                     "consist_length_m": 90, "consist_parts": [{"model_id": 1}]})
        samples = [{"passengers": {"truncated": False, "total_for_line": 40, "onboard": 40,
                                    "waiting": 0, "average_waiting_seconds": 0}}] * 6

        policy = plan_line_timetables(snapshot, manifest, frames, {7: samples})["lines"][0]["fleet_policy"]

        self.assertEqual("REMOVE_ONE_PROPOSAL", policy["decision"])
        self.assertEqual("REMOVE_CARRIAGES_BY_CONFIG_REPLACEMENT", policy["action_plan"]["kind"])
        self.assertEqual(160, policy["action_plan"]["aggregate_capacity_after"])
        self.assertGreaterEqual(policy["action_plan"]["aggregate_capacity_after"],
                                policy["action_plan"]["minimum_required_capacity"])

    def test_short_or_unknown_platform_blocks_consist_expansion(self):
        snapshot, manifest, frames = fixture()
        for vehicle in snapshot["vehicles"]:
            vehicle.update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                           consist_signature="same", consist_top_speed_kmh=160, consist_length_m=180)
        manifest["stations"][1]["terminals"][0]["platform_length_m"] = 160
        line = plan_line_timetables(snapshot, manifest, frames)["lines"][0]
        self.assertEqual("TOO_SHORT", line["platform_feasibility"]["status"])
        self.assertFalse(line["fleet_policy"]["consist_constraint"]["expansion_allowed"])

    def test_every_selectable_alternative_platform_must_fit(self):
        snapshot, manifest, frames = fixture()
        for vehicle in snapshot["vehicles"]:
            vehicle["consist_length_m"] = 150
        manifest["stations"][0]["terminals"].append({"station_index": 0, "terminal_index": 1, "cargo": False, "platform_length_m": 100})
        manifest["lines"][0]["stops"][0]["alternative_terminals"] = [{"station_index": 0, "terminal_index": 1}]
        line = plan_line_timetables(snapshot, manifest, frames)["lines"][0]
        self.assertEqual("TOO_SHORT", line["stops"][0]["platform_fit"]["status"])

    def test_partial_live_frame_does_not_drop_snapshot_vehicle(self):
        snapshot, manifest, frames = fixture()
        frames[0]["vehicles"] = [frames[0]["vehicles"][0]]
        line = plan_line_timetables(snapshot, manifest, frames)["lines"][0]
        self.assertEqual(2, line["vehicle_count"])
        self.assertEqual([0.0, 120.0], line["phase_offsets_seconds"])

    def test_mixed_speed_or_cargo_line_blocks_automatic_expansion_template(self):
        snapshot, manifest, frames = fixture()
        snapshot["vehicles"][0].update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                                       consist_signature="crh2", consist_top_speed_kmh=250)
        snapshot["vehicles"][1].update(capacity_total=100, capacity_by_cargo=[{"cargo_id": 0, "capacity": 100}],
                                       consist_signature="cr400", consist_top_speed_kmh=350)

        constraint = plan_line_timetables(snapshot, manifest, frames)["lines"][0]["fleet_policy"]["consist_constraint"]

        self.assertFalse(constraint["expansion_allowed"])
        self.assertFalse(constraint["homogeneous_speed_class"])

    def test_parallel_lines_report_assigned_demand_imbalance_without_claiming_direct_control(self):
        snapshot, manifest, frames = fixture()
        snapshot["lines"].append({"entity_id": 8, "frequency_seconds": 120, "throughput": 200})
        snapshot["vehicles"].append({"entity_id": 3, "line_id": 8, "capacity_total": 100})
        manifest["lines"].append({**manifest["lines"][0], "entity_id": 8, "name": "P2"})
        samples = {
            7: [{"passengers": {"truncated": False, "total_for_line": 100, "onboard": 80, "waiting": 20,
                                  "journey_granularity": "LINE_STOP_OD", "by_journey": [
                                      {"line_stop_0": 0, "line_stop_1": 1, "onboard": 80, "waiting": 20, "total": 100}]}}],
            8: [{"passengers": {"truncated": False, "total_for_line": 0, "onboard": 0, "waiting": 0,
                                  "journey_granularity": "LINE_STOP_OD", "by_journey": []}}],
        }

        result = plan_line_timetables(snapshot, manifest, frames, samples)
        diagnostic = result["parallel_service_diagnostics"][0]

        self.assertEqual("OBSERVED_PARALLEL_OD_IMBALANCE", diagnostic["status"])
        self.assertEqual("NATIVE_OD_REASSIGNMENT_CONTROL_PLANE_READY", diagnostic["direct_reassignment"])
        self.assertEqual("VERSION_LOCKED_NATIVE_HOOK", diagnostic["application_contract"]["mode"])
        self.assertEqual("EXPLICIT_OD_AND_MAX_COUNT", diagnostic["application_contract"]["scope"])
        self.assertTrue(diagnostic["application_contract"]["automatic_decision"])
        self.assertTrue(diagnostic["application_contract"]["automatic_application"])
        self.assertEqual([0, 1], next(item for item in diagnostic["lines"] if item["line_id"] == 7)["source_stop_pair"])
        self.assertFalse(diagnostic["observation_only"])
        self.assertTrue(diagnostic["automatic_decision"])
        self.assertFalse(diagnostic["proposed_adjustment"]["equal_split"])

    def test_parallel_line_advice_requires_exact_od_evidence(self):
        snapshot, manifest, frames = fixture()
        snapshot["lines"].append({"entity_id": 8, "frequency_seconds": 120, "throughput": 200})
        snapshot["vehicles"].append({"entity_id": 3, "line_id": 8, "capacity_total": 100})
        manifest["lines"].append({**manifest["lines"][0], "entity_id": 8, "name": "P2"})
        legacy = {7: [{"passengers": {"truncated": False, "onboard": 100, "waiting": 100}}],
                  8: [{"passengers": {"truncated": False, "onboard": 0, "waiting": 0}}]}

        result = plan_line_timetables(snapshot, manifest, frames, legacy)

        self.assertEqual([], result["parallel_service_diagnostics"])

    def test_parallel_od_keeps_direction_when_target_stop_order_is_reversed(self):
        def line(line_id, stops, waiting, capacity):
            return {"line_id": line_id, "line_name": str(line_id), "service_class": "PASSENGER",
                    "headway_seconds": 60, "stops": [{"station_group_id": value} for value in stops],
                    "fleet_policy": {"effective_capacity_total": capacity},
                    "demand": {"journey_granularity": "LINE_STOP_OD", "truncated": False,
                               "by_journey": [{"line_stop_0": 0, "line_stop_1": 1,
                                               "waiting": waiting, "onboard": 0, "total": waiting}]}}
        diagnostics = _parallel_service_diagnostics([
            line(1, [10, 20], 25, 0),
            line(2, [20, 10], 1, 100),
        ])
        forward = next(item for item in diagnostics if item["shared_station_pair"] == [10, 20])
        target = next(item for item in forward["lines"] if item["line_id"] == 2)
        self.assertEqual([1, 0], target["source_stop_pair"])
