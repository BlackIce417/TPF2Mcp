# World Snapshot Schema v3

> 2026-09-25 状态校订：本文为阶段记录或特定数据源/Schema 的历史说明，保留原结论以供追溯。载荷/候车量不可用不能推广为后续所有接口不可用；独立 line_demand 已提供客货计数和线路停站 OD，旧快照字段未必更新。当前入口与限制见 [CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md)。

Schema v3 extends v2 with only fields verified by the live public game-script
API:

- `company.balance` is the numeric public `ACCOUNT.balance` value.
- `company.loan` remains the numeric public `ACCOUNT.loan` value.
- `vehicles[].raw_state` is the numeric public `TRANSPORT_VEHICLE.state`
  value. Its enum meaning is not yet normalized.

The MCP operating-state tools place unverified metrics (`capacity`, `load`,
`waiting`, `frequency`, `revenue`, `cost`, `profit`) at `null` and expose a
per-field `availability` boolean. `null` means unavailable through the
currently verified public read API; it never means numeric zero.

The normalized snapshot version is independent from the file-bridge protocol,
which remains version 1.
