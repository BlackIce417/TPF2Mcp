# Phase 14: Operational Control Completion

Phase 14 closes the product-layer gap between an engine command proven in a
dedicated save and an operation usable through MCP. Capability responses now
separate `discovered`, `engine_verified`, `controller_supported`,
`task_supported`, and `runtime_enabled`; the last value stays false while the
Lua kill switch is off.

The handler registry in `operations/handlers` is the extension boundary.
`BUY_VEHICLE` and `ASSIGN_VEHICLE_TO_LINE` have proposal validation, command
envelopes, fresh-snapshot postconditions, and task-goal integration. The
canonical composite task is `BUY_AND_ASSIGN_VEHICLE_GOAL`: its second step is
created only after the first step's verified `new_entities` result provides an
actual vehicle ID in `runtime_context.new_vehicle_id`. Every `continue_task`
performs at most one mutation.

Operations and tasks are append-only JSONL journals in the local MCP state
directory (`%APPDATA%\\Transport Fever 2\\tpf2_mcp_state` by default), separate
from Bridge Protocol files. On restart the latest state is recovered without
resending an engine command.

The Phase 14 source scan found only UI/sound references for `sellVehicle`,
`sendToDepot`, and line creation; it found no callable signature. Selling,
stop changes, and line creation therefore remain deliberately unsupported
until a concrete command signature and dedicated-save evidence exist. No
status is collapsed into a vague “supported”.
