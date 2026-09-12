"""One-shot dedicated-save SELL_VEHICLE acceptance harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.operations import OperationController
from tpf2_mcp.snapshot import SnapshotIndex


def write(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Irreversibly sell one newly purchased disposable test vehicle.")
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()

    bridge = BridgeClient(timeout_seconds=20)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    before = current.vehicle_by_id.get(args.vehicle_id)
    if before is None:
        raise SystemExit(f"vehicle {args.vehicle_id} not found")
    write(args.evidence_directory, "before.json", before)

    confirmation = f"SELL_VEHICLE:{args.vehicle_id}"
    controller = OperationController(
        snapshot,
        lambda envelope: bridge.call("execute_operation", envelope),
        allow_unverified_test=True,
    )
    proposal = controller.propose("SELL_VEHICLE", {"vehicle_id": args.vehicle_id}, {"confirmation": confirmation})
    write(args.evidence_directory, "proposal.json", proposal)
    execution = controller.execute(proposal["operation_id"], dry_run=False)
    write(args.evidence_directory, "execution.json", execution)
    if not execution.get("command_sent"):
        raise SystemExit(f"command was not sent: {execution.get('execution_status')}")

    verification = controller.verify(proposal["operation_id"])
    write(args.evidence_directory, "verification.json", verification)
    result = {
        "status": verification["status"],
        "vehicle_id": args.vehicle_id,
        "previous_line_id": before.get("line_id"),
        "vehicle_present": args.vehicle_id in current.vehicle_by_id,
        "confirmation": confirmation,
        "command_result": execution.get("command_result"),
    }
    write(args.evidence_directory, "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "POSTCONDITION_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
