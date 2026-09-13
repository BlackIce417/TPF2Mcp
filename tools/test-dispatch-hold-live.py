"""Live MRE for a bounded per-vehicle terminal hold and release."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient  # noqa: E402
from tpf2_mcp.config import bridge_dir  # noqa: E402
from tpf2_mcp.operations import OperationController  # noqa: E402
from tpf2_mcp.snapshot import SnapshotIndex  # noqa: E402


def write(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", type=int, help="Vehicle to test; omit to select a terminal-state assigned vehicle from the same fresh snapshot.")
    parser.add_argument("--max-hold-seconds", type=int, default=30)
    parser.add_argument("--observe-seconds", type=float, default=8)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    bridge_directory = bridge_dir()
    bridge = BridgeClient(timeout_seconds=60)
    current = SnapshotIndex(bridge.game_state(force_refresh=True))

    simulation = current.state.get("simulation") if isinstance(current.state.get("simulation"), dict) else {}
    multiplier = simulation.get("speed_multiplier")
    running = simulation.get("paused") is not True and isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool) and multiplier > 0
    if not running:
        result = {"status": "TEST_BLOCKED_SIMULATION_NOT_RUNNING", "command_sent": False, "simulation": simulation}
        write(args.evidence_directory, "00-simulation-gate.json", result)
        print(json.dumps(result, ensure_ascii=False))
        return 3

    def snapshot(force: bool) -> SnapshotIndex:
        nonlocal current
        if force:
            current = SnapshotIndex(bridge.game_state(force_refresh=True))
        return current

    if args.vehicle_id is None:
        manifest = json.loads((ROOT / "ui" / "rail-map" / "rail-network-manifest.json").read_text(encoding="utf-8"))
        rail_line_ids = {item.get("entity_id") for item in manifest.get("lines", [])}
        vehicle = next((item for item in current.vehicle_by_id.values() if item.get("raw_state") == 2 and item.get("line_id") in rail_line_ids and item.get("raw_autoDeparture") is True), None)
        args.vehicle_id = vehicle.get("entity_id") if vehicle else None
    else:
        vehicle = current.vehicle_by_id.get(args.vehicle_id)
    if vehicle is None or not isinstance(vehicle.get("line_id"), int):
        raise SystemExit("no terminal-state assigned vehicle is available")
    controller = OperationController(snapshot, lambda envelope: bridge.call("execute_operation", envelope), allow_unverified_test=True, journal_path=args.evidence_directory / "operations.jsonl")
    hold = controller.propose("HOLD_VEHICLE_AT_TERMINAL", {"vehicle_id": args.vehicle_id}, {"max_hold_seconds": args.max_hold_seconds})
    write(args.evidence_directory, "01-hold-proposal.json", hold)
    if not hold.get("operation_id"):
        print(json.dumps({"status": hold.get("status"), "command_sent": False, "vehicle_id": args.vehicle_id}, ensure_ascii=False))
        return 2
    hold_execution = controller.execute(hold["operation_id"], dry_run=False)
    write(args.evidence_directory, "02-hold-execution.json", hold_execution)
    hold_verification = controller.verify(hold["operation_id"])
    write(args.evidence_directory, "03-hold-verification.json", hold_verification)
    time.sleep(max(0, min(args.observe_seconds, args.max_hold_seconds - 5)))
    bridge.call("get_operational_telemetry", {"section": "vehicles_live"})
    telemetry = json.loads((bridge_directory / "operational-telemetry-vehicles_live.json").read_text(encoding="utf-8"))
    observed = next((item for item in telemetry.get("vehicles", []) if item.get("entity_id") == args.vehicle_id), None)
    write(args.evidence_directory, "04-held-observation.json", observed)

    release = controller.propose("RELEASE_VEHICLE_FROM_HOLD", {"vehicle_id": args.vehicle_id}, {})
    write(args.evidence_directory, "05-release-proposal.json", release)
    release_execution = controller.execute(release["operation_id"], dry_run=False)
    write(args.evidence_directory, "06-release-execution.json", release_execution)
    release_verification = controller.verify(release["operation_id"])
    write(args.evidence_directory, "07-release-verification.json", release_verification)
    success = hold_verification.get("status") == "POSTCONDITION_VERIFIED" and release_verification.get("status") == "POSTCONDITION_VERIFIED"
    result = {"status": "POSTCONDITION_VERIFIED" if success else "FAILED", "vehicle_id": args.vehicle_id, "line_id": vehicle.get("line_id"), "hold": hold_verification.get("verification"), "held_observation": observed, "release": release_verification.get("verification"), "fail_safe_seconds": args.max_hold_seconds}
    write(args.evidence_directory, "result.json", result)
    print(json.dumps({"status": result["status"], "vehicle_id": args.vehicle_id, "line_id": vehicle.get("line_id")}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
