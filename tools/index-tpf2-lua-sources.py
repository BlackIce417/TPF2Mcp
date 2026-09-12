#!/usr/bin/env python3
"""Index TPF2 Lua source references without executing any game code."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


KEYWORDS = (
    "balance", "loan", "frequency", "rate", "throughput", "income", "revenue", "profit", "cost",
    "capacity", "power", "speed", "waiting", "cargo", "passenger", "production", "shipment", "transport",
)
CALL_RE = re.compile(r"\b(?:game\.interface|api\.engine|api\.res)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
SYMBOL_RE = re.compile(r"\b(?:function\s+([\w.:]+)|local\s+function\s+([\w_]+)|([\w_.:]+)\s*=\s*function)\b")


def line_symbols(text: str) -> list[str]:
    return [part for match in SYMBOL_RE.finditer(text) for part in match.groups() if part]


def index_file(path: Path, root: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [{"file": path.relative_to(root).as_posix(), "line": 0, "read_error": str(exc)}]
    records: list[dict[str, object]] = []
    for line_number, text in enumerate(lines, start=1):
        lowered = text.lower()
        keywords = [keyword for keyword in KEYWORDS if keyword in lowered]
        calls = CALL_RE.findall(text)
        symbols = line_symbols(text)
        if keywords or calls or symbols:
            records.append({
                "file": path.relative_to(root).as_posix(), "line": line_number, "text": text.strip(),
                "keywords": keywords, "api_calls": calls, "symbols": symbols,
            })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_root", type=Path, help="Transport Fever 2 installation root")
    parser.add_argument("--output", type=Path, default=Path("diagnostics/ui-source-index.json"))
    args = parser.parse_args()
    roots = [args.game_root / "res" / name for name in ("scripts", "config")]
    files = sorted(path for root in roots if root.is_dir() for path in root.rglob("*.lua"))
    entries = [entry for path in files for entry in index_file(path, args.game_root)]
    payload = {
        "game_root": str(args.game_root), "scan_roots": [str(root) for root in roots],
        "file_count": len(files), "match_count": len(entries), "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {len(files)} Lua files; {len(entries)} matching source lines -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
