import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "export-rail-network-map.py"
SPEC = importlib.util.spec_from_file_location("export_rail_network_map", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RailNetworkMapTests(unittest.TestCase):
    def test_rail_depot_is_exported_with_derived_track_connection(self):
        source = {
            "status": "OK", "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 0}},
            ],
            "edges": [{"entity_id": 10, "node0": 1, "node1": 2}],
            "stations": [], "lines": [],
            "depots": [{
                "entity_id": 50, "name": "Train depot", "center": {"x": 40, "y": 10, "z": 0},
                "rail_candidate": True, "rail_classification_source": "CONSTRUCTION_FILE_CLASSIFIED",
                "assigned_vehicle_ids": [7, 8], "rail_assigned_vehicle_ids": [7],
                "parked_vehicle_ids": [8], "parked_vehicle_count_source": "TRANSPORT_VEHICLE_SYSTEM_GET_DEPOT_VEHICLES",
            }],
            "counts": {"nodes": 2, "edges": 1, "stations": 0, "lines": 0, "depots": 1},
        }
        result = MODULE.prepare(source)
        self.assertEqual(1, result["counts"]["rail_depots"])
        depot = result["depots"][0]
        self.assertEqual(10, depot["nearest_edge_id"])
        self.assertEqual(10.0, depot["nearest_edge_distance_m"])
        self.assertEqual({"x": 40.0, "y": 0.0, "z": 0.0}, depot["track_connection_position"])
        self.assertEqual(2, depot["assigned_vehicle_count"])
        self.assertEqual(1, depot["parked_vehicle_count"])

    def test_routes_line_over_observed_physical_edges(self):
        source = {
            "status": "OK",
            "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 200, "y": 0, "z": 0}},
            ],
            "edges": [
                {"entity_id": 10, "node0": 1, "node1": 2, "track_type": 1},
                {"entity_id": 11, "node0": 2, "node1": 3, "track_type": 1},
            ],
            "stations": [
                {"entity_id": 20, "name": "A", "center": {"x": 0, "y": 0, "z": 0}, "terminals": []},
                {"entity_id": 21, "name": "B", "center": {"x": 200, "y": 0, "z": 0}, "terminals": []},
            ],
            "lines": [{"entity_id": 30, "name": "L", "stops": [{"node_id": 1}, {"node_id": 3}]}],
            "counts": {"nodes": 3, "edges": 2, "stations": 2, "lines": 1},
        }

        result = MODULE.prepare(source)

        self.assertEqual([10, 11], result["lines"][0]["route_edge_ids"])
        self.assertTrue(all(edge["line_used"] for edge in result["edges"]))
        self.assertEqual(1, result["counts"]["routed_lines"])
        self.assertEqual(0, result["counts"]["disconnected_segments"])

    def test_reports_disconnected_stop_pair(self):
        source = {
            "status": "OK", "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 1, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 5, "y": 0, "z": 0}},
            ],
            "edges": [{"entity_id": 10, "node0": 1, "node1": 2}],
            "stations": [],
            "lines": [{"entity_id": 30, "name": "L", "stops": [{"node_id": 1}, {"node_id": 3}]}],
            "counts": {"nodes": 3, "edges": 1, "stations": 0, "lines": 1},
        }

        result = MODULE.prepare(source)

        self.assertEqual([], result["lines"][0]["route_edge_ids"])
        self.assertEqual(1, result["counts"]["disconnected_segments"])

    def test_physical_overview_keeps_unserved_station_connected(self):
        source = {
            "status": "OK", "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 200, "y": 0, "z": 0}},
            ],
            "edges": [
                {"entity_id": 10, "node0": 1, "node1": 2, "track_type": 1},
                {"entity_id": 11, "node0": 2, "node1": 3, "track_type": 1},
            ],
            "stations": [{"entity_id": 20, "name": "Unserved", "terminals": [{"node_id": 2}]}],
            "lines": [],
            "counts": {"nodes": 3, "edges": 2, "stations": 1, "lines": 0},
        }

        result = MODULE.prepare(source)
        points = [point for segment in result["physical_overview_segments"] for point in segment]

        self.assertIn([100, 0], points)
        self.assertEqual(2, len(result["physical_overview_segments"]))

    def test_builds_lightweight_spatial_tiles(self):
        result = {
            "diagram_type": "ENGINE_OBSERVED_GLOBAL_RAIL_GRAPH", "source_status": "ENGINE_OBSERVED",
            "bounds": {"min": {"x": 0, "y": 0}, "max": {"x": 4000, "y": 1000}},
            "nodes": [
                {"entity_id": 1, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 1000, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 3000, "y": 0, "z": 0}},
                {"entity_id": 4, "position": {"x": 4000, "y": 0, "z": 0}},
            ],
            "edges": [
                {"entity_id": 10, "node0": 1, "node1": 2},
                {"entity_id": 11, "node0": 3, "node1": 4},
            ],
            "stations": [],
            "lines": [{"entity_id": 30, "route_edge_ids": [10, 11], "overview_segments": [[[0, 0], [4000, 0]]]}],
            "counts": {"nodes": 4, "edges": 2, "stations": 0, "lines": 1},
            "routing": {}, "limitations": [],
        }

        manifest, tiles = MODULE.build_manifest_and_tiles(result, 2000)

        self.assertEqual(2, len(tiles))
        self.assertNotIn("route_edge_ids", manifest["lines"][0])
        self.assertNotIn("nodes", manifest)
        self.assertEqual(2, len(manifest["tiles"]))

    def test_platform_chain_stops_before_switch_throat(self):
        edges = {
            9: {"entity_id": 9, "node0": 0, "node1": 1, "track_type": 5},
            10: {"entity_id": 10, "node0": 1, "node1": 2, "track_type": 5},
            11: {"entity_id": 11, "node0": 2, "node1": 3, "track_type": 5},
            12: {"entity_id": 12, "node0": 3, "node1": 4, "track_type": 5},
            13: {"entity_id": 13, "node0": 3, "node1": 5, "track_type": 5},
        }
        adjacency = {
            0: [(1, 9, 20.0), (6, 14, 20.0), (7, 15, 20.0)],
            1: [(0, 9, 20.0), (2, 10, 50.0)],
            2: [(1, 10, 50.0), (3, 11, 60.0)],
            3: [(2, 11, 60.0), (4, 12, 20.0), (5, 13, 20.0)],
            4: [(3, 12, 20.0)], 5: [(3, 13, 20.0)],
            6: [(0, 14, 20.0)], 7: [(0, 15, 20.0)],
        }

        edge_ids, length, node_ids = MODULE.platform_chain(2, adjacency, edges)

        self.assertEqual([10], edge_ids)
        self.assertEqual(50.0, length)
        self.assertEqual([1, 2], node_ids)

    def test_clips_freestyle_platform_chain_to_station_bounds(self):
        points = [[-500, 0], [-100, 0], [0, 0], [100, 0], [500, 0]]
        bounds = {"min": {"x": -120, "y": -15}, "max": {"x": 120, "y": 15}}

        clipped = MODULE.clip_polyline_to_bounds(points, bounds, {"x": 0, "y": 0})

        self.assertEqual([[-120.0, 0.0], [-100.0, 0.0], [0.0, 0.0], [100.0, 0.0], [120.0, 0.0]], clipped)
        self.assertEqual(240.0, sum(MODULE.math.dist(a, b) for a, b in zip(clipped, clipped[1:])))

    def test_platform_centerline_samples_engine_curve(self):
        nodes = {1: {"x": 0, "y": 0, "z": 0}, 2: {"x": 100, "y": 0, "z": 0}}
        edges = {10: {
            "entity_id": 10, "node0": 1, "node1": 2,
            "tangent0": {"x": 100, "y": 100, "z": 0},
            "tangent1": {"x": 100, "y": -100, "z": 0},
        }}

        points = MODULE.sampled_edge_path(1, [10], edges, nodes, steps=4)

        self.assertEqual([0.0, 0.0], points[0])
        self.assertEqual([100.0, 0.0], points[-1])
        self.assertGreater(points[2][1], 20)

    def test_freestyle_station_is_identified_from_observed_track_resource(self):
        source = {
            "status": "OK", "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": -100, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 100, "y": 0, "z": 0}},
            ],
            "edges": [
                {"entity_id": 10, "node0": 1, "node1": 2, "track_type": 54,
                 "track_resource_file": "lollo_freestyle_train_station/era_c_passenger_platform_5m.lua", "freestyle_station_track": True},
                {"entity_id": 11, "node0": 2, "node1": 3, "track_type": 54,
                 "track_resource_file": "lollo_freestyle_train_station/era_c_passenger_platform_5m.lua", "freestyle_station_track": True},
            ],
            "stations": [{"entity_id": 20, "name": "Free", "center": {"x": 0, "y": 0},
                          "bounds": {"min": {"x": -80, "y": -10}, "max": {"x": 80, "y": 10}},
                          "terminals": [{"node_id": 2, "position": {"x": 0, "y": 0}}]}],
            "lines": [], "depots": [],
            "counts": {"nodes": 3, "edges": 2, "stations": 1, "lines": 0, "depots": 0},
        }

        result = MODULE.prepare(source)

        self.assertEqual("FREESTYLE_STATION", result["stations"][0]["station_model"])
        self.assertEqual("FREESTYLE_STATION", result["stations"][0]["terminals"][0]["station_model"])
        self.assertEqual("TRACK_TYPE_RESOURCE_FILE_ENGINE_OBSERVED", result["stations"][0]["station_model_source"])

    def test_freestyle_station_is_identified_from_construction_file(self):
        model, source = MODULE.classify_terminal_station_model(
            [], 0, 0, "station/rail/lollo_freestyle_train_station/station.con"
        )
        self.assertEqual("FREESTYLE_STATION", model)
        self.assertEqual("STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED", source)

        model, source = MODULE.classify_terminal_station_model([], 42, 280, "station/rail/modular_station/train_station.con")
        self.assertEqual("OTHER", model)
        self.assertEqual("STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED", source)

    def test_freestyle_platform_model_track_does_not_replace_operating_track(self):
        nodes = [
            {"entity_id": index + 1, "position": {"x": 0, "y": index * 10, "z": 0}}
            for index in range(21)
        ]
        nodes.extend([
            {"entity_id": 100, "position": {"x": 5, "y": -10, "z": 0}},
            {"entity_id": 101, "position": {"x": 5, "y": 0, "z": 0}},
            {"entity_id": 102, "position": {"x": 5, "y": 100, "z": 0}},
            {"entity_id": 103, "position": {"x": 5, "y": 200, "z": 0}},
            {"entity_id": 104, "position": {"x": 5, "y": 210, "z": 0}},
        ])
        model_edges = [
            {"entity_id": 1000 + index, "node0": index + 1, "node1": index + 2, "track_type": 118}
            for index in range(20)
        ]
        operating_edges = [
            {"entity_id": 2000, "node0": 100, "node1": 101, "track_type": 54},
            {"entity_id": 2001, "node0": 101, "node1": 102, "track_type": 54},
            {"entity_id": 2002, "node0": 102, "node1": 103, "track_type": 54},
            {"entity_id": 2003, "node0": 103, "node1": 104, "track_type": 54},
        ]
        source = {
            "status": "OK", "source_status": "ENGINE_OBSERVED", "nodes": nodes,
            "edges": model_edges + operating_edges,
            "stations": [{
                "entity_id": 20, "name": "Freestyle layout", "center": {"x": 2.5, "y": 100},
                "bounds": {"min": {"x": -1, "y": 0}, "max": {"x": 6, "y": 200}},
                "terminals": [{"node_id": 102, "position": {"x": 5, "y": 100}}],
            }],
            "lines": [], "depots": [],
            "counts": {"nodes": 26, "edges": 24, "stations": 1, "lines": 0, "depots": 0},
        }

        result = MODULE.prepare(source)
        terminal = result["stations"][0]["terminals"][0]

        self.assertEqual([2001, 2002], terminal["platform_edge_ids"])
        self.assertEqual(list(range(1000, 1020)), terminal["platform_model_edge_ids"])
        self.assertEqual(118, terminal["platform_model_track_type"])
        self.assertEqual("INVISIBLE_PLATFORM_TRACK_SIGNATURE_DERIVED", terminal["platform_model_source"])
        self.assertTrue(all(point[0] == 0 for point in terminal["platform_centerline"]))
        self.assertEqual("PLATFORM_MODEL_TRACK_CHAIN_DERIVED", terminal["platform_length_source"])
        self.assertEqual("UNKNOWN", terminal["station_model"])
        self.assertEqual({2000, 2001, 2002, 2003}, {edge["entity_id"] for edge in result["edges"]})
        self.assertEqual(20, result["counts"]["platform_model_edges_excluded_from_rail_render"])

    def test_freestyle_platform_chain_keeps_connector_just_outside_construction_bounds(self):
        nodes = {
            1: {"x": 1, "y": 0, "z": 0},
            2: {"x": 1, "y": 40, "z": 0},
            3: {"x": -5, "y": 80, "z": 0},
            4: {"x": 1, "y": 120, "z": 0},
            5: {"x": 1, "y": 160, "z": 0},
        }
        edges = [
            {"entity_id": 100 + index, "node0": index + 1, "node1": index + 2, "track_type": 118}
            for index in range(4)
        ]
        station = {
            "bounds": {"min": {"x": 0, "y": 0}, "max": {"x": 10, "y": 160}},
        }

        chains = MODULE.platform_model_chains(station, edges, nodes, {118})

        self.assertEqual(1, len(chains))
        self.assertEqual([100, 101, 102, 103], chains[0]["edge_ids"])
        self.assertGreater(chains[0]["length_m"], 150)

    def test_micro_segment_signature_does_not_identify_freestyle_station(self):
        model, source = MODULE.classify_terminal_station_model([], 42, 280.0)

        self.assertEqual("UNKNOWN", model)
        self.assertEqual("UNKNOWN", source)

        self.assertEqual(("UNKNOWN", "UNKNOWN"), MODULE.classify_terminal_station_model([], 9, 273.0))

    def test_station_model_ground_truth_is_separate_from_engine_evidence(self):
        result = {"stations": [
            {"entity_id": 1, "center": {"x": 0, "y": 5}, "station_model": "UNKNOWN", "station_model_source": "UNKNOWN",
             "terminals": [{"position": {"x": -2.5, "y": 5}, "platform_centerline": [[-2.5, 0], [-2.5, 10]]}]},
            {"entity_id": 2, "station_model": "UNKNOWN", "station_model_source": "UNKNOWN", "terminals": [{}]},
        ]}

        MODULE.apply_station_model_ground_truth(result, {"stations": [
            {"entity_id": 1, "station_model": "FREESTYLE_STATION", "note": "observed in save",
             "platform_layout": "OUTER_SIDE_OF_TERMINAL_TRACKS", "platform_offset_m": 5},
            {"entity_id": 2, "station_model": "OTHER", "note": "user correction"},
        ]})

        self.assertEqual(("FREESTYLE_STATION", "USER_GROUND_TRUTH"),
                         (result["stations"][0]["station_model"], result["stations"][0]["station_model_source"]))
        self.assertEqual(("OTHER", "USER_GROUND_TRUTH"),
                         (result["stations"][1]["station_model"], result["stations"][1]["station_model_source"]))
        terminal = result["stations"][0]["terminals"][0]
        self.assertEqual([[-2.5, 0], [-2.5, 10]], terminal["operating_track_centerline"])
        self.assertEqual([[-7.5, 0.0], [-7.5, 10.0]], terminal["platform_centerline"])

    def test_modular_terminal_tags_place_side_and_island_platforms(self):
        station = {
            "center": {"x": 7.5, "y": 5},
            "terminals": [
                {"tag": 4, "position": {"x": 0, "y": 5}, "platform_centerline": [[0, 0], [0, 10]]},
                {"tag": 7, "position": {"x": 5, "y": 5}, "platform_centerline": [[5, 0], [5, 10]]},
                {"tag": 8, "position": {"x": 10, "y": 5}, "platform_centerline": [[10, 0], [10, 10]]},
                {"tag": 11, "position": {"x": 15, "y": 5}, "platform_centerline": [[15, 0], [15, 10]]},
            ],
        }

        MODULE.offset_modular_station_platforms(station)

        self.assertEqual([-5.0, 10.0, 5.0, 20.0], [terminal["platform_centerline"][0][0] for terminal in station["terminals"]])
        self.assertTrue(all(terminal["platform_geometry_source"] == "MODULAR_TERMINAL_TAG_SIDE_DERIVED" for terminal in station["terminals"]))

    def test_modular_station_platforms_share_one_longitudinal_span(self):
        station = {
            "center": {"x": 5, "y": 50},
            "terminals": [
                {"platform_centerline": [[0, 0], [0, 100]], "platform_length_m": 100,
                 "platform_length_source": "TERMINAL_CURVE_TO_PRE_SWITCH_NODES"},
                {"platform_centerline": [[10, 20], [10, 80]], "platform_length_m": 60,
                 "platform_length_source": "TERMINAL_CURVE_TO_PRE_SWITCH_NODES"},
            ],
        }

        MODULE.normalize_modular_station_platform_spans(station)

        self.assertEqual([[10.0, 0.0], [10, 20], [10, 80], [10.0, 100.0]], station["terminals"][1]["platform_centerline"])
        self.assertEqual([100, 100], [terminal["platform_length_m"] for terminal in station["terminals"]])
        self.assertTrue(all(terminal["platform_length_source"] == "MODULAR_STATION_SHARED_SPAN_DERIVED"
                            for terminal in station["terminals"]))

    def test_modular_platforms_from_separate_station_groups_can_share_span(self):
        passenger = {"platform_centerline": [[0, 0], [0, 80]], "platform_length_m": 80,
                     "platform_length_source": "TERMINAL_TRACK_CLIPPED_TO_STATION_BOUNDS"}
        cargo = {"platform_centerline": [[10, -10], [10, 90]], "platform_length_m": 100,
                 "platform_length_source": "TERMINAL_CURVE_TO_PRE_SWITCH_NODES"}

        MODULE.normalize_modular_station_platform_spans({"terminals": [passenger, cargo]})

        self.assertEqual([100, 100], [passenger["platform_length_m"], cargo["platform_length_m"]])
        self.assertAlmostEqual(-10, passenger["platform_centerline"][0][1])
        self.assertAlmostEqual(90, passenger["platform_centerline"][-1][1])

    def test_track_loading_terminal_is_not_rendered_as_a_side_platform(self):
        station = {"terminals": [{"platform_centerline": [[0, 0], [0, 10]]}]}

        MODULE.mark_track_loading_terminals(station)

        terminal = station["terminals"][0]
        self.assertEqual([], terminal["platform_centerline"])
        self.assertEqual([[0, 0], [0, 10]], terminal["terminal_hit_centerline"])
        self.assertEqual("TRACK_LOADING_AREA", terminal["platform_render_mode"])
        self.assertEqual("CONSTRUCTION_TERMINAL_LANE_COLOCATED_WITH_TRACK", terminal["platform_geometry_source"])

    def test_engine_station_model_wins_without_skipping_geometry_ground_truth(self):
        result = {"stations": [{
            "entity_id": 2, "center": {"x": 0, "y": 5},
            "station_model": "OTHER", "station_model_source": "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED",
            "terminals": [{
                "station_model": "OTHER", "station_model_source": "STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED",
                "position": {"x": 2.5, "y": 5}, "platform_centerline": [[2.5, 0], [2.5, 10]],
            }],
        }]}

        MODULE.apply_station_model_ground_truth(result, {"stations": [{
            "entity_id": 2, "station_model": "FREESTYLE_STATION",
            "platform_layout": "OUTER_SIDE_OF_TERMINAL_TRACKS", "platform_offset_m": 5,
        }]})

        station, terminal = result["stations"][0], result["stations"][0]["terminals"][0]
        self.assertEqual("OTHER", station["station_model"])
        self.assertEqual("STATION_CONSTRUCTION_FILE_ENGINE_OBSERVED", station["station_model_source"])
        self.assertFalse(station["station_model_ground_truth_match"])
        self.assertEqual([[7.5, 0.0], [7.5, 10.0]], terminal["platform_centerline"])


if __name__ == "__main__":
    unittest.main()
