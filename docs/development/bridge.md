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

The compatibility Bridge directory is `<mod_root>/bridge/`. A bundled Python service uses its own Mod root; runtime paths follow [Deployment](../usage/deployment.md). This document describes the legacy file bridge. Current production MCP commands and telemetry use shared memory, and a channel key ending in `.json` is not necessarily a disk file.
