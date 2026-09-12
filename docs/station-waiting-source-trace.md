# Station waiting source trace

## Status

`UNRESOLVED`. No station-waiting value is exported in the snapshot.

## Evidence and candidates

The Phase 6 station-component probe found no `waiting`, `cargo`, or capacity payload on sampled `STATION_GROUP`/`STATION` components. The installed game-script source proves that `game.interface.getStationTransportSamples(stationId)` exists, but uses `samples[1] / samples[2]` only as a station-quality guidance ratio. A live probe returned values such as `[743, 743]` for Locarno; that still does not establish either number as waiting people or cargo.

The engine API documents terminal-oriented candidates: `simCargoSystem.getSimCargoAtTerminalForTransportNetwork(transportNetworkEntity)` and `simPersonSystem.getSimPersonsAtTerminalForTransportNetwork(transportNetworkEntity)`. Their documented input is a transport-network entity, not a station-group entity, so the required station/group-to-terminal mapping remains unverified.

Phase 8's bounded live mapping probe sampled three station groups (6493, 7251, 7626) and their child stations. `TRANSPORT_NETWORK_PROVIDER` is not an available component type in this game context, so its `terminals`/`transportNetwork` fields cannot provide the mapping. No terminal query was attempted.

## Safe next probe

First trace that mapping using a bounded, read-only source probe. Only then enumerate terminal cargo/person entities, identify their quantity fields, and compare three paused station-window samples. Do not infer station waiting from station quality samples or from a missing component field.

## Promotion rule

If a stable station-level aggregation is verified, normalize its scope explicitly:

```text
STATION terminal waiting -> STATION_GROUP waiting_total
```

Until then every station waiting field must remain `null` with availability `false`/`UNAVAILABLE`.
