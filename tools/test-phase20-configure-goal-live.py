"""Live acceptance for CREATE_AND_CONFIGURE_LINE_GOAL on an authorized test save."""
from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--start-station-id", type=int, required=True)
    parser.add_argument("--end-station-id", type=int, required=True)
    parser.add_argument("--source-vehicle-id", type=int, required=True)
    parser.add_argument("--depot-id", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--vehicle-count", type=int, default=1, choices=range(1, 5))
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
    goal = {
        "name": args.name,
        "start_station_id": args.start_station_id,
        "via_station_ids": [],
        "end_station_id": args.end_station_id,
        "source_vehicle_id": args.source_vehicle_id,
        "depot_id": args.depot_id,
        "vehicle_count": args.vehicle_count,
    }
    budget = 2 + 2 * args.vehicle_count
    task = tasks.create("CREATE_AND_CONFIGURE_LINE_GOAL", goal, max_steps=budget, max_write_operations=budget)
    write(args.evidence_directory, "01-created.json", task)
    task = tasks.plan(task["task_id"])
    write(args.evidence_directory, "02-planned.json", task)
    task = tasks.approve(task["task_id"])
    write(args.evidence_directory, "03-approved.json", task)
    for number in range(1, budget + 1):
        task = tasks.continue_task(task["task_id"])
        write(args.evidence_directory, f"04-step-{number}.json", task)
        if task["status"] in {"COMPLETED", "FAILED", "BLOCKED", "PARTIALLY_COMPLETED"}:
            break
    result = {
        "status": task["status"],
        "created_line_id": task.get("goal", {}).get("created_line_id"),
        "created_vehicle_id": task.get("goal", {}).get("created_vehicle_id"),
        "assigned_vehicle_ids": task.get("goal", {}).get("assigned_vehicle_ids", []),
        "writes_used": task.get("budget", {}).get("writes_used"),
        "step_operations": [step.get("operation_type") for step in task.get("steps", [])],
        "step_statuses": [step.get("status") for step in task.get("steps", [])],
        "result": task.get("result"),
    }
    write(args.evidence_directory, "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
