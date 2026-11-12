"""Inspect, configure, arm, or stop the local engineered control system."""
from __future__ import annotations

import argparse
import json
import urllib.request


def request(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    value = urllib.request.Request(base.rstrip("/") + path, data=data,
                                   headers={"Content-Type": "application/json"} if data else {},
                                   method="POST" if data else "GET")
    with urllib.request.urlopen(value, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "shadow", "arm", "disable", "stop"))
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--features", default="timetable,fleet,routing,speed,spacing,station,path")
    parser.add_argument("--speed-rule", action="append", default=[], metavar="VEHICLE:LINE:START_KM:END_KM:SPEED_KMH")
    args = parser.parse_args()
    if args.command == "status":
        result = request(args.url, "/api/control-system")
    elif args.command == "stop":
        result = request(args.url, "/api/control-system/stop", {"reason": "CLI_EMERGENCY_STOP"})
    else:
        mode = {"shadow": "SHADOW", "arm": "ARMED", "disable": "DISABLED"}[args.command]
        names = [item.strip() for item in args.features.split(",") if item.strip()]
        features = {name: name in names for name in ("timetable", "fleet", "routing", "speed", "spacing", "station", "path")}
        patch: dict = {"mode": mode, "features": features}
        if args.speed_rule:
            rules = []
            for raw in args.speed_rule:
                vehicle, line, start, end, speed = raw.split(":")
                rules.append({"vehicle_id": int(vehicle), "line_id": int(line), "start_km": float(start),
                              "end_km": float(end), "speed_kmh": float(speed)})
            patch["speed_rules"] = rules
        save_id = request(args.url, "/api/status").get("save_id")
        confirmation = f"ARM:{save_id}" if mode == "ARMED" else None
        result = request(args.url, "/api/control-system/config", {"patch": patch, "confirmation": confirmation})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
