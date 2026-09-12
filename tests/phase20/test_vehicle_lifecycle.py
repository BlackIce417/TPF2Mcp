import json
import unittest
from copy import deepcopy
from pathlib import Path

from tpf2_mcp.operations import OperationController, capabilities
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks.goals import goal_capability, planned_steps, scope_for
from tpf2_mcp.tasks import TaskOrchestrator


class VehicleLifecycleTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parents[1] / "fixtures" / "world_snapshot_001.json"
        self.state = json.loads(fixture.read_text(encoding="utf-8"))
        self.state["simulation"] = {"source_status": "ENGINE_COMPONENT", "paused": False, "speed_multiplier": 1}
        self.state["vehicles"][0]["raw_state"] = 2

    def controller(self, executor=None, allow_unverified_test=False):
        return OperationController(
            lambda _: SnapshotIndex(deepcopy(self.state)),
            executor,
            allow_unverified_test=allow_unverified_test,
        )

    def test_remove_capability_is_fail_closed_after_engine_rejection(self):
        item = next(item for item in capabilities() if item["operation_type"] == "REMOVE_VEHICLE_FROM_LINE")
        self.assertFalse(item["controller_supported"])
        self.assertFalse(item["engine_verified"])
        self.assertEqual("ENGINE_REJECTED_UNAVAILABLE", item["source_status"])

    def test_sell_requires_exact_vehicle_confirmation(self):
        controller = self.controller()
        missing = controller.propose("SELL_VEHICLE", {"vehicle_id": 50}, {})
        wrong = controller.propose("SELL_VEHICLE", {"vehicle_id": 50}, {"confirmation": "SELL_VEHICLE:51"})
        self.assertEqual("INVALID_PARAMETERS", missing["status"])
        self.assertEqual("INVALID_PARAMETERS", wrong["status"])

    def test_sell_capability_records_live_postcondition_evidence(self):
        item = next(item for item in capabilities() if item["operation_type"] == "SELL_VEHICLE")
        self.assertTrue(item["engine_verified"])
        self.assertTrue(item["controller_supported"])
        self.assertTrue(item["live_mcp_verified"])
        self.assertTrue(item["task_supported"])
        self.assertEqual("POSTCONDITION_VERIFIED", item["source_status"])

    def test_sell_proposal_records_vehicle_and_does_not_write(self):
        calls = []
        proposal = self.controller(lambda command: calls.append(command)).propose(
            "SELL_VEHICLE", {"vehicle_id": 50}, {"confirmation": "SELL_VEHICLE:50"}
        )
        self.assertEqual("PROPOSED", proposal["status"])
        self.assertEqual(40, proposal["operation"]["expected_entity_state"]["line_id"])
        self.assertEqual({"vehicle_removed": True, "previous_line_id": 40}, proposal["operation"]["expected_effect"])
        self.assertEqual([], calls)

    def test_changed_vehicle_is_rejected_before_sell(self):
        calls = []
        controller = self.controller(lambda command: calls.append(command), allow_unverified_test=True)
        proposal = controller.propose("SELL_VEHICLE", {"vehicle_id": 50}, {"confirmation": "SELL_VEHICLE:50"})
        self.state["vehicles"][0]["line_id"] = 41
        result = controller.execute(proposal["operation_id"], dry_run=False)
        self.assertEqual("ENTITY_STATE_CHANGED", result["execution_status"])
        self.assertFalse(result["command_sent"])
        self.assertEqual([], calls)

    def test_authorized_sell_test_executes_and_verifies_vehicle_absent(self):
        def executor(command):
            self.assertEqual("SELL_VEHICLE", command["operation_type"])
            self.assertEqual(50, command["target"]["vehicle_id"])
            self.assertEqual("SELL_VEHICLE:50", command["parameters"]["confirmation"])
            self.state["vehicles"] = [vehicle for vehicle in self.state["vehicles"] if vehicle["entity_id"] != 50]
            self.state["sequence"] += 1
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}

        controller = self.controller(executor, allow_unverified_test=True)
        proposal = controller.propose("SELL_VEHICLE", {"vehicle_id": 50}, {"confirmation": "SELL_VEHICLE:50"})
        execution = controller.execute(proposal["operation_id"], dry_run=False)
        verification = controller.verify(proposal["operation_id"])
        self.assertTrue(execution["command_sent"])
        self.assertEqual("POSTCONDITION_VERIFIED", verification["status"])
        self.assertFalse(verification["verification"]["vehicle_present"])

    def test_create_and_configure_goal_is_a_bounded_four_operation_plan(self):
        goal = {
            "name": "Configured line",
            "start_station_id": 30,
            "via_station_ids": [31],
            "end_station_id": 30,
            "source_vehicle_id": 50,
            "depot_id": 60,
        }
        cap = goal_capability("CREATE_AND_CONFIGURE_LINE_GOAL")
        scope = scope_for("CREATE_AND_CONFIGURE_LINE_GOAL", goal)
        steps = planned_steps("CREATE_AND_CONFIGURE_LINE_GOAL", goal, {})
        self.assertEqual("EXECUTABLE_BUT_DISABLED", cap["status"])
        self.assertEqual(["CREATE_LINE", "SET_LINE_STOPS", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE"], scope["operation_types"])
        self.assertEqual(scope["operation_types"], [step["operation_type"] for step in steps])
        self.assertIsNone(steps[1]["target"]["line_id"])
        self.assertIsNone(steps[3]["target"]["vehicle_id"])

    def test_create_and_configure_goal_supports_two_vehicles(self):
        goal = {"name": "Two vehicles", "start_station_id": 30, "end_station_id": 31, "source_vehicle_id": 50, "depot_id": 60, "vehicle_count": 2}
        steps = planned_steps("CREATE_AND_CONFIGURE_LINE_GOAL", goal, {})
        self.assertEqual(6, len(steps))
        self.assertEqual(2, sum(step["operation_type"] == "BUY_VEHICLE" for step in steps))
        self.assertEqual(2, sum(step["operation_type"] == "ASSIGN_VEHICLE_TO_LINE" for step in steps))

    def test_all_verified_mutations_have_task_goals(self):
        expected = {
            "SET_LINE_STOPS_GOAL": "SET_LINE_STOPS",
            "SET_LINE_STOP_POLICY_GOAL": "SET_LINE_STOP_POLICY",
            "SELL_VEHICLE_GOAL": "SELL_VEHICLE",
        }
        for goal_type, operation_type in expected.items():
            item = goal_capability(goal_type)
            self.assertEqual(operation_type, item["operation_type"])
            self.assertEqual("EXECUTABLE_BUT_DISABLED", item["status"])

    def test_product_ready_requires_live_task_evidence(self):
        ready = {item["operation_type"] for item in capabilities() if item["product_ready"]}
        expected = {"RENAME_LINE", "CREATE_LINE", "SET_LINE_STOPS", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE", "SELL_VEHICLE", "SET_LINE_STOP_POLICY"}
        self.assertTrue(expected.issubset(ready))
        self.assertNotIn("CREATE_LINE_FROM_SOURCE_ROUTE", ready)

    def test_sell_goal_keeps_confirmation_in_task_step(self):
        goal = {"vehicle_id": 50, "confirmation": "SELL_VEHICLE:50"}
        step = planned_steps("SELL_VEHICLE_GOAL", goal, {})[0]
        self.assertEqual({"confirmation": "SELL_VEHICLE:50"}, step["parameters"])

    def test_stop_policy_validates_and_verifies_exact_values(self):
        policy = {"stop_index": 0, "load_mode": 1, "min_waiting_time": 30, "max_waiting_time": 120}

        def executor(command):
            self.assertEqual("SET_LINE_STOP_POLICY", command["operation_type"])
            self.state["lines"][0]["stops"][0]["policy"] = {
                "load_mode": 1,
                "min_waiting_time": 30,
                "max_waiting_time": 120,
            }
            self.state["sequence"] += 1
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}

        controller = self.controller(executor, allow_unverified_test=True)
        proposal = controller.propose("SET_LINE_STOP_POLICY", {"line_id": 40}, policy)
        execution = controller.execute(proposal["operation_id"], dry_run=False)
        verification = controller.verify(proposal["operation_id"])
        self.assertTrue(execution["command_sent"])
        self.assertEqual("POSTCONDITION_VERIFIED", verification["status"])

    def test_stop_policy_rejects_invalid_wait_range(self):
        result = self.controller().propose(
            "SET_LINE_STOP_POLICY",
            {"line_id": 40},
            {"stop_index": 0, "load_mode": 0, "min_waiting_time": 120, "max_waiting_time": 30},
        )
        self.assertEqual("INVALID_PARAMETERS", result["status"])

    def test_departure_hold_is_bounded_and_fail_closed_before_live_verification(self):
        controller = self.controller()
        invalid = controller.propose("HOLD_VEHICLE_AT_TERMINAL", {"vehicle_id": 50}, {"max_hold_seconds": 601})
        self.assertEqual("INVALID_PARAMETERS", invalid["status"])
        proposal = controller.propose("HOLD_VEHICLE_AT_TERMINAL", {"vehicle_id": 50}, {"max_hold_seconds": 60})
        execution = controller.execute(proposal["operation_id"], dry_run=False)
        self.assertEqual("OPERATION_NOT_VERIFIED", execution["execution_status"])
        self.assertFalse(execution["command_sent"])

    def test_hold_is_blocked_while_paused_but_release_remains_available(self):
        self.state["simulation"].update({"paused": True, "speed_multiplier": 0})
        controller = self.controller(allow_unverified_test=True)
        hold = controller.propose("HOLD_VEHICLE_AT_TERMINAL", {"vehicle_id": 50}, {"max_hold_seconds": 60})
        release = controller.propose("RELEASE_VEHICLE_FROM_HOLD", {"vehicle_id": 50}, {})
        self.assertEqual("SIMULATION_NOT_RUNNING", hold["status"])
        self.assertEqual("PROPOSED", release["status"])

    def test_authorized_hold_and_release_verify_exact_departure_control(self):
        def executor(command):
            manual = command["operation_type"] == "HOLD_VEHICLE_AT_TERMINAL"
            self.state["vehicles"][0]["departure_control"] = {
                "manual": manual,
                "command_confirmed": True,
            }
            self.state["vehicles"][0]["raw_autoDeparture"] = not manual
            self.state["sequence"] += 1
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}

        controller = self.controller(executor, allow_unverified_test=True)
        hold = controller.propose("HOLD_VEHICLE_AT_TERMINAL", {"vehicle_id": 50}, {"max_hold_seconds": 60})
        self.assertTrue(controller.execute(hold["operation_id"], dry_run=False)["command_sent"])
        self.assertEqual("POSTCONDITION_VERIFIED", controller.verify(hold["operation_id"])["status"])
        release = controller.propose("RELEASE_VEHICLE_FROM_HOLD", {"vehicle_id": 50}, {})
        self.assertTrue(controller.execute(release["operation_id"], dry_run=False)["command_sent"])
        self.assertEqual("POSTCONDITION_VERIFIED", controller.verify(release["operation_id"])["status"])

    def test_hold_and_release_have_bounded_manual_task_goals(self):
        def snapshot(force):
            if force:
                self.state["sequence"] += 1
            return SnapshotIndex(deepcopy(self.state))

        def executor(command):
            vehicle = next(item for item in self.state["vehicles"] if item["entity_id"] == command["target"]["vehicle_id"])
            vehicle["departure_control"] = {"manual": command["operation_type"] == "HOLD_VEHICLE_AT_TERMINAL", "command_confirmed": True}
            vehicle["raw_autoDeparture"] = command["operation_type"] != "HOLD_VEHICLE_AT_TERMINAL"
            return {"accepted": True, "engine_command_sent": True, "code": "EXECUTED"}

        tasks = TaskOrchestrator(snapshot, OperationController(snapshot, executor))
        for goal_type, goal in (
            ("HOLD_VEHICLE_AT_TERMINAL_GOAL", {"vehicle_id": 50, "max_hold_seconds": 30}),
            ("RELEASE_VEHICLE_FROM_HOLD_GOAL", {"vehicle_id": 50}),
        ):
            task = tasks.create(goal_type, goal)
            self.assertEqual("WAITING_FOR_APPROVAL", tasks.plan(task["task_id"])["status"])
            tasks.approve(task["task_id"])
            self.assertEqual("COMPLETED", tasks.continue_task(task["task_id"])["status"])


if __name__ == "__main__":
    unittest.main()
