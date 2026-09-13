# TPF2 MCP

TPF2 MCP connects a Transport Fever 2 mod to an MCP client through a small, versioned file bridge. The first milestone is deliberately read-only: prove the bridge with `ping`, then expose `get_game_state`. TPF2 game scripts use the documented engine `load` and periodic `update` callbacks.

## Architecture

```text
MCP client <-> Python stdio MCP server <-> bridge files <-> TPF2 Lua mod <-> TPF2 API
```

The MCP server never reads or writes bridge files from tool handlers directly; `BridgeClient` is the only bridge boundary.

## Prerequisites

- Windows 10/11
- Python 3.11+
- Transport Fever 2 installed at `D:\Steam\steamapps\common\Transport Fever 2`

No third-party Python dependency is required for this milestone.

## Quick start

```powershell
python -m pip install -e .\mcp_server
python -m tpf2_mcp.cli status
python -m tpf2_mcp.cli ping
python -m tpf2_mcp.cli game-state
python -m tpf2_mcp.server
python -m unittest discover -s tests -v
```

The package installation is intentional: tests do not depend on manually
setting `PYTHONPATH`.

Set `TPF2_MCP_BRIDGE_DIR` when the bridge directory differs from the Windows default (`%APPDATA%\Transport Fever 2\tpf2_mcp_bridge`). Before starting a real game, run `tools/install-mod.ps1`; on this machine it installs `tpf2_mod` to `D:\Steam\steamapps\common\Transport Fever 2\mods\tpf2_mcp_1`, then generates a matching Bridge configuration.

## Live capability status

The bridge, native stop-vector construction, and controlled operations have
been verified in a real open save. Writes remain disabled by default and are
enabled only for a dedicated, explicitly installed test configuration.

| Operation | Engine | Controller | Task | Live verification |
|---|---:|---:|---:|---:|
| CREATE_LINE_FROM_SOURCE_ROUTE | Yes | Yes | Yes | Yes |
| CREATE_LINE | Yes | Yes | Yes | Yes |
| BUY_VEHICLE | Yes | Yes | Yes | Yes |
| ASSIGN_VEHICLE_TO_LINE | Yes | Yes | Yes | Yes |
| SET_LINE_STOPS | Yes | Yes | Yes | Yes |
| SET_LINE_STOP_POLICY | Yes | Yes | Yes | Yes |
| SELL_VEHICLE | Yes | Yes | Yes | Yes |
| REMOVE_VEHICLE_FROM_LINE | Unavailable | No | No | Engine rejected |

`CREATE_LINE` and `SET_LINE_STOPS` resolve user station IDs and terminals to
an exact-length engine-native stop vector; terminal ambiguity is rejected
unless explicitly selected. See [Phase 18](docs/PHASE18_NATIVE_STOP_CONSTRUCTION.md)
and [Phase 19](docs/PHASE19_LINE_OPERATIONS.md).

Phase 20.1 live verification established irreversible vehicle sale through
`api.cmd.make.sellVehicle`. The controller and Lua dispatcher both require the
exact confirmation string `SELL_VEHICLE:<vehicle_id>`, and a fresh snapshot
must show that entity absent. A separate “unassign but keep the vehicle” API
was not found: `setLine(vehicle, -1, 0)` was safely rejected by the engine, so
`REMOVE_VEHICLE_FROM_LINE` remains unavailable rather than being conflated
with sale or depot return. See [Phase 20.1 documentation](docs/PHASE20_VEHICLE_LIFECYCLE.md).

`CREATE_AND_CONFIGURE_LINE_GOAL` is a bounded workflow for one to four
vehicles: create, explicitly configure stops, then repeat buy and assign. A
two-vehicle six-write Task has been live verified end to end. Phase 20.3
adds per-stop `load_mode`, `min_waiting_time`, and `max_waiting_time` control
through `updateLine`. Observed frequency and throughput are not direct
settings. Automatic optimization remains plan-only. A bounded
`get_line_demand` Bridge probe now supplies live line-assigned onboard/waiting
passenger and freight totals, observed freight cargo types, and waiting-time
samples. Schema version 2 also records engine-observed `lineStop0` → `lineStop1`
journey counts, allowing read-only detection of passenger/freight allocation
imbalance between genuinely parallel OD services. The detector only emits an
AI timetable suggestion: it never moves demand or changes fleets, consists,
headways, dwell policies, stops, or cargo filters. Demand history is persisted in SQLite,
and fleet proposals enforce exact existing-consist cloning, speed-class
consistency, and cargo capability constraints.

