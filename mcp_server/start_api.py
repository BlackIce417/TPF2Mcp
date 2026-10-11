"""Run the bundled TPF2 FastAPI JSON service."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parent
MOD_DIRECTORY = SERVER_DIRECTORY.parent
RUNTIME_MARKER = MOD_DIRECTORY / "res" / "scripts" / "tpf2_mcp" / "runtime.lua"
API_SERVER = MOD_DIRECTORY / "tools" / "serve-rail-map.py"

sys.dont_write_bytecode = True
if RUNTIME_MARKER.is_file():
    os.environ.setdefault("TPF2_MCP_MOD_DIR", str(MOD_DIRECTORY))
sys.path.insert(0, str(SERVER_DIRECTORY / "src"))

if not API_SERVER.is_file():
    raise SystemExit(f"Bundled API server not found: {API_SERVER}")

runpy.run_path(str(API_SERVER), run_name="__main__")
