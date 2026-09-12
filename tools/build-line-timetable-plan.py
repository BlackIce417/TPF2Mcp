"""Build a disabled line-template timetable plan from current exported evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.timetable_planner import plan_line_timetables  # noqa: E402
from tpf2_mcp.config import state_dir  # noqa: E402
from tpf2_mcp.demand_history import DemandHistoryStore  # noqa: E402
from tpf2_mcp.vehicle_length import VehicleModelLengthResolver  # noqa: E402


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "ui" / "rail-map" / "rail-network-data.json")
    parser.add_argument("--live-frame", type=Path, action="append", default=[])
    parser.add_argument("--observation", type=Path, action="append", default=[], help="JSON object containing a frames array")
    parser.add_argument("--demand-database", type=Path, default=state_dir() / "line-demand.sqlite3")
    parser.add_argument("--demand-sample-limit", type=int, default=12)
    parser.add_argument("--game-directory", type=Path, default=Path(r"D:\Steam\steamapps\common\Transport Fever 2"))
    parser.add_argument("--output", type=Path, default=ROOT / "diagnostics" / "rail-operations" / "line-timetable-plan.json")
    args = parser.parse_args()
    frames = []
    for path in args.observation:
        frames.extend(read(path).get("frames", []))
    frames.extend(read(path) for path in args.live_frame)
    snapshot, manifest = read(args.snapshot), read(args.manifest)
    length_resolution = VehicleModelLengthResolver(args.game_directory).enrich_snapshot(snapshot)
    line_ids = [int(item["entity_id"]) for item in manifest.get("lines", [])]
    histories = DemandHistoryStore(args.demand_database).histories(line_ids, args.demand_sample_limit) if args.demand_database.exists() else {}
    result = plan_line_timetables(snapshot, manifest, frames, histories)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["counts"], **length_resolution}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
