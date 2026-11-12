"""Loader-backed MCP tools for relatively static world and rail-network data."""
from __future__ import annotations

import time
import copy
import hashlib
import json
import threading
from typing import Any, Callable

from tpf2_mcp.transport.loader_telemetry import read_json_channel
from tpf2_mcp.services.line_routes import TRAIN_ROUTES_TOOL, export_train_routes


STATE_CHANNEL = "state.json"
NETWORK_CHANNEL = "rail-network.json"
HEARTBEAT_CHANNEL = "heartbeat.json"
ENTITY_COLLECTIONS = {
    "town": "towns",
    "industry": "industries",
    "station": "stations",
    "line": "lines",
}
NETWORK_SECTIONS = ("nodes", "edges", "stations", "lines", "depots")


from tpf2_mcp.repositories.world import LoaderWorldError, LoaderWorldRepository



def _list_tool(kind: str, plural: str) -> dict[str, Any]:
    return {
        "name": f"get_{plural}",
        "title": f"Get {plural.capitalize()}",
        "description": f"Read a paginated {kind} catalog directly from the Loader shared-memory world snapshot.",
        "inputSchema": {"type": "object", "properties": {
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            "name_contains": {"type": "string", "minLength": 1, "maxLength": 256},
        }, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "entity_kind": {"type": "string"},
            "source": {"type": "string"}, "snapshot_sequence": {}, "snapshot_timestamp": {},
            "items": {"type": "array", "items": {"type": "object"}},
            "total": {"type": "integer"}, "offset": {"type": "integer"},
            "limit": {"type": "integer"}, "next_offset": {"type": ["integer", "null"]},
        }, "required": ["schema_version", "entity_kind", "source", "items", "total", "offset", "limit", "next_offset"]},
    }


def _entity_tool(kind: str) -> dict[str, Any]:
    return {
        "name": f"get_{kind}",
        "title": f"Get {kind.capitalize()}",
        "description": f"Read one {kind} by stable TPF2 entity ID from Loader shared memory.",
        "inputSchema": {"type": "object", "properties": {
            "entity_id": {"type": "integer", "minimum": 1},
        }, "required": ["entity_id"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "entity_kind": {"type": "string"},
            "source": {"type": "string"}, "entity": {"type": "object"},
        }, "required": ["schema_version", "entity_kind", "source", "entity"]},
    }


WORLD_TOOL_DEFINITIONS = [
    TRAIN_ROUTES_TOOL,
    {
        "name": "get_full_network_topology",
        "title": "获取全路网拓扑图",
        "description": "获取完整有向路网拓扑：车站已合并终端与咽喉区，向外500米寻找进站信号作为边界；同时导出区间道岔、信号机、端点、边长与原始轨道映射。要求路网与信号清单同批采集。站内细节保存在station_wrapper；通行许可及道岔进路尚未验证，不能据此直接执行调度。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "nodes": {"type": "array", "items": {"type": "object"}},
            "edges": {"type": "array", "items": {"type": "object"}},
            "schema_version": {"type": "integer"},
            "topology_id": {"type": "string"},
            "capture_id": {"type": "string"},
            "source": {"type": "string"},
            "counts": {"type": "object"},
            "parameters": {"type": "object"},
            "dispatch_ready": {"type": "boolean"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        }, "required": ["nodes", "edges", "schema_version", "topology_id", "capture_id", "source", "counts", "parameters", "dispatch_ready", "warnings"]},
    },
    {
        "name": "get_world_catalog_status",
        "title": "Get World Catalog Status",
        "description": "Read asset snapshot age/counts and current save health. Assets are captured once per save and on demand; timestamps describe collection age, not current dynamic statistics. force_refresh=true explicitly recollects world assets and queues network/signal inventory refresh; this can briefly pause simulation.",
        "inputSchema": {"type": "object", "properties": {"force_refresh": {"type": "boolean", "default": False}}, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "source": {"type": "string"},
            "heartbeat_age_seconds": {"type": "number"}, "world_counts": {"type": "object"},
            "rail_network_counts": {"type": "object"},
        }, "required": ["schema_version", "source", "heartbeat_age_seconds", "world_counts"]},
    },
    _list_tool("town", "towns"), _entity_tool("town"),
    _list_tool("industry", "industries"), _entity_tool("industry"),
    _list_tool("station", "stations"), _entity_tool("station"),
    _list_tool("line", "lines"), _entity_tool("line"),
    {
        "name": "get_rail_network",
        "title": "Get Rail Network",
        "description": "Read the complete Loader rail network by section. Call summary first, then page through nodes, edges, stations, lines, and depots using next_offset.",
        "inputSchema": {"type": "object", "properties": {
            "section": {"type": "string", "enum": ["summary", *NETWORK_SECTIONS], "default": "summary"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 500},
        }, "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "schema_version": {"type": "integer"}, "source": {"type": "string"},
            "status": {}, "source_status": {}, "counts": {"type": "object"},
            "section": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}},
            "total": {"type": "integer"}, "offset": {"type": "integer"},
            "limit": {"type": "integer"}, "next_offset": {"type": ["integer", "null"]},
        }, "required": ["schema_version", "source", "counts", "section"]},
    },
]

