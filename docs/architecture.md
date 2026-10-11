# Architecture

Updated 2026-09-25 against the current working tree. Start with [current capabilities](CURRENT_CAPABILITIES.md) for validated boundaries.

## Existing runtime paths

    MCP client -> Python stdio JSON-RPC server -> BridgeClient -> Lua runtime -> game API
    Vite UI / local client -> FastAPI web_app -> web_state / existing engineering controller
    Engineering controller -> bounded native INI leases -> version-locked native DLL hooks
    Regional worker -> immutable JSON frames + SQLite -> shadow handover ledger (game_write=false)

BridgeClient owns request IDs, file transport and matching responses. MCP tools use it rather than manipulating Bridge files themselves. Lua normalizes engine observations. The generic world snapshot, on-demand line demand and high-frequency telemetry are distinct data products; availability in one does not imply availability in every legacy field.

MCP exposes read tools and controlled line/fleet/stop-policy Tasks. The HTTP dispatch facade also exists, but several commands only enable internal policies. It is inaccurate to describe all commands as read-only or all game writes as passing through the MCP Task chain.

The old controller remains hosted by the Web state lifecycle. The independent regional worker has storage, observation and shadow coordination, but no game execution adapter. Full collector/decision/executor separation is described in [modular-dispatch-design.md](modular-dispatch-design.md), not completed across all existing paths.

## Protocol and validation

The stdio server remains a project JSON-RPC implementation; this document does not establish official SDK compatibility. See actual server tool declarations, protocol schemas and command handlers rather than the original Phase 2 interface list.

- Offline tests exercise code without a game.
- Mock tests use synthetic fixtures; their results are not engine evidence.
- Historical live records are scoped to their executable, loaded Mod, save and date.
- ACCEPTED, published leases, Hook counters and shadow ledger results must not be treated as equivalent to observed game effects.

Current source locations: server.py, bridge.py, web_app.py, web_state.py, dispatch_platform.py, control_system.py, dispatch_runtime/, and native/tpf2_control/tpf2_control.c. Known execution gaps and the 2026-09-25 review are recorded in [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md).
