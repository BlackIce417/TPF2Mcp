"""Publish a trusted Lua telemetry bundle to an already-loaded hot reload bootstrap."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

MODULES = (
    "tpf2_mcp/collectors/common", "tpf2_mcp/json",
    "tpf2_mcp/collectors/signal_direction", "tpf2_mcp/collectors/signal_state",
    "tpf2_mcp/collectors/operational_telemetry", "tpf2_mcp/collectors/train_telemetry",
    "tpf2_mcp/state", "tpf2_mcp/runtime",
)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def inside(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes Mod/source root: {resolved}")
    return resolved


def mod_root(path):
    root = Path(path).resolve(strict=True)
    if not (root / "mod.lua").is_file() or not (root / "res/scripts/tpf2_mcp/runtime.lua").is_file():
        raise ValueError("Target must be an existing tpf2mcp Mod directory")
    return root


def source_scripts(path):
    root = Path(path).resolve(strict=True)
    if (root / "tpf2_mod").is_dir():
        root = root / "tpf2_mod"
    scripts = inside(root, root / "res/scripts")
    if not (scripts / "tpf2_mcp/hot_reload.lua").is_file():
        raise ValueError("Source does not contain the hot reload bootstrap")
    return scripts


def publish(target, source, *, clock=time.time):
    root = mod_root(target)
    bridge = inside(root, root / "bridge")
    heartbeat = read_json(bridge / "heartbeat.json")
    support = heartbeat.get("hot_reload") or {}
    if support.get("protocol_version") != 1:
        raise ValueError("Bootstrap is not loaded. Install the bootstrap and reload the save once; "
                         "if the game retains its Lua cache, restart once. No update was published.")
    age = clock() - heartbeat.get("last_update", 0)
    if not heartbeat.get("bridge_ready") or not 0 <= age <= 15:
        raise ValueError("Game heartbeat is stale/unavailable. Resume the simulation before updating.")
    scripts = source_scripts(source)
    payloads = {}
    for module in MODULES:
        path = inside(scripts, scripts / (module + ".lua"))
        data = path.read_bytes()
        if not 1 <= len(data) <= 524288:
            raise ValueError(f"Invalid module size: {module}")
        payloads[module] = data
    revision = uuid.uuid4().hex
    hot_root = inside(root, bridge / "hot-reload")
    bundle = inside(root, hot_root / "bundles" / revision)
    bundle.mkdir(parents=True, exist_ok=False)
    for module, data in payloads.items():
        dest = inside(root, bundle / (module + ".lua"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    request = {"protocol_version": 1, "revision": revision,
               "files": {name: len(data) for name, data in payloads.items()},
               "created_at": clock()}
    temporary = inside(root, hot_root / (revision + ".tmp"))
    temporary.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    # Publish the pointer last. Lua never reads files while they are being copied.
    os.replace(temporary, inside(root, hot_root / "request.json"))
    return request


def receipt(target, revision):
    root = mod_root(target)
    return next((value for value in (
        read_json(root / "bridge/hot-reload/status.json"),
        read_json(root / "bridge/heartbeat.json").get("hot_reload") or {},
    ) if value.get("revision") == revision), {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mod-root", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--wait", type=float, default=15, help="receipt timeout in seconds, 0..60")
    args = parser.parse_args()
    if not 0 <= args.wait <= 60:
        parser.error("--wait must be between 0 and 60")
    try:
        request = publish(args.mod_root, args.source_root)
        deadline = time.monotonic() + args.wait
        while True:
            result = receipt(args.mod_root, request["revision"])
            if result.get("state") in {"APPLIED", "REJECTED", "ROLLED_BACK"}:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["state"] == "APPLIED" else 1
            if time.monotonic() >= deadline:
                print(json.dumps({"state": "PUBLISHED_PENDING", "revision": request["revision"],
                                  "detail": "No matching receipt yet; this is not confirmation of activation."}))
                return 2
            time.sleep(0.25)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
