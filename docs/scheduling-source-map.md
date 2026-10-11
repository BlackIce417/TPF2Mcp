# Scheduling source map

The current snapshot has verified observed `frequency` and `rate` on a line.
They are observed KPIs, not direct write controls. The early shipped-script
scan was inconclusive; later updateLine stop-policy operations were verified,
as listed below. Station hold/release and timetable execution are separate
controls, not setters for observed frequency/rate. Current native and public
interface limits are documented in [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md).

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
