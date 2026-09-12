# TPF2 Lua API capability log

This file records observed results. A **LIVE TPF2 TEST** passed on 2026-09-08 using the active test save. TPF2's executable did not expose a file/product version through Windows metadata, so the version remains `UNKNOWN`.

| Capability | Result | TPF2 version | Observed output | Evidence/log |
| --- | --- | --- |
| Lua version | PASS | UNKNOWN | `Lua 5.2` | `heartbeat.json`, 2026-09-08 |
| `require` custom script | PASS | UNKNOWN | `require: true` | `heartbeat.json`, 2026-09-08 |
| `io.open` read/write | PASS | UNKNOWN | `io_open`, `io_read`, `io_write`: true | `heartbeat.json`, 2026-09-08 |
| `os.rename` | UNAVAILABLE | UNKNOWN | `os.rename unavailable` | `heartbeat.json`, 2026-09-08 |
| `os.remove` | UNAVAILABLE | UNKNOWN | `os.remove unavailable` | `heartbeat.json`, 2026-09-08 |
| Absolute bridge path | PASS | UNKNOWN | `absolute_path: true` | `heartbeat.json`, 2026-09-08 |
| `api`, `api.engine` | PASS | UNKNOWN | `api`, `api_engine`: true | `heartbeat.json`, 2026-09-08 |
| `api.engine.util.getWorld()` / `getPlayer()` | PASS | UNKNOWN | `world_entity: 0`, `player_entity: 175104` | `state.json`, 2026-09-08 |

## Procedure

1. Install and enable `tpf2_mod` in a test save.
2. Wait for a heartbeat file, then run `python -m tpf2_mcp.cli status`.
3. Record the `probe` object and the relevant TPF2 log lines here.
4. Preserve unsupported APIs as explicit restrictions rather than assuming a fallback exists.

## Design references

- [TPF2 Game Scripts](https://wiki.transportfever2.com/doku.php?id=modding:gamescripts) documents the `load`, `save`, and periodic engine `update` callbacks used by this mod.
- [TPF2 api.engine reference](https://wiki.transportfever2.com/api/modules/api.engine.html) documents the read-only engine API and `api.engine.util.getWorld()` / `getPlayer()`.
