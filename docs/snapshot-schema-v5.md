# World Snapshot Schema v5

> 2026-09-25 状态校订：本文为阶段记录或特定数据源/Schema 的历史说明，保留原结论以供追溯。载荷/候车量不可用不能推广为后续所有接口不可用；独立 line_demand 已提供客货计数和线路停站 OD，旧快照字段未必更新。当前入口与限制见 [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md)。

Schema v5 adds two paused-UI-cross-verified line metrics. The bridge command protocol remains version 1.

| Field | Type | Source | Verification | Semantics |
| --- | --- | --- | --- | --- |
| `lines[].frequency_seconds` | number | `game.interface.getEntity(line_id).frequency`, normalized as `1 / raw` | UI_CROSS_VERIFIED | Seconds between vehicles. Native UI formats the value as rounded whole minutes. |
| `lines[].throughput` | number | `game.interface.getEntity(line_id).rate` | UI_CROSS_VERIFIED | Native UI field labeled `吞吐量`; the game documentation describes Rate as average yearly cargo/passengers transported per station. |
| `metadata.field_sources` entries | string | Collector declaration | UI_CROSS_VERIFIED | Exact source and conversion provenance. |

Verification used a paused save: lines 29, 35, and 91 returned API rates 106, 345, and 406, exactly matching UI `吞吐量`; inverse raw frequencies were 30.97, 6.36, and 5.52 minutes, displayed by the UI as 31, 6, and 6 minutes.
