"""Arm one native, reachability-checked terminal assignment for one vehicle."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--station-index", type=int, required=True)
    parser.add_argument("--terminal-index", type=int, required=True)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    if min(args.vehicle_id, args.station_index, args.terminal_index) < 0:
        parser.error("IDs and indices must be non-negative")
    bridge = args.bridge.resolve(); bridge.mkdir(parents=True, exist_ok=True)
    path = bridge / "native-control.ini"; temporary = path.with_suffix(".ini.tmp")
    value = configparser.ConfigParser()
    if path.exists(): value.read(path, encoding="ascii")
    value["station"] = {"enabled": str(0 if args.disable else 1), "vehicle_id": str(args.vehicle_id),
                        "station_index": str(args.station_index), "terminal_index": str(args.terminal_index)}
    with temporary.open("w", encoding="ascii") as stream: value.write(stream)
    os.replace(temporary, path)
    print(json.dumps({"config": str(path), "enabled": not args.disable, "vehicle_id": args.vehicle_id,
                      "station_index": args.station_index, "terminal_index": args.terminal_index}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
