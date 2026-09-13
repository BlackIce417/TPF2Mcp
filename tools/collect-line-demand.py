"""Collect real passenger/cargo demand into the local SQLite history."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient  # noqa: E402
from tpf2_mcp.config import bridge_dir, state_dir  # noqa: E402
from tpf2_mcp.demand_history import DemandHistoryStore  # noqa: E402
from tpf2_mcp.save_scope import snapshot_save_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-id", type=int, action="append", default=[])
    parser.add_argument("--all-rail", action="store_true")
    parser.add_argument("--maximum-entities", type=int, default=20000)
    parser.add_argument("--database", type=Path, default=state_dir() / "line-demand.sqlite3")
    args = parser.parse_args()
    line_ids = list(dict.fromkeys(args.line_id))
    if args.all_rail:
        manifest = json.loads((ROOT / "ui" / "rail-map" / "rail-network-data.json").read_text(encoding="utf-8"))
        line_ids = list(dict.fromkeys([*line_ids, *(int(item["entity_id"]) for item in manifest.get("lines", []))]))
    if not line_ids:
        raise SystemExit("provide --line-id or --all-rail")
    client, store = BridgeClient(bridge_dir(), timeout_seconds=30), DemandHistoryStore(args.database)
    snapshot = client.game_state(force_refresh=False)
    save_id = snapshot_save_id(snapshot)
    collected, failures = [], []
    for line_id in line_ids:
        try:
            sample = client.line_demand(line_id, args.maximum_entities)
            store.record(sample, save_id)
            collected.append({"line_id": line_id, "passengers": sample.get("passengers", {}).get("total_for_line"),
                              "cargo": sample.get("cargo", {}).get("total_for_line")})
        except Exception as exc:
            failures.append({"line_id": line_id, "error": str(exc)})
    print(json.dumps({"database": str(args.database), "save_id": save_id, "collected": collected, "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
