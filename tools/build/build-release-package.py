"""Build a reproducible release archive with one tpf2-mcp/ project root."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".git", "node_modules", "dist", ".venv", "old", "x64", "Win32", "Release", "Debug", ".vs"}
SOURCE_SUFFIXES = {".py", ".lua", ".cpp", ".h", ".asm", ".vcxproj", ".filters", ".slnx", ".def", ".md", ".json", ".toml", ".ps1", ".yml", ".css", ".html", ".js", ".mjs", ".tga", ".jpg", ".png", ".svg"}
INCLUDED = ("AGENTS.md", "README.md", "start-mcp.ps1", ".gitignore", "environment.yml", "docs", "skills", "mcp_server", "protocol", "tools", "tpf2_mod", "native", "ui")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if not output.is_relative_to(root):
        raise ValueError("release output must remain inside the project root")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in INCLUDED:
            candidate = root / name
            if candidate.is_file():
                archive.write(candidate, Path("tpf2-mcp") / name)
            elif candidate.is_dir():
                for item in sorted(candidate.rglob("*")):
                    if (not item.is_file() or item.suffix.lower() not in SOURCE_SUFFIXES
                            or item.name in {'local_config.lua', 'NATIVE_ENGINE_RESEARCH.md', 'SIGNAL_OBSERVATIONS.md'}
                            or item.relative_to(root).as_posix().startswith('docs/images/')
                            or any(part in EXCLUDED_PARTS or part.startswith('.tmp-') for part in item.relative_to(root).parts)):
                        continue
                    archive.write(item, Path("tpf2-mcp") / item.relative_to(root))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
