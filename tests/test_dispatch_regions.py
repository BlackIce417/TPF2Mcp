from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server/src"))
from tpf2_mcp.dispatch_regions import build_region_view, current_region_view


def fixture():
    network = {"save_id": "test-save", "bounds": {"min": {"x": 0, "y": -50}, "max": {"x": 200, "y": 50}},
               "nodes": [{"entity_id": i, "position": {"x": x, "y": 0, "z": 0}} for i, x in [(1, 0), (2, 100), (3, 200)]],
               "edges": [{"entity_id": 11, "node0": 1, "node1": 2}, {"entity_id": 12, "node0": 2, "node1": 3}],
               "stations": [{"entity_id": 101}, {"entity_id": 102}]}
    territories = {"save_id": "test-save", "topology_sha256": "hash", "topology_generation": 100, "created_at": "now",
                   "regions": {"A": {"name": "甲区", "color": "#123456", "track_km": .05},
                               "B": {"name": "乙区", "color": "#654321", "track_km": .15}},
                   "segments": [{"edge_id": 11, "start": 0, "end": .5, "region": "A"},
                                {"edge_id": 11, "start": .5, "end": 1, "region": "B"},
                                {"edge_id": 12, "start": 0, "end": 1, "region": "B"}],
                   "stations": [{"entity_id": 101, "name": "甲站", "region": "A", "center": {"x": 0, "y": 0}},
                                {"entity_id": 102, "name": "乙站", "region": "B", "center": {"x": 200, "y": 0}}],
                   "boundaries": [{"regions": ["A", "B"], "position": {"x": 50, "y": 0, "z": 0}}],
                   "coverage": {"edges": 2, "unassigned_edges": 0}, "depots": [], "unseeded_components": []}
    anchors = {"save_id": "test-save", "anchors": [{"anchor_id": "fixed-id", "label": "B001",
                "position": {"x": 50, "y": 0, "z": 0}, "negative_region": "A", "positive_region": "B",
                "calibration": {"status": "PENDING_DIRECTIONAL_CALIBRATION"}}]}
    return territories, anchors, network


class DispatchRegionTests(unittest.TestCase):
    def test_compile_retains_stations_and_fixed_coordinates_without_runtime_internals(self):
        view = build_region_view(*fixture(), "hash")
        self.assertEqual([1, 1], [r["station_count"] for r in view["regions"]])
        self.assertEqual([1, 1], [len(r["overview_segments"]) for r in view["regions"]])
        self.assertEqual({(0.0, 0.0), (50.0, 0.0)},
                         {tuple(point) for point in view["regions"][0]["overview_segments"][0]})
        self.assertEqual({(50.0, 0.0), (200.0, 0.0)},
                         {tuple(point) for point in view["regions"][1]["overview_segments"][0]})
        self.assertEqual([[11, 0, .5, "A"], [11, .5, 1, "B"], [12, 0, 1, "B"]],
                         view["track_intervals"])
        self.assertEqual("fixed-id", view["anchors"][0]["anchor_id"])
        self.assertEqual({"x": 50, "y": 0, "z": 0}, view["anchors"][0]["position"])
        self.assertEqual("PENDING_DIRECTIONAL_CALIBRATION", view["anchors"][0]["status"])
        self.assertNotIn("node_owners", view)
        self.assertNotIn("segments", view)

    def test_rejects_overlap_gap_and_missing_track(self):
        for mutation in ("gap", "overlap", "missing"):
            with self.subTest(mutation=mutation):
                draft, anchors, network = fixture()
                if mutation == "missing": draft["segments"].pop()
                else: draft["segments"][1]["start"] = .6 if mutation == "gap" else .4
                with self.assertRaises(ValueError): build_region_view(draft, anchors, network, "hash")

    def test_rejects_wrong_save_or_changed_geometry(self):
        draft, anchors, network = fixture()
        with self.assertRaises(ValueError): build_region_view(draft, anchors, network, "changed")
        anchors["save_id"] = "other"
        with self.assertRaises(ValueError): build_region_view(draft, anchors, network, "hash")

    def test_new_signal_cannot_move_fixed_boundary_silently(self):
        draft, anchors, network = fixture()
        draft["boundaries"][0]["position"]["x"] = 80
        with self.assertRaisesRegex(ValueError, "fixed anchors"):
            build_region_view(draft, anchors, network, "hash")

    def test_rejects_unanchored_or_duplicate_boundary(self):
        draft, anchors, network = fixture()
        draft["boundaries"].append(deepcopy(draft["boundaries"][0]))
        with self.assertRaisesRegex(ValueError, "unanchored"):
            build_region_view(draft, anchors, network, "hash")
        draft, anchors, network = fixture()
        anchors["anchors"].append(deepcopy(anchors["anchors"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_region_view(draft, anchors, network, "hash")

    def test_view_scope_rejects_other_save_and_stale_topology_without_leaking_geometry(self):
        view = build_region_view(*fixture(), "hash")
        manifest = {"save_id": "test-save", "generated_at": 100}
        self.assertIs(view, current_region_view(view, "test-save", manifest))
        for save, generation, error in [("other", 100, "REGIONS_SAVE_MISMATCH"), ("test-save", 101, "REGIONS_TOPOLOGY_STALE")]:
            value = current_region_view(view, save, {"save_id": save, "generated_at": generation})
            self.assertEqual(error, value["error"])
            self.assertNotIn("regions", value)
        self.assertEqual("REGIONS_NOT_CONFIGURED", current_region_view({}, "test-save", manifest)["error"])


if __name__ == "__main__":
    unittest.main()
