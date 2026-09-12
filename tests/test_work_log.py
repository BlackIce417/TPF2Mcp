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
            completed = {"task_id": "b", "status": "COMPLETED", "goal": {"target_line_id": 91},
                         "planned_steps": [{"target": {"line_id": 91, "vehicle_id": 8}}],
                         "steps": [{"step_id": "s1", "sequence": 1, "operation_type": "SET_LINE_STOP_POLICY",
                                    "status": "POSTCONDITION_VERIFIED", "verification": {"status": "POSTCONDITION_VERIFIED", "verified_at": "2026-09-12T00:00:00+00:00"}}]}
            journal.write_text("\n".join(json.dumps(item) for item in (proposed, completed)), encoding="utf-8")
            store = McpWorkLogStore(root / "work.sqlite3")
            store.sync_task_journal(journal)
            store.sync_task_journal(journal)
            rows = store.query()
            self.assertEqual(1, len(rows))
            self.assertTrue(rows[0]["applied"])
            self.assertEqual("POSTCONDITION_VERIFIED", rows[0]["verification_status"])


if __name__ == "__main__":
    unittest.main()
