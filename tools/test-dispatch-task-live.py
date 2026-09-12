"""Verify hold/release through the bounded Task orchestration layer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient  # noqa: E402
from tpf2_mcp.operations import OperationController  # noqa: E402
from tpf2_mcp.snapshot import SnapshotIndex  # noqa: E402
from tpf2_mcp.tasks import TaskOrchestrator  # noqa: E402


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", type=int, help="Vehicle to test; omit to select a railway terminal-state vehicle.")
    parser.add_argument("--max-hold-seconds", type=int, default=30)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    bridge = BridgeClient(timeout_seconds=60)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    if args.vehicle_id is None:
        manifest = json.loads((ROOT / "ui" / "rail-map" / "rail-network-manifest.json").read_text(encoding="utf-8"))
        rail_line_ids = {item.get("entity_id") for item in manifest.get("lines", [])}
        vehicle = next((item for item in current.vehicle_by_id.values() if item.get("raw_state") == 2 and item.get("line_id") in rail_line_ids and item.get("raw_autoDeparture") is True), None)
        if vehicle is None:
            result = {"status": "TEST_BLOCKED_NO_RAIL_VEHICLE_AT_TERMINAL", "command_sent": False}
            write(args.evidence_directory / "00-vehicle-gate.json", result)
            print(json.dumps(result, ensure_ascii=False))
            return 4
        args.vehicle_id = vehicle["entity_id"]

    simulation = current.state.get("simulation") if isinstance(current.state.get("simulation"), dict) else {}
    multiplier = simulation.get("speed_multiplier")
    running = simulation.get("paused") is not True and isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool) and multiplier > 0
    if not running:
        result = {"status": "TEST_BLOCKED_SIMULATION_NOT_RUNNING", "command_sent": False, "simulation": simulation}
        write(args.evidence_directory / "00-simulation-gate.json", result)
        print(json.dumps(result, ensure_ascii=False))
        return 3

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    operations = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), allow_unverified_test=True, journal_path=args.evidence_directory / "operations.jsonl")
    tasks = TaskOrchestrator(snapshot, operations, journal_path=args.evidence_directory / "tasks.jsonl")

    def run(goal_type: str, goal: dict) -> dict:
        task = tasks.create(goal_type, goal, policy="MANUAL", max_steps=1, max_write_operations=1)
        task = tasks.plan(task["task_id"])
        task = tasks.approve(task["task_id"])
        return tasks.continue_task(task["task_id"])

    hold = run("HOLD_VEHICLE_AT_TERMINAL_GOAL", {"vehicle_id": args.vehicle_id, "max_hold_seconds": args.max_hold_seconds})
    write(args.evidence_directory / "01-hold-task.json", hold)
    release = run("RELEASE_VEHICLE_FROM_HOLD_GOAL", {"vehicle_id": args.vehicle_id})
    write(args.evidence_directory / "02-release-task.json", release)
    success = hold.get("status") == release.get("status") == "COMPLETED"
    result = {"status": "POSTCONDITION_VERIFIED" if success else "FAILED", "vehicle_id": args.vehicle_id, "hold_task_id": hold.get("task_id"), "release_task_id": release.get("task_id"), "hold_status": hold.get("status"), "release_status": release.get("status")}
    write(args.evidence_directory / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
