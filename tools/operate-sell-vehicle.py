"""Sell one explicitly identified vehicle through a confirmed Task."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator
from tpf2_mcp.config import state_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bridge = BridgeClient(timeout_seconds=20)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    if args.vehicle_id not in current.vehicle_by_id:
        raise SystemExit("vehicle is not present")
    state = state_dir()
    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), journal_path=state / "operations.jsonl")
    tasks = TaskOrchestrator(snapshot, controller, journal_path=state / "tasks.jsonl")
    task = tasks.create("SELL_VEHICLE_GOAL", {"vehicle_id": args.vehicle_id, "confirmation": f"SELL_VEHICLE:{args.vehicle_id}"})
    task = tasks.plan(task["task_id"])
    if task["status"] == "WAITING_FOR_APPROVAL":
        task = tasks.approve(task["task_id"])
    if task["status"] == "READY":
        task = tasks.continue_task(task["task_id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": task["status"], "vehicle_id": args.vehicle_id, "result": task.get("result")}, ensure_ascii=False))
    return 0 if task["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
