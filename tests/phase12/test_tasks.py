import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


class TaskTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures" / "world_snapshot_001.json"
        self.state = json.loads(fixture.read_text(encoding="utf-8"))
        self.calls = 0

        def snapshot(force):
            if force: self.state["sequence"] += 1
            return SnapshotIndex(deepcopy(self.state))

        def executor(command):
            self.calls += 1
            line = next(item for item in self.state["lines"] if item["entity_id"] == command["target"]["line_id"])
            line["name"] = command["parameters"]["name"]
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}

        self.snapshot = snapshot
        self.tasks = TaskOrchestrator(snapshot, OperationController(snapshot, executor))

    def test_manual_goal_is_one_verified_mutation(self):
        task = self.tasks.create("RENAME_LINE_GOAL", {"line_id": 40, "desired_name": "Task name"})
        planned = self.tasks.plan(task["task_id"])
        self.assertEqual("WAITING_FOR_APPROVAL", planned["status"])
        self.tasks.approve(task["task_id"])
        result = self.tasks.continue_task(task["task_id"])
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual(1, self.calls)
        self.assertEqual("POSTCONDITION_VERIFIED", result["steps"][0]["status"])

    def test_already_satisfied_goal_writes_nothing(self):
        task = self.tasks.create("RENAME_LINE_GOAL", {"line_id": 40, "desired_name": self.state["lines"][0]["name"]})
        result = self.tasks.plan(task["task_id"])
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual(0, self.calls)

    def test_plan_only_and_scope_and_budget_are_bounded(self):
        network = self.tasks.create("IMPROVE_CONNECTIVITY_GOAL", {}, policy="PLAN_ONLY")
        self.assertEqual("BLOCKED", self.tasks.plan(network["task_id"])["status"])
        task = self.tasks.create("RENAME_LINE_GOAL", {"line_id": 40, "desired_name": "Bounded"}, max_write_operations=1)
        self.tasks.plan(task["task_id"]); self.tasks.approve(task["task_id"])
        self.assertEqual("COMPLETED", self.tasks.continue_task(task["task_id"])["status"])
        self.assertEqual(1, self.calls)

    def test_composite_purchase_then_assignment_keeps_verified_progress(self):
        state = deepcopy(self.state)
        calls = []
        def snapshot(force):
            if force: state["sequence"] += 1
            return SnapshotIndex(deepcopy(state))
        def executor(command):
            calls.append(command["operation_type"])
            if command["operation_type"] == "BUY_VEHICLE":
                state["vehicles"].append({"entity_id": 99, "entity_type": "vehicle", "name": "New bus", "line_id": None})
            else:
                next(item for item in state["vehicles"] if item["entity_id"] == command["target"]["vehicle_id"])["line_id"] = command["target"]["line_id"]
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}
        tasks = TaskOrchestrator(snapshot, OperationController(snapshot, executor))
        task = tasks.create("BUY_AND_ASSIGN_VEHICLE_GOAL", {"depot_id": 60, "source_vehicle_id": 50, "target_line_id": 40}, max_steps=2, max_write_operations=2)
        tasks.plan(task["task_id"]); tasks.approve(task["task_id"])
        first = tasks.continue_task(task["task_id"])
        self.assertEqual("READY", first["status"])
        result = tasks.continue_task(task["task_id"])
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual(["BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"], calls)
        self.assertEqual(99, result["goal"]["created_vehicle_id"])
        self.assertEqual(0, result["budget"]["replans_used"])

    def test_task_journal_recovers_state_without_executing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            first = TaskOrchestrator(self.snapshot, OperationController(self.snapshot), journal_path=path)
            task = first.create("RENAME_LINE_GOAL", {"line_id": 40, "desired_name": "Persisted"})
            first.plan(task["task_id"])
            recovered = TaskOrchestrator(self.snapshot, OperationController(self.snapshot), journal_path=path)
            value = recovered.get(task["task_id"])
            self.assertEqual("WAITING_FOR_APPROVAL", value["status"])
            self.assertEqual(0, self.calls)
