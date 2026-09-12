# Phase 13: Operational Expansion

Phase 13 established two meaningful engine commands in the dedicated
acceptance save. They remain protected by the existing proposal/validation
architecture and the Lua global kill switch, which is off by default.

| Capability | Status | Risk |
| --- | --- | --- |
| `RENAME_LINE` | `POSTCONDITION_VERIFIED` | LOW |
| `BUY_VEHICLE` | `POSTCONDITION_VERIFIED` | MEDIUM |
| `ASSIGN_VEHICLE_TO_LINE` | `POSTCONDITION_VERIFIED` | MEDIUM |
| `SELL_VEHICLE` | `DISCOVERED_NOT_VERIFIED` | HIGH |
| `SET_LINE_STOPS` / line create/delete | `DISCOVERED_NOT_VERIFIED` | MEDIUM/HIGH |

The live test constructed `buyVehicle(playerEntity, depotEntity,
TransportVehicleConfig)` using an existing vehicle's documented
`transportVehicleConfig`—not the incompatible internal `.config` pointer.
It observed exactly one new vehicle (`1747376`) in a fresh snapshot. A second,
separate operation used `setLine(vehicleEntity, lineEntity, stopIndex)` and a
fresh snapshot confirmed `vehicle.line_id == 531841`.

This is deliberately not AUTO_SAFE: purchase and assignment are MEDIUM risk,
and no price/catalog or sell rollback semantic is yet verified. The test
vehicle is left in the dedicated save rather than attempting an unverified
sale. Evidence is in `diagnostics/phase13-live-20260909-1340`.

The read APIs `get_fleet_profile` and `get_line_fleet_profile` expose only
snapshot-backed assignment, raw depot/state, capacity, throughput, and
frequency fields. Raw fields are not given invented operational meanings.
