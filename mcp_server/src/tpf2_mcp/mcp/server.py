"""MCP request routing and service bindings; transports live in entrypoints."""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any
from tpf2_mcp.mcp.tool_definitions import _TRAIN_CONTROL_TOOLS, _RUNTIME_STATUS_TOOL
from tpf2_mcp.mcp.rules_mcp import DISPATCH_RULES_TOOL
from tpf2_mcp.repositories.dispatch_rules import DispatchRulesError, get_dispatch_rules

from tpf2_mcp.transport.bridge import BridgeClient, BridgeError, MockBridge
from tpf2_mcp.services.train_control import TrainControlError, TrainControlService
from tpf2_mcp.services.stop_control import StopControlService, STOP_CONTROL_TOOLS, OPERATIONS as STOP_CONTROL_OPERATIONS
from tpf2_mcp.mcp.movement_mcp import MovementService, MOVEMENT_TOOLS, MOVEMENT_TOOL_NAMES, MOVEMENT_WRITES
from tpf2_mcp.mcp.demand_mcp import DemandService, DEMAND_TOOLS, DEMAND_TOOL_NAMES
from tpf2_mcp.common.audit import write_audit, safe_arguments
from tpf2_mcp.common import dispatch_log
from tpf2_mcp.mcp.world_mcp import (
    LoaderWorldError, LoaderWorldRepository, WORLD_TOOL_DEFINITIONS,
    WORLD_TOOL_NAMES, call_world_tool,
)


def _bridge() -> None:
    """Production MCP uses shared memory directly; no file-bridge lifecycle."""
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _tool_result(value: Any) -> dict[str, Any]:
    safe = _json_safe(value)
    return {"content": [{"type": "text", "text": json.dumps(safe, ensure_ascii=False, indent=2, allow_nan=False)}],
            "structuredContent": safe}


def _error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


_loader_world_repository = LoaderWorldRepository()
_train_control_service = TrainControlService(topology_reader=_loader_world_repository.get_full_network_topology)
_stop_control_service = StopControlService()
_movement_service = MovementService()
_demand_service = DemandService(_loader_world_repository)


_STATEFUL_TOOLS = {
    "propose_operation", "validate_operation", "create_rollback_operation",
    "create_task", "plan_task", "approve_task_step", "continue_task", "cancel_task",
    "set_train_speed_limit", "cancel_train_speed_limit",
}
_DESTRUCTIVE_TOOLS = {"continue_task", "cancel_task", "set_train_speed_limit", "cancel_train_speed_limit"}
_IDEMPOTENT_WRITES = {"set_train_speed_limit", "cancel_train_speed_limit"}
_STATEFUL_TOOLS.update(STOP_CONTROL_OPERATIONS)
_DESTRUCTIVE_TOOLS.update(STOP_CONTROL_OPERATIONS)
_IDEMPOTENT_WRITES.update(STOP_CONTROL_OPERATIONS)
_STATEFUL_TOOLS.update(MOVEMENT_WRITES)
_DESTRUCTIVE_TOOLS.update(MOVEMENT_WRITES)
_IDEMPOTENT_WRITES.update(MOVEMENT_WRITES)


def _tool_title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_"))


