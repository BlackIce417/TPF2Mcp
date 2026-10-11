"""Arm a bounded native OD reassignment between two compatible line legs."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--source-line", type=int, required=True)
    parser.add_argument("--target-line", type=int, required=True)
    parser.add_argument("--source-stops", type=int, nargs=2, required=True, metavar=("FROM", "TO"))
    parser.add_argument("--target-stops", type=int, nargs=2, required=True, metavar=("FROM", "TO"))
    parser.add_argument("--max-assignments", type=int, default=10)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    values = [args.source_line, args.target_line, *args.source_stops, *args.target_stops]
    if min(values) < 0 or args.source_line == args.target_line or not 1 <= args.max_assignments <= 10000:
        parser.error("lines/stops must be valid and max-assignments must be 1..10000")
    bridge = args.bridge.resolve(); bridge.mkdir(parents=True, exist_ok=True)
    path = bridge / "native-control.ini"; temporary = path.with_suffix(".ini.tmp")
    value = configparser.ConfigParser()
    if path.exists(): value.read(path, encoding="ascii")
    value["routing"] = {
        "enabled": str(0 if args.disable else 1), "source_line": str(args.source_line),
        "target_line": str(args.target_line), "source_stop0": str(args.source_stops[0]),
        "source_stop1": str(args.source_stops[1]), "target_stop0": str(args.target_stops[0]),
        "target_stop1": str(args.target_stops[1]), "max_assignments": str(args.max_assignments),
    }
    with temporary.open("w", encoding="ascii") as stream: value.write(stream)
    os.replace(temporary, path)
    result = {"config": str(path), "enabled": not args.disable, "source_line": args.source_line,
              "target_line": args.target_line, "source_stops": args.source_stops,
              "target_stops": args.target_stops, "max_assignments": args.max_assignments}
    print(json.dumps(result))
    return 0


if __name__ == "__main__": raise SystemExit(main())
