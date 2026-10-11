# Phase 6 acceptance record

> 2026-09-25 状态校订：本文为阶段记录或特定数据源/Schema 的历史说明，保留原结论以供追溯。载荷/候车量不可用不能推广为后续所有接口不可用；独立 line_demand 已提供客货计数和线路停站 OD，旧快照字段未必更新。当前入口与限制见 [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md)。

Date: 2026-09-09

## Completed UI-cross-verified fields

| Field | Structured source | Paused UI cross-check |
| --- | --- | --- |
| Vehicle capacity | `TRANSPORT_VEHICLE.config.capacities` summed | Vehicles 42, 45, 145: 285, 232, 184 — exact matches. |
| Line throughput | `game.interface.getEntity(line_id).rate` | Lines 29, 35, 91: 106, 345, 406 — exact matches with UI `吞吐量`. |
| Line frequency | `1 / game.interface.getEntity(line_id).frequency` | Raw seconds 1858.000, 381.487, 331.250 format to UI 31, 6, 6 minutes. |

`game.interface` is live-verified in the MCP mod's `game_script.update` context. The final MCP E2E passed with schema v5, and `get_line_operating_summary` returns both frequency and throughput with availability `true`.

## Still unavailable

Line income/finance, station waiting, industry production, vehicle load, and vehicle speed/power are not exposed as verified MCP metrics. Company `ACCOUNT` and `game.interface` values agree, but native finance UI has not yet been sampled at three time points.

Evidence: `diagnostics/20260909-003037/`.
