"""Dedicated-save-only Phase 11 rename/rollback acceptance harness."""
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
    parser = argparse.ArgumentParser(description="Run only in an explicitly authorized TPF2 test save.")
    parser.add_argument("--line-id", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    bridge = BridgeClient(timeout_seconds=20)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), allow_unverified_test=True)
    before = current.line_by_id.get(args.line_id)
    if before is None:
        raise SystemExit(f"line {args.line_id} not found")
    write(args.evidence_directory, "before.json", before)
    proposal = controller.propose("RENAME_LINE", {"line_id": args.line_id}, {"name": "TPF2 MCP Phase11 Test"})
    write(args.evidence_directory, "proposal.json", proposal)
    execution = controller.execute(proposal["operation_id"], dry_run=False)
    write(args.evidence_directory, "command.json", execution.get("command"))
    write(args.evidence_directory, "command-response.json", execution.get("command_result"))
    duplicate = bridge.call("execute_operation", execution["command"])
    write(args.evidence_directory, "duplicate-operation.json", duplicate)
    verified = controller.verify(proposal["operation_id"])
    write(args.evidence_directory, "after.json", current.line_by_id[args.line_id])
    write(args.evidence_directory, "rename-verification.json", verified)
    if verified["status"] != "POSTCONDITION_VERIFIED":
        raise SystemExit("rename postcondition not met; rollback was not attempted")
    rollback = controller.rollback(proposal["operation_id"])
    write(args.evidence_directory, "rollback-proposal.json", rollback)
    rollback_execution = controller.execute(rollback["operation_id"], dry_run=False)
    write(args.evidence_directory, "rollback-command-response.json", rollback_execution.get("command_result"))
    rollback_verified = controller.verify(rollback["operation_id"])
    write(args.evidence_directory, "rollback-after.json", current.line_by_id[args.line_id])
    write(args.evidence_directory, "rollback-verification.json", rollback_verified)
    result = {"rename": verified, "rollback": rollback_verified, "duplicate": duplicate}
    write(args.evidence_directory, "result.json", result)
    if rollback_verified["status"] != "POSTCONDITION_VERIFIED":
        raise SystemExit("rollback postcondition not met")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
