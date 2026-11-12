# Company balance UI cross-check

| Sample | UI bank balance | UI loan | Snapshot sequence | `ACCOUNT.balance` | `ACCOUNT.loan` | Result |
| --- | --- | --- | ---: | ---: | ---: | --- |
| A | `$∞` | `$0` | 8 | 0 | 0 | Balance mismatch |
| B | `$∞` | `$0` | 9 | 0 | 0 | Balance mismatch |
| C | `$∞` | `$0` | 10 | 0 | 0 | Balance mismatch |

The three paused UI samples were captured from the Finance/Data Chart window in the same active save. Because the UI uses infinite-money display while the engine `ACCOUNT.balance` is numeric zero, the MCP exposes `balance` only as an engine raw field. It does not label it cash, current money, or bank balance.
