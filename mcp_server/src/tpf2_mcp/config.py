from __future__ import annotations

import os
from pathlib import Path


def bridge_dir() -> Path:
    """Return the configured bridge directory without creating it."""
    configured = os.environ.get("TPF2_MCP_BRIDGE_DIR")
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Transport Fever 2" / "tpf2_mcp_bridge"
    return Path.home() / ".tpf2_mcp_bridge"


def state_dir() -> Path:
    """Local MCP state, intentionally separate from the mod bridge protocol."""
    configured = os.environ.get("TPF2_MCP_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA")
    return (Path(appdata) / "Transport Fever 2" / "tpf2_mcp_state") if appdata else Path.home() / ".tpf2_mcp_state"


def mock_enabled() -> bool:
    return os.environ.get("TPF2_MCP_MOCK", "").lower() in {"1", "true", "yes"}


def snapshot_cache_seconds() -> float:
    """Return a bounded read-only MCP snapshot cache duration."""
    try:
        value = float(os.environ.get("TPF2_MCP_SNAPSHOT_CACHE_SECONDS", "8"))
    except ValueError:
        value = 8.0
    return min(60.0, max(1.0, value))
