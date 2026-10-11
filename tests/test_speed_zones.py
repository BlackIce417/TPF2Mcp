import unittest

from tpf2_mcp.speed_zones import map_chainage_zone


NETWORK = {"nodes": [
    {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
    {"entity_id": 2, "position": {"x": 1000, "y": 0, "z": 0}},
    {"entity_id": 3, "position": {"x": 2000, "y": 0, "z": 0}},
    {"entity_id": 4, "position": {"x": 3000, "y": 0, "z": 0}},
], "edges": [
    {"entity_id": 10, "node0": 1, "node1": 2}, {"entity_id": 11, "node0": 2, "node1": 3},
    {"entity_id": 12, "node0": 3, "node1": 4},
], "lines": [{"entity_id": 7, "route_edge_ids": [10, 11, 12]}]}


class SpeedZoneTests(unittest.TestCase):
    def test_maps_partial_chainage_to_ordered_edges(self):
        zone = map_chainage_zone(NETWORK, 7, .5, 2.2, 60, 99)
        self.assertEqual([10, 11, 12], zone["edge_ids"])
        self.assertEqual(.5, zone["segments"][0]["from_param"])
        self.assertEqual(.2, zone["segments"][-1]["to_param"])
        self.assertAlmostEqual(16.666667, zone["speed_mps"])

    def test_reverse_chainage_reverses_edge_order_and_rejects_overrun(self):
        self.assertEqual([12], map_chainage_zone(NETWORK, 7, 0, .5, 60, 99, "REVERSE")["edge_ids"])
        with self.assertRaises(ValueError):
            map_chainage_zone(NETWORK, 7, 2, 4, 60, 99)
