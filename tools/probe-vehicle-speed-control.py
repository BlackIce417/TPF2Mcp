"""Run the read-only speed-control discovery through the public MCP handler."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))
sys.dont_write_bytecode = True

from tpf2_mcp.bridge import BridgeClient  # noqa: E402
from tpf2_mcp.server import handle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "diagnostics" / "speed-control-probe" / "result.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        parser.error("evidence must stay inside this source/Mod root")
    bridge = BridgeClient(timeout_seconds=30)
    if not bridge.status().get("connected"):
        raise SystemExit("Bridge is not live; open a save with the Mod enabled")
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "probe_vehicle_speed_control", "arguments": {}}}, bridge)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    if "error" in response:
        print(json.dumps(response["error"], ensure_ascii=False))
        return 1
    result = response["result"]["structuredContent"]
    print(json.dumps({key: result[key] for key in ("status", "snapshot_sequence", "evidence_fresh", "command_count",
                                                  "interface_member_count", "control_verified", "write_command_sent")}, ensure_ascii=False))
    print(f"Evidence: {output}")
    return 0 if result["enumeration_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
