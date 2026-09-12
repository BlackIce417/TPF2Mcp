import unittest

from tpf2_mcp.overtake_planner import plan_overtakes


class OvertakePlannerTests(unittest.TestCase):
    def test_finds_skip_stop_speed_advantage_but_never_auto_applies(self):
        manifest = {
            "stations": [
                {"entity_id": 1, "terminals": [{"cargo": False}]},
                {"entity_id": 2, "name": "Passing", "terminals": [{"cargo": False}, {"cargo": False}]},
                {"entity_id": 3, "terminals": [{"cargo": False}]},
            ],
            "lines": [
                {"entity_id": 10, "name": "Local", "stops": [{"station_group_id": 1}, {"station_group_id": 2}, {"station_group_id": 3}]},
                {"entity_id": 20, "name": "Express", "stops": [{"station_group_id": 1}, {"station_group_id": 3}]},
            ],
        }
        frames = [{"simulation": {"analysis_allowed": True}, "vehicles": [{"entity_id": 100, "line_id": 10, "speed_kmh": 80}, {"entity_id": 200, "line_id": 20, "speed_kmh": 160}]}]
        detail = {"lines": [{"entity_id": 10, "route_edge_ids": [7]}, {"entity_id": 20, "route_edge_ids": [8]}]}
        manifest["stations"][1]["terminals"][0]["platform_edge_ids"] = [7]
        result = plan_overtakes(frames, manifest, network_detail=detail)
        self.assertEqual(1, result["counts"]["candidates"])
        self.assertFalse(result["candidates"][0]["apply_ready"])
        self.assertTrue(result["candidates"][0]["bypass_path_verified"])

    def test_rejects_single_platform_and_non_skipping_line(self):
        manifest = {"stations": [{"entity_id": value, "terminals": [{"cargo": False}]} for value in (1, 2, 3)], "lines": [{"entity_id": 10, "stops": [{"station_group_id": 1}, {"station_group_id": 2}, {"station_group_id": 3}]}, {"entity_id": 20, "stops": [{"station_group_id": 1}, {"station_group_id": 2}, {"station_group_id": 3}]}]}
        frames = [{"simulation": {"analysis_allowed": True}, "vehicles": [{"entity_id": 100, "line_id": 10, "speed_kmh": 80}, {"entity_id": 200, "line_id": 20, "speed_kmh": 160}]}]
        self.assertEqual([], plan_overtakes(frames, manifest)["candidates"])

    def test_paused_frames_cannot_generate_candidates(self):
        result = plan_overtakes([{"simulation": {"status": "PAUSED", "analysis_allowed": False}, "vehicles": []}], {"stations": [], "lines": []})
        self.assertEqual("ANALYSIS_BLOCKED_SIMULATION_INACTIVE", result["source_status"])


if __name__ == "__main__":
    unittest.main()
