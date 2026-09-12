# Phase 9 — Network Intelligence / Planning Layer

## Verified facts

- Line frequency and throughput are `UI_CROSS_VERIFIED`.
- Vehicle configured capacity is `UI_CROSS_VERIFIED`.
- Line/station/vehicle membership and stops are normalized runtime relations.
- Current vehicle load, occupancy, station waiting, and line finance are `UNAVAILABLE`.

## Derived metrics

- `fleet_capacity_total = sum(assigned vehicle.capacity_total)` when all assigned capacities are available.
- `average_vehicle_capacity = fleet_capacity_total / vehicle_count`.
- `capacity_per_stop = fleet_capacity_total / stop_count`.
- `vehicles_per_stop = vehicle_count / stop_count`.
- `throughput_per_vehicle = throughput / vehicle_count`; this is only a derived ratio, not utilization.
- Graph degree, components, reachability, rankings, outlier bounds, and structural distance are deterministic derived analytics.

Every intelligence response carries `snapshot_sequence`; the server caches one `NetworkIntelligenceIndex` per sequence and rebuilds it when the normalized snapshot changes.

## Heuristic rules

Line classifications and recommendations are labeled `HEURISTIC` and include their triggering rule/evidence. Long verified headways can produce `CHECK_LONG_HEADWAY_LINE`; small disconnected graph components can produce `REVIEW_ISOLATED_NETWORK_CLUSTER`. These prompt inspection, never game edits.

## Unsupported claims

The system cannot currently determine profitability, vehicle load, occupancy, waiting, congestion, or demand. Station hubs are topology hubs, not traffic rankings. `find_station_route` is a line/station connectivity route, not track, road, or physical-map navigation. Town/station and industry/cargo probes remain `UNRESOLVED` unless a verified runtime relation is found.
