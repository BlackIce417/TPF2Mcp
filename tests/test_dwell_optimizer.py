import unittest

from tpf2_mcp.dwell_optimizer import optimize_dwell_times


MANIFEST = {
    "stations": [
        {"entity_id": 100, "name": "A", "terminals": [{"station_index": 0, "terminal_index": 0, "cargo": False, "platform_edge_ids": [10]}]},
        {"entity_id": 200, "name": "B", "terminals": [{"station_index": 0, "terminal_index": 0, "cargo": False, "platform_edge_ids": [20]}]},
        {"entity_id": 300, "name": "Cargo", "terminals": [{"station_index": 0, "terminal_index": 0, "cargo": True, "platform_edge_ids": [30]}]},
    ],
    "lines": [
        {"entity_id": 1, "name": "Passenger", "stops": [{"sequence_index": 0, "station_group_id": 100, "station_index": 0, "terminal_index": 0}, {"sequence_index": 1, "station_group_id": 200, "station_index": 0, "terminal_index": 0}]},
        {"entity_id": 2, "name": "Freight", "stops": [{"sequence_index": 0, "station_group_id": 300, "station_index": 0, "terminal_index": 0}]},
    ],
}
SNAPSHOT = {"lines": [
    {"entity_id": 1, "frequency_seconds": 300, "throughput": 600, "stops": [{"index": 0, "policy": {"load_mode": 0, "min_waiting_time": 0, "max_waiting_time": 180}}, {"index": 1, "policy": {"load_mode": 0, "min_waiting_time": 0, "max_waiting_time": 180}}]},
    {"entity_id": 2, "frequency_seconds": 600, "throughput": 200, "stops": [{"index": 0, "policy": {"load_mode": 2, "min_waiting_time": 0, "max_waiting_time": 600}}]},
]}


class DwellOptimizerTests(unittest.TestCase):
    def test_recommends_passenger_cap_and_preserves_cargo(self):
        frames = []
        for sampled_at in range(0, 66, 5):
            frames.append({"sampled_at": sampled_at, "simulation": {"status": "RUNNING", "analysis_allowed": True, "speed_multiplier": 1}, "vehicles": [
                {"entity_id": 11, "line_id": 1, "edge_id": 10, "stop_index": 0, "speed_kmh": 0, "approaching_station": True},
                {"entity_id": 12, "line_id": 1, "edge_id": 99, "stop_index": 1, "speed_kmh": 0, "approaching_station": True},
                {"entity_id": 21, "line_id": 2, "edge_id": 30, "stop_index": 0, "speed_kmh": 0, "approaching_station": True},
            ], "line_diagnostics": [{"line_id": 1, "diagnosis": "POSSIBLE_BUNCHING", "minimum_spacing_m": 100, "target_spacing_m": 1000}]})
        result = optimize_dwell_times(frames, MANIFEST, SNAPSHOT)
        self.assertEqual(2, result["counts"]["recommendations"])
        self.assertTrue(all(item["line_id"] == 1 for item in result["recommendations"]))
        self.assertTrue(all(item["recommended_policy"]["load_mode"] == 0 for item in result["recommendations"]))
        self.assertTrue(all(item["recommended_policy"]["max_waiting_time"] == 45 for item in result["recommendations"]))
        self.assertFalse(next(item for item in result["recommendations"] if item["stop_index"] == 0)["apply_ready"])
        self.assertTrue(next(item for item in result["recommendations"] if item["stop_index"] == 1)["apply_ready"])
        self.assertTrue(result["safety"]["cargo_full_load_policies_preserved"])

    def test_short_observation_is_not_apply_ready(self):
        frames = [{"sampled_at": 0, "simulation": {"analysis_allowed": True, "speed_multiplier": 1}, "vehicles": []}, {"sampled_at": 10, "simulation": {"analysis_allowed": True, "speed_multiplier": 1}, "vehicles": []}]
        result = optimize_dwell_times(frames, MANIFEST, SNAPSHOT)
        self.assertTrue(result["recommendations"])
        self.assertFalse(any(item["apply_ready"] for item in result["recommendations"]))

    def test_paused_observation_is_rejected_completely(self):
        frames = [{"sampled_at": 0, "simulation": {"status": "PAUSED", "analysis_allowed": False, "speed_multiplier": 0}, "vehicles": []}]
        result = optimize_dwell_times(frames, MANIFEST, SNAPSHOT)
        self.assertEqual("ANALYSIS_BLOCKED_SIMULATION_INACTIVE", result["source_status"])
        self.assertEqual(0, result["counts"]["recommendations"])


if __name__ == "__main__":
    unittest.main()
