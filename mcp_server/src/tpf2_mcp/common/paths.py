"""One runtime root: the directory containing this copy of mcp_server."""
from pathlib import Path


def runtime_root() -> Path:
    return Path(__file__).resolve().parents[4]


def runtime_path(relative: str | Path, *, root: Path | None = None) -> Path:
    owner = (runtime_root() if root is None else root).resolve()
    path = (owner / relative).resolve()
    if not path.is_relative_to(owner):
        raise ValueError(f'Runtime path must remain inside its project/Mod root: {relative}')
    return path
