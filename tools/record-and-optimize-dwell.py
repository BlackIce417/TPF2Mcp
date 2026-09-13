"""Record live railway frames and emit a conservative stop-policy plan."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.dwell_optimizer import optimize_dwell_times  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/live")
    parser.add_argument("--duration-seconds", type=float, default=90)
    parser.add_argument("--interval-seconds", type=float, default=1.5)
    parser.add_argument("--output-directory", type=Path, default=ROOT / "diagnostics" / "rail-operations")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-frame progress while retaining the final summary.")
    args = parser.parse_args()
    bridge = Path(os.environ["APPDATA"]) / "Transport Fever 2" / "tpf2_mcp_bridge"
    frames, last_sample = [], None
    deadline = time.monotonic() + max(0, args.duration_seconds)
    while True:
        frame = fetch_json(args.url)
        simulation = frame.get("simulation") if isinstance(frame.get("simulation"), dict) else {}
        if simulation.get("analysis_allowed") is False or simulation.get("status") in {"PAUSED", "PAUSED_OR_STALLED"}:
            frames.append(frame)
            print(f"blocked: simulation={simulation.get('status')} speed={simulation.get('speed_multiplier')}", flush=True)
            break
        sample = frame.get("sampled_at")
        if sample != last_sample:
            frames.append(frame)
            last_sample = sample
            if not args.quiet:
                print(f"frame={len(frames)} sampled_at={sample} vehicles={len(frame.get('vehicles', []))}", flush=True)
        if time.monotonic() >= deadline:
            break
        time.sleep(max(.2, args.interval_seconds))
    manifest = read_json(ROOT / "ui" / "rail-map" / "rail-network-manifest.json")
    snapshot = read_json(bridge / "state.json")
    plan = optimize_dwell_times(frames, manifest, snapshot)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    observation_path = args.output_directory / "dwell-observation.json"
    plan_path = args.output_directory / "dwell-optimization-plan.json"
    observation_path.write_text(json.dumps({"schema_version": 1, "frames": frames}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"observation": str(observation_path), "plan": str(plan_path), "counts": plan["counts"], "duration_seconds": plan["observation"]["duration_seconds"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
