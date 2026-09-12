# Phase 7 acceptance — dynamic transport state and explainable diagnosis

## Implemented interface behavior

- `get_game_state` and `get_world_snapshot` accept optional `force_refresh: true`. It bypasses the Python interaction cache and the Lua two-second snapshot cache. Phase 8 renames the former ambiguous `snapshot_age_ms` to `index_age_ms` and adds source-derived `source_snapshot_age_ms`.
- `get_vehicle_operating_state`, `get_station_operating_state`, and `get_line_operating_summary` retain boolean availability for compatibility and add `source_status` plus `unavailable_reasons` for every unresolved dynamic metric.
- `frequency_seconds` and `throughput` remain `UI_CROSS_VERIFIED`; line finance is explicitly `UNAVAILABLE` rather than represented as zero.

## Live evidence

| Topic | Method | Result | Status |
| --- | --- | --- | --- |
| Vehicle dynamic source | `api.engine.system.transportVehicleSystem.getInfo` on vehicle entities 7656, 8055, 8328 | All three calls succeeded; nested `cargoInfos` exposed configuration `capacity`/`offset`, while `load`, `amount`, and `count` were absent. | API `ENGINE_AVAILABLE`; current load `UNAVAILABLE`. |
| Station samples | `game.interface.getStationTransportSamples` and installed `guidesystem.lua` trace | Locarno emitted `[743,743]`; vanilla uses the pair only to calculate a quality ratio. | Waiting `UNAVAILABLE`. |
| Line finance | Bounded `game.interface.getEntity(lineId)` fields and shipped-Lua index | No income/revenue/cost/profit binding located. | `UNAVAILABLE` / UI-only. |
| No-regression live request | File-bridge `get_game_state` | Full MCP E2E passed on the active save after the dynamic probe was installed. | Pass. |

## Safety result

All dynamic probes are read-only, bounded to three vehicles, and serialize only primitive whitelisted values. No mutation API is referenced. Current load, occupancy, waiting, and line finance remain unavailable until an independently traced structured field plus paused UI comparison validates each metric.

## Verification record

- Offline test suite: 25 passed.
- Python compilation: passed.
- Live E2E session before the final force-refresh wiring: `diagnostics/20260909-004651/mcp-session.jsonl`.

## Remaining evidence needed for promotion

1. A documented, safe current-load source that is numeric in three paused vehicle samples.
2. A verified station/group-to-transport-network mapping and terminal quantity semantics.
3. A documented or source-traced line-finance binding with three same-save UI comparisons.
