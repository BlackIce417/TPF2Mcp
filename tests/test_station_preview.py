import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.station_preview import build_station_platforms, build_station_previews, write_station_previews


class StationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.network = {
            "save_id": "save-a", "source_status": "ENGINE_OBSERVED",
            "nodes": [
                {"entity_id": 1, "position": {"x": -100, "y": 0, "z": 0}},
                {"entity_id": 2, "position": {"x": 0, "y": 0, "z": 0}},
                {"entity_id": 3, "position": {"x": 100, "y": 0, "z": 0}},
                {"entity_id": 4, "position": {"x": 0, "y": 100, "z": 0}},
                {"entity_id": 5, "position": {"x": 2000, "y": 0, "z": 0}},
                {"entity_id": 6, "position": {"x": 2100, "y": 0, "z": 0}},
            ],
            "edges": [
                {"entity_id": 10, "node0": 1, "node1": 2},
                {"entity_id": 11, "node0": 2, "node1": 3},
                {"entity_id": 12, "node0": 2, "node1": 4},
                {"entity_id": 13, "node0": 5, "node1": 6},
            ],
            "stations": [{
                "entity_id": 20, "name": "测试站", "center": {"x": 0, "y": 0},
                "bounds": {"min": {"x": -80, "y": -20}, "max": {"x": 80, "y": 20}},
                "terminals": [{"terminal_index": 0, "node_id": 2, "cargo": False, "platform_length_m": 160}],
            }],
            "depots": [],
            "grade_separated_crossings": [{
                "position": {"x": 10, "y": 10}, "upper_edge_id": 10, "lower_edge_id": 12,
            }],
            "lines": [{"entity_id": 30, "name": "测试线", "route_edge_ids": [10, 11], "stops": [{"station_group_id": 20}]}],
        }

    def test_builds_one_bounded_physical_preview_per_station(self):
        manifest, previews = build_station_previews(self.network, margin_m=100, minimum_span_m=400, generated_at=7)

        preview = previews[20]
        self.assertEqual(1, manifest["station_count"])
        self.assertEqual("save-a", preview["save_id"])
        self.assertEqual("ENGINE_OBSERVED_STATION_PHYSICAL_PREVIEW", preview["diagram_type"])
        self.assertEqual(1, preview["counts"]["switch_nodes"])
        self.assertEqual(3, next(node for node in preview["nodes"] if node["entity_id"] == 2)["degree"])
        self.assertEqual([30], [line["entity_id"] for line in preview["lines"]])
        self.assertNotIn("route_edge_ids", preview["lines"][0])
        self.assertNotIn(13, [edge["entity_id"] for edge in preview["edges"]])
        self.assertEqual(1, preview["counts"]["grade_separated_crossings"])
        self.assertEqual(1, len(preview["grade_separated_crossings"]))

    def test_oriented_scope_uses_outer_throats_and_siding_plus_fifty_metres(self):
        nodes = [
            {"entity_id": index, "position": {"x": x, "y": y, "z": 0}}
            for index, (x, y) in enumerate((
                (-200, 0), (-130, 0), (-100, 0), (100, 0), (140, 0), (200, 0),
                (-100, 20), (100, 20), (0, 80), (100, 80),
            ), 1)
        ]
        edges = [
            {"entity_id": edge_id, "node0": node0, "node1": node1}
            for edge_id, node0, node1 in (
                (20, 1, 2), (21, 2, 3), (10, 3, 4), (22, 4, 5), (23, 5, 6),
                (24, 2, 7), (25, 7, 8), (26, 8, 5), (30, 9, 10),
            )
        ]
        network = {
            "save_id": "oriented", "source_status": "ENGINE_OBSERVED",
            "nodes": nodes, "edges": edges, "depots": [], "lines": [],
            "stations": [{
                "entity_id": 40, "name": "方向站", "center": {"x": 0, "y": 0},
                "terminals": [{
                    "terminal_index": 0, "node_id": 3, "cargo": False,
                    "platform_edge_ids": [10], "platform_length_m": 200,
                    "platform_centerline": [[-100, 0], [100, 0]],
                    "operating_track_centerline": [[-100, 0], [100, 0]],
                }],
            }],
        }

        _, previews = build_station_previews(network, generated_at=10)
        preview = previews[40]

        self.assertEqual("PLATFORM_SIDING_THROAT_ORIENTED_RECTANGLE_DERIVED", preview["scope"]["source"])
        self.assertEqual({"min": -180.0, "max": 190.0}, preview["scope"]["along"])
        self.assertEqual(-50.0, min(point["y"] for point in preview["scope"]["polygon"]))
        self.assertEqual(70.0, max(point["y"] for point in preview["scope"]["polygon"]))
        self.assertEqual(2, preview["scope"]["relevant_switch_count"])
        self.assertNotIn(30, {edge["entity_id"] for edge in preview["edges"]})

    def test_writer_removes_only_stale_station_payloads_and_publishes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "station-999.json").write_text("{}", encoding="utf-8")
            (output / "notes.txt").write_text("keep", encoding="utf-8")

            manifest = write_station_previews(self.network, output, generated_at=8)

            self.assertEqual(1, manifest["station_count"])
            self.assertTrue((output / "station-20.json").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertFalse((output / "station-999.json").exists())
            self.assertTrue((output / "notes.txt").is_file())

    def test_preview_combines_passenger_and_cargo_groups_from_one_construction(self):
        network = {
            "save_id": "save-mixed", "source_status": "ENGINE_OBSERVED",
            "nodes": [], "edges": [], "depots": [],
            "stations": [
                {
                    "entity_id": 20, "name": "混合站", "center": {"x": 0, "y": 0},
                    "bounds": {"min": {"x": -50, "y": -10}, "max": {"x": 50, "y": 0}},
                    "construction_entity_ids": [99],
                    "terminals": [{"terminal_index": 0, "node_id": 1, "cargo": False,
                                   "platform_centerline": [[-40, -5], [40, -5]], "platform_length_m": 80}],
                },
                {
                    "entity_id": 21, "name": "混合站", "center": {"x": 0, "y": 15},
                    "bounds": {"min": {"x": -50, "y": 10}, "max": {"x": 50, "y": 20}},
                    "construction_entity_ids": [99],
                    "terminals": [{"terminal_index": 0, "node_id": 2, "cargo": True,
                                   "platform_centerline": [[-40, 15], [40, 15]], "platform_length_m": 80}],
                },
            ],
            "lines": [{"entity_id": 30, "name": "货运线", "stops": [{"station_group_id": 21}]}],
        }

        _, previews = build_station_previews(network, generated_at=9)
        preview = previews[20]

        self.assertEqual([20, 21], [item["entity_id"] for item in preview["station_groups"]])
        self.assertEqual({False, True}, {item["cargo"] for item in preview["platforms"]})
        self.assertEqual(2, preview["counts"]["terminals"])
        self.assertEqual(2, preview["counts"]["platforms"])
        self.assertEqual([30], [item["entity_id"] for item in preview["lines"]])

    def test_two_close_mod_tracks_remain_two_outer_side_platforms(self):
        station = {
            "center": {"x": 50, "y": 2.5},
            "terminals": [
                {"station_index": 0, "terminal_index": 0, "node_id": 1, "cargo": False,
                 "platform_length_m": 100, "platform_centerline": [[0, 0], [100, 0]]},
                {"station_index": 0, "terminal_index": 1, "node_id": 2, "cargo": False,
                 "platform_length_m": 100, "platform_centerline": [[100, 5], [0, 5]]},
            ],
        }

        platforms = build_station_platforms(station)

        self.assertEqual(2, len(platforms))
        self.assertTrue(all(item["platform_kind"] == "SIDE_OR_SINGLE_FACE" for item in platforms))
        self.assertTrue(all(item["platform_width_units"] == 1 for item in platforms))
        self.assertLess(platforms[0]["platform_centerline"][0][1], 0)
        self.assertGreater(platforms[1]["platform_centerline"][0][1], 5)

    def test_large_gap_between_inner_tracks_becomes_one_double_width_island(self):
        station = {
            "center": {"x": 50, "y": 12.5},
            "terminals": [
                {"terminal_index": 0, "cargo": False, "platform_centerline": [[0, 0], [100, 0]]},
                {"terminal_index": 1, "cargo": False, "platform_centerline": [[100, 5], [0, 5]]},
                {"terminal_index": 2, "cargo": False, "platform_centerline": [[0, 20], [100, 20]]},
                {"terminal_index": 3, "cargo": False, "platform_centerline": [[100, 25], [0, 25]]},
            ],
        }

        platforms = build_station_platforms(station)

        self.assertEqual(3, len(platforms))
        self.assertEqual(["SIDE_OR_SINGLE_FACE", "ISLAND", "SIDE_OR_SINGLE_FACE"],
                         [item["platform_kind"] for item in platforms])
        self.assertEqual([1, 2, 1], [item["platform_width_units"] for item in platforms])
        self.assertEqual([1, 2], [face["terminal_index"] for face in platforms[1]["terminal_faces"]])
        self.assertTrue(all(abs(point[1] - 12.5) < 1e-6 for point in platforms[1]["platform_centerline"]))

    def test_widely_separated_mod_tracks_are_offset_as_two_side_platforms(self):
        station = {
            "center": {"x": 50, "y": 7.5},
            "terminals": [
                {"terminal_index": 0, "cargo": False, "platform_centerline": [[0, 0], [100, 0]]},
                {"terminal_index": 1, "cargo": False, "platform_centerline": [[100, 15], [0, 15]]},
            ],
        }

        platforms = build_station_platforms(station)

        self.assertEqual(2, len(platforms))
        self.assertTrue(all(item["platform_kind"] == "SIDE_OR_SINGLE_FACE" for item in platforms))
        self.assertTrue(all(item["platform_geometry_source"] == "UNPAIRED_TERMINAL_SIDE_OFFSET_DERIVED" for item in platforms))
        self.assertLess(platforms[0]["platform_centerline"][0][1], 0)
        self.assertGreater(platforms[1]["platform_centerline"][0][1], 15)

    def test_explicit_modular_faces_pointing_into_gap_form_an_island(self):
        station = {
            "center": {"x": 50, "y": 12.5},
            "terminals": [
                {"terminal_index": 0, "cargo": False,
                 "operating_track_centerline": [[0, 0], [100, 0]],
                 "platform_centerline": [[0, -5], [100, -5]],
                 "platform_geometry_source": "MODULAR_TERMINAL_TAG_SIDE_DERIVED"},
                {"terminal_index": 1, "cargo": False,
                 "operating_track_centerline": [[100, 5], [0, 5]],
                 "platform_centerline": [[100, 10], [0, 10]],
                 "platform_geometry_source": "MODULAR_TERMINAL_TAG_SIDE_DERIVED"},
                {"terminal_index": 2, "cargo": False,
                 "operating_track_centerline": [[0, 20], [100, 20]],
                 "platform_centerline": [[0, 15], [100, 15]],
                 "platform_geometry_source": "MODULAR_TERMINAL_TAG_SIDE_DERIVED"},
                {"terminal_index": 3, "cargo": False,
                 "operating_track_centerline": [[100, 25], [0, 25]],
                 "platform_centerline": [[100, 30], [0, 30]],
                 "platform_geometry_source": "MODULAR_TERMINAL_TAG_SIDE_DERIVED"},
            ],
        }

        platforms = build_station_platforms(station)

        self.assertEqual(3, len(platforms))
        self.assertEqual("ISLAND", platforms[1]["platform_kind"])
        self.assertEqual([1, 2], [face["terminal_index"] for face in platforms[1]["terminal_faces"]])


if __name__ == "__main__":
    unittest.main()
