import json
import unittest
from pathlib import Path

from tpf2_mcp.snapshot import SnapshotIndex


class SnapshotIndexTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "world_snapshot_001.json"
        self.index = SnapshotIndex(json.loads(fixture.read_text(encoding="utf-8")))

    def test_builds_verified_reverse_indexes(self):
        self.assertEqual([50, 51], [item["entity_id"] for item in self.index.vehicles_by_line[40]])
        self.assertEqual([40, 40], [item["entity_id"] for item in self.index.lines_by_station[30]])
        self.assertEqual([], self.index.unresolved_stop_references)

    def test_line_summary_resolves_stations_and_vehicles(self):
        result = self.index.line_summary(40)
        self.assertEqual(3, result["summary"]["stop_count"])
        self.assertEqual(2, result["summary"]["vehicle_count"])
        self.assertEqual("北京站", result["stations"][0]["name"])

    def test_network_analysis(self):
        summary = self.index.network_summary()
        self.assertEqual(0, summary["unassigned_vehicle_count"])
        self.assertEqual([], summary["lines_without_vehicles"])
        self.assertEqual([], self.index.unassigned_vehicles()["broken_reference"])

    def test_operating_state_marks_unavailable_metrics(self):
        vehicle = self.index.vehicle_operating_state(50)
        self.assertFalse(vehicle["availability"]["capacity"])
        self.assertIsNone(vehicle["operations"]["occupancy_ratio"])
        line = self.index.line_operating_summary(40)
        self.assertFalse(line["availability"]["revenue"])

    def test_cargo_registry_is_dynamic_and_key_addressable(self):
        self.assertEqual("IRON_ORE", self.index.cargo_registry.by_key["IRON_ORE"]["cargo_key"])
        self.assertEqual(2, len(self.index.cargo_types()))
        self.assertEqual(2, self.index.overview()["counts"]["cargo_types"])

    def test_vehicle_capacity_is_available_only_when_normalized(self):
        self.index.vehicle_by_id[50]["capacity_total"] = 40
        result = self.index.vehicle_operating_state(50)
        self.assertTrue(result["availability"]["capacity"])
        self.assertEqual(40, result["operations"]["capacity"])

    def test_dynamic_unavailability_is_explicit(self):
        vehicle = self.index.vehicle_operating_state(50)
        station = self.index.station_operating_state(30)
        line = self.index.line_operating_summary(40)
        self.assertEqual("UNAVAILABLE", vehicle["source_status"]["load"])
        self.assertIn("No verified", vehicle["unavailable_reasons"]["load"])
        self.assertEqual("UNAVAILABLE", station["source_status"]["waiting"])
        self.assertEqual("UNAVAILABLE", line["source_status"]["revenue"])

    def test_line_frequency_and_throughput_are_available_when_normalized(self):
        self.index.line_by_id[40]["frequency_seconds"] = 360
        self.index.line_by_id[40]["throughput"] = 405
        result = self.index.line_operating_summary(40)
        self.assertTrue(result["availability"]["frequency"])
        self.assertTrue(result["availability"]["throughput"])
        self.assertEqual(360, result["operations"]["frequency_seconds"])
        self.assertEqual(405, result["operations"]["throughput"])

    def test_line_scorecard_uses_verified_or_derived_values(self):
        self.index.vehicle_by_id[50]["capacity_total"] = 40
        self.index.vehicle_by_id[51]["capacity_total"] = 60
        self.index.line_by_id[40]["frequency_seconds"] = 120
        self.index.line_by_id[40]["throughput"] = 180
        result = self.index.line_scorecard(40)
        self.assertEqual(100, result["network"]["fleet_capacity_total"])
        self.assertEqual(50, result["network"]["average_vehicle_capacity"])
        self.assertEqual(30, result["derived"]["departures_per_hour"])
        self.assertEqual("DERIVED", result["source_status"]["fleet_capacity_total"])

    def test_structural_diagnostics_are_evidence_backed(self):
        self.index.line_by_id[40]["frequency_seconds"] = 900
        result = self.index.diagnose_line_structure(40, long_headway_seconds=600)
        diagnostic = next(item for item in result["diagnostics"] if item["code"] == "LONG_HEADWAY")
        self.assertEqual(40, diagnostic["entity_id"])
        self.assertEqual(900, diagnostic["evidence"]["frequency_seconds"])

    def test_graph_route_and_station_connectivity(self):
        route = self.index.find_station_route(30, 32)
        connectivity = self.index.station_connectivity(31)
        self.assertEqual("line_station_connectivity_not_physical_path", route["route_type"])
        self.assertEqual([30, 31, 32], route["station_ids"])
        self.assertEqual(1, route["transfer_count"])
        self.assertEqual(2, connectivity["line_count"])

    def test_network_helpers_and_capabilities(self):
        self.index.vehicle_by_id[50]["capacity_total"] = 40
        self.index.vehicle_by_id[51]["capacity_total"] = 60
        self.index.vehicle_by_id[52]["capacity_total"] = 20
        comparison = self.index.compare_lines([40, 41, 999])
        fleet = self.index.fleet_summary()
        self.assertEqual([999], comparison["missing_line_ids"])
        self.assertEqual(120, fleet["capacity_total"])
        self.assertEqual("UNAVAILABLE", self.index.capabilities()["vehicle_load"]["status"])
        self.assertEqual("UNRESOLVED", self.index.capabilities()["company_cash_semantic"]["status"])
