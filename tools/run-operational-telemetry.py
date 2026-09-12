"""Run all bounded live telemetry sections and merge their safe JSON outputs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.bridge import BridgeClient  # noqa: E402


def main() -> None:
    client = BridgeClient(timeout_seconds=90)
    merged = {
        "schema_version": 1,
        "probe_kind": "UNIFIED_OPERATIONAL_TELEMETRY_DISCOVERY",
        "source_status": "ENGINE_OBSERVED_DIAGNOSTIC",
        "counts": {},
        "errors": [],
        "write_command_sent": False,
        "sections": {},
    }
    # Station UI sampling has caused a repeatable native crash in build 35924
    # on the live large save.  Station identity comes from the already proven
    # world snapshot instead; demand remains explicitly UNKNOWN.
    for section in ("inventory", "signals", "vehicles"):
        result = client.operational_telemetry(section)
        print(section + "=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        section_path = client.directory / result["file_name"]
        payload = json.loads(section_path.read_text(encoding="utf-8"))
        merged["sections"][section] = {
            "duration_ms": payload.get("duration_ms"),
            "errors": len(payload.get("errors") or []),
        }
        for key in ("component_types", "systems", "clock", "signals", "signal_edge_objects", "vehicles", "station_demand"):
            if key in payload:
                merged[key] = payload[key]
        merged["counts"].update(payload.get("counts") or {})
        merged["errors"].extend(payload.get("errors") or [])
    snapshot_path = client.directory / "state.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    merged["station_demand"] = [
        {
            "station_group_id": station.get("entity_id"),
            "name": station.get("name"),
            "transport_samples_ok": False,
            "transport_samples_error": "UNKNOWN: unsafe live station sampling disabled after native crash",
        }
        for station in snapshot.get("stations", [])
    ]
    merged["counts"]["stations"] = len(merged["station_demand"])
    merged["sections"]["stations"] = {"source": "existing_world_snapshot", "errors": 0}
    output = client.directory / "operational-telemetry.json"
    output.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("merged=" + str(output))
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "analyze-operational-telemetry.py")],
        cwd=ROOT,
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
