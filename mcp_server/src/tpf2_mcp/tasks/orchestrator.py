from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid
from typing import Any, Callable

from ..journal import JsonlJournal
from ..operations.capabilities import capability
from ..operations.controller import OperationController
from .goals import goal_capability, planned_steps, satisfied, scope_for
from .policy import POLICIES, can_auto_execute


class TaskOrchestrator:
    """Bounded task state machine; never accesses a bridge or Lua directly."""
    def __init__(self, snapshot_provider: Callable[[bool], Any], operations: OperationController, journal_path: Any = None):
        self._snapshot_provider, self._operations = snapshot_provider, operations
        self._persistent_journal = JsonlJournal(journal_path)
        self._tasks = self._persistent_journal.latest("task_id")
        self._order = sorted(self._tasks, key=lambda key: self._tasks[key].get("timeline", [{}])[0].get("at", "") if self._tasks[key].get("timeline") else "")

    @staticmethod
    def _now() -> str: return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _event(task: dict[str, Any], event: str, **data: Any) -> None:
        task["timeline"].append({"event": event, "at": datetime.now(timezone.utc).isoformat(), **data})

    def create(self, goal_type: str, goal: dict[str, Any], policy: str = "MANUAL", max_steps: int = 1, max_replans: int = 3, max_write_operations: int = 1) -> dict[str, Any]:
        if policy not in POLICIES: return {"status": "INVALID_POLICY", "reason": "policy must be MANUAL, AUTO_SAFE, or PLAN_ONLY"}
        if not all(isinstance(value, int) and 1 <= value <= maximum for value, maximum in ((max_steps, 10), (max_replans, 3), (max_write_operations, 10))): return {"status": "INVALID_BUDGET", "reason": "max_steps 1..10, max_replans 1..3, max_write_operations 1..10"}
        cap = goal_capability(goal_type)
        if cap is None: return {"status": "UNKNOWN_GOAL", "goal_type": goal_type}
        if goal_type in {"RENAME_LINE_GOAL", "RESTORE_LINE_NAME_GOAL"} and (not isinstance(goal.get("line_id"), int) or not isinstance(goal.get("desired_name"), str) or not goal["desired_name"].strip()): return {"status": "INVALID_GOAL", "reason": "Rename goals require line_id and desired_name."}
        required = {
            "BUY_VEHICLE_GOAL": ("depot_id", "source_vehicle_id"),
            "ASSIGN_VEHICLE_TO_LINE_GOAL": ("vehicle_id", "line_id"),
            "EXPAND_LINE_WITH_VEHICLE_GOAL": ("depot_id", "source_vehicle_id", "line_id"),
            "BUY_AND_ASSIGN_VEHICLE_GOAL": ("depot_id", "source_vehicle_id", "target_line_id"),
            "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL": ("source_line_id",),
            "CREATE_LINE_GOAL": ("start_station_id", "end_station_id"),
            "CREATE_AND_STAFF_LINE_GOAL": ("start_station_id", "end_station_id", "vehicle_template_source_line_id", "vehicle_count"),
            "CREATE_AND_CONFIGURE_LINE_GOAL": ("start_station_id", "end_station_id", "source_vehicle_id", "depot_id"),
            "SET_LINE_STOPS_GOAL": ("line_id", "start_station_id", "end_station_id"),
            "SET_LINE_STOP_POLICY_GOAL": ("line_id", "stop_index", "load_mode"),
            "HOLD_VEHICLE_AT_TERMINAL_GOAL": ("vehicle_id", "max_hold_seconds"),
            "RELEASE_VEHICLE_FROM_HOLD_GOAL": ("vehicle_id",),
            "SELL_VEHICLE_GOAL": ("vehicle_id",),
        }.get(goal_type, ())
        if any(not isinstance(goal.get(field), int) for field in required): return {"status": "INVALID_GOAL", "reason": f"{goal_type} requires integer {', '.join(required)}."}
        if goal_type == "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL" and (not isinstance(goal.get("name"), str) or not goal["name"].strip()): return {"status": "INVALID_GOAL", "reason": "CREATE_LINE_FROM_SOURCE_ROUTE_GOAL requires non-empty name."}
        if goal_type in {"CREATE_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}:
            if not isinstance(goal.get("name"), str) or not goal["name"].strip() or not isinstance(goal.get("via_station_ids", []), list) or not all(isinstance(value, int) for value in goal.get("via_station_ids", [])):
                return {"status": "INVALID_GOAL", "reason": f"{goal_type} requires name and an integer via_station_ids list."}
        if goal_type == "CREATE_AND_CONFIGURE_LINE_GOAL" and (max_steps < 4 or max_write_operations < 4):
            return {"status": "INVALID_BUDGET", "reason": "CREATE_AND_CONFIGURE_LINE_GOAL requires sufficient step and write budgets."}
        if goal_type == "CREATE_AND_CONFIGURE_LINE_GOAL":
            vehicle_count = goal.get("vehicle_count", 1)
            required_writes = 2 + 2 * vehicle_count if isinstance(vehicle_count, int) else 0
            if not isinstance(vehicle_count, int) or not 1 <= vehicle_count <= 4:
                return {"status": "INVALID_GOAL", "reason": "vehicle_count must be an integer from 1 to 4."}
            if max_steps < required_writes or max_write_operations < required_writes:
                return {"status": "INVALID_BUDGET", "reason": f"CREATE_AND_CONFIGURE_LINE_GOAL with {vehicle_count} vehicles requires budgets of at least {required_writes}."}
        if goal_type == "SET_LINE_STOPS_GOAL" and (not isinstance(goal.get("via_station_ids", []), list) or not all(isinstance(value, int) for value in goal.get("via_station_ids", []))):
            return {"status": "INVALID_GOAL", "reason": "SET_LINE_STOPS_GOAL requires an integer via_station_ids list."}
        if goal_type in {"CREATE_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL", "SET_LINE_STOPS_GOAL"}:
            route = [goal["start_station_id"], *goal.get("via_station_ids", []), goal["end_station_id"]]
            if len(set(route)) != len(route):
                return {"status": "INVALID_GOAL", "reason": "REPEATED_STATION_UNSAFE: TPF2 lines loop automatically; each requested stop must be unique."}
        if goal_type == "SET_LINE_STOP_POLICY_GOAL":
            minimum, maximum = goal.get("min_waiting_time"), goal.get("max_waiting_time")
            if not isinstance(goal.get("stop_index"), int) or goal["stop_index"] < 0 or goal.get("load_mode") not in {0, 1, 2} or not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or minimum < 0 or maximum < minimum:
                return {"status": "INVALID_GOAL", "reason": "Invalid stop policy values."}
        if goal_type == "HOLD_VEHICLE_AT_TERMINAL_GOAL" and not 10 <= goal.get("max_hold_seconds", 0) <= 600:
            return {"status": "INVALID_GOAL", "reason": "max_hold_seconds must be 10..600."}
        if goal_type == "SELL_VEHICLE_GOAL" and goal.get("confirmation") != f"SELL_VEHICLE:{goal.get('vehicle_id')}":
            return {"status": "INVALID_GOAL", "reason": f"confirmation must equal SELL_VEHICLE:{goal.get('vehicle_id')}."}
        index = self._snapshot_provider(False)
        if goal_type == "CREATE_AND_STAFF_LINE_GOAL":
            if not isinstance(goal.get("name"), str) or not goal["name"].strip() or not isinstance(goal.get("vehicle_count"), int) or not 1 <= goal["vehicle_count"] <= 4:
                return {"status": "INVALID_GOAL", "reason": "CREATE_AND_STAFF_LINE_GOAL requires name and vehicle_count 1..4."}
            template_line = index.line_by_id.get(goal["vehicle_template_source_line_id"])
            requested_route = [goal["start_station_id"], *goal.get("via_station_ids", []), goal["end_station_id"]]
            template_route = [stop.get("station_id") for stop in template_line.get("stops", [])] if template_line else []
            if template_route != requested_route: return {"status": "INVALID_GOAL", "reason": "TEMPLATE_LINE_ROUTE_MISMATCH"}
            templates = sorted((item for item in index.vehicle_by_id.values() if item.get("line_id") == goal["vehicle_template_source_line_id"] and isinstance(item.get("raw_depot"), int) and item["raw_depot"] >= 0), key=lambda item: item["entity_id"])
            if not templates: return {"status": "INVALID_GOAL", "reason": "NO_VERIFIED_DEPOT_OR_TEMPLATE_VEHICLE"}
            goal["source_vehicle_id"], goal["depot_id"] = templates[0]["entity_id"], templates[0]["raw_depot"]
        task_id = f"task-{uuid.uuid4()}"
        task = {"task_id": task_id, "goal_type": goal_type, "goal": deepcopy(goal), "created_snapshot_sequence": index.state.get("sequence"), "status": "CREATED", "policy": policy, "approved": False, "scope": scope_for(goal_type, goal), "runtime_context": {}, "budget": {"max_steps": max_steps, "max_replans": max_replans, "max_write_operations": max_write_operations, "steps_used": 0, "writes_used": 0, "replans_used": 0}, "steps": [], "timeline": [], "result": None, "limitations": []}
        self._event(task, "TASK_CREATED", snapshot_sequence=index.state.get("sequence"))
        self._tasks[task_id] = task; self._order.append(task_id)
        return self._public(task)

    def plan(self, task_id: str, fresh: bool = False) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None: return {"status": "TASK_NOT_FOUND", "task_id": task_id}
        index = self._snapshot_provider(fresh)
        is_satisfied, evidence = satisfied(task["goal_type"], task["goal"], index)
        if is_satisfied:
            task["status"], task["result"] = "COMPLETED", {"reason": "GOAL_ALREADY_SATISFIED", "evidence": evidence, "executed_operations": task["budget"]["writes_used"]}
            self._event(task, "TASK_COMPLETED", reason="GOAL_ALREADY_SATISFIED", snapshot_sequence=index.state.get("sequence")); return self._public(task)
        cap = goal_capability(task["goal_type"])
        if task["policy"] == "PLAN_ONLY" or not cap or cap["status"] == "PLAN_ONLY":
            task["status"], task["result"] = "BLOCKED", {"planning_status": "PLAN_AVAILABLE", "execution_status": "NOT_EXECUTABLE", "reason": cap.get("reason") if cap else "Unknown goal"}
            self._event(task, "PLAN_ONLY", snapshot_sequence=index.state.get("sequence")); return self._public(task)
        operation_cap = capability(cap["operation_type"])
        if not operation_cap or not operation_cap["verified"]:
            task["status"], task["result"] = "BLOCKED", {"reason": "OPERATION_NOT_VERIFIED"}; self._event(task, "TASK_BLOCKED"); return self._public(task)
        task["planned_snapshot_sequence"] = index.state.get("sequence")
        task["planned_steps"] = planned_steps(task["goal_type"], task["goal"], evidence)
        # A fresh snapshot may advance its sequence after an already verified
        # step.  Replanning must retain that progress, never restart a buy.
        next_index = min(task.get("next_step_index", 0), len(task["planned_steps"]) - 1)
        task["next_step_index"] = next_index
        task["next_step"] = task["planned_steps"][next_index]
        if task["next_step"]["operation_type"] == "SET_LINE_STOPS" and task["next_step"]["target"].get("line_id") is None:
            task["next_step"]["target"]["line_id"] = task["goal"].get("created_line_id")
        if task["next_step"]["operation_type"] == "ASSIGN_VEHICLE_TO_LINE" and task["next_step"]["target"].get("vehicle_id") is None:
            task["next_step"]["target"]["vehicle_id"] = task["goal"].get("created_vehicle_id")
            if task["goal_type"] in {"CREATE_AND_STAFF_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}: task["next_step"]["target"]["line_id"] = task["goal"].get("created_line_id")
        task["status"] = "READY" if task["approved"] or can_auto_execute(task["policy"], operation_cap) else "WAITING_FOR_APPROVAL"
        self._event(task, "PLAN_CREATED", snapshot_sequence=task["planned_snapshot_sequence"], next_status=task["status"])
        return self._public(task)

    def approve(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None: return {"status": "TASK_NOT_FOUND", "task_id": task_id}
        if task["status"] != "WAITING_FOR_APPROVAL": return {"status": "APPROVAL_NOT_APPLICABLE", "task": self._public(task)}
        task["approved"] = True; task["status"] = "READY"; self._event(task, "STEP_APPROVED")
        return self._public(task)

    def continue_task(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None: return {"status": "TASK_NOT_FOUND", "task_id": task_id}
        if task["status"] in {"COMPLETED", "CANCELLED", "BLOCKED", "FAILED", "PARTIALLY_COMPLETED"}: return self._public(task)
        # Re-observe before every mutation. A changed sequence causes a new plan,
        # never execution of an old proposal.
        current = self._snapshot_provider(True)
        if task.get("planned_snapshot_sequence") != current.state.get("sequence"):
            # Bridge sequence identifies snapshot publications, not semantic
            # world mutations. A forced refresh therefore advances it during
            # every normal step. Rebuild the remaining step from the fresh
            # index without charging the exceptional replan budget; operation
            # preconditions still detect scoped entity changes before sending.
            task["status"] = "REPLANNING"; self._event(task, "SNAPSHOT_REFRESHED", snapshot_sequence=current.state.get("sequence"))
            self.plan(task_id, fresh=False)
        if task["status"] == "WAITING_FOR_APPROVAL": return self._public(task)
        if task["status"] != "READY": return self._public(task)
        if task["budget"]["steps_used"] >= task["budget"]["max_steps"] or task["budget"]["writes_used"] >= task["budget"]["max_write_operations"]:
            task["status"], task["result"] = "BLOCKED", {"reason": "WRITE_BUDGET_EXCEEDED"}; return self._public(task)
        step_data = task["next_step"]
        target = step_data["target"]
        line_ok = ("line_id" not in target or target["line_id"] in task["scope"].get("line_ids", [])) and ("source_line_id" not in target or target["source_line_id"] in task["scope"].get("line_ids", []))
        vehicle_ok = "vehicle_id" not in target or target["vehicle_id"] in task["scope"].get("vehicle_ids", []) or task["goal_type"] in {"EXPAND_LINE_WITH_VEHICLE_GOAL", "BUY_AND_ASSIGN_VEHICLE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}
        depot_ok = "depot_id" not in target or target["depot_id"] in task["scope"].get("depot_ids", [])
        if not (line_ok and vehicle_ok and depot_ok) or step_data["operation_type"] not in task["scope"]["operation_types"]:
            task["status"], task["result"] = "BLOCKED", {"reason": "TASK_SCOPE_VIOLATION"}; return self._public(task)
        proposal = self._operations.propose(step_data["operation_type"], step_data["target"], step_data["parameters"])
        step = {"step_id": f"step-{len(task['steps']) + 1}", "sequence": len(task["steps"]) + 1, "step_type": "GAME_OPERATION", "operation_type": step_data["operation_type"], "proposal_id": proposal.get("operation_id"), "snapshot_before": current.state.get("sequence"), "expected_effect": proposal.get("operation", {}).get("expected_effect")}
        task["steps"].append(step); task["status"] = "EXECUTING"; self._event(task, "OPERATION_PROPOSED", operation_id=proposal.get("operation_id"))
        execution = self._operations.execute(proposal.get("operation_id", ""), dry_run=False)
        task["budget"]["steps_used"] += 1
        if not execution.get("command_sent"):
            step["status"] = execution.get("execution_status", "EXECUTION_FAILED"); task["status"] = "FAILED" if not task["budget"]["writes_used"] else "PARTIALLY_COMPLETED"; task["result"] = {"reason": step["status"]}; return self._public(task)
        task["budget"]["writes_used"] += 1; self._event(task, "OPERATION_EXECUTED", operation_id=proposal["operation_id"])
        verification = self._operations.verify(proposal["operation_id"])
        step["verification"], step["snapshot_after"], step["observed_effect"] = verification.get("verification"), verification.get("verification", {}).get("after_snapshot_sequence"), verification.get("verification", {}).get("observed_change")
        step["status"] = verification.get("status")
        if verification.get("status") != "POSTCONDITION_VERIFIED": task["status"] = "FAILED"; task["result"] = {"reason": "POSTCONDITION_NOT_MET"}; return self._public(task)
        if step_data["operation_type"] == "BUY_VEHICLE":
            created = verification.get("verification", {}).get("new_entities", [])
            if len(created) == 1:
                task["goal"]["created_vehicle_id"] = created[0]["entity_id"]
                task["runtime_context"]["new_vehicle_id"] = created[0]["entity_id"]
                if task["goal_type"] in {"EXPAND_LINE_WITH_VEHICLE_GOAL", "BUY_AND_ASSIGN_VEHICLE_GOAL", "CREATE_AND_STAFF_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}:
                    task["scope"].setdefault("vehicle_ids", []).append(created[0]["entity_id"])
        if step_data["operation_type"] == "ASSIGN_VEHICLE_TO_LINE" and task["goal_type"] in {"CREATE_AND_STAFF_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}:
            task["goal"].setdefault("assigned_vehicle_ids", []).append(step_data["target"]["vehicle_id"])
        if step_data["operation_type"] in {"CREATE_LINE_FROM_SOURCE_ROUTE", "CREATE_LINE"}:
            created = verification.get("verification", {}).get("new_entities", [])
            if len(created) == 1:
                task["goal"]["created_line_id"] = created[0]["entity_id"]
                task["runtime_context"]["new_line_id"] = created[0]["entity_id"]
                task["scope"].setdefault("line_ids", []).append(created[0]["entity_id"])
        if task.get("next_step_index", 0) + 1 < len(task.get("planned_steps", [])):
            task["next_step_index"] += 1
            task["next_step"] = task["planned_steps"][task["next_step_index"]]
            if task["next_step"]["operation_type"] == "SET_LINE_STOPS" and task["next_step"]["target"].get("line_id") is None:
                task["next_step"]["target"]["line_id"] = task["goal"].get("created_line_id")
            if task["next_step"]["operation_type"] == "ASSIGN_VEHICLE_TO_LINE" and task["next_step"]["target"].get("vehicle_id") is None:
                task["next_step"]["target"]["vehicle_id"] = task["goal"].get("created_vehicle_id")
                if task["goal_type"] in {"CREATE_AND_STAFF_LINE_GOAL", "CREATE_AND_CONFIGURE_LINE_GOAL"}: task["next_step"]["target"]["line_id"] = task["goal"].get("created_line_id")
            task["planned_snapshot_sequence"] = verification.get("verification", {}).get("after_snapshot_sequence")
            task["status"] = "READY"; self._event(task, "NEXT_STEP_READY", snapshot_sequence=task["planned_snapshot_sequence"]); return self._public(task)
        final_index = self._snapshot_provider(False); done, evidence = satisfied(task["goal_type"], task["goal"], final_index)
        task["status"] = "COMPLETED" if done else "REPLANNING"; task["result"] = {"evidence": evidence, "executed_operations": task["budget"]["writes_used"]}; self._event(task, "TASK_COMPLETED" if done else "REPLAN_REQUIRED", snapshot_sequence=final_index.state.get("sequence"))
        return self._public(task)

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None: return {"status": "TASK_NOT_FOUND", "task_id": task_id}
        task["status"] = "CANCELLED"; self._event(task, "TASK_CANCELLED"); return self._public(task)

    def get(self, task_id: str) -> dict[str, Any]: return self._public(self._tasks[task_id]) if task_id in self._tasks else {"status": "TASK_NOT_FOUND", "task_id": task_id}
    def recent(self, limit: int = 20) -> dict[str, Any]: return {"tasks": [self._public(self._tasks[item]) for item in reversed(self._order[-limit:])], "limit": limit}
    def explain(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if "goal_type" not in task: return task
        return {"task_id": task_id, "status": task["status"], "goal": task["goal"], "current_step": task.get("next_step"), "timeline": task["timeline"], "remaining_write_budget": task["budget"]["max_write_operations"] - task["budget"]["writes_used"], "limitations": task["limitations"]}
    def _public(self, task: dict[str, Any]) -> dict[str, Any]:
        # Recording the latest complete state makes restart recovery idempotent;
        # it never invokes an operation executor during recovery.
        self._persistent_journal.append(deepcopy(task))
        return deepcopy(task)
