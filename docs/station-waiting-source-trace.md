# Station waiting sources

Updated 2026-09-25 after a source review. See [current capabilities](CURRENT_CAPABILITIES.md).

## Current status

Station-wide waiting remains unavailable in the generic snapshot: SnapshotIndex.station_operating_state returns waiting_total=null. The operational telemetry stations section only enumerates station groups/children and keeps unsafe station transport sampling disabled.

However, waiting passengers and cargo assigned to a line ARE available through get_line_demand and get_line_dispatch_state.demand. The Lua line_demand collector enumerates simPersonSystem.getSimPersonsForLine and simCargoSystem.getSimCargosForLine, classifies SIM_ENTITY_AT_TERMINAL, and aggregates lineStop0→lineStop1 plus cargo type.

get_station_dispatch_state now performs that additional aggregation. For every unique connected line it maps journeys whose lineStop0 is one of the station's stop indices, so repeated visits on a loop line are combined without counting the line twice. The result is returned under waiting with passenger/cargo counts, cargo types, per-line evidence, and quality fields for errors, truncation and waiting entities whose journey cannot be mapped.

The aggregate covers classified, line-assigned entities whose observed LINE_STOP_OD starts at the station. It excludes unassigned demand and does not claim a passenger's final building or a cargo shipment's final consumer. Passenger and cargo availability are tracked independently: a cargo probe failure does not hide valid passenger counts. If a connected line is unavailable for one kind, that kind's aggregate is null; truncated or unmapped samples set quality.complete=false.

## Historical probes

Phase 6–8 failed to obtain waiting values directly from STATION_GROUP/STATION or establish the transport-network-terminal mapping. getStationTransportSamples values such as [743,743] were quality-ratio inputs, not established waiting counts. Those conclusions remain valid for those probes, but do not negate the later line-entity collector.

Do not revive unsafe station UI sampling or fill missing generic snapshot waiting fields with invented values.
