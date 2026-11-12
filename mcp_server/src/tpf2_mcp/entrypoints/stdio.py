"""Line-oriented stdio MCP transport."""
import json
import sys
from tpf2_mcp.common.audit import start_audit
from tpf2_mcp.mcp.server import handle, _bridge, _error

def main() -> int:
    start_audit()
    # Windows console code pages otherwise leak into redirected stdio and can
    # corrupt valid UTF-8 game names in JSON-RPC captures.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    bridge = _bridge()
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle(message, bridge)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        except json.JSONDecodeError as exc:
            print(json.dumps(_error(-32700, f"parse error: {exc.msg}")), flush=True)
        except Exception as exc:  # Keep stdio protocol alive after unexpected failures.
            print(json.dumps(_error(-32603, f"internal error: {exc}")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
