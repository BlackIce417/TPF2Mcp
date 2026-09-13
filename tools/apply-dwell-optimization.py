"""Safely dry-run or apply the executable entries in a dwell plan."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient  # noqa: E402
from tpf2_mcp.config import state_dir  # noqa: E402
from tpf2_mcp.operations import OperationController  # noqa: E402
from tpf2_mcp.snapshot import SnapshotIndex  # noqa: E402
from tpf2_mcp.tasks.orchestrator import TaskOrchestrator  # noqa: E402
from tpf2_mcp.work_log import McpWorkLogStore  # noqa: E402


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "diagnostics" / "rail-operations" / "dwell-optimization-plan.json")
    parser.add_argument("--evidence-directory", type=Path, default=ROOT / "diagnostics" / "rail-operations" / "dwell-application")
    parser.add_argument("--execute", action="store_true", help="Send the approved bounded write; default is dry-run.")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    ready = [item for item in plan.get("recommendations", []) if item.get("apply_ready")]
    # A full state refresh on this large save currently takes about 25 seconds.
    bridge = BridgeClient(timeout_seconds=60)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    simulation = current.state.get("simulation") if isinstance(current.state.get("simulation"), dict) else {}
    multiplier = simulation.get("speed_multiplier")
    running = simulation.get("paused") is not True and isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool) and multiplier > 0
    if args.execute and not running:
        blocked = {"status": "EXECUTION_BLOCKED_SIMULATION_NOT_RUNNING", "command_sent": False, "simulation": simulation}
        write(args.evidence_directory / "00-simulation-gate.json", blocked)
        print(json.dumps(blocked, ensure_ascii=False))
        return 3

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    preflight = {"at": datetime.now(timezone.utc).isoformat(), "execute": args.execute, "snapshot_sequence": current.state.get("sequence"), "entries": [], "status": "READY"}
    for item in ready:
        line = current.line_by_id.get(item["line_id"])
        stop_index = item["stop_index"]
        stop = line.get("stops", [])[stop_index] if line and stop_index < len(line.get("stops", [])) else None
        observed = stop.get("policy") if stop else None
        matches = observed == item["current_policy"]
        preflight["entries"].append({"line_id": item["line_id"], "line_name": item.get("line_name"), "stop_index": stop_index, "station_name": item.get("station_name"), "expected_current_policy": item["current_policy"], "observed_current_policy": observed, "recommended_policy": item["recommended_policy"], "precondition_matches": matches})
        if not matches:
            preflight["status"] = "STALE_PLAN"
    write(args.evidence_directory / "01-preflight.json", preflight)
    if not ready or preflight["status"] != "READY":
        print(json.dumps(preflight, ensure_ascii=False))
        return 2

    rollback = {"schema_version": 1, "created_at": preflight["at"], "status": "NOT_APPLIED", "operations": [{"goal_type": "SET_LINE_STOP_POLICY_GOAL", "line_id": item["line_id"], "stop_index": item["stop_index"], **item["current_policy"]} for item in ready]}
    write(args.evidence_directory / "rollback-plan.json", rollback)
    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), journal_path=args.evidence_directory / "operations.jsonl")

    if not args.execute:
        dry_runs = []
        for item in ready:
            proposal = controller.propose("SET_LINE_STOP_POLICY", {"line_id": item["line_id"]}, {"stop_index": item["stop_index"], **item["recommended_policy"]})
            dry_runs.append({"proposal": proposal, "execution": controller.execute(proposal.get("operation_id", ""), dry_run=True)})
        result = {"status": "DRY_RUN_VALIDATED", "command_sent": False, "operation_count": len(dry_runs), "operations": dry_runs}
        write(args.evidence_directory / "02-dry-run.json", result)
        print(json.dumps({"status": result["status"], "operation_count": len(dry_runs)}, ensure_ascii=False))
        return 0

    tasks = TaskOrchestrator(snapshot, controller, journal_path=args.evidence_directory / "tasks.jsonl")
    results = []
    for item in ready:
        goal = {"line_id": item["line_id"], "stop_index": item["stop_index"], **item["recommended_policy"]}
        task = tasks.create("SET_LINE_STOP_POLICY_GOAL", goal, policy="MANUAL", max_steps=1, max_write_operations=1)
        task = tasks.plan(task["task_id"], fresh=False)
        task = tasks.approve(task["task_id"])
        task = tasks.continue_task(task["task_id"])
        results.append(task)
        if task.get("status") != "COMPLETED":
            break
    success = len(results) == len(ready) and all(item.get("status") == "COMPLETED" for item in results)
    if success:
        work_log = McpWorkLogStore(state_dir() / "mcp-work-log.sqlite3")
        for recommendation, task in zip(ready, results):
            work_log.record_verified_action(
                task["save_id"],
                f"task:{task['task_id']}:dwell",
                "SET_LINE_STOP_POLICY",
                f"调整停站上限 · {recommendation.get('line_name') or recommendation['line_id']} · "
                f"{recommendation.get('station_name') or ('停站 ' + str(recommendation['stop_index']))} · "
                f"{recommendation['current_policy'].get('max_waiting_time')}→"
                f"{recommendation['recommended_policy'].get('max_waiting_time')} 秒",
                line_id=recommendation["line_id"],
                details={"recommendation": recommendation, "task_id": task["task_id"]},
            )
    rollback["status"] = "AVAILABLE" if success else "REVIEW_REQUIRED"
    write(args.evidence_directory / "rollback-plan.json", rollback)
    result = {"status": "POSTCONDITION_VERIFIED" if success else "FAILED", "operation_count": len(results), "tasks": results}
    write(args.evidence_directory / "03-execution.json", result)
    print(json.dumps({"status": result["status"], "operation_count": len(results)}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
