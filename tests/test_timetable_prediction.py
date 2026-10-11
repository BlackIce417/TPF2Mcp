import unittest
import tempfile
from pathlib import Path

from tpf2_mcp.timetable_prediction import TimetablePredictor, project_prediction_to_wall


LINE = {"line_id": 9, "epoch_game_time_ms": 100_000, "cycle_seconds": 120,
        "phase_offsets_seconds": [0, 60], "stops": [
            {"station_group_id": 10, "station_name": "甲", "arrival_offset_seconds": 0},
            {"station_group_id": 11, "station_name": "乙", "arrival_offset_seconds": 50},
        ]}


def frame(game, status="RUNNING", rate=2, sampled=1000):
    return {"sampled_at": sampled, "simulation": {"status": status, "speed_multiplier": rate,
            "clock": {"game_time": game * 1000}}}


class TimetablePredictionTests(unittest.TestCase):
    def test_waits_for_station_then_keeps_fixed_phase_and_propagates_delay(self):
        predictor = TimetablePredictor()
        moving = {"entity_id": 7, "stop_index": 0, "raw_state": 1}
        self.assertEqual("UNBOUND", predictor.predictions("save", LINE, frame(105), [moving])[7]["binding_state"])
        at_station = {**moving, "raw_state": 2}
        bound = predictor.predictions("save", LINE, frame(105), [at_station])[7]
        self.assertEqual(0, bound["phase_index"])
        self.assertEqual(5, bound["delay_seconds"])
        toward_next = {**moving, "stop_index": 1}
        predicted = predictor.predictions("save", LINE, frame(120), [toward_next])[7]
        self.assertEqual(155, predicted["estimated_arrival_game_time"])
        self.assertEqual("ON_TIME", predicted["punctuality"])
        arrived = predictor.predictions("save", LINE, frame(200), [{**toward_next, "raw_state": 2}])[7]
        self.assertEqual(50, arrived["delay_seconds"])
        self.assertEqual("LATE", arrived["punctuality"])
        wrapped = predictor.predictions("save", LINE, frame(230), [{**moving, "stop_index": 0}])[7]
        self.assertEqual(270, wrapped["estimated_arrival_game_time"])

        very_late = predictor.predictions("save", LINE, frame(400), [{**moving, "stop_index": 0, "raw_state": 2}])[7]
        self.assertEqual(180, very_late["delay_seconds"])
        self.assertEqual(1, very_late["cycle_index"])

    def test_overrun_pause_projection_and_save_reset(self):
        predictor = TimetablePredictor()
        predictor.predictions("a", LINE, frame(105), [{"entity_id": 7, "stop_index": 0, "raw_state": 2}])
        overdue = predictor.predictions("a", LINE, frame(200), [{"entity_id": 7, "stop_index": 1, "raw_state": 1}])[7]
        self.assertEqual("LATE_UNDETERMINED", overdue["punctuality"])
        self.assertIsNone(overdue["estimated_arrival_game_time"])
        wall = project_prediction_to_wall({"scheduled_arrival_game_time": 150, "estimated_arrival_game_time": 160}, frame(100))
        self.assertEqual(1025, wall["scheduled_arrival_at"])
        self.assertEqual(1030, wall["estimated_arrival_at"])
        paused = project_prediction_to_wall(wall, frame(100, "PAUSED", 0))
        self.assertIsNone(paused["estimated_arrival_at"])
        reset = predictor.predictions("b", LINE, frame(200), [{"entity_id": 7, "stop_index": 1, "raw_state": 1}])[7]
        self.assertEqual("UNBOUND", reset["binding_state"])

    def test_bad_clock_stop_and_stale_position_remain_unbound(self):
        predictor = TimetablePredictor()
        vehicle = {"entity_id": 7, "stop_index": 99, "raw_state": 2}
        self.assertEqual("STOP_INDEX_UNAVAILABLE", predictor.predictions("a", LINE, frame(100), [vehicle])[7]["prediction_source"])
        vehicle.update(stop_index=0, position_stale=True)
        self.assertEqual("UNBOUND", predictor.predictions("a", LINE, frame(100), [vehicle])[7]["binding_state"])
        self.assertEqual("GAME_CLOCK_UNAVAILABLE", predictor.predictions("a", LINE, {"simulation": {}}, [vehicle])[7]["prediction_source"])

    def test_binding_survives_predictor_restart_for_same_world(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "bindings.json"
            first = TimetablePredictor(state_path=state_path)
            vehicle = {"entity_id": 7, "stop_index": 0, "raw_state": 2}
            bound = first.predictions("save", LINE, frame(105), [vehicle])[7]
            self.assertEqual("INFERRED_FIXED_PERSISTED", bound["binding_state"])
            second = TimetablePredictor(state_path=state_path)
            moving = {"entity_id": 7, "stop_index": 1, "raw_state": 1}
            restored = second.predictions("save", LINE, frame(120), [moving])[7]
            self.assertEqual(0, restored["phase_index"])
            self.assertEqual(155, restored["estimated_arrival_game_time"])
            self.assertEqual("save", __import__("json").loads(state_path.read_text())["save_id"])
