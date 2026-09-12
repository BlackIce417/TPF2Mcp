"""Safely replace all vehicles on one line: add/verify replacements before selling originals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.config import state_dir
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex
from tpf2_mcp.tasks import TaskOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-id", type=int, required=True)
    parser.add_argument("--source-vehicle-id", type=int, required=True)
    parser.add_argument("--depot-id", type=int, required=True)
    parser.add_argument("--expected-old-vehicle-id", type=int, action="append", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.count != len(args.expected_old_vehicle_id) or not 1 <= args.count <= 10:
        raise SystemExit("replacement count must equal the exact old-vehicle list and be 1..10")

    bridge = BridgeClient(timeout_seconds=25)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    before = sorted(item["entity_id"] for item in current.vehicles_by_line.get(args.line_id, []))
    if before != sorted(args.expected_old_vehicle_id):
        raise SystemExit(f"target line fleet changed: expected {sorted(args.expected_old_vehicle_id)}, observed {before}")
    source = current.vehicle_by_id.get(args.source_vehicle_id)
    if source is None:
        raise SystemExit("source template vehicle no longer exists")

    state = state_dir()
    operations = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), journal_path=state / "operations.jsonl")
    tasks = TaskOrchestrator(snapshot, operations, journal_path=state / "tasks.jsonl")
    evidence, replacements = [], []

    def run(task: dict) -> dict:
        task = tasks.plan(task["task_id"])
        if task["status"] == "WAITING_FOR_APPROVAL":
            task = tasks.approve(task["task_id"])
        while task["status"] == "READY":
            task = tasks.continue_task(task["task_id"])
        evidence.append(task)
        return task

    for _ in range(args.count):
        task = tasks.create("BUY_AND_ASSIGN_VEHICLE_GOAL", {
            "depot_id": args.depot_id, "source_vehicle_id": args.source_vehicle_id,
            "target_line_id": args.line_id, "stop_index": 0,
        }, max_steps=2, max_write_operations=2)
        task = run(task)
        if task["status"] != "COMPLETED":
            break
        replacements.append(task.get("goal", {}).get("created_vehicle_id"))

    current = SnapshotIndex(bridge.game_state(force_refresh=True))
    assigned = {item["entity_id"] for item in current.vehicles_by_line.get(args.line_id, [])}
    additions_verified = len(replacements) == args.count and all(item in assigned for item in replacements)
    if additions_verified:
        for vehicle_id in args.expected_old_vehicle_id:
            task = tasks.create("SELL_VEHICLE_GOAL", {"vehicle_id": vehicle_id, "confirmation": f"SELL_VEHICLE:{vehicle_id}"})
            task = run(task)
            if task["status"] != "COMPLETED":
                break

    current = SnapshotIndex(bridge.game_state(force_refresh=True))
    after = sorted(item["entity_id"] for item in current.vehicles_by_line.get(args.line_id, []))
    complete = additions_verified and sorted(after) == sorted(replacements) and not any(item in current.vehicle_by_id for item in args.expected_old_vehicle_id)
    result = {"status": "COMPLETED" if complete else "PARTIAL_OR_FAILED", "line_id": args.line_id,
              "before_vehicle_ids": before, "replacement_vehicle_ids": replacements, "after_vehicle_ids": after,
              "old_vehicles_absent": [item not in current.vehicle_by_id for item in args.expected_old_vehicle_id], "tasks": evidence}
    args.evidence_directory.mkdir(parents=True, exist_ok=True)
    (args.evidence_directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "line_id", "before_vehicle_ids", "replacement_vehicle_ids", "after_vehicle_ids", "old_vehicles_absent")}, ensure_ascii=False))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
