"""Compile a validated territory draft for UI; all inputs are explicit, no game writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "mcp_server/src"))
from tpf2_mcp.dispatch_regions import build_region_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--mod-root", type=Path, required=True)
    parser.add_argument("--rail-map-root", type=Path,
                        help="Directory containing rail-network-data.json; defaults to <mod-root>/var/rail-map")
    args = parser.parse_args()
    mod = args.mod_root.resolve()
    if not (mod / "res/scripts/tpf2_mcp/runtime.lua").is_file():
        raise ValueError("Target must be a TPF2 MCP Mod root")
    target = (mod / "bridge/dispatch/region-view.json").resolve()
    if not target.is_relative_to(mod):
        raise ValueError("Output escaped Mod root")
    study = args.study.resolve()
    rail_map_root = args.rail_map_root.resolve() if args.rail_map_root else mod / "var/rail-map"
    net_path = rail_map_root / "rail-network-data.json"
    raw = net_path.read_bytes()
    result = build_region_view(json.loads((study / "territories.json").read_text(encoding="utf-8")),
                               json.loads((study / "boundary-anchors.json").read_text(encoding="utf-8")),
                               json.loads(raw), hashlib.sha256(raw).hexdigest())
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix(".json.tmp")
    pending.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(pending, target)
    print(f"Exported {len(result['regions'])} regions, {len(result['stations'])} stations, {len(result['anchors'])} anchors ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
