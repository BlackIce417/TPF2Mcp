"""Create the native per-train speed-zone config from verified rail geometry."""
from __future__ import annotations

import argparse
import configparser
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))
from tpf2_mcp.speed_zones import map_chainage_zone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--line-id", type=int, required=True)
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--start-km", type=float, required=True)
    parser.add_argument("--end-km", type=float, required=True)
    parser.add_argument("--speed-kmh", type=float, required=True)
    parser.add_argument("--direction", choices=("FORWARD", "REVERSE"), default="FORWARD")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    network = json.loads(args.network.resolve().read_text(encoding="utf-8"))
    zone = map_chainage_zone(network, args.line_id, args.start_km, args.end_km,
                             args.speed_kmh, args.vehicle_id, args.direction)
    bridge = args.bridge.resolve()
    bridge.mkdir(parents=True, exist_ok=True)
    config = bridge / "native-control.ini"
    temporary = config.with_suffix(".ini.tmp")
    parser_value = configparser.ConfigParser()
    if config.exists():
        parser_value.read(config, encoding="ascii")
    parser_value["speed"] = {"enabled": str(0 if args.disable else 1), "vehicle_id": str(zone["vehicle_id"]),
                             "speed_mps": str(zone["speed_mps"]),
                             "edge_ids": ",".join(map(str, zone["edge_ids"]))}
    with temporary.open("w", encoding="ascii") as stream:
        parser_value.write(stream)
    os.replace(temporary, config)
    metadata = bridge / "native-control-zone.json"
    temporary = metadata.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(zone, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, metadata)
    print(json.dumps({"config": str(config), "enabled": not args.disable, **zone}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
