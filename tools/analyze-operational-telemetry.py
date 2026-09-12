"""Summarize a unified live telemetry discovery result into a readiness matrix."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def observed_number(fields: dict | None, name: str) -> bool:
    detail = (fields or {}).get(name) or {}
    return detail.get("type") == "number" and isinstance(detail.get("value"), (int, float))


def observed_reference(fields: dict | None, names: tuple[str, ...]) -> bool:
    return any(((fields or {}).get(name) or {}).get("type") not in {None, "nil"} for name in names)


def analyze(report: dict) -> dict:
    signals = report.get("signals") or []
    vehicles = report.get("vehicles") or []
    stations = report.get("station_demand") or []
    signal_positions = sum(item.get("position") is not None for item in signals)
    vehicle_positions = sum(item.get("position") is not None for item in vehicles)
    vehicle_speed = sum(any(observed_number(item.get(source), key) for source in ("component", "info", "move_path", "sim_entity_moving", "interface_fields") for key in ("speed", "velocity")) for item in vehicles)
    vehicle_path = sum(any(observed_reference(item.get(source), ("path", "movePath", "edge", "edgeId", "edgePos", "pathPos", "segment", "section")) for source in ("component", "info", "move_path", "sim_entity_moving", "interface_fields")) for item in vehicles)
    clock_methods = report.get("clock", {}).get("methods", {})
    clocks = [name for name, detail in clock_methods.items() if detail.get("call_ok")]
    station_samples = sum(bool(item.get("transport_samples_ok")) for item in stations)
    linked_signals = len(report.get("signal_edge_objects") or [])
    return {
        "schema_version": 1,
        "source_status": report.get("source_status", "UNKNOWN"),
        "counts": report.get("counts", {}),
        "evidence": {
            "signals_with_world_position": signal_positions,
            "signals_linked_to_track_edge": linked_signals,
            "vehicles_with_world_position": vehicle_positions,
            "vehicles_with_speed_candidate": vehicle_speed,
            "vehicles_with_path_candidate": vehicle_path,
            "stations_with_transport_samples": station_samples,
            "working_clock_methods": clocks,
            "collector_errors": len(report.get("errors") or []),
        },
        "readiness": {
            "signal_layer": "READY_FOR_NORMALIZATION" if signals and (signal_positions or linked_signals) else "UNKNOWN",
            "block_derivation": "READY_FOR_MODELING" if linked_signals >= 2 else "UNKNOWN",
            "moving_train_layer": "READY_FOR_NORMALIZATION" if vehicle_positions and vehicle_speed else "PARTIAL" if vehicle_positions else "UNKNOWN",
            "actual_route_validation": "READY_FOR_RECORDING" if vehicle_path else "UNKNOWN",
            "time_distance_recorder": "READY_FOR_MODELING" if clocks and vehicle_positions else "UNKNOWN",
            "demand_calibration": "PARTIAL" if station_samples else "UNKNOWN",
        },
    }


def main() -> None:
    bridge = Path(os.environ["APPDATA"]) / "Transport Fever 2" / "tpf2_mcp_bridge"
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=bridge / "operational-telemetry.json")
    parser.add_argument("--output", type=Path, default=Path("diagnostics/operational-telemetry-readiness.json"))
    args = parser.parse_args()
    summary = analyze(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
