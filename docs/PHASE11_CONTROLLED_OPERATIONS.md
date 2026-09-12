# Phase 11: Controlled Operations

Phase 11 introduces a separate controlled-operation path. It is intentionally
not an autonomous game editor and it does not turn a planning option into a
command.

```text
proposal -> validation -> explicit execution -> new snapshot -> verification
```

The current delivery is a safe, fail-closed foundation. TPF2's shipped
`mission/nameutil.lua` references `game.interface.setName(id, name)`. In the
authorized test save, line `11833` was renamed, observed in a new snapshot,
then restored and observed again. `RENAME_LINE` is therefore
`POSTCONDITION_VERIFIED`; `RENAME_STATION` remains `DISCOVERED_NOT_VERIFIED`.

## Safety controls

- `tpf2_mod/.../config.lua` defaults `allow_write_operations = false` and has
  an empty operation allowlist.
- The Lua dispatcher rejects all operations while that kill switch is false.
- The Python controller sends no write bridge command while a capability is
  unverified. Verified writes still require the Lua kill switch and explicit
  allowlist, both disabled by default.
- The Lua write API probe only reads function types. It never invokes a write
  function and writes `write-api-probe.json` during a normal state request.

## MCP lifecycle tools

`get_operation_capabilities`, `propose_operation`, `validate_operation`,
`execute_operation`, `get_operation`, `list_recent_operations`, and
`create_rollback_operation` all go through one `OperationController`.

`RENAME_LINE` proposals capture the snapshot sequence, old line name, desired
name, and expected effect. Validation rejects an absent line, stale snapshot,
changed old name, or unverified capability. A rollback is a new compensating
proposal (old name), never a database transaction.

## What remains before a live write

The dedicated-save live rename test is complete: `EXECUTED`, fresh-snapshot
`POSTCONDITION_VERIFIED`, duplicate `ALREADY_EXECUTED`, and a separately
proposed rollback with `POSTCONDITION_VERIFIED`. Its evidence is retained in
`diagnostics/phase11-live`. The installed mod has since been regenerated with
all writes disabled; reload the save before any later operation attempt.
