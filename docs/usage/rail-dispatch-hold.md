# Per-vehicle terminal hold

Status: `POSTCONDITION_VERIFIED_RUNNING_SIMULATION` on 2026-09-11.

## Operations

- `HOLD_VEHICLE_AT_TERMINAL` calls native `setVehicleManualDeparture(entity, true)`.
- `RELEASE_VEHICLE_FROM_HOLD` clears manual departure and requests departure.
- Every hold requires `max_hold_seconds` in `10..600`. The Lua runtime releases an expired hold independently of the MCP process.
- Both operations use proposal, scoped validation, explicit Task approval, one-write budget, callback state, and fresh-snapshot postcondition verification. New holds are rejected unless the engine reports `paused=false` and a positive speed multiplier; release remains available while paused.

Running Controller evidence: `diagnostics/rail-operations/dispatch-train-hold-running-verified/result.json`.

Running Task evidence: `diagnostics/rail-operations/dispatch-train-task-running-verified/result.json`.

The earlier evidence in `dispatch-hold-mre-terminal` and `dispatch-task-live` was captured while paused and is retained only as command-path history.

The first geometry-only sample (`dispatch-hold-mre`) proved that an edge inside a platform chain is not sufficient to identify terminal service. Dispatch selection must also require `raw_state == 2`, zero speed, the exact line stop/station/terminal match, and an interior stopping position. A released train may remain stopped at an exit signal; clearing manual departure is verified independently from physical movement.

## Current overtaking candidates

`diagnostics/rail-operations/overtake-candidates.json` contains eight structural combinations at Camorino. Lines 78 and 84 call there; lines 86 and 87 skip it. The derived physical graph confirms the fast lines do not traverse either platform chain while the stopping lines do.

No candidate is automatically executable yet. A live hold additionally requires a faster train behind in the same direction, a bounded ETA window, and downstream-merge clearance. This prevents a structural candidate from becoming an unsafe hold at the wrong time.

## Non-passenger operational stop

The documented `Line.Stop.how.load/unload` structure may support a stop with passenger service disabled. This build did not expose a serializable `how` value in the live stop snapshot, so mutation remains `UNKNOWN` and is not implemented.
