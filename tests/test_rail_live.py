import unittest

from tpf2_mcp.rail_live import RailSpatialIndex, derive_blocks, line_diagnostics, normalize_live_state


NETWORK = {
    "nodes": [
        {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
        {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 0}},
        {"entity_id": 3, "position": {"x": 200, "y": 0, "z": 0}},
    ],
    "edges": [
        {"entity_id": 10, "node0": 1, "node1": 2},
        {"entity_id": 11, "node0": 2, "node1": 3},
    ],
}
MANIFEST = {"lines": [{"entity_id": 7, "name": "L7", "overview_segments": [[[0, 0], [100, 0], [200, 0]]]}]}


class RailLiveTests(unittest.TestCase):
    def test_spatial_index_snaps_to_observed_edge(self):
        value = RailSpatialIndex(NETWORK).snap({"x": 40, "y": 3, "z": 0})
        self.assertEqual(10, value["edge_id"])
        self.assertAlmostEqual(.4, value["edge_param"])
        self.assertAlmostEqual(3, value["distance_m"])

    def test_signal_splits_degree_two_chain_into_blocks(self):
        index = RailSpatialIndex(NETWORK)
        signals = [{"entity_id": 50, "edge_id": 10, "edge_param": .5}]
        blocks, atoms = derive_blocks(NETWORK, signals, index)
        self.assertEqual(2, len(blocks))
        self.assertEqual(3, len(atoms))
        self.assertAlmostEqual(50, blocks[0]["length_m"])

    def test_track_objects_are_conservative_signal_candidates(self):
        telemetry = {"track_edge_objects": [{"object_entity_id": 50, "edge_entity_id": 10, "position": {"x": 50, "y": 0, "z": 0}}]}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        self.assertEqual(1, result["counts"]["signal_candidates"])
        self.assertEqual(0, result["counts"]["confirmed_signals"])
        self.assertEqual("TRACK_OBJECT_CANDIDATE", result["signals"][0]["source_status"])

    def test_signal_list_classification_is_confirmed(self):
        telemetry = {"signal_edge_objects": [{"object_entity_id": 50, "edge_entity_id": 10, "position": {"x": 50, "y": 0, "z": 0}, "operational_signal_observed": True, "signal_types": [0]}]}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        self.assertEqual(1, result["counts"]["confirmed_signals"])
        self.assertEqual("SIGNAL_LIST_CLASSIFIED", result["signals"][0]["source_status"])
        self.assertAlmostEqual(.5, result["signals"][0]["edge_param"], places=4)

    def test_non_rail_line_vehicle_is_never_snapped_to_nearby_track(self):
        telemetry = {"vehicles": [{"entity_id": 3, "position": {"x": 20, "y": 1, "z": 0}, "component": {"line": {"value": 999}}}]}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        self.assertEqual([], result["vehicles"])

    def test_rail_vehicle_falls_back_to_first_observed_path_edge(self):
        telemetry = {"vehicles": [{"entity_id": 3, "component": {"line": {"value": 7}}, "path_edges": {"items": [{"edge_id": 11}]}}]}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        self.assertEqual(11, result["vehicles"][0]["edge_id"])
        self.assertEqual("MOVE_PATH_EDGE_APPROXIMATION", result["vehicles"][0]["position_source"])

    def test_compact_live_frame_uses_current_edge_param_and_engine_speed(self):
        telemetry = {"vehicles": [{
            "entity_id": 3,
            "name": "Train",
            "line_id": 7,
            "raw_state": 1,
            "stop_index": 0,
            "current_edge_id": 10,
            "current_edge_param": .25,
            "speed_mps": 20,
            "acceleration_mps2": .5,
        }]}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        vehicle = result["vehicles"][0]
        self.assertEqual("MOVE_PATH_DYN", vehicle["position_source"])
        self.assertAlmostEqual(25, vehicle["position"]["x"])
        self.assertAlmostEqual(72, vehicle["speed_kmh"])
        self.assertAlmostEqual(.5, vehicle["acceleration_mps2"])

    def test_transient_unknown_edge_retains_last_valid_position(self):
        first = normalize_live_state({"vehicles": [{
            "entity_id": 3, "name": "Tunnel train", "line_id": 7,
            "current_edge_id": 10, "current_edge_param": .4, "speed_mps": 20,
        }]}, NETWORK, MANIFEST, None, 10)
        second = normalize_live_state({"vehicles": [{
            "entity_id": 3, "name": "Tunnel train", "line_id": 7,
            "current_edge_id": 9999, "current_edge_param": .7, "speed_mps": 20,
        }]}, NETWORK, MANIFEST, first, 12)
        self.assertEqual(1, second["counts"]["rail_vehicles"])
        self.assertEqual(1, second["counts"]["position_fallback_vehicles"])
        self.assertTrue(second["vehicles"][0]["position_stale"])
        self.assertEqual("LAST_VALID_TRACK_POSITION", second["vehicles"][0]["position_source"])
        self.assertAlmostEqual(40, second["vehicles"][0]["position"]["x"])
        self.assertNotIn("block_id", second["vehicles"][0])

    def test_transient_position_fallback_expires_after_thirty_seconds(self):
        previous = {"sampled_at": 10, "vehicles": [{
            "entity_id": 3, "line_id": 7, "position": {"x": 40, "y": 0, "z": 0},
            "snapped_position": {"x": 40, "y": 0, "z": 0}, "edge_id": 10,
            "edge_param": .4, "rail_distance_m": 0, "position_observed_at": 10,
        }]}
        result = normalize_live_state({"vehicles": [{
            "entity_id": 3, "line_id": 7, "current_edge_id": 9999,
            "current_edge_param": .7,
        }]}, NETWORK, MANIFEST, previous, 41)
        self.assertEqual([], result["vehicles"])
        self.assertEqual(0, result["counts"]["position_fallback_vehicles"])

    def test_two_frames_produce_speed_occupancy_and_spacing_diagnosis(self):
        first = {"sampled_at": 10, "vehicles": [{"entity_id": 99, "position": {"x": 10, "y": 0, "z": 0}}]}
        telemetry = {"vehicles": [{"entity_id": 99, "name": "Train", "position": {"x": 20, "y": 1, "z": 0}, "component": {"line": {"value": 7}, "stopIndex": {"value": 0}, "state": {"value": 1}}}], "signal_edge_objects": []}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, first, 12)
        self.assertEqual(1, result["counts"]["rail_vehicles"])
        self.assertAlmostEqual(5.02, result["vehicles"][0]["speed_mps"], places=2)
        self.assertEqual("INSUFFICIENT_TRAINS", result["line_diagnostics"][0]["diagnosis"])

    def test_spacing_flags_bunching(self):
        vehicles = [{"line_id": 7, "position": {"x": 10, "y": 0}}, {"line_id": 7, "position": {"x": 20, "y": 0}}]
        self.assertEqual("POSSIBLE_BUNCHING", line_diagnostics(MANIFEST["lines"], vehicles)[0]["diagnosis"])

    def test_native_zero_speedup_marks_simulation_paused(self):
        telemetry = {"vehicles": [], "simulation_clock": {"speedup": 0, "update_count": 10}}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, None, 1)
        self.assertEqual("PAUSED", result["simulation"]["status"])
        self.assertFalse(result["simulation"]["analysis_allowed"])
        self.assertEqual(0, result["simulation"]["speed_multiplier"])

    def test_positive_speedup_and_update_delta_reports_multiplier(self):
        previous = {"sampled_at": 1, "vehicles": [], "simulation": {"clock": {"update_count": 10, "game_time": 100}}}
        telemetry = {"vehicles": [], "simulation_clock": {"speedup": 2, "update_count": 12, "game_time": 120}}
        result = normalize_live_state(telemetry, NETWORK, MANIFEST, previous, 2)
        self.assertEqual("RUNNING", result["simulation"]["status"])
        self.assertTrue(result["simulation"]["analysis_allowed"])
        self.assertEqual(2, result["simulation"]["speed_multiplier"])


if __name__ == "__main__":
    unittest.main()
