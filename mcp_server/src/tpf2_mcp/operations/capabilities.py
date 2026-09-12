"""Registry for write capabilities, kept conservative by design."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "operation_type": "RENAME_LINE",
        "available": True,
        "verified": True,
        "destructive": False,
        "requires_confirmation": True,
        "supports_rollback": True,
        "risk_class": "LOW",
        "source": "TPF2 res/scripts/mission/nameutil.lua: game.interface.setName(id, name)",
        "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/final-goal-live/rename-task/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/rename-task/result.json",
        "limitations": ["Lua write kill switch is false by default.", "All production execution still requires a current Task and fresh postcondition snapshot."],
    },
    {
        "operation_type": "RENAME_STATION",
        "available": False,
        "verified": False,
        "destructive": False,
        "requires_confirmation": True,
        "supports_rollback": True,
        "risk_class": "LOW",
        "source": "TPF2 res/scripts/mission/nameutil.lua: game.interface.setName(id, name)",
        "source_status": "DISCOVERED_NOT_VERIFIED",
        "limitations": ["Function was found in shipped Lua source only.", "No dedicated-save live write verification has occurred.", "Lua write kill switch is false by default."],
    },
    {
        "operation_type": "BUY_VEHICLE", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "api.cmd.make.buyVehicle(playerEntity, depotEntity, TransportVehicleConfig)", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/phase13-live-20260909-1340/buy-vehicle/verification.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/two-vehicle-line/result.json",
        "limitations": ["Config is currently selected from an existing vehicle's documented transportVehicleConfig.", "No price/catalog semantic is yet verified.", "AUTO_SAFE is prohibited by MEDIUM risk."],
    },
    {
        "operation_type": "ASSIGN_VEHICLE_TO_LINE", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "api.cmd.make.setLine(vehicleEntity, lineEntity, stopIndex)", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/phase13-live-20260909-1340/assign-vehicle/verification.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/two-vehicle-line/result.json",
        "limitations": ["Verified only from an unassigned newly bought vehicle to one compatible line at stop_index 0.", "AUTO_SAFE is prohibited by MEDIUM risk."],
    },
    {
        "operation_type": "CREATE_LINE_FROM_SOURCE_ROUTE", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "api.cmd.make.createLine(name, Vec3f color, playerEntity, Line)", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "Phase 16 live probe: source line 11833 -> new line 1735075, two ordered stops verified.",
        "limitations": ["Current product input deliberately copies native stop userdata from an existing source line.", "Arbitrary station-to-terminal descriptor resolution remains unverified.", "AUTO_SAFE is prohibited by MEDIUM risk."],
    },
    {
        "operation_type": "CREATE_LINE", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "native Line stop-vector copy/mutation plus api.cmd.make.createLine",
        "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/final-goal-live/two-vehicle-line/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/two-vehicle-line/04-step-1.json",
        "limitations": ["The controller resolves only observed unambiguous station/terminal pairs unless a terminal selector is explicit.", "A native vector template with exactly the requested stop count is required."],
    },
    {
        "operation_type": "SET_LINE_STOPS", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "api.cmd.make.updateLine(lineEntity, Line)", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/final-goal-live/task-gate-safe/01-set_line_stops_goal.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/task-gate-safe/01-set_line_stops_goal.json",
        "limitations": ["Only exact-size native stop-vector templates are accepted."],
    },
    {
        "operation_type": "REMOVE_VEHICLE_FROM_LINE", "available": False, "verified": False,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "No distinct native command found; setLine(vehicleEntity, -1, 0) was engine-rejected", "source_status": "ENGINE_REJECTED_UNAVAILABLE",
        "evidence": "diagnostics/phase20-live/remove-vehicle/03-remove/execution.json",
        "limitations": ["TPF2 exposes assignment, depot return, and sale as distinct commands, but no verified unassign-and-keep primitive.", "SEND_VEHICLE_TO_DEPOT must not be mislabeled as this operation."],
    },
    {
        "operation_type": "SELL_VEHICLE", "available": False, "verified": True,
        "destructive": True, "requires_confirmation": True, "supports_rollback": False, "risk_class": "HIGH",
        "source": "api.cmd.make.sellVehicle(vehicleEntity)", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/phase20-live/sell-vehicle/02-sell/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/task-gate-safe/04-sell_vehicle_goal.json",
        "limitations": ["Irreversible operation requires exact per-vehicle confirmation.", "Live verification is restricted to a newly purchased disposable test vehicle."],
    },
    {
        "operation_type": "SET_LINE_STOP_POLICY", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": False, "risk_class": "MEDIUM",
        "source": "Line.Stop loadMode/minWaitingTime/maxWaitingTime plus api.cmd.make.updateLine", "source_status": "POSTCONDITION_VERIFIED",
        "evidence": "diagnostics/phase20-live/scheduling-policy/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/final-goal-live/task-gate-safe/02-set_line_stop_policy_goal.json",
        "limitations": ["Verified on one stop of a disposable two-stop line.", "Frequency and throughput remain observed outcomes, not direct controls."],
    },
    {
        "operation_type": "HOLD_VEHICLE_AT_TERMINAL", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": True, "supports_rollback": True, "risk_class": "MEDIUM",
        "source": "api.cmd.make.setVehicleManualDeparture(vehicleEntity, true)", "source_status": "POSTCONDITION_VERIFIED_RUNNING_SIMULATION",
        "evidence": "diagnostics/rail-operations/dispatch-train-hold-running-verified/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/rail-operations/dispatch-train-task-running-verified/result.json",
        "limitations": ["Must only be armed for a railway vehicle observed with raw_state=2 at a terminal.", "A Lua-side max_hold_seconds fail-safe releases the vehicle after 10..600 seconds.", "Overtaking additionally requires an independently usable through route."],
    },
    {
        "operation_type": "RELEASE_VEHICLE_FROM_HOLD", "available": False, "verified": True,
        "destructive": False, "requires_confirmation": False, "supports_rollback": False, "risk_class": "LOW",
        "source": "api.cmd.make.setVehicleManualDeparture(vehicleEntity, false) then api.cmd.make.setVehicleShouldDepart(vehicleEntity)", "source_status": "POSTCONDITION_VERIFIED_RUNNING_SIMULATION",
        "evidence": "diagnostics/rail-operations/dispatch-train-hold-running-verified/result.json",
        "live_mcp_verified": True,
        "task_live_verified": True,
        "live_mcp_evidence": "diagnostics/rail-operations/dispatch-train-task-running-verified/result.json",
        "limitations": ["Immediate departure succeeds only while the vehicle is waiting at a terminal; clearing manual departure remains the fail-safe action."],
    },
    *tuple({
        "operation_type": operation_type, "available": False, "verified": False,
        "destructive": destructive, "requires_confirmation": True,
        "supports_rollback": False, "risk_class": risk_class,
        "source": "Phase 13 source scan/runtime discovery pending",
        "source_status": "DISCOVERED_NOT_VERIFIED",
        "limitations": ["No documented shipped-script command signature was found.", "No live write test has occurred."],
    } for operation_type, destructive, risk_class in (
        ("SEND_VEHICLE_TO_DEPOT", False, "MEDIUM"),
        ("DELETE_LINE", True, "HIGH"),
    )),
)


def capabilities() -> list[dict[str, Any]]:
    """Return copies so callers cannot mutate the registry."""
    values = deepcopy(list(_CAPABILITIES))
    # Keep legacy fields for existing clients while exposing the non-ambiguous
    # product-readiness state introduced in Phase 14.
    for item in values:
        item["discovered"] = item.get("source_status") not in {"UNKNOWN", "UNAVAILABLE"}
        item["engine_verified"] = bool(item.get("verified"))
        item["live_mcp_verified"] = bool(item.get("live_mcp_verified", False))
        item["task_live_verified"] = bool(item.get("task_live_verified", False))
        item["controller_supported"] = item["operation_type"] in {"RENAME_LINE", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE", "CREATE_LINE_FROM_SOURCE_ROUTE", "CREATE_LINE", "SET_LINE_STOPS", "SET_LINE_STOP_POLICY", "SELL_VEHICLE", "HOLD_VEHICLE_AT_TERMINAL", "RELEASE_VEHICLE_FROM_HOLD"}
        item["task_supported"] = item["operation_type"] in {"RENAME_LINE", "BUY_VEHICLE", "ASSIGN_VEHICLE_TO_LINE", "CREATE_LINE_FROM_SOURCE_ROUTE", "CREATE_LINE", "SET_LINE_STOPS", "SET_LINE_STOP_POLICY", "SELL_VEHICLE", "HOLD_VEHICLE_AT_TERMINAL", "RELEASE_VEHICLE_FROM_HOLD"}
        item["runtime_enabled"] = False  # Python cannot override Lua's kill switch.
        item["product_ready"] = bool(item["engine_verified"] and item["controller_supported"] and item["task_supported"] and item["live_mcp_verified"] and item["task_live_verified"])
        item["available"] = bool(item["controller_supported"] and item["runtime_enabled"])
    return values


def capability(operation_type: str) -> dict[str, Any] | None:
    return next((item for item in capabilities() if item["operation_type"] == operation_type), None)
