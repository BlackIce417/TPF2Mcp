import unittest

from tpf2_mcp.train_spacing import compile_train_spacing


NETWORK = {
    "nodes": [
        {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
        {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 0}},
        {"entity_id": 3, "position": {"x": 200, "y": 0, "z": 0}},
        {"entity_id": 4, "position": {"x": 300, "y": 0, "z": 0}},
    ],
    "edges": [
        {"entity_id": 10, "node0": 1, "node1": 2},
        {"entity_id": 11, "node0": 2, "node1": 3},
        {"entity_id": 12, "node0": 3, "node1": 4},
    ],
}


def train(vehicle_id, edge_id, edge_index, edge_param, speed, body_x, *, directions=None):
    directions = directions or [True, True, True]
    return {
        "entity_id": vehicle_id, "edge_id": edge_id, "edge_param": edge_param,
        "current_edge_index": edge_index, "speed_mps": speed,
        "path_edge_ids": [10, 11, 12], "path_edge_directions": directions,
        "path_transport_indices": [0, 0, 0], "position_stale": False,
        "footprint_complete": True, "footprint_sampled_at": 1000,
        "brake_decel_mps2": .8, "braking_verified": True,
        "body_samples": [{"position": {"x": x, "y": 0, "z": 0}, "radius_m": 5} for x in body_x],
    }


class TrainSpacingTests(unittest.TestCase):
    def test_nearest_leader_creates_route_bounded_speed_lease(self):
        live = {"sampled_at": 1000, "vehicles": [
            train(1, 10, 0, .8, 20, [70, 80]),
            train(2, 11, 1, .5, 12, [130, 150]),
            train(3, 12, 2, .8, 12, [270, 280]),
        ]}
        result = compile_train_spacing(NETWORK, live, 1020,
                                       {"armed_execution": True}, publishable=True, now=1000)
        lease = next(item for item in result if item.get("kind") == "speed" and item["vehicle_id"] == 1)
        self.assertEqual(2, lease["leader_vehicle_id"])
        self.assertEqual([10, 11], lease["edge_ids"])
        self.assertEqual((0, 1), (lease["path_index_start"], lease["path_index_end"]))
        self.assertLess(lease["speed_kmh"], 72)

    def test_opposite_direction_train_is_not_a_leader(self):
        follower = train(1, 10, 0, .8, 20, [70, 80])
        opposite = train(2, 11, 1, .5, 12, [130, 150], directions=[False, False, False])
        opposite['path_edge_ids'] = [12, 11, 10]
        result = compile_train_spacing(NETWORK, {"sampled_at": 1000, "vehicles": [follower, opposite]}, 1020, now=1000)
        own = next(item for item in result if item["vehicle_id"] == 1)
        self.assertEqual("spacing_clear", own["kind"])
        self.assertEqual("NO_LEADER_ON_ROUTE", own["reason"])

    def test_missing_complete_body_fails_closed(self):
        follower = train(1, 10, 0, .8, 20, [70, 80])
        follower["body_samples"] = []
        result = compile_train_spacing(NETWORK, {"sampled_at": 1000, "vehicles": [follower]}, 1020, now=1000)
        self.assertEqual("COMPLETE_TRAIN_FOOTPRINT_UNAVAILABLE", result[0]["reason"])

    def test_unverified_braking_remains_advisory_when_armed(self):
        follower = train(1, 10, 0, .8, 20, [70, 80])
        follower["braking_verified"] = False
        leader = train(2, 11, 1, .5, 12, [130, 150])
        result = compile_train_spacing(NETWORK, {"sampled_at": 1000, "vehicles": [follower, leader]}, 1020,
                                       {"armed_execution": True}, publishable=True, now=1000)
        own = next(item for item in result if item["vehicle_id"] == 1)
        self.assertEqual("spacing_advisory", own["kind"])

    def test_shadow_never_publishes_a_native_lease(self):
        follower = train(1, 10, 0, .8, 20, [70, 80])
        leader = train(2, 11, 1, .5, 12, [130, 150])
        result = compile_train_spacing(NETWORK, {"sampled_at": 1000, "vehicles": [follower, leader]}, 1020,
                                       {"armed_execution": True}, publishable=False, now=1000)
        own = next(item for item in result if item["vehicle_id"] == 1)
        self.assertEqual("spacing_advisory", own["kind"])

    def test_repeated_physical_edge_rejects_ambiguous_occurrence(self):
        follower = train(1, 10, 0, .8, 30, [70, 80])
        leader = train(2, 10, 2, .5, 12, [40, 50])
        for item in (follower, leader):
            item["path_edge_ids"] = [10, 10, 10]
            item["path_edge_directions"] = [True, False, True]
        result = compile_train_spacing(NETWORK, {"sampled_at": 1000, "vehicles": [follower, leader]}, 1020,
                                       {"armed_execution": True}, publishable=True, now=1000)
        own = next(item for item in result if item["vehicle_id"] == 1)
        self.assertEqual('AMBIGUOUS_PATH_OCCURRENCE', own['reason'])


if __name__ == "__main__":
    unittest.main()
