import json
import unittest
from pathlib import Path

from tpf2_mcp.analytics import NetworkIntelligenceIndex
from tpf2_mcp.snapshot import SnapshotIndex


class NetworkIntelligenceTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures" / "world_snapshot_001.json"
        self.snapshot = SnapshotIndex(json.loads(fixture.read_text(encoding="utf-8")))
        self.snapshot.vehicle_by_id[50]["capacity_total"] = 40
        self.snapshot.vehicle_by_id[51]["capacity_total"] = 60
        self.snapshot.vehicle_by_id[52]["capacity_total"] = 20
        self.snapshot.line_by_id[40].update({"frequency_seconds": 100, "throughput": 180})
        self.snapshot.line_by_id[41].update({"frequency_seconds": 1000, "throughput": 20})
        self.index = NetworkIntelligenceIndex(self.snapshot)

    def test_profile_is_sequence_bound_and_uses_safe_ratios(self):
        profile = self.index.line_profile(40)
        self.assertEqual(1, profile["snapshot_sequence"])
        self.assertEqual(2, profile["topology"]["unique_station_count"])
        self.assertEqual(100, profile["fleet"]["fleet_capacity_total"])
        self.assertEqual(90, profile["derived"]["throughput_per_vehicle"])
        self.assertEqual("UNAVAILABLE", profile["availability"]["load"])

    def test_classification_and_outliers_are_explicit(self):
        classifications = self.index.classify_lines(high_frequency_seconds=120)
        line40 = next(item for item in classifications["results"] if item["line_id"] == 40)
        self.assertTrue(any(item["classification"] == "SIMPLE_SHUTTLE" for item in line40["classifications"]))
        outliers = self.index.line_outliers("frequency_seconds", "percentile", .25)
        self.assertEqual("Statistical outliers, not operating-health conclusions.", outliers["interpretation"])
        self.assertTrue(outliers["results"])

    def test_similarity_hubs_reachability_and_recommendations_are_deterministic(self):
        similar = self.index.similar_lines(40)
        self.assertEqual(["stop_count", "vehicle_count", "frequency_seconds", "throughput", "fleet_capacity_total"], similar["features"])
        profile = self.index.station_profile(31)
        self.assertEqual(2, profile["connectivity"]["line_count"])
        reachability = self.index.reachability()
        self.assertEqual(1, reachability["connected_component_count"])
        self.assertEqual(self.index.recommendations(), self.index.recommendations())
        self.assertEqual(1, self.index.rank_station_hubs()["snapshot_sequence"])

    def test_invalid_metrics_do_not_silently_fall_back(self):
        with self.assertRaises(ValueError):
            self.index.line_outliers("profit")
        with self.assertRaises(ValueError):
            self.index.rank_station_hubs("traffic")
