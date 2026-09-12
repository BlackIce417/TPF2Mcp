#!/usr/bin/env python3
"""Validate a normalized TPF2 world snapshot without changing it."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

COLLECTIONS = ("towns", "industries", "stations", "lines", "vehicles")
SINGULAR = {"towns": "town", "industries": "industry", "stations": "station", "lines": "line", "vehicles": "vehicle"}

def check(state: dict) -> tuple[list[str], list[str], dict]:
    passed, failures, levels = [], [], {}
    schema_version = state.get("schema_version")
    if schema_version in {1, 2, 3, 4, 5}: passed.append(f"Schema ........ PASS ({schema_version})")
    else: failures.append("Schema ........ FAIL (schema_version must be 1, 2, 3, 4, or 5)")
    status = state.get("metadata", {}).get("collector_status", {})
    for collection in COLLECTIONS:
        values, label = state.get(collection), SINGULAR[collection].title()
        if not isinstance(values, list):
            failures.append(f"{label:<14} FAIL (not a list)"); continue
        ids = [item.get("entity_id") for item in values if isinstance(item, dict)]
        entity_type = "station_group" if schema_version >= 2 and collection == "stations" else SINGULAR[collection]
        required = all(isinstance(item, dict) and isinstance(item.get("entity_id"), int) and item.get("entity_type") == entity_type for item in values)
        valid = required and status.get(collection, {}).get("count") == len(values) and len(ids) == len(values) == len(set(ids))
        levels[collection] = "LIVE_NON_EMPTY" if valid and values else ("LIVE_EMPTY" if valid else "NOT_TESTED")
        (passed if valid else failures).append(f"{label:<14} {'PASS' if valid else 'FAIL'} ({len(values)})" + ("" if valid else " required fields, unique IDs, or collector count"))
    company = state.get("company")
    company_ok = isinstance(company, dict) and isinstance(company.get("entity_id"), int) and company.get("entity_type") == "company"
    levels["company"] = "LIVE_NON_EMPTY" if company_ok else "NOT_TESTED"
    (passed if company_ok else failures).append("Company ........ " + ("PASS (1)" if company_ok else "FAIL (required base fields)"))
    cargo_types = state.get("cargo_types")
    cargo_keys = [item.get("cargo_key") for item in cargo_types] if isinstance(cargo_types, list) else []
    cargo_ok = isinstance(cargo_types, list) and all(isinstance(item, dict) and isinstance(item.get("cargo_key"), str) for item in cargo_types) and len(cargo_keys) == len(set(cargo_keys)) and status.get("cargo_types", {}).get("count") == len(cargo_types)
    levels["cargo_types"] = "LIVE_NON_EMPTY" if cargo_ok and cargo_types else ("LIVE_EMPTY" if cargo_ok else "NOT_TESTED")
    (passed if cargo_ok else failures).append(f"Cargo types .... {'PASS' if cargo_ok else 'FAIL'} ({len(cargo_types) if isinstance(cargo_types, list) else 0})" + ("" if cargo_ok else " required cargo_key, unique keys, or collector count"))
    line_ids = {item.get("entity_id") for item in state.get("lines", []) if isinstance(item, dict)}
    broken = [item.get("entity_id") for item in state.get("vehicles", []) if isinstance(item, dict) and item.get("line_id") is not None and item.get("line_id") not in line_ids]
    (failures if broken else passed).append(f"References ..... {'FAIL (BROKEN_REFERENCE vehicles: ' + str(broken) + ')' if broken else 'PASS'}")
    stop_broken = [line.get("entity_id") for line in state.get("lines", []) if isinstance(line, dict) for stop in line.get("stops", []) if isinstance(stop, dict) and stop.get("station_id") not in {item.get("entity_id") for item in state.get("stations", []) if isinstance(item, dict)}]
    (failures if stop_broken else passed).append(f"Line stops ..... {'FAIL (unresolved lines: ' + str(stop_broken) + ')' if stop_broken else 'PASS'}")
    passed.append("UTF-8 .......... PASS")
    return passed, failures, levels

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("snapshot", type=Path); parser.add_argument("--verification", type=Path); args = parser.parse_args()
    try: state = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: print(f"UTF-8 .......... FAIL ({exc})"); return 1
    passed, failures, levels = check(state); print("\n".join(passed + failures))
    if args.verification:
        report = {"snapshot": str(args.snapshot), "expected_minimums": {"towns_min": 2, "industries_min": 1, "stations_min": 3, "lines_min": 2, "vehicles_min": 3}, "verification_level": levels, "result": "PASS" if not failures else "FAIL"}
        args.verification.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0
if __name__ == "__main__": sys.exit(main())
