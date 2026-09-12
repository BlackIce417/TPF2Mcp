"""Capture live, read-only evidence for automatic line candidate planning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tpf2_mcp.analytics import NetworkIntelligenceIndex
from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.planning import DecisionSupport
from tpf2_mcp.snapshot import SnapshotIndex


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    snapshot = SnapshotIndex(BridgeClient(timeout_seconds=20).game_state(force_refresh=True))
    result = DecisionSupport(NetworkIntelligenceIndex(snapshot)).new_line_candidates(args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot_sequence": result["snapshot_sequence"], "candidate_count": len(result["candidates"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
