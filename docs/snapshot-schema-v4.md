# World Snapshot Schema v4

Schema v4 adds a dynamic cargo registry. The file-bridge command protocol stays at version 1; only the normalized `world-state.json` contract changes.

| Field | Type | Source | Semantics |
| --- | --- | --- | --- |
| `cargo_types` | array | `api.res.cargoTypeRep.getAll()` | Current game/mod cargo identifiers, including installed content when exposed by the repository. |
| `cargo_types[].cargo_key` | string | Repository item value | Stable engine-facing key, such as `PASSENGERS` or `IRON_ORE`. |
| `cargo_types[].cargo_id` | integer | Zero-based repository position / `CargoTypeId` | Runtime ID used only for repository calls such as `getName`; do not persist it as a stable identity. |
| `cargo_types[].index` | integer | Enumeration order | Zero-based position in the current repository result; do not treat as a persistent ID. |
| `cargo_types[].display_name` | string, optional | `api.res.cargoTypeRep.getName(cargo_id)` | Localized display name when the game returns one. Absence is valid. |
| `metadata.field_sources.cargo_types` | string | Collector declaration | Provenance marker: `api.res.cargoTypeRep.getAll`. |

`cargo_types` is intentionally not a hard-coded vanilla list. Consumers should use `cargo_key`, tolerate unknown keys, and treat `display_name` as optional.

## Vehicle capacity field (Phase 6)

When `TRANSPORT_VEHICLE.config.capacities` is present and contains non-negative numeric slots, `vehicles[].capacity_total` is their sum. It is a static configured capacity, not current load. Its provenance is recorded as `metadata.field_sources["vehicles[].capacity_total"]`.
