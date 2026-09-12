"""Verify that route, scheduling, purchase, and sale mutations run only through Tasks."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


def write(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-id", type=int)
    parser.add_argument("--station-a", type=int, required=True)
    parser.add_argument("--station-b", type=int, required=True)
    parser.add_argument("--source-vehicle-id", type=int, required=True)
    parser.add_argument("--depot-id", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()

    bridge = BridgeClient(timeout_seconds=20)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    operations = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope))
    tasks = TaskOrchestrator(snapshot, operations)

    def run(number: int, goal_type: str, goal: dict, budget: int = 1) -> dict:
        task = tasks.create(goal_type, goal, max_steps=budget, max_write_operations=budget)
        task = tasks.plan(task["task_id"])
        if task["status"] == "WAITING_FOR_APPROVAL":
            task = tasks.approve(task["task_id"])
        while task["status"] == "READY":
            task = tasks.continue_task(task["task_id"])
        write(args.evidence_directory, f"{number:02d}-{goal_type.lower()}.json", task)
        if task["status"] != "COMPLETED":
            raise SystemExit(f"{goal_type} ended as {task['status']}: {task.get('result')}")
        return task

    line_id = args.line_id
    next_number = 1
    if line_id is None:
        created = run(next_number, "CREATE_LINE_GOAL", {
            "name": f"MCP Final Gate {datetime.now().strftime('%H%M%S')}",
            "start_station_id": args.station_a,
            "via_station_ids": [],
            "end_station_id": args.station_b,
        })
        line_id = created.get("goal", {}).get("created_line_id")
        if not isinstance(line_id, int):
            line_id = created.get("result", {}).get("evidence", {}).get("created_line_id")
        if not isinstance(line_id, int):
            raise SystemExit("CREATE_LINE_GOAL did not discover one line")
        next_number += 1

    # Reverse the known two-stop route so this is a real SET_LINE_STOPS mutation.
    route = run(next_number, "SET_LINE_STOPS_GOAL", {"line_id": line_id, "start_station_id": args.station_b, "via_station_ids": [], "end_station_id": args.station_a})
    policy = run(next_number + 1, "SET_LINE_STOP_POLICY_GOAL", {"line_id": line_id, "stop_index": 0, "load_mode": 0, "min_waiting_time": 0, "max_waiting_time": 60})
    purchase = run(next_number + 2, "BUY_VEHICLE_GOAL", {"depot_id": args.depot_id, "source_vehicle_id": args.source_vehicle_id})
    vehicle_id = purchase["goal"].get("created_vehicle_id")
    if not isinstance(vehicle_id, int):
        raise SystemExit("BUY_VEHICLE_GOAL did not discover one vehicle")
    sale = run(next_number + 3, "SELL_VEHICLE_GOAL", {"vehicle_id": vehicle_id, "confirmation": f"SELL_VEHICLE:{vehicle_id}"})
    result = {
        "status": "POSTCONDITION_VERIFIED",
        "task_only": True,
        "line_id": line_id,
        "route": route["result"]["evidence"]["observed_route"],
        "policy": policy["result"]["evidence"]["observed_policy"],
        "purchased_then_sold_vehicle_id": vehicle_id,
        "sale_vehicle_present": sale["result"]["evidence"]["vehicle_present"],
        "goal_types": ["SET_LINE_STOPS_GOAL", "SET_LINE_STOP_POLICY_GOAL", "BUY_VEHICLE_GOAL", "SELL_VEHICLE_GOAL"],
    }
    write(args.evidence_directory, "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
