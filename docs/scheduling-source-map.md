# Scheduling source map

The current snapshot has verified observed `frequency` and `rate` on a line.
They are KPIs, not established write controls. The installed shipped-script
scan found no command signature for minimum load, maximum wait, full-load, or
terminal waiting policy.

| UI/control concept | Read path | Write command | Status |
|---|---|---|---|
| Frequency | `game.interface.getEntity(line).frequency` | none found | observed KPI only |
| Throughput/rate | `game.interface.getEntity(line).rate` | none found | observed KPI only |
| Load mode | `LINE.stops[].loadMode` | `updateLine` | POSTCONDITION_VERIFIED |
| Minimum wait | `LINE.stops[].minWaitingTime` | `updateLine` | POSTCONDITION_VERIFIED |
| Maximum wait | `LINE.stops[].maxWaitingTime` | `updateLine` | POSTCONDITION_VERIFIED |

Phase 20 exposes these fields through `SET_LINE_STOP_POLICY`. Values are
validated as load mode `0..2` and `0 <= min_waiting_time <= max_waiting_time`.
The live evidence is in `diagnostics/phase20-live/scheduling-policy/result.json`.
Frequency and throughput remain outcomes and are not exposed as write controls.
