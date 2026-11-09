"""Loader-backed MCP tools for relatively static world and rail-network data."""
from __future__ import annotations

import time
from typing import Any, Callable

from .loader_telemetry import read_json_channel


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
    def __init__(self, *, reader: Callable[[str], dict] = read_json_channel,
                 clock: Callable[[], float] = time.time):
        self._reader = reader
        self._clock = clock

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
        return heartbeat, age

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
        state = self._read(STATE_CHANNEL)
        network = self._read(NETWORK_CHANNEL)
        state_timestamp = state.get("timestamp")
        state_age = self._clock() - state_timestamp if isinstance(state_timestamp, (int, float)) else None
        return {
            "schema_version": 1,
            "source": "tpf2_loader_shared_memory",
            "heartbeat_age_seconds": round(heartbeat_age, 3),
            "snapshot_sequence": state.get("sequence"),
            "snapshot_age_seconds": round(state_age, 3) if state_age is not None else None,
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

    def entities(self, kind: str, *, offset: int, limit: int,
                 name_contains: str | None = None) -> dict[str, Any]:
        self._heartbeat()
        state = self._read(STATE_CHANNEL)
        collection = ENTITY_COLLECTIONS[kind]
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
                    "entity": row,
                }
        raise LoaderWorldError(f"ENTITY_NOT_FOUND: {kind} {entity_id}")

    def rail_network(self, *, section: str, offset: int, limit: int) -> dict[str, Any]:
        self._heartbeat()
        network = self._read(NETWORK_CHANNEL)
        base = {
            "schema_version": 1,
            "source": "tpf2_loader_shared_memory",
            "network_schema_version": network.get("schema_version"),
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
    {
        "name": "get_world_catalog_status",
        "title": "Get World Catalog Status",
        "description": "Check Loader heartbeat, world snapshot age/counts, collectors, and complete rail-network availability before reading catalogs.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
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
    if name == "get_world_catalog_status":
        if arguments:
            raise LoaderWorldError("INVALID_ARGUMENTS: get_world_catalog_status accepts no arguments")
        return repository.status()
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
