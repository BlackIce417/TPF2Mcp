"""Preview, apply, or clear one resident line timetable."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))
from tpf2_mcp.bridge import BridgeClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("line_id", type=int)
    parser.add_argument("--plan", type=Path, default=ROOT / "diagnostics" / "rail-operations" / "line-timetable-plan.json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--stage-disabled", action="store_true", help="Load and validate the plan without controlling vehicles")
    args = parser.parse_args()
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    line = next((item for item in payload.get("lines", []) if item.get("line_id") == args.line_id), None)
    if line is None and not args.clear:
        raise SystemExit(f"line {args.line_id} is absent from the plan")
    operation_type = "CLEAR_LINE_TIMETABLE" if args.clear else "APPLY_LINE_TIMETABLE"
    parameters = {} if args.clear else {
        "enabled": not args.stage_disabled, "cycle_seconds": line["cycle_seconds"], "epoch_game_time_ms": line["epoch_game_time_ms"],
        "late_release_seconds": line["late_release_seconds"], "priority": line["priority"],
        "stops": [{key: stop[key] for key in ("stop_index", "departure_offsets_seconds", "max_hold_seconds")} for stop in line["stops"]],
    }
    envelope = {"protocol_version": 1, "operation_id": f"timetable-{uuid.uuid4()}", "operation_type": operation_type,
                "target": {"line_id": args.line_id}, "parameters": parameters}
    if not args.execute:
        print(json.dumps({"status": "DRY_RUN", "command": envelope}, ensure_ascii=False, indent=2))
        return 0
    result = BridgeClient(timeout_seconds=30).call("execute_operation", envelope)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
