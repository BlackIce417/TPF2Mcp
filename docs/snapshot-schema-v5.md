# World Snapshot Schema v5

Schema v5 adds two paused-UI-cross-verified line metrics. The bridge command protocol remains version 1.

| Field | Type | Source | Verification | Semantics |
| --- | --- | --- | --- | --- |
| `lines[].frequency_seconds` | number | `game.interface.getEntity(line_id).frequency`, normalized as `1 / raw` | UI_CROSS_VERIFIED | Seconds between vehicles. Native UI formats the value as rounded whole minutes. |
| `lines[].throughput` | number | `game.interface.getEntity(line_id).rate` | UI_CROSS_VERIFIED | Native UI field labeled `吞吐量`; the game documentation describes Rate as average yearly cargo/passengers transported per station. |
| `metadata.field_sources` entries | string | Collector declaration | UI_CROSS_VERIFIED | Exact source and conversion provenance. |

Verification used a paused save: lines 29, 35, and 91 returned API rates 106, 345, and 406, exactly matching UI `吞吐量`; inverse raw frequencies were 30.97, 6.36, and 5.52 minutes, displayed by the UI as 31, 6, and 6 minutes.
