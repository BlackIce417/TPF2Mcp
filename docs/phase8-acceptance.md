# Phase 8 acceptance — operational diagnostics and explanation layer

## Capabilities and boundaries

The MCP publishes `tpf2://capabilities` before analytical tools are used. Capacity, line frequency, and line throughput are `UI_CROSS_VERIFIED`; live vehicle load, occupancy, station waiting, and line finance are `UNAVAILABLE`. `company_balance` remains an `ENGINE_AVAILABLE` raw field, while `company_cash_semantic` is `UNRESOLVED`.

## Implemented read-only analysis

- Correct snapshot timing semantics: `index_age_ms` measures local index age; `source_snapshot_age_ms` derives from the game snapshot timestamp and declares second-level precision.
- `get_line_scorecard`, `compare_lines`, and `rank_lines` use only stops, assigned vehicles, verified frequency/throughput, and derived static configured fleet capacity.
- `diagnose_line_structure` and `diagnose_transport_network` return structured evidence (`code`, severity, entity ID, evidence, interpretation) for structural warnings only.
- `TransportGraph` uses station groups as nodes and adjacent line stops as undirected edges. `find_station_route` is explicitly a line/station connectivity route, never a physical track/road route.
- Station connectivity, transfer-station ranking, fleet summary, and capacity ranking are all derived from verified topology/static capacity.

## Live verification

`diagnostics/20260909-011951/mcp-session.jsonl` passed the full MCP suite. It records `get_game_state` followed by `force_refresh: true`, with snapshot sequence `4 -> 5`, and exercises the Phase 8 scorecard/diagnostic tools and capabilities resource.

## Station terminal mapping probe

The new bounded, read-only probe sampled three station groups. On each child station, `TRANSPORT_NETWORK_PROVIDER` was unavailable as a component type. No unsafe terminal enumeration followed; station waiting remains `UNAVAILABLE`.

## Company balance UI cross-check

Three paused samples all showed UI bank balance `$∞` and loan `$0`. The same-save forced snapshots were sequences 8, 9, and 10: each returned `ACCOUNT.balance=0` and `loan=0`. Loan happened to agree, but balance did not; this save's infinite-money UI mode means `ACCOUNT.balance` must not be presented as current cash.
