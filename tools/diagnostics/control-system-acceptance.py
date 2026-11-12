"""Run bounded live acceptance phases and always return control to DISABLED."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable


def request(base: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    value = urllib.request.Request(base.rstrip("/") + path, data=data,
                                   headers={"Content-Type": "application/json"} if data else {},
                                   method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(value, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="replace")) from exc


def wait_for(base: str, label: str, predicate: Callable[[dict[str, Any]], Any],
             timeout: float) -> tuple[dict[str, Any], Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = request(base, "/api/control-system")
        value = predicate(last)
        if value:
            return last, value
        lifecycle = (last.get("state") or {}).get("lifecycle")
        if lifecycle == "TRIPPED":
            raise RuntimeError(f"{label}: control system tripped: {(last.get('state') or {}).get('trip_reason')}")
        time.sleep(1)
    raise TimeoutError(f"{label}: timed out after {timeout:g}s; last lifecycle={(last.get('state') or {}).get('lifecycle')}")


def configure(base: str, save_id: str, features: set[str], mode: str = "ARMED") -> dict[str, Any]:
    switches = {name: name in features for name in ("timetable", "fleet", "routing", "speed", "station", "path")}
    return request(base, "/api/control-system/config", {
        "patch": {"mode": mode, "features": switches, "max_actions_per_cycle": 1},
        "confirmation": f"ARM:{save_id}" if mode == "ARMED" else None,
    })


def actions(value: dict[str, Any]) -> list[dict[str, Any]]:
    return list((value.get("state") or {}).get("actions") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--phase-timeout", type=float, default=300)
    parser.add_argument("--fleet-timeout", type=float, default=90)
    parser.add_argument("--require-fleet-mutation", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {"started_at": time.time(), "phases": []}
    status = request(args.url, "/api/status")
    save_id = status.get("save_id")
    if not status.get("bridge_connected") or not save_id:
        raise RuntimeError("current save and Bridge must be live")
    initial = request(args.url, "/api/control-system")
    if not (initial.get("config") or {}).get("speed_rules"):
        raise RuntimeError("at least one validated speed rule must be configured before acceptance")
    try:
        configure(args.url, save_id, {"timetable"})
        value, evidence = wait_for(args.url, "timetable", lambda item: next(
            (action for action in actions(item) if action.get("kind") == "TIMETABLE_APPLIED"), None),
            args.phase_timeout)
        result["phases"].append({"phase": "timetable", "status": "VERIFIED", "evidence": evidence})
        request(args.url, "/api/control-system/stop", {"reason": "ACCEPTANCE_TIMETABLE_COMPLETE"})

        configure(args.url, save_id, {"routing", "speed", "station"})
        value, leases = wait_for(args.url, "native leases", lambda item: (
            item.get("leases", {}).get("leases") if {lease.get("kind") for lease in item.get("leases", {}).get("leases", [])}
            >= {"routing", "speed", "station"} else None), args.phase_timeout)
        expected = {"speed": "SPEED_ZONE_OBSERVED", "station": "STATION_ASSIGNMENT_VERIFIED",
                    "routing": "OD_REASSIGNMENT_NATIVE_VERIFIED"}
        observed: dict[str, dict[str, Any]] = {}

        def native_verified(item: dict[str, Any]) -> bool:
            for action in actions(item):
                for kind, action_kind in expected.items():
                    if action.get("kind") == action_kind and (kind != "speed" or action.get("within_limit") is True):
                        observed[kind] = action
            return set(observed) == set(expected)

        wait_for(args.url, "native postconditions", native_verified, args.phase_timeout)
        result["phases"].append({"phase": "native", "status": "VERIFIED",
                                 "lease_count": len(leases), "evidence": observed})
        request(args.url, "/api/control-system/stop", {"reason": "ACCEPTANCE_NATIVE_COMPLETE"})

        configure(args.url, save_id, {"fleet"})
        try:
            value, evidence = wait_for(args.url, "fleet", lambda item: next(
                (action for action in actions(item) if action.get("kind") == "FLEET_ACTION"), None),
                args.fleet_timeout)
            fleet_result = evidence.get("result") or {}
            completed = fleet_result.get("status") in {"COMPLETED", "POSTCONDITION_VERIFIED"}
            compensated = (fleet_result.get("status") == "COMPENSATED_FAIL_CLOSED"
                           and ((fleet_result.get("compensation") or {}).get("verification") or {}).get("status")
                           == "POSTCONDITION_VERIFIED")
            if not (completed or compensated):
                raise RuntimeError(f"fleet action did not verify: {evidence}")
            result["phases"].append({"phase": "fleet",
                                     "status": "VERIFIED" if completed else "VERIFIED_COMPENSATED_FAIL_CLOSED",
                                     "evidence": evidence})
        except TimeoutError:
            if args.require_fleet_mutation:
                raise
            plan = request(args.url, "/api/timetable-plan")
            eligible = [line.get("line_id") for line in plan.get("lines", [])
                        if (line.get("fleet_policy") or {}).get("action_plan")]
            if eligible:
                raise RuntimeError(f"safe fleet decisions existed but were not executed: {eligible}")
            result["phases"].append({"phase": "fleet", "status": "VERIFIED_FAIL_CLOSED",
                                     "reason": "NO_SAFE_ACTION_PLAN_IN_CURRENT_SAVE"})
    finally:
        stopped = request(args.url, "/api/control-system/stop", {"reason": "ACCEPTANCE_FINISHED_DISABLED"})
        result["final_mode"] = (stopped.get("config") or {}).get("mode")
        result["final_lifecycle"] = (stopped.get("state") or {}).get("lifecycle")
        result["finished_at"] = time.time()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("final_mode") == "DISABLED" and result.get("final_lifecycle") == "DISABLED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
