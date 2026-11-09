"""Run the shared local TPF2 MCP Streamable HTTP server."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parent
MOD_DIRECTORY = SERVER_DIRECTORY.parent
RUNTIME_MARKER = MOD_DIRECTORY / "res" / "scripts" / "tpf2_mcp" / "runtime.lua"

sys.dont_write_bytecode = True
if RUNTIME_MARKER.is_file():
    os.environ.setdefault("TPF2_MCP_MOD_DIR", str(MOD_DIRECTORY))
sys.path.insert(0, str(SERVER_DIRECTORY / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the TPF2 MCP Streamable HTTP endpoint")
    parser.add_argument("--host", default=os.environ.get("TPF2_MCP_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TPF2_MCP_HTTP_PORT", "8766")))
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("port must be between 1 and 65535")

    import uvicorn
    uvicorn.run(
        "tpf2_mcp.http_server:app",
        host=arguments.host,
        port=arguments.port,
        log_level="info",
        access_log=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
