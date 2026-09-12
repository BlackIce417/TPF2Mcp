# AI Traffic Operator final-goal acceptance

Date: 2026-09-11 (Asia/Shanghai)

## Outcome

The verified operational core is complete: MCP can inspect the live network,
produce evidence-limited line candidates, and execute line/fleet/policy
changes only through bounded Tasks. Every Product Ready mutation has live Task
evidence and a fresh-snapshot postcondition.

The broader autonomous optimization target is intentionally only partially
available. Current snapshots do not expose verified passenger/vehicle load,
station waiting, line finance, physical path reachability, or town-region
mapping. The system therefore does not claim demand-driven autonomous
optimization, direct frequency control, or safe line deletion.

## Live acceptance results

| Requirement | Result | Evidence |
|---|---|---|
| Create a line from observed stations/terminals | PASS | `diagnostics/final-goal-live/two-vehicle-line/04-step-1.json` |
| Explicitly configure ordered stops | PASS | `diagnostics/final-goal-live/two-vehicle-line/04-step-2.json` |
| Buy and assign two vehicles | PASS | `diagnostics/final-goal-live/two-vehicle-line/result.json` |
| Modify an existing line's stop order | PASS | `diagnostics/final-goal-live/task-gate-safe/01-set_line_stops_goal.json` |
| Adjust stop load/wait policy | PASS | `diagnostics/final-goal-live/task-gate-safe/02-set_line_stop_policy_goal.json` |
| Buy a disposable vehicle | PASS | `diagnostics/final-goal-live/task-gate-safe/03-buy_vehicle_goal.json` |
| Confirm and sell that exact vehicle | PASS | `diagnostics/final-goal-live/task-gate-safe/04-sell_vehicle_goal.json` |
| Rename and restore through Tasks | PASS | `diagnostics/final-goal-live/rename-task/result.json` |
| Automatically rank new-line candidates | PASS (read-only) | `diagnostics/final-goal-live/planner/new-line-candidates.json` |
| Direct MCP mutation bypass | BLOCKED BY DESIGN | `execute_operation` absent from `tools/list` and rejects direct calls |

The six-step scenario created line `1799706`, set route
`498162 → 213303`, bought vehicles `1400525` and `1113139`, and verified both
were assigned. A later live snapshot (sequence 33) still showed the line, both
vehicle assignments, frequency about 98.3 seconds, and throughput 238.

The sale scenario bought vehicle `1804498`, required confirmation
`SELL_VEHICLE:1804498`, sold it, and verified the entity was absent.

## Safety correction discovered during acceptance

An attempted `A → B → A` stop vector caused a native TPF2 hang in
`tpf2_mcp.lua_update()` before the engine returned a command result. TPF2 lines
already cycle from their final stop back to their first stop, so the third
duplicate stop was unnecessary. Both Task validation and operation validation
now reject any repeated station ID before bridge dispatch. The safe two-stop
form `A → B` was then live verified.

## Product Ready mutations

- `RENAME_LINE`
- `CREATE_LINE`
- `SET_LINE_STOPS`
- `BUY_VEHICLE`
- `ASSIGN_VEHICLE_TO_LINE`
- `SET_LINE_STOP_POLICY`
- `SELL_VEHICLE`

`product_ready` now additionally requires `task_live_verified`; old direct
controller evidence alone cannot qualify an operation.

## Operator workflow

1. Refresh the snapshot and inspect network/line/fleet evidence.
2. Use `plan_new_line_candidates` or the existing diagnostics and simulations.
3. Resolve every station, terminal, line, depot, template vehicle, and target
   vehicle from that snapshot. Reject ambiguity.
4. Create and plan a bounded Goal/Task.
5. Obtain manual approval for MEDIUM/HIGH-risk writes.
6. Call `continue_task` once per mutation. Each call re-observes, executes at
   most one operation, refreshes again, and checks its postcondition.
7. Observe frequency and throughput after operation; do not present them as
   directly settable values.

## Honest remaining boundaries

- Direct departure-interval/frequency commands are not verified. Service
  frequency can be influenced by fleet count, while stop wait/load policy is
  directly controllable.
- `OPTIMIZE_LINE_GOAL` stays PLAN_ONLY until load/wait/profit evidence exists.
- Candidate planning is topology-based. It cannot prove demand, economic
  value, distance, travel time, or physical track/road reachability.
- `REMOVE_VEHICLE_FROM_LINE` is engine-rejected and unavailable.
- `DELETE_LINE` and `SEND_VEHICLE_TO_DEPOT` are not live verified; full line
  resource cleanup therefore remains incomplete.
- Infrastructure construction is out of scope by requirement.

These are explicit unavailable capabilities, not silently guessed behavior.
