from __future__ import annotations

import os
import re
from pathlib import Path


TPF2_APP_ID = "1066780"
TPF2_DIRECTORY_NAME = "Transport Fever 2"
MOD_RUNTIME_MARKER = Path("res/scripts/tpf2_mcp/runtime.lua")


def _unique_existing_directories(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if resolved.is_dir() and key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _steam_roots() -> list[Path]:
    """Return Steam library roots without assuming a drive letter."""
    candidates: list[Path] = []
    configured = os.environ.get("TPF2_STEAM_ROOT")
    if configured:
        candidates.append(Path(configured))

    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                candidates.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except (OSError, ImportError):
            pass
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "Steam")
    else:
        candidates.extend((Path.home() / ".local/share/Steam", Path.home() / ".steam/steam"))

    roots = _unique_existing_directories(candidates)
    library_candidates = list(roots)
    for root in roots:
        library_file = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = library_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw_path in re.findall(r'"path"\s+"([^"]+)"', text):
            library_candidates.append(Path(raw_path.replace(r"\\", "\\")))
    return _unique_existing_directories(library_candidates)


def game_dir() -> Path:
    """Locate the TPF2 installation from explicit config or Steam libraries."""
    configured = os.environ.get("TPF2_GAME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    for steam_root in _steam_roots():
        candidate = steam_root / "steamapps" / "common" / TPF2_DIRECTORY_NAME
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("Transport Fever 2 installation not found; set TPF2_GAME_DIR")


def mod_dir() -> Path:
    """Locate the installed TPF2 MCP mod and return its root directory."""
    configured = os.environ.get("TPF2_MCP_MOD_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates: list[Path] = []
    try:
        installed_game = game_dir()
    except FileNotFoundError:
        installed_game = None
    if installed_game is not None:
        candidates.extend((installed_game / "mods" / name for name in ("tpf2mcp_1", "tpf2_mcp_1", "blackice_tpf2_mcp_bridge_1")))
        mods_root = installed_game / "mods"
        if mods_root.is_dir():
            candidates.extend(sorted(mods_root.iterdir()))

    for steam_root in _steam_roots():
        userdata = steam_root / "userdata"
        if userdata.is_dir():
            for user in sorted(userdata.iterdir()):
                mods_root = user / TPF2_APP_ID / "local" / "mods"
                if mods_root.is_dir():
                    candidates.extend(sorted(mods_root.iterdir()))
        workshop = steam_root / "steamapps" / "workshop" / "content" / TPF2_APP_ID
        if workshop.is_dir():
            candidates.extend(sorted(workshop.iterdir()))

    for candidate in _unique_existing_directories(candidates):
        if (candidate / MOD_RUNTIME_MARKER).is_file():
            return candidate
    raise FileNotFoundError("TPF2 MCP mod installation not found; set TPF2_MCP_MOD_DIR")


def bridge_dir() -> Path:
    """Return the bridge beside the installed mod unless explicitly overridden."""
    configured = os.environ.get("TPF2_MCP_BRIDGE_DIR")
    if configured:
        return Path(configured).expanduser()
    return mod_dir() / "bridge"


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
