# Phase 20.1 Vehicle Lifecycle

## Outcome

`SELL_VEHICLE` is live verified through the controlled-operation pipeline.
`REMOVE_VEHICLE_FROM_LINE` is unavailable because no distinct native
unassign-and-keep command has been verified.

## SELL_VEHICLE safety contract

- Risk class: `HIGH`; destructive and not rollback-capable.
- The proposal requires `parameters.confirmation` to equal
  `SELL_VEHICLE:<vehicle_id>`.
- The Lua dispatcher repeats the same exact confirmation check.
- Validation requires the vehicle to exist and retain its proposed name and
  line assignment immediately before execution.
- Verification requires a forced fresh snapshot in which the vehicle entity
  no longer exists.
- The live acceptance target was newly purchased disposable vehicle `1790269`.

Evidence is under `diagnostics/phase20-live/sell-vehicle/`.

## REMOVE_VEHICLE_FROM_LINE result

The constructor `api.cmd.make.setLine(vehicle, -1, 0)` can create a command
object, but the engine rejected its execution without changing the vehicle.
Official commands and observed implementations distinguish:

- assigning a vehicle to a valid line;
- sending a vehicle to a depot;
- selling a vehicle.

No distinct primitive for leaving an active vehicle unassigned in the world
was verified. The capability therefore fails closed as
`ENGINE_REJECTED_UNAVAILABLE`; it is not controller-supported or allowlisted.
Failure evidence is under `diagnostics/phase20-live/remove-vehicle/03-remove/`.

## Phase 20.2 create/configure/staff result

`CREATE_AND_CONFIGURE_LINE_GOAL` performs four bounded writes and discovers
new entity IDs only from verified postconditions. The final live run created
line `1740957`, explicitly reapplied route `[498162, 213303]`, bought vehicle
`1796867`, and assigned it to that line. Every step was
`POSTCONDITION_VERIFIED`.

Evidence is under `diagnostics/phase20-live/create-and-configure-goal-final/`.

## Phase 20.3 scheduling result

`SET_LINE_STOP_POLICY` controls documented `Line.Stop` fields through the
already verified `updateLine` command:

- load mode (`0..2`);
- minimum waiting time;
- maximum waiting time.

On disposable line `1762625`, stop `0` was changed to load mode `1`, minimum
waiting time `30`, and maximum waiting time `120`; a fresh snapshot matched
all three values exactly. Frequency and throughput are measured outcomes, not
direct scheduling controls.

Evidence is under `diagnostics/phase20-live/scheduling-policy/`.

## Optimization boundary

The existing analytics and decision-support layers can identify structural
outliers and produce hypothetical fleet options. Automatic mutation is not
claimed: vehicle load, station waiting, and line profit remain unavailable,
so an evidence-based optimizer cannot safely decide whether to add, sell, or
retime vehicles. Optimization stays `PLAN_ONLY`.
