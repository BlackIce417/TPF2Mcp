import unittest

from tpf2_mcp.congestion_advisor import CongestionAdvisor


NETWORK = {
    "stations": [
        {"entity_id": 1, "name": "汉口", "terminals": [{}, {}]},
        {"entity_id": 2, "name": "武昌", "terminals": [{}, {}]},
    ],
    "lines": [{"entity_id": 10, "name": "汉口-武昌", "stops": [
        {"station_group_id": 1}, {"station_group_id": 2},
    ]}],
}
LIVE = {
    "vehicles": [
        {"entity_id": 100, "line_id": 10, "stop_index": 1, "approaching_station": True, "speed_kmh": 0},
        {"entity_id": 101, "line_id": 10, "stop_index": 1, "approaching_station": True, "speed_kmh": 4},
    ],
    "line_diagnostics": [{"line_id": 10, "diagnosis": "POSSIBLE_BUNCHING", "minimum_spacing_m": 80}],
    "line_block_occupancy": [{"line_id": 10, "occupied_blocks": 3, "total_blocks": 10, "occupancy_ratio": .3}],
}


class CongestionAdvisorTests(unittest.TestCase):
    def test_requires_persistence_then_emits_named_templates_without_duplicates(self):
        advisor = CongestionAdvisor(minimum_duration_seconds=10, minimum_samples=3)
        self.assertEqual([], advisor.sample(NETWORK, LIVE, now=100))
        self.assertEqual([], advisor.sample(NETWORK, LIVE, now=105))
        result = advisor.sample(NETWORK, LIVE, now=111)
        templates = {item["template"] for item in result}
        self.assertIn("STATION_THROAT_CONGESTION", templates)
        self.assertIn("PLATFORM_SATURATION", templates)
        self.assertIn("SECTION_CONGESTION", templates)
        self.assertEqual(len(result), len({item["evidence_key"] for item in result}))
        self.assertTrue(any("汉口—武昌区间拥堵严重" == item["title"] for item in result))

    def test_clears_episode_when_condition_disappears(self):
        advisor = CongestionAdvisor(0, 1)
        self.assertTrue(advisor.sample(NETWORK, LIVE, now=100))
        cleared = {**LIVE, "vehicles": [], "line_block_occupancy": []}
        self.assertEqual([], advisor.sample(NETWORK, cleared, now=101))
        self.assertTrue(advisor.sample(NETWORK, LIVE, now=102))
        item = next(value for value in advisor.sample(NETWORK, LIVE, now=103)
                    if value["template"] == "STATION_THROAT_CONGESTION")
        self.assertEqual(1, item["duration_seconds"])

    def test_low_speed_turnout_template_uses_real_station_name(self):
        advisor = CongestionAdvisor(0, 1)
        profile = {"turnouts": [{"station_name": "武昌", "side_speed_kmh": 45}]}
        result = advisor.sample(NETWORK, LIVE, profile, now=100)
        item = next(value for value in result if value["template"] == "TURNOUT_SPEED_BOTTLENECK")
        self.assertEqual("武昌站侧向道岔限速成为瓶颈", item["title"])


if __name__ == "__main__":
    unittest.main()
