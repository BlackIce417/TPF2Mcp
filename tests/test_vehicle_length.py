import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.vehicle_length import VehicleModelLengthResolver


class VehicleModelLengthResolverTests(unittest.TestCase):
    def test_enriches_exact_model_parts_with_conservative_consist_length(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "res/models/model/vehicle/train/a.mdl"
            model.parent.mkdir(parents=True)
            model.write_text("return { boundingInfo = { bbMax = { 11, 2, 4 }, bbMin = { -10, -2, 0 }, }, }", encoding="utf-8")
            snapshot = {"vehicles": [{"consist_parts": [{"model_name": "vehicle/train/a.mdl"}, {"model_name": "vehicle/train/a.mdl"}]}]}
            result = VehicleModelLengthResolver(Path(directory)).enrich_snapshot(snapshot)
            self.assertEqual(1, result["known_vehicle_lengths"])
            self.assertEqual(43, snapshot["vehicles"][0]["consist_length_m"])
            self.assertEqual("MEDIUM_CONSERVATIVE", snapshot["vehicles"][0]["consist_length_confidence"])


if __name__ == "__main__":
    unittest.main()
