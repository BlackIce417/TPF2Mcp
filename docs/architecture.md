# Architecture

TPF2 MCP has four isolated layers:

```text
MCP client
  -> Python MCP adapter (server.py)
  -> BridgeClient / file transport (bridge.py)
  -> TPF2 mod runtime (runtime.lua)
  -> TPF2 API collector (state.lua)
```

The boundary data is JSON validated by the schemas in `protocol/`. Lua API tables are normalized in the mod before they cross that boundary. Schema-v2 snapshots are indexed in Python; `get_game_state` returns game/company/metadata/counts while `get_world_snapshot` returns the complete normalized model. `SnapshotIndex` builds entity dictionaries plus `vehicles_by_line` and `lines_by_station` once per read-only MCP interaction window.

`BridgeClient` owns request IDs, polling, timeouts, and atomic command writes. The MCP adapter only maps `get_bridge_status` and `get_game_state` to it. This keeps a later IPC transport replacement local to the bridge layer.

Commands are level 0/read-only. Network summary and deterministic anomaly tools only query the indexed snapshot; they cannot modify the game. Future write commands require explicit permission levels and dry-run support.

## MCP compatibility status

Current implementation: a legacy/minimal MCP compatibility layer implemented directly over stdio JSON-RPC. It exists only to validate the live TPF2 bridge and must not be treated as proof of current official MCP SDK compatibility. The project will migrate to the official MCP SDK after live bridge validation in Phase 2.

## Test classifications

- **OFFLINE TEST** validates Python protocol and transport behavior without a game process.
- **MOCK TEST** uses `MockBridge` and fixture JSON; it is not a TPF2 bridge result.
- **LIVE TPF2 TEST** requires an enabled mod in an open TPF2 save and must be run with `tools/test-live-bridge.ps1`.
