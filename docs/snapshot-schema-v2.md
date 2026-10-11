# World Snapshot Schema v2

> 2026-09-25 状态校订：本文为阶段记录或特定数据源/Schema 的历史说明，保留原结论以供追溯。载荷/候车量不可用不能推广为后续所有接口不可用；独立 line_demand 已提供客货计数和线路停站 OD，旧快照字段未必更新。当前入口与限制见 [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md)。

`schema_version: 2` applies to the normalized world snapshot only. The file
bridge request/response protocol remains version 1.

`get_game_state` is now a compact overview: `game`, `company`, `metadata`, and
collection `counts`. `get_world_snapshot` returns the complete schema-v2 model.

## Verified network fields

- `stations[]` contains **station groups**, with `entity_type:
  "station_group"`, `station_count`, derived `line_ids`, and `line_count`.
- `lines[].stops[]` contains `{index, station_id}`. `station_id` is the real
  `LINE.stop.stationGroup` entity ID, verified against the station-group index.
- `lines[]` includes derived `vehicle_ids` and `vehicle_count`, built from the
  verified `TRANSPORT_VEHICLE.line` ID relation.
- `vehicles[]` includes `line_id`; `transport_mode` is `UNKNOWN` unless a
  public API field has been verified.

## Explicit unavailable fields

No public `transportMode` field was observed on live `LINE` or
`TRANSPORT_VEHICLE` userdata. Industry type/production fields were also absent
from the live public component probes. These remain `UNKNOWN`; no name-based
inference is applied.
