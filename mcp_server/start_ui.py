"""Run the bundled TPF2 rail-map HTTP service."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parent
MOD_DIRECTORY = SERVER_DIRECTORY.parent
RUNTIME_MARKER = MOD_DIRECTORY / "res" / "scripts" / "tpf2_mcp" / "runtime.lua"
UI_SERVER = MOD_DIRECTORY / "tools" / "serve-rail-map.py"

sys.dont_write_bytecode = True
if RUNTIME_MARKER.is_file():
    os.environ.setdefault("TPF2_MCP_MOD_DIR", str(MOD_DIRECTORY))
sys.path.insert(0, str(SERVER_DIRECTORY / "src"))

if not UI_SERVER.is_file():
    raise SystemExit(f"Bundled UI server not found: {UI_SERVER}")

runpy.run_path(str(UI_SERVER), run_name="__main__")
