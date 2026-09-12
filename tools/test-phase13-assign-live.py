"""One-shot dedicated-save ASSIGN_VEHICLE_TO_LINE probe; never retries."""
from __future__ import annotations
import argparse, json, uuid
from pathlib import Path
from tpf2_mcp.bridge import BridgeClient
def dump(directory, name, value):
    directory.mkdir(parents=True, exist_ok=True); (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--vehicle-id", type=int, required=True); parser.add_argument("--line-id", type=int, required=True); parser.add_argument("--evidence-directory", type=Path, required=True); args = parser.parse_args()
    bridge = BridgeClient(timeout_seconds=20); before = bridge.game_state(force_refresh=True)
    vehicle = next((item for item in before["vehicles"] if item["entity_id"] == args.vehicle_id), None); dump(args.evidence_directory, "before.json", {"sequence": before.get("sequence"), "vehicle": vehicle})
    envelope = {"protocol_version": 1, "operation_id": f"phase13-assign-{uuid.uuid4()}", "operation_type": "ASSIGN_VEHICLE_TO_LINE", "target": {"vehicle_id": args.vehicle_id, "line_id": args.line_id}, "parameters": {"stop_index": 0}}
    dump(args.evidence_directory, "command.json", envelope); response = bridge.call("execute_operation", envelope); dump(args.evidence_directory, "response.json", response)
    observations = []
    for poll in range(1, 4):
        after = bridge.game_state(force_refresh=True); observed = next((item for item in after["vehicles"] if item["entity_id"] == args.vehicle_id), None)
        result = {"poll": poll, "sequence": after.get("sequence"), "vehicle": observed, "line_vehicle_ids": [item["entity_id"] for item in after["vehicles"] if item.get("line_id") == args.line_id]}; observations.append(result); dump(args.evidence_directory, f"after-{poll}.json", result)
        if observed and observed.get("line_id") == args.line_id: break
    status = "POSTCONDITION_VERIFIED" if observations[-1]["vehicle"] and observations[-1]["vehicle"].get("line_id") == args.line_id and args.vehicle_id in observations[-1]["line_vehicle_ids"] else "POSTCONDITION_NOT_MET"
    dump(args.evidence_directory, "verification.json", {"status": status, "response": response, "observations": observations}); print(json.dumps({"status": status, "response": response, "observed": observations[-1]["vehicle"]}, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
