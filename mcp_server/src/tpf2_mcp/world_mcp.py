"""Loader-backed MCP tools for relatively static world and rail-network data."""
from __future__ import annotations

import time
import copy
import hashlib
import json
import threading
from typing import Any, Callable

from .loader_telemetry import read_json_channel
from .line_routes import TRAIN_ROUTES_TOOL, export_train_routes


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


class LoaderWorldError(RuntimeError):
    """Loader world data is missing, stale, or structurally incompatible."""


class LoaderWorldRepository:
    def __init__(self, *, reader: Callable[[str], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        if reader is None:
            from .lua_commands import LoaderLuaCommandClient
            reader = LoaderLuaCommandClient.for_simulation().reader
        self._reader = reader
        self._clock = clock
        self._topology_lock = threading.Lock()
        self._topology_cache: tuple[str, dict[str, Any]] | None = None

    def get_full_network_topology(self) -> dict[str, Any]:
        """获取全路网拓扑图：车站、道岔、信号机为节点，保留轨道端点与闭环锚点。"""
        from .algorithms.generate_topology.gen_topology import generate_topology
        from .algorithms.generate_topology.station_topology_node import DEFAULT_SIGNAL_SEARCH_M

        heartbeat, _ = self._heartbeat()
        for _ in range(3):
            network = self._read_current(NETWORK_CHANNEL, heartbeat)
            signals = self._read_current('operational-telemetry-signals.json', heartbeat)
            capture_id = network.get('capture_id')
            if capture_id and capture_id == signals.get('capture_id'):
                break
        else:
            raise LoaderWorldError('ASSET_CAPTURE_MISMATCH: rail network and signal inventories must share capture_id')
        if network.get('status') != 'OK' or network.get('errors') or signals.get('errors'):
            raise LoaderWorldError('ASSET_COLLECTION_INCOMPLETE: rail or signal collection has errors')
        # Collection timestamps change even when the topology does not. Only
        # structural inputs invalidate the expensive graph construction cache.
        structural = {
            'topology_algorithm_version': 2,
            'network': {key: network.get(key) for key in ('schema_version', 'nodes', 'edges', 'stations')},
            'signals': signals.get('signal_edge_objects'),
            'session_id': signals.get('session_id'),
            'signal_search_m': DEFAULT_SIGNAL_SEARCH_M,
        }
        fingerprint = hashlib.sha256(json.dumps(structural, sort_keys=True, allow_nan=False,
                                                separators=(',', ':')).encode('utf-8')).hexdigest()
        with self._topology_lock:
            if self._topology_cache is None or self._topology_cache[0] != fingerprint:
                try:
                    graph = generate_topology(network, signals)
                except (ValueError, KeyError, TypeError) as exc:
                    raise LoaderWorldError(f'TOPOLOGY_GENERATION_FAILED: {exc}') from exc
                value = graph.to_dict()
                value.update({
                    'topology_id': fingerprint,
                    'generated_at': self._clock(),
                    'counts': {'nodes': len(graph.nodes), 'edges': len(graph.edges),
                               'stations': sum(n.station_wrapper is not None for n in graph.nodes.values())},
                    'parameters': {'signal_search_m': DEFAULT_SIGNAL_SEARCH_M,
                                   'approach_limit_m': 800.0, 'switch_gap_m': 250.0},
                })
                self._topology_cache = (fingerprint, value)
            result = copy.deepcopy(self._topology_cache[1])
        result.update({'source': 'tpf2_loader_shared_memory', 'capture_id': capture_id,
                       'session_id': signals.get('session_id'),
                       'source_generated_at': network.get('generated_at'),
                       'signal_generated_at': signals.get('generated_at')})
        self.assert_session(heartbeat['session_id'])
        return result

    def _read(self, channel: str) -> dict[str, Any]:
        try:
            return self._reader(channel)
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            raise LoaderWorldError(f"LOADER_CHANNEL_UNAVAILABLE: {channel}: {exc}") from exc

    def _heartbeat(self) -> tuple[dict[str, Any], float]:
        heartbeat = self._read(HEARTBEAT_CHANNEL)
        updated = heartbeat.get("last_update")
        if not isinstance(updated, (int, float)):
            raise LoaderWorldError("LOADER_HEARTBEAT_INVALID: last_update is missing")
        age = self._clock() - updated
        if age < 0 or age > 10 or heartbeat.get("bridge_ready") is not True:
            raise LoaderWorldError(f"LOADER_HEARTBEAT_STALE: age_seconds={age:.3f}")
        if not isinstance(heartbeat.get('session_id'), str) or not heartbeat['session_id']:
            raise LoaderWorldError('LOADER_SESSION_UNAVAILABLE')
        return dict(heartbeat), age

    def assert_session(self, session_id: str) -> None:
        heartbeat, _ = self._heartbeat()
        if heartbeat['session_id'] != session_id:
            raise LoaderWorldError('LOADER_SESSION_CHANGED: retry after world collection completes')

    def _read_current(self, channel: str, heartbeat=None) -> dict[str, Any]:
        if heartbeat is None:
            heartbeat, _ = self._heartbeat()
        value = self._read(channel)
        session = (value.get('metadata') or {}).get('session_id') if channel == STATE_CHANNEL else value.get('session_id')
        if session != heartbeat['session_id']:
            raise LoaderWorldError(f'LOADER_SESSION_MISMATCH: {channel} does not belong to the current save')
        if channel == STATE_CHANNEL:
            timestamp = value.get('timestamp')
            on_demand = (value.get('metadata') or {}).get('refresh_policy') == 'ON_DEMAND_ASSETS'
            if (not isinstance(timestamp, (int, float)) or self._clock()-timestamp < 0
                or (not on_demand and self._clock()-timestamp > 120)):
                raise LoaderWorldError('WORLD_SNAPSHOT_STALE: automatic world publication has not recovered')
        self.assert_session(heartbeat['session_id'])
        return value

    @staticmethod
    def _page(items: list, *, offset: int, limit: int) -> dict[str, Any]:
        total = len(items)
        page = items[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "items": page,
            "total": total,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if next_offset < total else None,
        }

    def status(self) -> dict[str, Any]:
        heartbeat, heartbeat_age = self._heartbeat()
        state = self._read_current(STATE_CHANNEL, heartbeat)
        network = self._read_current(NETWORK_CHANNEL, heartbeat)
        state_timestamp = state.get("timestamp")
        state_age = self._clock() - state_timestamp if isinstance(state_timestamp, (int, float)) else None
        return {
            "schema_version": 1,
            "connected": True,
            "source": "tpf2_loader_shared_memory",
            "heartbeat_age_seconds": round(heartbeat_age, 3),
            "snapshot_sequence": state.get("sequence"),
            "snapshot_age_seconds": round(state_age, 3) if state_age is not None else None,
            "refresh_policy": (state.get('metadata') or {}).get('refresh_policy', 'LEGACY_PERIODIC'),
            "session_id": (state.get("metadata") or {}).get("session_id"),
            "world_counts": {
                key: len(state.get(key, [])) if isinstance(state.get(key), list) else None
                for key in ("towns", "industries", "stations", "lines")
            },
            "rail_network_status": network.get("status"),
            "rail_network_source_status": network.get("source_status"),
            "rail_network_counts": network.get("counts"),
            "collector_status": (state.get("metadata") or {}).get("collector_status"),
            "loader_snapshot_seq": heartbeat.get("snapshot_seq"),
        }

    def refresh_assets(self):
        from .lua_commands import LoaderLuaCommandClient
        heartbeat, _ = self._heartbeat()
        # Reuse Loader's existing GET_GAME_STATE opcode, with no control writes.
        client = LoaderLuaCommandClient(reader=self._reader, timeout=60)
        client.call('get_game_state', {'force_refresh': True, 'refresh_assets': True},
                    expected_session=heartbeat['session_id'])
        return {**self.status(), 'network_refresh_status': 'QUEUED'}

    def entities(self, kind: str, *, offset: int, limit: int,
                 name_contains: str | None = None) -> dict[str, Any]:
        state = self._read_current(STATE_CHANNEL)
        collection = ENTITY_COLLECTIONS[kind]
        collector_status = ((state.get('metadata') or {}).get('collector_status') or {}).get(collection)
        if isinstance(collector_status, dict) and collector_status.get('ok') is False:
            raise LoaderWorldError(f'WORLD_COLLECTION_INCOMPLETE: {collection}')
        rows = state.get(collection)
        if not isinstance(rows, list):
            raise LoaderWorldError(f"LOADER_PAYLOAD_INVALID: {collection} is not an array")
        if name_contains:
            needle = name_contains.casefold()
            rows = [row for row in rows if needle in str(row.get("name", "")).casefold()]
        result = self._page(rows, offset=offset, limit=limit)
        result.update({
            "schema_version": 1,
            "entity_kind": kind,
            "source": "tpf2_loader_shared_memory",
            "snapshot_sequence": state.get("sequence"),
            "snapshot_timestamp": state.get("timestamp"),
            "session_id": state['metadata']['session_id'],
        })
        return result

    def entity(self, kind: str, entity_id: int) -> dict[str, Any]:
        result = self.entities(kind, offset=0, limit=100000)
        for row in result["items"]:
            if row.get("entity_id") == entity_id:
                return {
                    "schema_version": 1,
                    "entity_kind": kind,
                    "source": result["source"],
                    "snapshot_sequence": result["snapshot_sequence"],
                    "snapshot_timestamp": result["snapshot_timestamp"],
                    "session_id": result['session_id'],
                    "entity": row,
                }
        raise LoaderWorldError(f"ENTITY_NOT_FOUND: {kind} {entity_id}")

    def rail_network(self, *, section: str, offset: int, limit: int) -> dict[str, Any]:
        network = self._read_current(NETWORK_CHANNEL)
        base = {
            "schema_version": 1,
            "source": "tpf2_loader_shared_memory",
            "network_schema_version": network.get("schema_version"),
            "session_id": network['session_id'],
            "capture_id": network.get('capture_id'),
            "status": network.get("status"),
            "source_status": network.get("source_status"),
            "counts": network.get("counts"),
            "errors": network.get("errors", []),
            "section": section,
        }
        if section == "summary":
            return base
        rows = network.get(section)
        if not isinstance(rows, list):
            raise LoaderWorldError(f"LOADER_PAYLOAD_INVALID: rail-network {section} is not an array")
        base.update(self._page(rows, offset=offset, limit=limit))
        return base


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
