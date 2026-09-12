"""One-shot dedicated-save BUY_VEHICLE probe; never retries a command."""
from __future__ import annotations
import argparse
import json
import uuid
from pathlib import Path
from tpf2_mcp.bridge import BridgeClient

def dump(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--source-vehicle-id", type=int, required=True); parser.add_argument("--depot-id", type=int, required=True)
    args = parser.parse_args(); bridge = BridgeClient(timeout_seconds=20)
    before = bridge.game_state(force_refresh=True); before_ids = {item["entity_id"] for item in before.get("vehicles", [])}
    dump(args.evidence_directory, "before.json", {"sequence": before.get("sequence"), "vehicle_ids": sorted(before_ids)})
    envelope = {"protocol_version": 1, "operation_id": f"phase13-buy-{uuid.uuid4()}", "operation_type": "BUY_VEHICLE", "target": {"source_vehicle_id": args.source_vehicle_id, "depot_id": args.depot_id}, "parameters": {}}
    dump(args.evidence_directory, "command.json", envelope)
    response = bridge.call("execute_operation", envelope); dump(args.evidence_directory, "response.json", response)
    observations = []
    for number in range(1, 4):
        after = bridge.game_state(force_refresh=True); new_ids = sorted({item["entity_id"] for item in after.get("vehicles", [])} - before_ids)
        observation = {"poll": number, "sequence": after.get("sequence"), "vehicle_count": len(after.get("vehicles", [])), "new_vehicle_ids": new_ids}
        observations.append(observation); dump(args.evidence_directory, f"after-{number}.json", observation)
        if len(new_ids) == 1: break
    status = "POSTCONDITION_VERIFIED" if observations[-1]["new_vehicle_ids"] and len(observations[-1]["new_vehicle_ids"]) == 1 else "NEW_ENTITY_NOT_OBSERVED" if not observations[-1]["new_vehicle_ids"] else "AMBIGUOUS_NEW_ENTITY"
    result = {"status": status, "response": response, "observations": observations}; dump(args.evidence_directory, "verification.json", result); print(json.dumps(result, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
