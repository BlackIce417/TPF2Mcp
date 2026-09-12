#!/usr/bin/env python3
"""Cross-check manually recorded TPF2 UI evidence against a world snapshot."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from tpf2_mcp.snapshot import SnapshotIndex

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("ground_truth", type=Path); parser.add_argument("snapshot", type=Path); parser.add_argument("output", type=Path); args = parser.parse_args()
    truth = json.loads(args.ground_truth.read_text(encoding="utf-8")); index = SnapshotIndex(json.loads(args.snapshot.read_text(encoding="utf-8")))
    checks, failures = [], []
    for item in truth["lines"]:
        line = index.line_by_id.get(item["entity_id"]); observed = {"name": line.get("name") if line else None, "stop_count": len(line.get("stops", [])) if line else None, "vehicle_count": len(index.vehicles_by_line.get(item["entity_id"], []))}
        expected = item["structural_expected"]; ok = observed == expected
        checks.append({"kind": "line", "entity_id": item["entity_id"], "expected": expected, "observed": observed, "result": "PASS" if ok else "FAIL", "ui_only_metrics": item.get("ui_only_metrics", {})})
        if not ok: failures.append(item["entity_id"])
    for item in truth["vehicles"]:
        vehicle = index.vehicle_by_id.get(item["entity_id"]); line = index.line_by_id.get(vehicle.get("line_id")) if vehicle else None
        observed = {"name": vehicle.get("name") if vehicle else None, "line_name": line.get("name") if line else None}
        expected = item["structural_expected"]; ok = observed == expected
        checks.append({"kind": "vehicle", "entity_id": item["entity_id"], "expected": expected, "observed": observed, "result": "PASS" if ok else "FAIL", "ui_only_metrics": item.get("ui_only_metrics", {}), "mcp_availability": {"capacity": False, "load": False}})
        if not ok: failures.append(item["entity_id"])
    for item in truth["stations"]:
        station = index.station_by_id.get(item["entity_id"]); names = sorted({line.get("name") for line in index.lines_by_station.get(item["entity_id"], [])})
        observed = {"name": station.get("name") if station else None, "served_line_names": names}
        expected = item["structural_expected"]; ok = observed["name"] == expected["name"] and set(expected["served_line_names"]).issubset(names)
        checks.append({"kind": "station_group", "entity_id": item["entity_id"], "expected": expected, "observed": observed, "result": "PASS" if ok else "FAIL", "ui_only_metrics": item.get("ui_only_metrics", {}), "mcp_availability": {"waiting": False}})
        if not ok: failures.append(item["entity_id"])
    report = {"ground_truth_source": truth.get("source"), "snapshot_sequence": index.state.get("sequence"), "checks": checks, "unavailable_via_current_public_api": ["vehicle.capacity", "vehicle.load", "station.waiting", "line.revenue", "line.rate", "line.frequency", "industry.production"], "result": "PASS" if not failures else "FAIL"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"UI structural checks ..... {'PASS' if not failures else 'FAIL'} ({len(checks) - len(failures)}/{len(checks)})")
    print("UI-only operating metrics .. RECORDED (public API unavailable)")
    return 0 if not failures else 1

if __name__ == "__main__": sys.exit(main())
