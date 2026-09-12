# Phase 12: Closed-Loop Task Orchestration

Phase 12 adds bounded task orchestration, not unrestricted autonomous play.
Every game mutation remains owned by `OperationController`; the task layer has
no bridge or Lua access.

```text
goal -> plan one step -> approval/policy -> one operation -> fresh snapshot
     -> postcondition verification -> goal check -> completed or replan
```

## Goal and policy boundaries

- `RENAME_LINE_GOAL` is executable because `RENAME_LINE` is
  `POSTCONDITION_VERIFIED` in Phase 11.
- Network-improvement and isolation goals are `PLAN_ONLY`: they never invent
  construction commands.
- `MANUAL` is the default and requires `approve_task_step`.
- `AUTO_SAFE` requires a verified, non-destructive, rollback-supported
  operation. `PLAN_ONLY` never executes.

## Safety limits

Each task freezes its line IDs and operation types, defaults to one write, and
is bounded by `max_steps <= 10`, `max_replans <= 3`, and
`max_write_operations <= 5`. A `continue_task` invocation re-observes state,
replans on a changed snapshot, and executes at most one mutation.

Task journals record logical timeline events, proposal/operation IDs, snapshot
sequences, goal-relevant evidence, and verification; they do not copy full
world snapshots. A goal already satisfied externally completes with zero
writes. Execution failures after any prior write are represented as partial
completion rather than hidden.

## MCP tools

`get_task_capabilities`, `create_task`, `plan_task`, `get_task`, `list_tasks`,
`get_next_task_step`, `approve_task_step`, `continue_task`, `cancel_task`, and
`explain_task` expose the task state machine. The dedicated-save Phase 12
acceptance test completed on line `11833`: a manual rename task replanned on a
fresh snapshot, executed exactly one mutation, and reached
`POSTCONDITION_VERIFIED`; a separate restore task then restored the original
name and reached the same status. Evidence is in
`diagnostics/phase12-live-20260909-1235`. The installed configuration was
then restored to disabled writes and an empty allowlist.
