"""Add one verified template vehicle to a line through a bounded Task."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-id", type=int, required=True)
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

    before_line = current.line_scorecard(args.line_id)
    if before_line is None:
        raise SystemExit(f"line {args.line_id} not found")
    source = current.vehicle_by_id.get(args.source_vehicle_id)
    if source is None or source.get("line_id") != args.line_id or source.get("raw_depot") != args.depot_id:
        raise SystemExit("source vehicle/depot evidence no longer matches the target line")

    operations = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope))
    tasks = TaskOrchestrator(snapshot, operations)
    task = tasks.create("EXPAND_LINE_WITH_VEHICLE_GOAL", {
        "line_id": args.line_id,
        "source_vehicle_id": args.source_vehicle_id,
        "depot_id": args.depot_id,
        "stop_index": 0,
    }, max_steps=2, max_write_operations=2)
    task = tasks.plan(task["task_id"])
    if task["status"] == "WAITING_FOR_APPROVAL":
        task = tasks.approve(task["task_id"])
    while task["status"] == "READY":
        task = tasks.continue_task(task["task_id"])

    after_line = current.line_scorecard(args.line_id)
    result = {
        "status": task["status"],
        "task_id": task.get("task_id"),
        "line_id": args.line_id,
        "created_vehicle_id": task.get("goal", {}).get("created_vehicle_id"),
        "before": before_line,
        "after": after_line,
        "steps": task.get("steps", []),
        "result": task.get("result"),
    }
    save(args.evidence_directory / "result.json", result)
    print(json.dumps({
        "status": result["status"],
        "line_id": args.line_id,
        "created_vehicle_id": result["created_vehicle_id"],
        "before_vehicle_count": before_line["network"]["vehicle_count"],
        "after_vehicle_count": after_line["network"]["vehicle_count"] if after_line else None,
        "before_frequency_seconds": before_line["network"]["frequency_seconds"],
        "after_frequency_seconds": after_line["network"]["frequency_seconds"] if after_line else None,
    }, ensure_ascii=False))
    return 0 if task["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
