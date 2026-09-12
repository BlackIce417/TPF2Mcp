# World Snapshot Schema v3

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
