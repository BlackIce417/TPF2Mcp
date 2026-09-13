import tempfile
import unittest
import sqlite3
from pathlib import Path

from tpf2_mcp.demand_history import DemandHistoryStore


class DemandHistoryStoreTests(unittest.TestCase):
    def test_records_and_returns_oldest_to_newest_window(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DemandHistoryStore(Path(directory) / "demand.sqlite3")
            store.record({"line_id": 7, "source_status": "ENGINE_COMPONENT_CLASSIFIED", "passengers": {"waiting": 10}}, "save-a", 1)
            store.record({"line_id": 7, "source_status": "ENGINE_COMPONENT_CLASSIFIED", "passengers": {"waiting": 20}}, "save-a", 2)
            store.record({"line_id": 7, "source_status": "ENGINE_COMPONENT_CLASSIFIED", "passengers": {"waiting": 99}}, "save-b", 3)
            self.assertEqual([10, 20], [x["passengers"]["waiting"] for x in store.query(7, "save-a")])
            self.assertEqual([99], [x["passengers"]["waiting"] for x in store.query(7, "save-b")])

    def test_legacy_table_is_migrated_without_attributing_rows_to_current_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demand.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("""CREATE TABLE line_demand_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, line_id INTEGER NOT NULL, observed_at REAL NOT NULL,
                sampled_game_time_ms INTEGER, source_status TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            connection.execute("INSERT INTO line_demand_samples VALUES (NULL,7,1,NULL,'OLD','{}')")
            connection.commit(); connection.close()
            store = DemandHistoryStore(path)
            store.record({"line_id": 7, "source_status": "NEW"}, "save-a", 2)
            self.assertEqual([], store.query(7, "save-b"))
            self.assertEqual(1, len(store.query(7, "save-a")))
            connection = sqlite3.connect(path)
            self.assertEqual("legacy-unscoped", connection.execute(
                "SELECT save_id FROM line_demand_samples WHERE observed_at=1").fetchone()[0])
            connection.close()


if __name__ == "__main__":
    unittest.main()
