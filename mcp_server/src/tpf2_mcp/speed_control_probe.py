"""Classify observed API names without invoking any candidate setter."""
from __future__ import annotations

from typing import Any


EXCLUDED = {
    "setGameSpeed": "GLOBAL_SIMULATION_SPEED",
    "getGameSpeed": "GLOBAL_SIMULATION_SPEED_QUERY",
    "setCalendarSpeed": "CALENDAR_SPEED",
    "setAnimalState": "ANIMAL_MOVEMENT",
    "setUserStopped": "STOP_START_ONLY",
    "setVehicleManualDeparture": "TERMINAL_HOLD_ONLY",
    "setVehicleShouldDepart": "TERMINAL_DEPARTURE_ONLY",
}


def classify_speed_control(commands: dict[str, Any], interface: dict[str, Any], *, fresh: bool) -> dict[str, Any]:
    command_list = commands.get("api_cmd_make") or {}
    interface_list = interface.get("game_interface") or {}
    complete = (fresh and commands.get("probe_kind") == "READ_ONLY_API_COMMAND_INVENTORY"
                and command_list.get("value_type") == "table"
                and isinstance(command_list.get("items"), list) and bool(command_list["items"])
                and interface_list.get("readable") is True
                and isinstance(interface_list.get("members"), list)
                and 0 < len(interface_list["members"]) < 200)
    members = []
    for source, values, name_field in (
        ("api.cmd.make", command_list.get("items", []), "name"),
        ("game.interface", interface_list.get("members", []), "key"),
    ):
        for entry in values:
            if isinstance(entry, dict) and isinstance(entry.get(name_field), str):
                members.append({"source": source, "name": entry[name_field],
                                "value_type": entry.get("value_type"), "signature": entry.get("signature")})
    candidates, excluded = [], []
    for entry in members:
        name = entry["name"]
        if name in EXCLUDED:
            excluded.append({**entry, "reason": EXCLUDED[name]})
        elif any(word in (name + " " + str(entry.get("signature") or "")).lower()
                 for word in ("speed", "velocity", "accel", "brake")):
            # Lua command constructors are often callable tables, not functions.
            candidates.append({**entry, "status": "DISCOVERED_NOT_VERIFIED"})
    return {
        "probe_kind": "READ_ONLY_VEHICLE_SPEED_CONTROL_DISCOVERY",
        "status": "UNKNOWN" if not complete else "CANDIDATE_REQUIRES_VALIDATION" if candidates else "NO_EXPOSED_SETTER_FOUND",
        "evidence_fresh": fresh, "enumeration_complete": bool(complete),
        "control_verified": False, "write_command_sent": False,
        "command_count": len(command_list.get("items", [])),
        "interface_member_count": len(interface_list.get("members", [])),
        "candidates": candidates, "excluded_controls": excluded,
        "scope": ["api.cmd.make", "game.interface"],
        "limitations": [
            "Name/signature discovery does not establish a working per-vehicle speed limit.",
            "No candidate is constructed or invoked by this probe.",
            "This does not inspect hidden/native APIs or prove that all possible extensions are impossible.",
            "MOVE_PATH speed observations are not writable control interfaces.",
        ],
        "inventory": {"commands": commands, "interface": interface_list},
    }
