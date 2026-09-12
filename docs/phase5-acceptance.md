# Phase 5 acceptance record

Date: 2026-09-08

## Passed in the live TPF2 save

| Check | Result |
| --- | --- |
| Normalized snapshot schema | v4 |
| Cargo registry count | 17 |
| Cargo fields | 17/17 have `cargo_key`, `cargo_id`, `index`, and `display_name` |
| `api.res.cargoTypeRep.getName(0)` | Success; returned a string |
| MCP `get_cargo_types` | Count equals snapshot count (17) |
| MCP `tpf2://cargo-types` | Non-empty and readable |
| Existing topology APIs | towns 37, industries 83, station groups 178, lines 96, vehicles 262 |
| Snapshot validation | PASS; all entity collections, references, UTF-8, company, and cargo types valid |

Live E2E session: `diagnostics/20260908-231739/mcp-session.jsonl`.

## Deliberately unavailable

Vehicle capacity, line frequency/income/throughput, station waiting, and industry production remain unavailable to the collector. The UI map documents the evidence and keeps their MCP availability flags false; no derived or guessed values are emitted.
