from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import bridge_dir
from .protocol import request


class BridgeError(RuntimeError):
    pass


@contextmanager
def _mailbox_lock(directory: Path, timeout_seconds: float, poll_seconds: float):
    """Serialize the bridge's single command slot across UI and MCP processes."""
    lock_path = directory / "command.lock"
    deadline = time.monotonic() + timeout_seconds
    descriptor = None
    while time.monotonic() < deadline:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()} time={time.time()}\n".encode("ascii"))
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 180:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(poll_seconds)
    if descriptor is None:
        raise BridgeError("timeout waiting for the shared bridge mailbox lock")
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read {path.name}: {exc}") from exc


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class BridgeClient:
    def __init__(self, directory: Path | None = None, timeout_seconds: float = 15.0, poll_seconds: float = 0.05):
        self.directory = directory or bridge_dir()
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def _prepare_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "responses").mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        heartbeat = _read_json(self.directory / "heartbeat.json")
        if heartbeat is None:
            return {"connected": False, "bridge_dir": str(self.directory), "reason": "heartbeat.json not found"}
        age_seconds = max(0.0, time.time() - float(heartbeat.get("last_update", 0)))
        return {"connected": bool(heartbeat.get("bridge_ready")) and age_seconds < 10,
                "bridge_dir": str(self.directory), "heartbeat_age_seconds": round(age_seconds, 3), **heartbeat}

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._prepare_directory()
        with _mailbox_lock(self.directory, self.timeout_seconds, self.poll_seconds):
            payload = request(command, params)
            _atomic_json_write(self.directory / "command.json", payload)
            response_directory = self.directory / "responses"
            response_path = response_directory / f"{payload['request_id']}.json"
            ready_path = response_directory / f"{payload['request_id']}.ready"
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                # Lua lacks os.rename/os.remove in the live sandbox. It closes the
                # request-specific JSON response before writing this ready marker.
                if ready_path.exists():
                    response = _read_json(response_path)
                    if response is None:
                        time.sleep(self.poll_seconds)
                        continue
                    if not response.get("ok"):
                        error = response.get("error") or {}
                        raise BridgeError(f"{error.get('code', 'UNKNOWN')}: {error.get('message', 'bridge command failed')}")
                    return response["result"]
                time.sleep(self.poll_seconds)
            raise BridgeError(f"timeout waiting for {command}; ensure the mod is enabled in an open save")

    def ping(self) -> dict[str, Any]:
        return self.call("ping")

    def game_state(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.call("get_game_state", {"force_refresh": force_refresh})

    def towns(self) -> list[dict[str, Any]]:
        return self.call("get_towns")

    def town(self, entity_id: int) -> dict[str, Any]:
        return self.call("get_town", {"entity_id": entity_id})

    def export_rail_network(self) -> dict[str, Any]:
        """Request the one-shot full physical railway sidecar export."""
        return self.call("get_rail_network", {})

    def operational_telemetry(self, section: str = "inventory") -> dict[str, Any]:
        """Run one bounded section of the unified read-only telemetry probe."""
        return self.call("get_operational_telemetry", {"section": section})

    def timetable_status(self, line_id: int) -> dict[str, Any]:
        return self.call("get_timetable_status", {"line_id": line_id})

    def line_demand(self, line_id: int, maximum_entities: int = 20000) -> dict[str, Any]:
        return self.call("get_line_demand", {"line_id": line_id, "maximum_entities": maximum_entities})

    def vehicle_dispatch_state(self, vehicle_id: int, maximum_entities: int = 20000) -> dict[str, Any]:
        return self.call("get_vehicle_dispatch_state", {"vehicle_id": vehicle_id, "maximum_entities": maximum_entities})


class MockBridge:
    """Offline bridge backed by an explicitly supplied snapshot fixture.

    Test data is deliberately not discovered from the installed package.  This
    keeps production code independent of a repository-relative ``tests/`` tree.
    """
    def __init__(self, fixture: Path):
        self.fixture = Path(fixture)

    def status(self) -> dict[str, Any]:
        return {"connected": True, "mock": True, "bridge_ready": True, "snapshot_seq": 1}

    def ping(self) -> dict[str, Any]:
        return {"message": "pong", "mock": True}

    def game_state(self, force_refresh: bool = False) -> dict[str, Any]:
        return json.loads(self.fixture.read_text(encoding="utf-8"))

    def towns(self) -> list[dict[str, Any]]:
        return self.game_state()["towns"]

    def town(self, entity_id: int) -> dict[str, Any]:
        for town in self.towns():
            if town.get("entity_id") == entity_id:
                return town
        raise BridgeError(f"ENTITY_NOT_FOUND: town {entity_id} not found")

    def line_demand(self, line_id: int, maximum_entities: int = 20000) -> dict[str, Any]:
        lines = self.game_state().get("lines", [])
        if not any(line.get("entity_id") == line_id for line in lines):
            raise BridgeError(f"ENTITY_NOT_FOUND: line {line_id} not found")
        return {
            "line_id": line_id,
            "maximum_entities": maximum_entities,
            "passengers": {"onboard": 0, "waiting": 0, "total": 0},
            "cargo": {"onboard": 0, "waiting": 0, "total": 0, "by_cargo": []},
            "sampled_entities": 0,
            "source": "MOCK",
        }

    def vehicle_dispatch_state(self, vehicle_id: int, maximum_entities: int = 20000) -> dict[str, Any]:
        vehicle = next((item for item in self.game_state().get("vehicles", []) if item.get("entity_id") == vehicle_id), None)
        if vehicle is None:
            raise BridgeError(f"ENTITY_NOT_FOUND: vehicle {vehicle_id} not found")
        demand = self.line_demand(vehicle.get("line_id"), maximum_entities) if isinstance(vehicle.get("line_id"), int) else {}
        return {"vehicle": {"entity_id": vehicle_id, "line_id": vehicle.get("line_id"), "name": vehicle.get("name")}, "demand": demand}
