"""Continuously observe and conservatively operate one live TPF2 save until a deadline."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server" / "src"))

from tpf2_mcp.config import bridge_dir  # noqa: E402

LIVE_URL = "http://127.0.0.1:8765/api/live"
STATUS_URL = "http://127.0.0.1:8765/api/status"


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def emit(event: str, **values: object) -> None:
    print(json.dumps({"at": datetime.now().astimezone().isoformat(), "event": event, **values}, ensure_ascii=False), flush=True)


def run_tool(arguments: list[str], timeout: float) -> bool:
    completed = subprocess.run(
        [sys.executable, *arguments], cwd=ROOT, timeout=timeout,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        emit("TOOL_FAILED", tool=arguments[0], returncode=completed.returncode,
             stdout=completed.stdout[-1000:], stderr=completed.stderr[-1000:])
    return completed.returncode == 0


def resume_game_window() -> bool:
    """Toggle pause only through the exact Transport Fever 2 top-level window."""
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    window = user32.FindWindowW(None, "Transport Fever 2")
    if not window:
        return False
    user32.SetForegroundWindow(window)
    time.sleep(0.25)
    virtual_key_space = 0x20
    key_up = 0x0002
    user32.keybd_event(virtual_key_space, 0, 0, 0)
    user32.keybd_event(virtual_key_space, 0, key_up, 0)
    time.sleep(3)
    try:
        return (fetch(LIVE_URL).get("simulation") or {}).get("status") == "RUNNING"
    except (OSError, ValueError):
        return False


def deadline_today(clock: str) -> datetime:
    hour, minute = (int(value) for value in clock.split(":"))
    now = datetime.now().astimezone()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def plan_summary(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"error": "plan unavailable"}
    additions = []
    for line in plan.get("lines", []):
        fleet = line.get("fleet_policy") or {}
        if fleet.get("decision") != "ADD_ONE_PROPOSAL":
            continue
        additions.append({
            "line_id": line.get("line_id"),
            "name": line.get("line_name"),
            "waiting": (line.get("demand") or {}).get("waiting"),
            "vehicles": line.get("vehicle_count"),
            "eligibility": fleet.get("execution_eligibility"),
            "platform": (line.get("platform_feasibility") or {}).get("status"),
        })
    conflict = plan.get("global_conflict_plan") or {}
    return {
        "save_id": plan.get("save_id"),
        "fleet_add_candidates": additions,
        "conflicts_before": conflict.get("conflicts_before_shift"),
        "conflicts_after": conflict.get("conflicts_after_shift"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", default="21:00")
    parser.add_argument("--continuous", action="store_true",
                        help="Run until interrupted instead of stopping at a wall-clock deadline")
    parser.add_argument("--cycle-seconds", type=float, default=600)
    parser.add_argument("--observation-seconds", type=float, default=180)
    parser.add_argument("--demand-every-cycles", type=int, default=2)
    parser.add_argument("--heartbeat-seconds", type=float, default=50)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--execute-ready-dwell", action="store_true")
    parser.add_argument("--resume-paused", action="store_true")
    args = parser.parse_args()

    target = None if args.continuous else deadline_today(args.until)
    bridge = bridge_dir()
    snapshot = bridge / "state.json"
    main_plan = ROOT / "diagnostics" / "rail-operations" / "line-timetable-plan.json"
    args.output_directory.mkdir(parents=True, exist_ok=True)
    emit("WATCH_STARTED", until=target.isoformat() if target else "MANUAL_STOP")
    existing_cycles = [int(path.name.split("-", 1)[1]) for path in args.output_directory.glob("cycle-[0-9][0-9][0-9]")]
    cycle = max(existing_cycles, default=0)
    while target is None or datetime.now().astimezone() < target:
        cycle += 1
        cycle_started = time.monotonic()
        cycle_dir = args.output_directory / f"cycle-{cycle:03d}"
        try:
            status, live = fetch(STATUS_URL), fetch(LIVE_URL)
            simulation = live.get("simulation") or {}
            emit("CYCLE_STATUS", cycle=cycle, save_id=status.get("save_id"), bridge=status.get("bridge_connected"),
                 simulation=simulation.get("status"), speed=simulation.get("speed_multiplier"),
                 vehicles=len(live.get("vehicles", [])), live_error=status.get("live_error"))
            if simulation.get("status") == "PAUSED" and args.resume_paused:
                emit("RESUME_ATTEMPT", cycle=cycle, success=resume_game_window())
                live = fetch(LIVE_URL)
                simulation = live.get("simulation") or {}
            if not status.get("bridge_connected") or simulation.get("status") != "RUNNING":
                emit("CYCLE_DEFERRED", cycle=cycle, reason="bridge or simulation is not running")
            else:
                observed = run_tool([
                    "tools/record-and-optimize-dwell.py", "--duration-seconds", str(args.observation_seconds),
                    "--interval-seconds", "1.5", "--output-directory", str(cycle_dir), "--quiet",
                ], timeout=args.observation_seconds + 120)
                dwell_plan = cycle_dir / "dwell-optimization-plan.json"
                ready = []
                if observed and dwell_plan.exists():
                    ready = [item for item in json.loads(dwell_plan.read_text(encoding="utf-8")).get("recommendations", []) if item.get("apply_ready")]
                emit("DWELL_ANALYSIS", cycle=cycle, completed=observed, apply_ready=len(ready),
                     candidates=[{"line_id": item.get("line_id"), "stop_index": item.get("stop_index"), "station": item.get("station_name")} for item in ready])
                if ready and args.execute_ready_dwell:
                    application = cycle_dir / "application"
                    dry = run_tool(["tools/apply-dwell-optimization.py", "--plan", str(dwell_plan),
                                    "--evidence-directory", str(application)], timeout=180)
                    executed = dry and run_tool(["tools/apply-dwell-optimization.py", "--plan", str(dwell_plan),
                                                 "--evidence-directory", str(application), "--execute"], timeout=240)
                    emit("DWELL_EXECUTION", cycle=cycle, dry_run=dry, postcondition_verified=executed)
                if cycle == 1 or cycle % max(1, args.demand_every_cycles) == 0:
                    demand = run_tool(["tools/collect-line-demand.py", "--all-rail", "--maximum-entities", "20000"], timeout=420)
                    emit("DEMAND_COLLECTION", cycle=cycle, completed=demand)
                built = run_tool(["tools/build-line-timetable-plan.py", "--snapshot", str(snapshot),
                                  "--observation", str(cycle_dir / "dwell-observation.json"),
                                  "--output", str(main_plan)], timeout=180)
                emit("TIMETABLE_PLAN", cycle=cycle, completed=built, **plan_summary(main_plan))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            emit("CYCLE_ERROR", cycle=cycle, error=f"{type(exc).__name__}: {exc}")

        planned_next_cycle = time.time() + max(5, args.cycle_seconds - (time.monotonic() - cycle_started))
        next_cycle = min(target.timestamp(), planned_next_cycle) if target else planned_next_cycle
        while time.time() < next_cycle:
            remaining = max(0, int(target.timestamp() - time.time())) if target else None
            emit("WATCH_HEARTBEAT", cycle=cycle, seconds_until_end=remaining)
            time.sleep(min(max(10, args.heartbeat_seconds), max(1, next_cycle - time.time())))
    emit("WATCH_COMPLETED", until=target.isoformat() if target else "MANUAL_STOP")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