WORLD_TOOL_NAMES = {tool["name"] for tool in WORLD_TOOL_DEFINITIONS}


def call_world_tool(repository: LoaderWorldRepository, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == 'get_train_routes':
        if set(arguments)-{'line_id','vehicle_id'}:
            raise LoaderWorldError('INVALID_ARGUMENTS: unexpected route argument')
        for key in ('line_id','vehicle_id'):
            value=arguments.get(key)
            if (key=='line_id' or value is not None) and (not isinstance(value,int) or isinstance(value,bool) or value<=0):
                raise LoaderWorldError(f'INVALID_ARGUMENTS: {key} must be a positive integer')
        try:
            return export_train_routes(repository,arguments['line_id'],vehicle_id=arguments.get('vehicle_id'))
        except (OSError,KeyError,ValueError,RuntimeError) as exc:
            raise LoaderWorldError(f'LINE_ROUTE_UNAVAILABLE: {exc}') from exc
    if name == "get_full_network_topology":
        if arguments:
            raise LoaderWorldError("INVALID_ARGUMENTS: get_full_network_topology accepts no arguments")
        return repository.get_full_network_topology()
    if name == "get_world_catalog_status":
        if set(arguments)-{'force_refresh'} or type(arguments.get('force_refresh',False)) is not bool:
            raise LoaderWorldError("INVALID_ARGUMENTS: force_refresh must be boolean")
        return repository.refresh_assets() if arguments.get('force_refresh') else repository.status()
    if name == "get_rail_network":
        section = arguments.get("section", "summary")
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 500)
        if section not in ("summary", *NETWORK_SECTIONS):
            raise LoaderWorldError("INVALID_ARGUMENTS: invalid rail-network section")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise LoaderWorldError("INVALID_ARGUMENTS: offset must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise LoaderWorldError("INVALID_ARGUMENTS: limit must be an integer from 1 to 1000")
        return repository.rail_network(section=section, offset=offset, limit=limit)
    for kind, plural in ENTITY_COLLECTIONS.items():
        if name == f"get_{plural}":
            offset, limit, query = arguments.get("offset", 0), arguments.get("limit", 200), arguments.get("name_contains")
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise LoaderWorldError("INVALID_ARGUMENTS: offset must be a non-negative integer")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
                raise LoaderWorldError("INVALID_ARGUMENTS: limit must be an integer from 1 to 1000")
            if query is not None and (not isinstance(query, str) or not query or len(query) > 256):
                raise LoaderWorldError("INVALID_ARGUMENTS: name_contains must be a non-empty string of at most 256 characters")
            return repository.entities(kind, offset=offset, limit=limit, name_contains=query)
        if name == f"get_{kind}":
            entity_id = arguments.get("entity_id")
            if not isinstance(entity_id, int) or isinstance(entity_id, bool) or entity_id <= 0:
                raise LoaderWorldError("INVALID_ARGUMENTS: entity_id must be a positive integer")
            return repository.entity(kind, entity_id)
    raise LoaderWorldError(f"UNKNOWN_WORLD_TOOL: {name}")
