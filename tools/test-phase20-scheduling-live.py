"""Create a disposable line and verify one stop scheduling-policy update."""
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-station-id", type=int, required=True)
    parser.add_argument("--end-station-id", type=int, required=True)
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
    create = controller.propose("CREATE_LINE", {}, {"name": "TPF2 MCP Phase20 Scheduling", "start_station_id": args.start_station_id, "via_station_ids": [], "end_station_id": args.end_station_id})
    write(args.evidence_directory, "01-create-proposal.json", create)
    create_execution = controller.execute(create["operation_id"], dry_run=False)
    write(args.evidence_directory, "02-create-execution.json", create_execution)
    create_verification = controller.verify(create["operation_id"])
    write(args.evidence_directory, "03-create-verification.json", create_verification)
    created = create_verification.get("verification", {}).get("new_entities", [])
    if len(created) != 1:
        raise SystemExit("disposable test line was not uniquely observed")
    line_id = created[0]["entity_id"]

    parameters = {"stop_index": 0, "load_mode": 1, "min_waiting_time": 30, "max_waiting_time": 120}
    proposal = controller.propose("SET_LINE_STOP_POLICY", {"line_id": line_id}, parameters)
    write(args.evidence_directory, "04-policy-proposal.json", proposal)
    execution = controller.execute(proposal["operation_id"], dry_run=False)
    write(args.evidence_directory, "05-policy-execution.json", execution)
    verification = controller.verify(proposal["operation_id"])
    write(args.evidence_directory, "06-policy-verification.json", verification)
    result = {"status": verification["status"], "line_id": line_id, "stop_index": 0, "policy": parameters, "verification": verification.get("verification")}
    write(args.evidence_directory, "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "POSTCONDITION_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
