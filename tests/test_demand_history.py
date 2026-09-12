import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.demand_history import DemandHistoryStore


class DemandHistoryStoreTests(unittest.TestCase):
    def test_records_and_returns_oldest_to_newest_window(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DemandHistoryStore(Path(directory) / "demand.sqlite3")
            store.record({"line_id": 7, "source_status": "ENGINE_COMPONENT_CLASSIFIED", "passengers": {"waiting": 10}}, 1)
            store.record({"line_id": 7, "source_status": "ENGINE_COMPONENT_CLASSIFIED", "passengers": {"waiting": 20}}, 2)
            self.assertEqual([10, 20], [x["passengers"]["waiting"] for x in store.query(7)])


if __name__ == "__main__":
    unittest.main()
