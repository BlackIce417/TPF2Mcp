# Vehicle current-load source trace

## Status

`ENGINE_AVAILABLE` for the safe `getInfo` call, but **`UNAVAILABLE` for current load**. The live Phase 7 probe successfully called the source for vehicle entities 7656, 8055, and 8328. Each returned `cargoInfos`, but only the documented configuration fields `capacity` and `offset`; `load`, `amount`, and `count` were absent.

## Read-only path under test

```text
vehicle entity
  -> api.engine.system.transportVehicleSystem.getInfo(vehicle entity)
  -> TransportVehicleInfo.cargoInfos
  -> vehicle / compartment / cargo-type entries
```

The TPF2 API documents `transportVehicleSystem.getInfo` as a read-only engine-system query and documents `TransportVehicleInfo.cargoInfos` as a nested vehicle/compartment/cargo-type collection. The documented `VehicleCargoInfo` fields establish `capacity` and `offset`; they do not, by themselves, establish a current-load field. Phase 7 probed fixed candidate names `amount`, `load`, `count`, `cargo`, `cargoType`, `cargoTypeId`, and `type` alongside `capacity`/`offset`; all load candidates were absent in the three live samples.

## Safety boundary

`dynamic-transport-probe.json` samples at most three `TRANSPORT_VEHICLE` entities. It only calls `getInfo(entity)`, records call success and primitive whitelisted fields, and never serializes a userdata object. It does not modify an entity, issue commands, or feed a public MCP field.

## Promotion rule

Promote `vehicles[].load_total` only when the candidate is numerically reproducible and matches three paused Vehicle Manager cargo samples in the same save. Then derive:

```text
occupancy_ratio = load_total / capacity_total
```

with zero or missing capacity reported as unavailable rather than divided.
