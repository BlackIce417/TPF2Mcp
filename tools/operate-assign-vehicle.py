"""Assign one existing unassigned vehicle through a bounded Task."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--line-id", type=int, required=True)
    parser.add_argument("--stop-index", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bridge = BridgeClient(timeout_seconds=20)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    vehicle = current.vehicle_by_id.get(args.vehicle_id)
    if vehicle is None or vehicle.get("line_id") not in {None, -1}:
        raise SystemExit("vehicle is missing or no longer unassigned")
    if args.line_id not in current.line_by_id:
        raise SystemExit("line is missing")
    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope))
    tasks = TaskOrchestrator(snapshot, controller)
    task = tasks.create("ASSIGN_VEHICLE_TO_LINE_GOAL", {"vehicle_id": args.vehicle_id, "line_id": args.line_id, "stop_index": args.stop_index})
    task = tasks.plan(task["task_id"])
    if task["status"] == "WAITING_FOR_APPROVAL":
        task = tasks.approve(task["task_id"])
    if task["status"] == "READY":
        task = tasks.continue_task(task["task_id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": task["status"], "vehicle_id": args.vehicle_id, "line_id": args.line_id, "result": task.get("result")}, ensure_ascii=False))
    return 0 if task["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