def _standardize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the discovery and safety metadata expected by OpenAI MCP clients."""
    result = []
    for original in tools:
        tool = dict(original)
        name = tool["name"]
        tool.setdefault("title", _tool_title(name))
        # Legacy tools intentionally retain their existing structuredContent
        # shape (some return arrays). New tools define a narrower schema.
        tool.setdefault("outputSchema", {
            "anyOf": [{"type": "object"}, {"type": "array"}],
        })
        annotations = dict(tool.get("annotations", {}))
        read_only = name not in _STATEFUL_TOOLS
        annotations.update({
            "readOnlyHint": read_only,
            "destructiveHint": name in _DESTRUCTIVE_TOOLS,
            "idempotentHint": read_only or name in _IDEMPOTENT_WRITES,
            "openWorldHint": False,
        })
        tool["annotations"] = annotations
        result.append(tool)
    return result




_CURRENT_NATIVE_TOOL_NAMES = {
    "get_dispatch_rules",
    "get_bridge_status",
    "get_train_control_snapshot",
    "set_train_speed_limit",
    "cancel_train_speed_limit",
    "get_active_train_controls",
} | WORLD_TOOL_NAMES | STOP_CONTROL_OPERATIONS.keys() | DEMAND_TOOL_NAMES | MOVEMENT_TOOL_NAMES
















def handle(message: dict[str, Any], bridge: BridgeClient | MockBridge) -> dict[str, Any] | None:
    if message.get('method') != 'tools/call':
        return _handle(message, bridge)
    params = message.get('params') or {}
    with dispatch_log.capture(params.get('name'), message.get('id')) as invocation:
        try:
            response = _handle(message, bridge)
        except Exception as exc:
            dispatch_log.complete(invocation, error=str(exc))
            raise
        dispatch_log.complete(invocation, response)
        return response


def _handle(message: dict[str, Any], bridge: BridgeClient | MockBridge) -> dict[str, Any] | None:
    method, request_id, params = message.get("method"), message.get("id"), message.get("params", {})
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": "2025-03-26",
            "serverInfo": {"name": "tpf2-mcp", "version": "0.4.0"},
            "capabilities": {"tools": {}},
            "instructions": (
                "Read get_dispatch_rules for the packaged dispatch skill before making dispatch decisions. "
                "Only Loader shared-memory telemetry and Controller V2 command tools are exposed. Legacy file-bridge "
                "world, network, station, analysis, and task tools are isolated until migrated. Read current telemetry "
                "before control; refer to trains by display_name. Never control on stale route data. Speed writes are "
                "short-lived and require command_id-scoped confirmation. Movement/reversal tools are asynchronous: "
                "poll status and actual speed; MOVING does not prove physical movement. Reverse leaves manual stop set; "
                "wait for REVERSED, resume_train, refresh native movement context, then move. "
                "Native movement retains signal and occupancy protection; never claim it ignores red signals."
            ),
        }}
    if method == "tools/list":
        listed_tools = [_RUNTIME_STATUS_TOOL, *_TRAIN_CONTROL_TOOLS, *WORLD_TOOL_DEFINITIONS, *STOP_CONTROL_TOOLS, *DEMAND_TOOLS, *MOVEMENT_TOOLS, DISPATCH_RULES_TOOL]
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _standardize_tools(listed_tools)}}
    if method == "resources/list":
        if not isinstance(bridge, MockBridge):
            return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": [
            {"uri": "tpf2://game", "name": "TPF2 game overview", "mimeType": "application/json"},
            {"uri": "tpf2://network", "name": "TPF2 transport network", "mimeType": "application/json"},
            {"uri": "tpf2://network/lines", "name": "TPF2 lines", "mimeType": "application/json"},
            {"uri": "tpf2://network/stations", "name": "TPF2 station groups", "mimeType": "application/json"},
            {"uri": "tpf2://network/vehicles", "name": "TPF2 vehicles", "mimeType": "application/json"},
            {"uri": "tpf2://cargo-types", "name": "TPF2 cargo types", "mimeType": "application/json"},
            {"uri": "tpf2://agent-operations", "name": "TPF2 agent operations workflow", "mimeType": "application/json"},
            {"uri": "tpf2://capabilities", "name": "TPF2 metric capabilities", "mimeType": "application/json"}]}}
    try:
        if method == "tools/call":
            name = params.get("name")
            if name == "get_dispatch_rules":
                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict) or arguments:
                    return _error(-32602, "get_dispatch_rules accepts no arguments", request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(get_dispatch_rules())}
            if not isinstance(bridge, MockBridge) and name not in _CURRENT_NATIVE_TOOL_NAMES:
                return _error(-32601, f"TOOL_ISOLATED: {name} has not been migrated to Loader/Controller V2", request_id)
            if name in MOVEMENT_TOOL_NAMES:
                try:
                    value = _movement_service.call(name, params.get('arguments', {}))
                except ValueError as exc:
                    return _error(-32602, str(exc), request_id)
                except (OSError, KeyError, RuntimeError) as exc:
                    return _error(-32001, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if not isinstance(bridge, MockBridge) and name in DEMAND_TOOL_NAMES:
                try:
                    value = _demand_service.call(name, params.get('arguments', {}))
                except ValueError as exc:
                    return _error(-32602, str(exc), request_id)
                except (OSError, KeyError, RuntimeError) as exc:
                    return _error(-32001, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if name in STOP_CONTROL_OPERATIONS:
                try:
                    value = _stop_control_service.call(name, params.get('arguments', {}))
                except ValueError as exc:
                    return _error(-32602, str(exc), request_id)
                except (OSError, KeyError, RuntimeError) as exc:
                    return _error(-32001, str(exc), request_id)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if not isinstance(bridge, MockBridge) and name in WORLD_TOOL_NAMES:
                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict):
                    return _error(-32602, "arguments must be an object", request_id)
                value = call_world_tool(_loader_world_repository, name, arguments)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if name == "get_train_control_snapshot":
                arguments = params.get("arguments", {})
                display_name = arguments.get("display_name")
                include_parts = arguments.get("include_parts", False)
                if display_name is not None and (not isinstance(display_name, str) or not display_name or len(display_name) > 256):
                    return _error(-32602, "display_name must be a non-empty string of at most 256 characters", request_id)
                if not isinstance(include_parts, bool):
                    return _error(-32602, "include_parts must be a boolean", request_id)
                value = _train_control_service.snapshot(display_name=display_name, include_parts=include_parts)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if name == "set_train_speed_limit":
                arguments = params.get("arguments", {})
                command_id, display_name = arguments.get("command_id"), arguments.get("display_name")
                speed_kmh = arguments.get("speed_kmh")
                lookahead = arguments.get("lookahead_edges", 24)
                expiry = arguments.get("expires_in_seconds", 20)
                confirmation = arguments.get("confirmation")
                if not isinstance(command_id, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", command_id) is None:
                    return _error(-32602, "command_id must match [A-Za-z0-9._:-]{1,128}", request_id)
                if not isinstance(display_name, str) or not display_name or len(display_name) > 256:
                    return _error(-32602, "display_name must be a non-empty string of at most 256 characters", request_id)
                if not isinstance(speed_kmh, (int, float)) or isinstance(speed_kmh, bool) or not 0 <= speed_kmh <= 500:
                    return _error(-32602, "speed_kmh must be numeric from 0 to 500", request_id)
                if not isinstance(lookahead, int) or isinstance(lookahead, bool) or not 1 <= lookahead <= 192:
                    return _error(-32602, "lookahead_edges must be an integer from 1 to 192", request_id)
                if not isinstance(expiry, int) or isinstance(expiry, bool) or not 5 <= expiry <= 120:
                    return _error(-32602, "expires_in_seconds must be an integer from 5 to 120", request_id)
                if not isinstance(confirmation, str):
                    return _error(-32602, "confirmation must be a string", request_id)
                value = _train_control_service.set_speed_limit(
                    command_id=command_id, display_name=display_name, speed_kmh=float(speed_kmh),
                    lookahead_edges=lookahead, expires_in_seconds=expiry, confirmation=confirmation,
                    reason=arguments.get('reason'))
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if name == "cancel_train_speed_limit":
                arguments = params.get("arguments", {})
                command_id, confirmation = arguments.get("command_id"), arguments.get("confirmation")
                if not isinstance(command_id, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", command_id) is None:
                    return _error(-32602, "command_id must match [A-Za-z0-9._:-]{1,128}", request_id)
                if not isinstance(confirmation, str):
                    return _error(-32602, "confirmation must be a string", request_id)
                value = _train_control_service.cancel_speed_limit(command_id=command_id, confirmation=confirmation)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            if name == "get_active_train_controls":
                if params.get("arguments", {}):
                    return _error(-32602, "get_active_train_controls accepts no arguments", request_id)
                return {"jsonrpc": "2.0", "id": request_id,
                        "result": _tool_result(_train_control_service.active_controls())}
            if name == "get_bridge_status":
                status = _train_control_service.runtime_status()
                try:
                    lua = _stop_control_service.client.heartbeat()
                    status['lua_commands'] = {key: lua.get(key) for key in (
                        'lua_command_protocol', 'session_id', 'allow_write_operations', 'allowed_operations')}
                except (OSError, KeyError, ValueError, RuntimeError) as exc:
                    status['lua_commands'] = {'connected': False, 'reason': str(exc)}
                try:
                    status["world_data"] = _loader_world_repository.status()
                except LoaderWorldError as exc:
                    status["world_data"] = {"connected": False, "reason": str(exc)}
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(status)}
            from tpf2_mcp.mcp.legacy_adapter import call
            return call(name, params, bridge, request_id)
        if method == "resources/read":
            if not isinstance(bridge, MockBridge):
                return _error(-32601, "RESOURCE_ISOLATED: legacy file-bridge resources are not exposed", request_id)
            from tpf2_mcp.mcp.legacy_adapter import resource
            return resource(params, bridge, request_id)
    except (BridgeError, TrainControlError, LoaderWorldError, DispatchRulesError) as exc:
        return _error(-32001, str(exc), request_id)
    return _error(-32601, f"method not found: {method}", request_id)
