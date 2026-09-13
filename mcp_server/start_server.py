"""Run the bundled TPF2 MCP stdio server without installing the package."""
from __future__ import annotations

import os
import sys
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parent
MOD_DIRECTORY = SERVER_DIRECTORY.parent
RUNTIME_MARKER = MOD_DIRECTORY / "res" / "scripts" / "tpf2_mcp" / "runtime.lua"

# Keep Workshop/manual Mod directories free of Python bytecode build artifacts.
sys.dont_write_bytecode = True

# A Workshop release bundles this directory directly inside the Mod. Pinning
# discovery to that parent prevents another manual/Workshop copy from winning.
if RUNTIME_MARKER.is_file():
    os.environ.setdefault("TPF2_MCP_MOD_DIR", str(MOD_DIRECTORY))

sys.path.insert(0, str(SERVER_DIRECTORY / "src"))

from tpf2_mcp.server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
