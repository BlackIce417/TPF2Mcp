# Line finance source trace

## Status

`UI_ONLY`. The snapshot must not synthesize line finance.

## Evidence

The native line window visibly presents an income/result value, but the Phase 6 bounded `game.interface.getEntity(lineId)` probe found no primitive `income`, `revenue`, `profit`, or `cost` field. The indexed shipped Lua sources contain window routing but no accessible native line-finance data binding.

## Rule for future work

Do not broaden field-name guessing against engine objects. A candidate may be tested only after a documented API path or installed-source trace identifies it. Promote a finance field only after its unit, accounting period, sign convention, and three same-save paused UI comparisons agree. Otherwise the MCP response remains `null` and explicitly unavailable.
