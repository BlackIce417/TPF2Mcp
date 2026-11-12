# Line command source trace

2026-09-09 source scan of the installed TPF2 scripts found no shipped Lua call
site that exposes a callable line-create, line-delete, or stop-edit command.
The `api.cmd.make.setLine` signature is already live-verified only for vehicle
assignment (`vehicleEntity`, `lineEntity`, `stopIndex`); it must not be reused
as a line-stop mutation API.

| Candidate | Source trace | Signature | Confidence | Verification |
|---|---|---|---|---|
| `api.cmd.make.setLine` | Phase 13 dispatcher/live evidence | `(vehicleEntity, lineEntity, stopIndex)` | high | POSTCONDITION_VERIFIED for assignment only |
| `api.cmd.make.createLine` | live `__doc__` probe | `(String name, Vec3f color, Entity playerEntity, Line line) -> Command` | high signature / unknown payload | DISCOVERED_NOT_VERIFIED |
| `api.cmd.make.updateLine` | live `__doc__` probe | `(Entity lineEntity, Line line) -> Command` | high signature / unknown payload | DISCOVERED_NOT_VERIFIED |
| `api.cmd.make.deleteLine` | live `__doc__` probe | `(Entity lineEntity) -> Command` | high signature | DISCOVERED_NOT_VERIFIED |
| `sellVehicle` / `sendToDepot` | live `__doc__` probe | vehicle signatures found; no lifecycle semantics tested | medium | DISCOVERED_NOT_VERIFIED |

No command is implemented from a UI label or sound name.
