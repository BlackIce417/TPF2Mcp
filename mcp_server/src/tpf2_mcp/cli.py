from __future__ import annotations

import argparse
import json

from .bridge import BridgeClient, BridgeError, MockBridge
from .config import mock_enabled


def main() -> int:
    parser = argparse.ArgumentParser(description="TPF2 MCP bridge diagnostics")
    parser.add_argument("command", choices=("status", "ping", "game-state"))
    arguments = parser.parse_args()
    bridge = MockBridge() if mock_enabled() else BridgeClient()
    try:
        result = bridge.status() if arguments.command == "status" else bridge.ping() if arguments.command == "ping" else bridge.game_state()
    except BridgeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
