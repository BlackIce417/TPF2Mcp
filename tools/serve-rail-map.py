"""Launch the local FastAPI JSON API for railway-map and dispatch clients."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "mcp_server" / "src"))

from tpf2_mcp.config import bridge_dir  # noqa: E402
from tpf2_mcp.web_app import create_web_app  # noqa: E402
from tpf2_mcp.web_state import RailMapState  # noqa: E402


def create_app(state: RailMapState, *, manage_watcher: bool = False):
    """Create the FastAPI application without starting a network listener."""
    return create_web_app(state, manage_watcher=manage_watcher)


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-directory", type=Path, default=repository / "var" / "rail-map")
    parser.add_argument("--bridge-directory", type=Path, default=bridge_dir())
    parser.add_argument("--live-poll-seconds", type=float, default=0.2)
    args = parser.parse_args()
    data_directory = args.data_directory.resolve()
    data_directory.mkdir(parents=True, exist_ok=True)
    state = RailMapState(data_directory, args.bridge_directory.resolve(), repository / "tools" / "export-rail-network-map.py", args.live_poll_seconds)
    application = create_app(state, manage_watcher=True)
    print(f"TPF2 API: http://{args.host}:{args.port}/api/docs", flush=True)
    uvicorn.run(application, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
