# TPF2 Entity and Component API research

This document separates official API documentation from live observations. Component shapes not yet captured in diagnostics remain `UNKNOWN`.

| API / component | Purpose and parameters | Documented return | Live result | Entity type |
| --- | --- | --- | --- | --- |
| `api.engine.forEachEntityWithComponent(callback, componentType)` | Invoke `callback(entity)` for each entity with a component enum value. | Iterates matching entities. | PASS: `TOWN` iteration returned 48 entities. | Town |
| `api.engine.getComponent(entity, componentType)` | Read one component from an entity. | Component or `nil`. | PASS for `NAME`; live component is userdata. | Town |
| `api.type.ComponentType.TOWN` | Town filter enum. | Town component enum value. | PASS: 48 entities. | Town |
| `api.type.ComponentType.NAME` | Name component enum. | Name component. | PASS; `component.name` must be accessed on userdata under `pcall`. | Town and named entities |
| `api.engine.system.townBuildingSystem.getLandUsePersonCapacities(townEntity)` | Read three land-use person capacities for a town entity. | `{int, int, int}`. This is not documented as population. | Invocation is guarded; exact live return shape pending named Town re-test. | Town |
| `api.type.ComponentType.SIM_BUILDING` | Industry simulation-building filter. | SimBuilding component enum value. | PASS: 193 entities; production/shipment fields remain UNKNOWN. | Industry |
| `api.type.ComponentType.STATION_GROUP` | Station-group filter; MCP's `station` means one station group, not a child `STATION` entity. | `stations` is the grouped station-entity collection. | PASS: 178 named groups in MCP_TEST_SAVE; engine collections are userdata, so length is read through protected `#`. | Station group |
| `api.type.ComponentType.STATION` | Child station filter. | A station belonging to a station group. | Not exported as an MCP station: its parent group is obtained through `api.engine.system.stationGroupSystem.getStationGroup(stationEntity)`. | Child station |
| `api.type.ComponentType.LINE` | Line filter enum. | Line component with `stops`; each stop carries `stationGroup`, station index and terminal index. | PASS: 96 named lines in MCP_TEST_SAVE; `stop_count` is obtained through protected collection length. | Line |
| `api.type.ComponentType.TRANSPORT_VEHICLE` | Vehicle filter enum. | Vehicle component; `line` is an entity reference when assigned. | PASS: 262 named vehicles in MCP_TEST_SAVE; every non-null `line_id` resolved to an exported line ID. | Vehicle |
| `api.type.ComponentType.PLAYER` + `ACCOUNT` | Identify player and account data. | Player / account components. | PASS: player entity 175104. Money/loan field names remain UNKNOWN. | Company |

## Notes

`api.engine.getComponentType` is not present in the official reference consulted for this project; component identifiers are resolved from `api.type.ComponentType` and are always checked under `pcall` by `collectors/common.lua`.

The public [api.engine reference](https://wiki.transportfever2.com/api/modules/api.engine.html) documents entity iteration, component reads, and the town-building system. The [component/type reference](https://wiki.transportfever2.com/api/modules/api.type.html) documents `TOWN`, `NAME`, `LINE`, `PLAYER`, `ACCOUNT`, and the component field models.

## Current limitations

- Town population is UNKNOWN; the available town-building function reports capacities, not confirmed population.
- Industry production, shipment, transport percentage, and cargo flow are UNKNOWN.
- Station waiting loads, connected lines, and station type are UNKNOWN.
- Line transport mode, frequency, rate, and finance are UNKNOWN.
- Vehicle model, capacity, load, maintenance, age, and position are UNKNOWN.
- Company money is `UNAVAILABLE VIA CURRENT PUBLIC READ API`: the live `ACCOUNT.money` probe returned `nil`.
- Company loan is available as numeric `ACCOUNT.loan` and is exported as `company.loan` (live MCP_TEST_SAVE value: `0`).

## Phase 2.1 live verification

The 2026-09-08 MCP_TEST_SAVE exported 37 towns, 83 industries, 178 station groups, 96 lines and 262 vehicles. The normal station semantic is **station group**: this aligns with line stops, whose documented reference is `stationGroup`. `STATION` is a child entity and is deliberately not mixed into the MCP station collection.

`company-probe.json` records the live `PLAYER`, `ACCOUNT`, and `NAME` component types plus safe `ACCOUNT.money` / `ACCOUNT.loan` probe results. The live probe found `ACCOUNT.loan = 0`; `ACCOUNT.money` remained unavailable and is not fabricated.

## Phase 3 live semantic probe

The live `LINE.stops` collection is userdata with a safe length metamethod.
Each stop is userdata with numeric `stationGroup`, `station`, and `terminal`
fields. `stationGroup` is the station-group entity ID exported by the MCP
station collection; this was resolved for every line stop in MCP_TEST_SAVE.

Direct `LINE.transportMode`, `TRANSPORT_VEHICLE.transportMode`, `mode`,
`vehicleType`, and `modelId` probes returned `nil`. `LINE.vehicleInfo` exists
as userdata but no documented safe mode field was observed. Transport mode is
therefore explicitly `UNKNOWN`, rather than inferred from names. `SIM_BUILDING`
was present but the probed `type`, `production`, and `cargo` fields were `nil`;
industry type and cargo semantics remain unavailable via the currently verified
public read API.
