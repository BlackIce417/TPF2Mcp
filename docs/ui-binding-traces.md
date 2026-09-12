# Native UI binding traces

This document records source-level traces from the locally installed TPF2 Lua files. A trace only becomes an MCP source after a live, read-only probe succeeds.

## Contexts

| Context | Source evidence | `game.interface` status |
| --- | --- | --- |
| Game-script lifecycle | `res/config/game_script/base.lua` calls `game.interface.getGameTime()` in `init`/`update`. | Source-confirmed; Phase 6 `context-probe.json` performs the live confirmation from this mod's `game_script.update`. |
| GUI event bridge inside a game script | `res/scripts/mission/vehiclestore.lua` defines `guiHandleEvent` and calls `game.interface.getEntity`. | Source-confirmed. This is a game-script handler, not evidence that arbitrary GUI-only Lua can send data to the engine context. |
| GUI-oriented selection helper | `res/scripts/contexthelper.lua:686` calls `game.interface.getEntity(param)` to decide which native window to open. | Source-confirmed; native manager window value bindings are not present in the shipped Lua files indexed in Phase 6. |
| MCP collector | `tpf2_mcp` runs in `res/config/game_script/tpf2_mcp.lua` `update`. | Live probe pending after installation/reload. |

## Company balance and loan

```text
Finance / player state
  ↓
res/scripts/guidesystem.lua:658, 677–679
  ↓
game.interface.getEntity(game.interface.getPlayer())
  ↓
player.balance / player.loan
  ↓
candidate MCP source: game.interface player entity (read-only)
```

The existing collector source is `ACCOUNT.balance` / `ACCOUNT.loan`. Phase 6 compares the two sources but does not name either one UI cash until three same-save UI samples are captured.

## Vehicle model identity

```text
Vehicle-manager game-script handler
  ↓
res/scripts/mission/vehiclestore.lua:18–28
  ↓
game.interface.getVehicles()
  ↓
game.interface.getEntity(vehicleId)
  ↓
vehicle.fileName; for consists vehicle.vehicles[i].fileName
  ↓
candidate MCP source: game.interface vehicle fileName → api.res.modelRep lookup
```

This establishes a source-level path for vehicle entity → model file name. Separately, `TRANSPORT_VEHICLE.config.capacities` was read in the engine context and its sum matched all three Phase 4 UI capacity samples. Native Vehicle Manager speed/power bindings remain unresolved.

## Station transport sample

```text
Station-quality guide
  ↓
res/scripts/guidesystem.lua:1211–1219
  ↓
game.interface.getStations()
  ↓
game.interface.getStationTransportSamples(stationId)
  ↓
samples[1] / samples[2] quality ratio
  ↓
candidate MCP source: station transport samples (semantics unresolved)
```

The script proves this method exists in a game-script context, but does not label either element as current waiting cargo or passengers. It must not feed `waiting_total` until a dedicated probe and UI comparison establish its unit and scope.

## Line, station, and industry management windows

The indexed original Lua sources contain menu/window routing (`contexthelper.lua`) but no Lua data-binding expression for the native manager values: line frequency/result/throughput, station waiting, or industry production/shipment/transport. Those bindings are therefore **not located in shipped Lua**. They remain `OBSERVED_ONLY` until a structured `game.interface` method is located and verified.

## Trust levels

| Field | Current level | Reason |
| --- | --- | --- |
| `cargo_types` | ENGINE_VERIFIED | Repository read and MCP E2E passed. |
| `company.balance`, `company.loan` | ENGINE_VERIFIED | `ACCOUNT` fields pass; UI-side source trace is known, live dual-source/UI comparison pending. |
| vehicle `fileName` path | SOURCE_TRACE_ONLY | Original script trace; MCP context call pending. |
| vehicle capacity | UI_CROSS_VERIFIED | `TRANSPORT_VEHICLE.config.capacities` sums matched UI values 285, 232, and 184 for the three Phase 4 samples. |
| vehicle speed/power/spec | OBSERVED_ONLY | UI values exist, static model binding is traced but not yet normalized or cross-verified. |
| line `frequency` | UI_CROSS_VERIFIED | `game.interface.getEntity(lineId).frequency`; inverse raw value produces seconds, then native UI formats whole minutes. Paused samples: 31, 6, 6 minutes. |
| line `rate` | UI_CROSS_VERIFIED | It exactly matched the native UI field labeled `吞吐量` for paused samples 106, 345, 406. |
| line finance | OBSERVED_ONLY | `income`, `revenue`, `profit`, and `cost` were absent from live line entities. |
| station waiting | OBSERVED_ONLY | UI exists; sample method semantics unresolved. |
| industry rates | OBSERVED_ONLY | UI exists; binding not found. |
