#!/usr/bin/env python3
"""Create a reproducible relationship-verification report for schema-v2 data."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from tpf2_mcp.snapshot import SnapshotIndex

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("snapshot", type=Path); parser.add_argument("output", type=Path); args = parser.parse_args()
    state = json.loads(args.snapshot.read_text(encoding="utf-8")); index = SnapshotIndex(state)
    lines, failures = [], []
    for line in list(index.line_by_id.values())[:3]:
        summary = index.line_summary(line["entity_id"])
        expected = {"name": line.get("name"), "stop_count": len(line.get("stops", [])), "vehicle_count": len(index.vehicles_by_line[line["entity_id"]])}
        observed = {"name": summary["line"].get("name"), "stop_count": summary["summary"]["stop_count"], "vehicle_count": summary["summary"]["vehicle_count"], "station_ids": [item["entity_id"] for item in summary["stations"]], "vehicle_ids": [item["entity_id"] for item in summary["vehicles"]], "transport_mode": summary["summary"]["transport_mode"]}
        passed = expected["name"] == observed["name"] and expected["stop_count"] == observed["stop_count"] and expected["vehicle_count"] == observed["vehicle_count"]
        if not passed: failures.append(line["entity_id"])
        lines.append({"line_id": line["entity_id"], "expected": expected, "observed": observed, "result": "PASS" if passed else "FAIL"})
    network = index.network_summary()
    report = {"schema_version": state.get("schema_version"), "verification_scope": "SnapshotIndex relationship consistency; UI comparison not supplied", "lines": lines, "line_stop_references": network["stop_references"], "vehicle_line_references": {"broken": len(index.broken_vehicle_references)}, "transport_mode": "UNKNOWN via current public LINE/TRANSPORT_VEHICLE component probes", "result": "PASS" if not failures and not index.unresolved_stop_references and not index.broken_vehicle_references else "FAIL"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Semantic relationships .... {report['result']}")
    print(f"Selected lines ............ {len(lines)}")
    print(f"Line stop references ...... {network['stop_references']['resolved']}/{network['stop_references']['total']} resolved")
    return 0 if report["result"] == "PASS" else 1

if __name__ == "__main__": sys.exit(main())
