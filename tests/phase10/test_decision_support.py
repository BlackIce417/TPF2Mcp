import json
import unittest
from copy import deepcopy
from pathlib import Path

from tpf2_mcp.analytics import NetworkIntelligenceIndex
from tpf2_mcp.planning import DecisionSupport
from tpf2_mcp.snapshot import SnapshotIndex


class DecisionSupportTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures" / "world_snapshot_001.json"
        self.snapshot = SnapshotIndex(json.loads(fixture.read_text(encoding="utf-8")))
        self.snapshot.vehicle_by_id[50]["capacity_total"] = 40
        self.snapshot.vehicle_by_id[51]["capacity_total"] = 60
        self.snapshot.vehicle_by_id[52]["capacity_total"] = 20
        self.snapshot.line_by_id[40].update({"frequency_seconds": 100, "throughput": 180})
        self.snapshot.line_by_id[41].update({"frequency_seconds": 1000, "throughput": 20})
        self.support = DecisionSupport(NetworkIntelligenceIndex(self.snapshot))

    def test_routes_and_tarjan_resilience(self):
        route = self.support.route(30, 32, max_routes=3)
        resilience = self.support.resilience()
        self.assertEqual([30, 31, 32], route["routes"][0]["station_path"])
        self.assertIn(31, [item["station_id"] for item in resilience["articulation_stations"]])
        self.assertTrue(resilience["bridge_connections"])

    def test_virtual_connection_reduces_components_without_mutating_snapshot(self):
        before = deepcopy(self.snapshot.state)
        result = self.support.simulate_connection(30, 32)
        self.assertEqual(0, result["delta"]["connected_component_count"])
        self.assertEqual(before, self.snapshot.state)
        result = self.support.simulate_line_failure(41)
        self.assertGreater(result["delta"]["connected_component_count"], 0)
        self.assertEqual("HYPOTHETICAL", result["source_status"])

    def test_scenarios_are_deterministic_and_comparable(self):
        mutation = [{"type": "CHANGE_VIRTUAL_VEHICLE_COUNT", "line_id": 40, "delta": 1}]
        self.assertEqual(self.support.simulate(mutation), self.support.simulate(mutation))
        comparison = self.support.compare_scenarios([{"name": "baseline", "mutations": []}, {"name": "fleet", "mutations": mutation}])
        self.assertEqual(1, comparison["snapshot_sequence"])
        self.assertEqual("UNAVAILABLE", comparison["comparison"]["cost"]["status"])

    def test_problem_impact_and_station_failure(self):
        problems = self.support.detect_problems()["problems"]
        line_problem = next(item for item in problems if item["type"] == "LONG_HEADWAY_OUTLIER")
        impact = self.support.problem_impact(line_problem["problem_id"])
        failure = self.support.simulate_station_failure(31)
        self.assertEqual(41, impact["line_id"])
        self.assertGreater(failure["delta"]["connected_component_count"], 0)

    def test_new_line_candidates_use_observed_station_ids_and_are_read_only(self):
        before = deepcopy(self.snapshot.state)
        result = self.support.new_line_candidates(5)
        candidate = next(item for item in result["candidates"] if item["station_ids"] == [30, 32])
        self.assertEqual("TOPOLOGY_REDUNDANCY", candidate["candidate_type"])
        self.assertEqual("CREATE_LINE_GOAL", candidate["task_goal_candidate"]["goal_type"])
        self.assertEqual("NEEDS_TERMINAL_EVIDENCE", candidate["execution_readiness"])
        self.assertEqual(before, self.snapshot.state)

    def test_new_line_candidates_prioritize_resolved_terminal_evidence(self):
        state = deepcopy(self.snapshot.state)
        state["lines"][0]["raw_stops"] = [{"station_id": 30, "station_index": 0, "terminal_id": 2}, {"station_id": 31, "station_index": 0, "terminal_id": 0}]
        state["lines"][1]["raw_stops"] = [{"station_id": 32, "station_index": 0, "terminal_id": 4}, {"station_id": 31, "station_index": 0, "terminal_id": 0}]
        support = DecisionSupport(NetworkIntelligenceIndex(SnapshotIndex(state)))
        candidate = support.new_line_candidates(1)["candidates"][0]
        self.assertEqual([30, 32], candidate["station_ids"])
        self.assertEqual("TERMINAL_INPUT_READY_PHYSICAL_PATH_UNKNOWN", candidate["execution_readiness"])
        self.assertEqual({"30": 2, "32": 4}, candidate["task_goal_candidate"]["goal"]["terminal_selectors"])
