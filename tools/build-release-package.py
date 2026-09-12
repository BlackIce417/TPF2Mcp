"""Build a reproducible release archive with one tpf2-mcp/ project root."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".git"}
EXCLUDED_SUFFIXES = {".pyc"}
INCLUDED = ("AGENTS.md", "README.md", "docs", "mcp_server", "protocol", "tests", "tools", "tpf2_mod", "diagnostics")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in INCLUDED:
            candidate = root / name
            if candidate.is_file():
                archive.write(candidate, Path("tpf2-mcp") / name)
            elif candidate.is_dir():
                for item in candidate.rglob("*"):
                    if not item.is_file() or item.suffix in EXCLUDED_SUFFIXES or any(part in EXCLUDED_PARTS for part in item.parts):
                        continue
                    archive.write(item, Path("tpf2-mcp") / item.relative_to(root))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
