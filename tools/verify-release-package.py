"""Extract a release archive, validate its layout, and run its offline tests."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile


REQUIRED = ("README.md", "mcp_server/src/tpf2_mcp/server.py", "tpf2_mod", "tests", "docs", "diagnostics")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("archive", type=Path); args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tpf2-mcp-release-") as temporary:
        destination = Path(temporary)
        with ZipFile(args.archive) as archive:
            names = archive.namelist()
            bad = [name for name in names if "__pycache__/" in name or name.endswith(".pyc") or ".pytest_cache/" in name]
            if bad: raise SystemExit(f"archive hygiene failure: {bad[:3]}")
            archive.extractall(destination)
        root = destination / "tpf2-mcp"
        missing = [path for path in REQUIRED if not (root / path).exists()]
        if missing: raise SystemExit(f"archive layout failure: missing {missing}")
        environment = {**os.environ, "PYTHONPATH": str(root / "mcp_server" / "src")}
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=root, env=environment)
        if result.returncode: return result.returncode
    print("release package verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
