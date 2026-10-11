# Vehicle current-load sources

Updated 2026-09-25 after a source review. See [current capabilities](CURRENT_CAPABILITIES.md).

## Current status

There are two different read paths:

| Path | Current behavior |
|---|---|
| Generic snapshot / SnapshotIndex.vehicle_operating_state | Capacity is available; load_total and occupancy_ratio remain unavailable |
| get_vehicle_dispatch_state | Joins live motion and capacity with per-vehicle onboard counts from the line_demand collector |
| get_line_demand / get_line_dispatch_state.demand | Returns passenger/cargo onboard and waiting counts, per-vehicle counts, cargo breakdown and line-stop OD |

Actual load is obtained by enumerating line-assigned persons/cargo and reading SIM_ENTITY_AT_VEHICLE.vehicle. Cargo amounts are entity counts, not an established mass unit. The code does not obtain load from getInfo.cargoInfos.

dispatch.vehicle_dispatch_state now propagates non-empty collector errors and UNAVAILABLE buckets as availability.load=false. Truncated passenger or cargo enumeration keeps the observed counts as lower bounds but sets availability.complete_load=false and suppresses occupancy_ratio. The quality object preserves the source, per-kind truncation and errors, so a failed enumeration is not represented as an empty train.

## Historical getInfo probe

Phase 7 successfully queried transportVehicleSystem.getInfo for vehicles 7656, 8055 and 8328, but cargoInfos exposed capacity/offset without amount/load/count. That source remains unverified for actual load. The historical failure is not a statement that every later load source is unavailable.
