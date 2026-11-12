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


class LoaderWorldError(RuntimeError):
    """Loader world data is missing, stale, or structurally incompatible."""


class LoaderWorldRepository:
    def __init__(self, *, reader: Callable[[str], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        if reader is None:
            from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient
            reader = LoaderLuaCommandClient.for_simulation().reader
        self._reader = reader
        self._clock = clock
        self._topology_lock = threading.Lock()
        self._topology_cache: tuple[str, dict[str, Any]] | None = None

    def get_full_network_topology(self) -> dict[str, Any]:
        """获取全路网拓扑图：车站、道岔、信号机为节点，保留轨道端点与闭环锚点。"""
        from tpf2_mcp.algorithms.generate_topology.gen_topology import generate_topology
        from tpf2_mcp.algorithms.generate_topology.station_topology_node import DEFAULT_SIGNAL_SEARCH_M

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
        from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient
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
