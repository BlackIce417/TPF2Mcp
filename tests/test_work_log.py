import json
import tempfile
import unittest
from pathlib import Path

from tpf2_mcp.work_log import McpWorkLogStore


class McpWorkLogStoreTests(unittest.TestCase):
    def test_only_verified_completed_steps_are_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "tasks.jsonl"
            proposed = {"task_id": "a", "status": "WAITING_FOR_APPROVAL", "steps": []}
            completed = {"task_id": "b", "save_id": "save-a", "status": "COMPLETED", "goal": {"target_line_id": 91},
                         "planned_steps": [{"target": {"line_id": 91, "vehicle_id": 8}}],
                         "steps": [{"step_id": "s1", "sequence": 1, "operation_type": "SET_LINE_STOP_POLICY",
                                    "status": "POSTCONDITION_VERIFIED", "verification": {"status": "POSTCONDITION_VERIFIED", "verified_at": "2026-09-12T00:00:00+00:00"}}]}
            journal.write_text("\n".join(json.dumps(item) for item in (proposed, completed)), encoding="utf-8")
            store = McpWorkLogStore(root / "work.sqlite3")
            store.sync_task_journal(journal, "save-a")
            store.sync_task_journal(journal, "save-a")
            rows = store.query("save-a")
            self.assertEqual(1, len(rows))
            self.assertTrue(rows[0]["applied"])
            self.assertEqual("POSTCONDITION_VERIFIED", rows[0]["verification_status"])
            self.assertEqual(0, len(store.query("save-b")))

    def test_verified_action_is_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = McpWorkLogStore(Path(directory) / "work.sqlite3")
            store.record_verified_action("save-a", "op:1", "EXPAND_LINE_WITH_VEHICLE", "加车", 7, 8)
            store.record_verified_action("save-a", "op:1", "EXPAND_LINE_WITH_VEHICLE", "加车", 7, 8)
            self.assertEqual(1, len(store.query("save-a")))
            self.assertEqual([], store.query("save-b"))


if __name__ == "__main__":
    unittest.main()
