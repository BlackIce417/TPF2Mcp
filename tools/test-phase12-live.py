"""Dedicated-save-only task-orchestration acceptance harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


def save(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-id", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    bridge, current = BridgeClient(timeout_seconds=20), None

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if current is None or force: current = SnapshotIndex(bridge.game_state(force_refresh=force))
        return current

    original = snapshot(True).line_by_id.get(args.line_id)
    if original is None: raise SystemExit(f"line {args.line_id} not found")
    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope))
    tasks = TaskOrchestrator(snapshot, controller)
    save(args.evidence_directory, "before.json", original)
    task = tasks.create("RENAME_LINE_GOAL", {"line_id": args.line_id, "desired_name": "TPF2 MCP Phase12 Task Test"})
    save(args.evidence_directory, "task-created.json", task)
    save(args.evidence_directory, "plan.json", tasks.plan(task["task_id"]))
    save(args.evidence_directory, "approved.json", tasks.approve(task["task_id"]))
    completed = tasks.continue_task(task["task_id"])
    save(args.evidence_directory, "task-completed.json", completed)
    save(args.evidence_directory, "after.json", snapshot(False).line_by_id[args.line_id])
    if completed["status"] != "COMPLETED": raise SystemExit(f"task did not complete: {completed['status']}")
    restore = tasks.create("RESTORE_LINE_NAME_GOAL", {"line_id": args.line_id, "desired_name": original["name"]})
    tasks.plan(restore["task_id"]); tasks.approve(restore["task_id"])
    restored = tasks.continue_task(restore["task_id"])
    save(args.evidence_directory, "restore-task.json", restored)
    save(args.evidence_directory, "restored.json", snapshot(False).line_by_id[args.line_id])
    if restored["status"] != "COMPLETED": raise SystemExit(f"restore did not complete: {restored['status']}")
    save(args.evidence_directory, "result.json", {"task": completed, "restore": restored})
    print(json.dumps({"task": completed["status"], "restore": restored["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
