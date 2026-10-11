import unittest

from tpf2_mcp.infrastructure_speed import (
    TURNOUT_PROFILES, build_infrastructure_speed_profile, compile_vehicle_speed_leases,
)


NETWORK = {
    "nodes": [
        {"entity_id": 1, "position": {"x": 0, "y": 0}},
        {"entity_id": 2, "position": {"x": -100, "y": 0}},
        {"entity_id": 3, "position": {"x": 100, "y": 0}},
        {"entity_id": 4, "position": {"x": 80, "y": 40}},
    ],
    "edges": [
        {"entity_id": 10, "node0": 1, "node1": 2, "speed_limit_mps": 55.5556},
        {"entity_id": 11, "node0": 1, "node1": 3, "speed_limit_mps": 55.5556},
        {"entity_id": 12, "node0": 1, "node1": 4, "speed_limit_mps": 55.5556},
    ],
    "stations": [{"entity_id": 20, "name": "武汉站", "center": {"x": 20, "y": 0},
                  "terminals": [{"platform_edge_ids": [12]}]}],
    "lines": [{"entity_id": 30, "route_edge_ids": [10, 12]}],
}


class InfrastructureSpeedTests(unittest.TestCase):
    def test_official_turnout_profile_values_are_preserved(self):
        self.assertEqual(30, TURNOUT_PROFILES["9"]["passenger_kmh"])
        self.assertEqual(45, TURNOUT_PROFILES["12-330"]["passenger_kmh"])
        self.assertEqual(80, TURNOUT_PROFILES["18-860"]["passenger_kmh"])
        self.assertEqual(140, TURNOUT_PROFILES["30"]["passenger_kmh"])
        self.assertEqual(90, TURNOUT_PROFILES["30"]["freight_kmh"])

    def test_switch_straight_pair_keeps_track_limit_and_branch_is_capped(self):
        profile = build_infrastructure_speed_profile(NETWORK)
        turnout = profile["turnouts"][0]
        self.assertEqual([10, 11], turnout["straight_edge_ids"])
        self.assertEqual([12], turnout["lateral_edge_ids"])
        limits = {item["edge_id"]: item for item in profile["edge_limits"]}
        self.assertNotIn(10, limits)
        self.assertEqual(45, limits[12]["speed_kmh"])
        self.assertEqual("PLATFORM_TRACK", limits[12]["kind"])

    def test_node_profile_override_changes_lateral_cap(self):
        profile = build_infrastructure_speed_profile(
            NETWORK, {"turnout_nodes": {"1": {"profile": "18-860"}}}, platform_kmh=120
        )
        limit = next(item for item in profile["edge_limits"] if item["edge_id"] == 12)
        self.assertEqual(80, limit["speed_kmh"])
        self.assertEqual("USER_TURNOUT_PROFILE", limit["evidence"])

    def test_vehicle_lease_uses_route_intersection(self):
        profile = build_infrastructure_speed_profile(NETWORK)
        live = {"vehicles": [{"entity_id": 40, "line_id": 30, "approaching_station": True}]}
        leases = compile_vehicle_speed_leases(profile, NETWORK, live, 1000)
        self.assertEqual(1, len(leases))
        self.assertEqual([12], leases[0]["edge_ids"])
        self.assertEqual(45, leases[0]["speed_kmh"])


if __name__ == "__main__":
    unittest.main()
