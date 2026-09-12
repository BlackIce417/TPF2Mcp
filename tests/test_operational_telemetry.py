import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("analyze_operational_telemetry", ROOT / "tools" / "analyze-operational-telemetry.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class OperationalTelemetryTests(unittest.TestCase):
    def test_readiness_uses_observed_signal_vehicle_time_and_demand_evidence(self):
        report = {
            "source_status": "ENGINE_OBSERVED_DIAGNOSTIC",
            "counts": {"signals": 2, "vehicles": 1, "stations": 1},
            "signals": [{"position": {"x": 1}}, {"position": {"x": 2}}],
            "signal_edge_objects": [{"signal_entity_id": 1}, {"signal_entity_id": 2}],
            "vehicles": [{"position": {"x": 3}, "info": {"speed": {"type": "number", "value": 20}, "edgeId": {"type": "number", "value": 8}}}],
            "station_demand": [{"transport_samples_ok": True}],
            "clock": {"methods": {"getGameTime": {"call_ok": True}}},
            "errors": [],
        }

        result = MODULE.analyze(report)

        self.assertEqual("READY_FOR_NORMALIZATION", result["readiness"]["signal_layer"])
        self.assertEqual("READY_FOR_MODELING", result["readiness"]["block_derivation"])
        self.assertEqual("READY_FOR_NORMALIZATION", result["readiness"]["moving_train_layer"])
        self.assertEqual("READY_FOR_RECORDING", result["readiness"]["actual_route_validation"])

    def test_lua_probe_is_read_only_and_batched(self):
        source = (ROOT / "tpf2_mod" / "res" / "scripts" / "tpf2_mcp" / "collectors" / "operational_telemetry.lua").read_text(encoding="utf-8")
        self.assertIn("UNIFIED_OPERATIONAL_TELEMETRY_DISCOVERY", source)
        self.assertIn("write_command_sent = false", source)
        self.assertIn("collect_signals", source)
        self.assertIn("collect_vehicles", source)
        self.assertIn("collect_station_demand", source)
        self.assertIn("VALID_SECTIONS", source)
        self.assertIn("result.track_edge_objects", source)
        self.assertIn("signal_model_observed", source)
        self.assertIn('common.safe_get_component(raw_entity, "SIGNAL_LIST"', source)
        self.assertIn("operational_signal_observed", source)
        self.assertIn("#result.items >= 4", source)
        self.assertIn('common.field(edge_id_value, "entity")', source)
        self.assertIn('common.field(move_path, "dyn")', source)
        self.assertIn('common.field(path_pos, "edgeIndex")', source)
        self.assertIn('common.field(path_pos, "pos01")', source)
        self.assertIn('speed_mps = type(common.field(dyn, "speed"))', source)
        self.assertNotIn('interface_call("getStationTransportSamples"', source)
        self.assertNotIn("api.cmd", source)

    def test_runner_does_not_invoke_crashing_station_section(self):
        source = (ROOT / "tools" / "run-operational-telemetry.py").read_text(encoding="utf-8")
        self.assertIn('for section in ("inventory", "signals", "vehicles")', source)
        self.assertIn('snapshot_path = client.directory / "state.json"', source)
        self.assertNotIn('operational_telemetry("stations")', source)


if __name__ == "__main__":
    unittest.main()