SQLite runtime data is scoped by a derived `save_id`. The fingerprint uses
stable player/town entity identity rather than mutable lines or vehicles.
Demand samples, station events, timetable plans, and MCP work-log queries are
filtered by that scope. Rows created before this migration remain preserved as
`legacy-unscoped` and are never silently attributed to the currently loaded
save. Branches copied from the same underlying world may intentionally share a
fingerprint until TPF2 exposes an engine-native save UUID.

The local rail-map service polls the current world fingerprint every three
seconds. On a save switch it clears the old dynamic vehicle/signal layers,
requests a fresh physical rail network through the read-only Bridge, regenerates
the tiled map, and publishes the new `save_id`. The browser reloads only after
the replacement manifest is ready, so future save changes do not require a game
restart or a rail-map server restart.

All game mutations exposed by MCP now require `create_task` → `plan_task` →
`approve_task_step` → `continue_task`. The former direct
`execute_operation` MCP tool is no longer advertised and rejects calls.
Repeated station IDs are rejected before dispatch because TPF2 lines already
loop automatically and a repeated A-B-A stop vector caused a native hang in
acceptance testing.

## Network intelligence

The read-only MCP can answer topology and verified-metric questions such as:

- “分析一下我的运输网络” (`analyze_network`)
- “哪几条线路的班次最稀疏？” (`rank_lines` / `find_line_outliers`)
- “线路 23 和哪些线路结构类似？” (`find_similar_lines`)
- “网络有几个互相独立的区域？” (`analyze_network_reachability`)
- “哪些车站是网络拓扑中的换乘节点？” (`rank_station_hubs`)

These analyses are snapshot-bound and evidence-backed. They do not claim profitability, load, waiting volume, or demand when runtime telemetry is unavailable; see [Phase 9 documentation](docs/PHASE9_NETWORK_INTELLIGENCE.md).

## Phase 10 decision support

Decision support distinguishes a diagnostic (what to inspect), a planning option (what to simulate), and a scenario (an in-memory what-if hypothesis). Examples include `simulate_station_connection`, `simulate_line_failure`, `compare_network_scenarios`, and `analyze_and_plan_network`.

`plan_new_line_candidates` ranks gaps between observed station groups and
returns read-only `CREATE_LINE_GOAL` candidates. It prioritizes candidates
whose terminal IDs are unambiguous and includes those observed selectors;
physical track/road reachability, demand, and cost remain explicitly unknown.

Scenario simulation **does not modify the game**. It only reports structural topology/fleet deltas and keeps cost, demand, load, waiting, and profit unavailable when no verified source exists. See [Phase 10 documentation](docs/PHASE10_DECISION_SUPPORT.md).

## Phase 11 controlled operations

Phase 11 introduced the proposal/validation/journal framework. The current
product path remains **fail closed**: Lua write operations default to disabled,
and direct operation execution is not exposed as an MCP tool; only Tasks can
reach the internal operation executor.
See [Phase 11 documentation](docs/PHASE11_CONTROLLED_OPERATIONS.md).

## Phase 12 closed-loop tasks

Phase 12 adds bounded goal/task orchestration over controlled operations. A
task plans and verifies one step at a time; it is not unrestricted autonomous
gameplay. See [Phase 12 documentation](docs/PHASE12_CLOSED_LOOP_TASKS.md).

## Phase 13 operational expansion

Dedicated-save verification established `BUY_VEHICLE` and
`ASSIGN_VEHICLE_TO_LINE` as MEDIUM-risk operations. They are never AUTO_SAFE;
the installed Lua write kill switch remains off by default. See
[Phase 13 documentation](docs/PHASE13_OPERATIONAL_EXPANSION.md).

## Phase 14 line-management control path

`BUY_VEHICLE` and `ASSIGN_VEHICLE_TO_LINE` now share the controller's
proposal, current-snapshot validation, bridge dispatch, and fresh-snapshot
postcondition checks. `BUY_AND_ASSIGN_VEHICLE_GOAL` performs exactly one
mutation per `continue_task`: it discovers the purchased vehicle ID from the
verified first result before preparing its assignment step. Both operations
remain MANUAL and the installed Lua write kill switch remains disabled by
default. See [Phase 14 documentation](docs/PHASE14_LINE_MANAGEMENT.md).

## Historical Phase 15 capability matrix

| Operation | Engine | Controller | Task | Live MCP |
|---|---:|---:|---:|---:|
| BUY_VEHICLE | Yes | Yes | Yes | Yes |
| ASSIGN_VEHICLE_TO_LINE | Yes | Yes | Yes | Yes |
| REMOVE_VEHICLE_FROM_LINE | No | No | No | No |
| SELL_VEHICLE | No | No | No | No |
| CREATE_LINE | No | No | No | No |
| SET_LINE_STOPS | No | No | No | No |

The Phase 15 MCP-native acceptance evidence is at
`diagnostics/phase15-live/phase14-mcp-native-buy-and-assign/summary.json`.
