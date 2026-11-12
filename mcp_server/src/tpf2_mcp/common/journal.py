"""Append-only local journals, deliberately outside the game bridge directory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlJournal:
    def __init__(self, path: Path | None):
        self.path = path

    def append(self, value: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()

    def latest(self, key: str) -> dict[str, dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return {}
        result: dict[str, dict[str, Any]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            identifier = value.get(key) if isinstance(value, dict) else None
            if isinstance(identifier, str):
                result[identifier] = value
        return result
