# Phase 10 — Decision Support / What-If Planning

## Safety boundary

Every scenario is an in-memory Python hypothesis bound to one `snapshot_sequence`. No planning tool calls a game write API, edits bridge state, purchases vehicles, creates lines, or changes the save.

## Problem and evidence chain

`detect_network_problems` converts Phase 9 long-headway and isolated-component recommendations into deterministic `NetworkProblem` objects. `analyze_problem_impact` returns only verified topology/fleet relations. Source status propagates as `UI_CROSS_VERIFIED → DERIVED → HEURISTIC → HYPOTHETICAL`; unavailable load, waiting, finance, demand, travel time, cost, and ROI remain unavailable.

## Virtual mutations

- `CHANGE_VIRTUAL_VEHICLE_COUNT`
- `CHANGE_VIRTUAL_FREQUENCY`
- `CONNECT_EXISTING_STATIONS`
- `DISCONNECT_LINE`

Vehicle-count changes never infer a new frequency. Station connections and failures are reliable topology what-if calculations, not physical construction plans.

## Resilience and route analysis

Tarjan analysis derives articulation stations and bridge connections from the line/station graph. These are topology dependencies, not congestion or passenger-demand evidence. Routes are minimum-hop station/line connectivity paths, not fastest, cheapest, road, rail, or map paths.

## Scenario comparison

Scenarios are compared only on topology and virtual fleet dimensions: connectivity gain, isolation reduction, redundancy context, fleet change, and evidence strength. Cost, demand effect, and profit effect explicitly return `UNAVAILABLE`.
