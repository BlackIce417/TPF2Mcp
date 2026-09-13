import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.station_log import StationEventStore


class StationEventStoreTests(unittest.TestCase):
    def fixture(self):
        manifest = {
            "stations": [{"entity_id": 10, "name": "A", "center": {"x": 0, "y": 0},
                          "bounds": {"min": {"x": -10, "y": -10}, "max": {"x": 10, "y": 10}},
                          "terminals": [{"platform_edge_ids": [20]}]}],
            "lines": [
                {"entity_id": 91, "name": "线路 91", "stops": [{"station_group_id": 10}]},
                {"entity_id": 92, "name": "线路 92", "stops": [{"station_group_id": 11}]},
            ],
        }
        frame = {"simulation": {"clock": {"game_time": 1234}}, "vehicles": [
            {"entity_id": 1, "name": "列车1", "line_id": 91, "stop_index": 0, "raw_state": 2,
             "speed_kmh": 0, "position": {"x": 0, "y": 0}},
            {"entity_id": 2, "name": "列车2", "line_id": 92, "stop_index": 0, "raw_state": 1,
             "speed_kmh": 80, "edge_id": 20, "position": {"x": 1, "y": 1}},
        ]}
        return frame, manifest

    def test_records_stop_and_pass_once_per_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StationEventStore(Path(directory) / "events.sqlite3")
            frame, manifest = self.fixture()
            self.assertEqual(store.record_frame(frame, manifest, "save-a", observed_at=100), 2)
            self.assertEqual(store.record_frame(frame, manifest, "save-a", observed_at=101), 0)
            events = store.query(10, "save-a")
            self.assertEqual([item["event_type"] for item in events], ["PASS", "STOP"])
            self.assertTrue(all(item["observed_at"] == 100 for item in events))

    def test_presence_can_be_recorded_again_after_vehicle_leaves(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StationEventStore(Path(directory) / "events.sqlite3")
            frame, manifest = self.fixture()
            store.record_frame(frame, manifest, "save-a", observed_at=100)
            store.record_frame({"vehicles": []}, manifest, "save-a", observed_at=101)
            store.record_frame(frame, manifest, "save-a", observed_at=102)
            self.assertEqual(len(store.query(10, "save-a")), 4)

    def test_adjacent_mainline_inside_large_bounds_is_not_a_station_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StationEventStore(Path(directory) / "events.sqlite3")
            frame, manifest = self.fixture()
            frame["vehicles"] = [{"entity_id": 2, "name": "列车2", "line_id": 92,
                                  "stop_index": 0, "raw_state": 1, "speed_kmh": 80,
                                  "edge_id": 999, "position": {"x": 1, "y": 1}}]
            self.assertEqual(store.record_frame(frame, manifest, "save-a", observed_at=100), 0)
            self.assertEqual(store.query(10, "save-a"), [])

    def test_same_station_and_vehicle_ids_are_isolated_by_save(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StationEventStore(Path(directory) / "events.sqlite3")
            frame, manifest = self.fixture()
            self.assertEqual(store.record_frame(frame, manifest, "save-a", observed_at=100), 2)
            self.assertEqual(store.record_frame(frame, manifest, "save-b", observed_at=101), 2)
            self.assertEqual(2, len(store.query(10, "save-a")))
            self.assertEqual(2, len(store.query(10, "save-b")))
