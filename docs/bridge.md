# File bridge MRE

The bridge directory contains these files:

```text
command.json       Python -> TPF2 request
responses/<id>.json  TPF2 -> Python response, written once per request
responses/<id>.ready TPF2 -> Python completion marker, written after response close
heartbeat.json     TPF2 liveness and probe result
state.json         latest normalized game snapshot
```

Python writers create a same-directory temporary file and atomically replace the final command filename. The live TPF2 Lua sandbox on this machine exposes neither `os.rename` nor `os.remove`, so Lua uses a request-specific response file and creates its `.ready` marker only after the response is closed. Every command includes a UUID `request_id`; the Python client accepts only the matching ready-marked response. The Lua runtime keeps the last handled request ID to avoid executing a command twice during a polling cycle.

For testing without the game, `MockBridge` returns `tests/fixtures/world_snapshot_001.json`. Use `TPF2_MCP_MOCK=1`.

The default bridge directory is `%APPDATA%\Transport Fever 2\tpf2_mcp_bridge`. Its availability to the TPF2 sandbox is not assumed: `io.open`, absolute paths, and atomic rename are probed and reported through `heartbeat.json`.
