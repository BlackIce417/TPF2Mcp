"""Windows shared-memory transport for the Loader-managed native Controller."""
from __future__ import annotations

import ctypes
import os
import struct
import threading
import time
from ctypes import wintypes
from typing import Any


MAGIC = 0x32465054
VERSION = 1
CONFIG_CAPACITY = 384 * 1024
STATUS_CAPACITY = 64 * 1024
HEADER_SIZE = 64
STRUCTURE_SIZE = HEADER_SIZE + CONFIG_CAPACITY + STATUS_CAPACITY
MAPPING_NAME = "Local\\tpf2mcp_native_ipc_v1"
CONFIG_EVENT_NAME = "Local\\tpf2mcp_native_config_v1"
STATUS_EVENT_NAME = "Local\\tpf2mcp_native_status_v1"

FILE_MAP_WRITE = 0x0002
FILE_MAP_READ = 0x0004
EVENT_MODIFY_STATE = 0x0002
CONFIG_SEQUENCE_OFFSET = 20
CONFIG_LENGTH_OFFSET = 24
STATUS_SEQUENCE_OFFSET = 28
STATUS_LENGTH_OFFSET = 32
CONFIG_OFFSET = HEADER_SIZE
STATUS_OFFSET = HEADER_SIZE + CONFIG_CAPACITY

COMMAND_MAGIC = 0x32434D54
COMMAND_VERSION = 2
COMMAND_RING_CAPACITY = 64
COMMAND_PAYLOAD_CAPACITY = 12 * 1024
COMMAND_SLOT_SIZE = 32 + COMMAND_PAYLOAD_CAPACITY
COMMAND_REPLY_SIZE = 288
COMMAND_HEADER_SIZE = 264
COMMAND_STRUCTURE_SIZE = (COMMAND_HEADER_SIZE + COMMAND_RING_CAPACITY * COMMAND_SLOT_SIZE
                          + COMMAND_RING_CAPACITY * COMMAND_REPLY_SIZE)
COMMAND_MAPPING_NAME = "Local\\tpf2mcp_controller_cmd_v2"
COMMAND_EVENT_NAME = "Local\\tpf2mcp_controller_cmd_event_v2"
REPLY_EVENT_NAME = "Local\\tpf2mcp_controller_reply_event_v2"
COMMAND_MUTEX_NAME = "Local\\tpf2mcp_controller_cmd_mutex_v2"
LOADER_HOT_RELOAD_EVENT_NAME = "Local\\tpf2mcp_loader_hotreload_v1"

CMD_PING = 0x0001
CMD_GET_STATUS = 0x0002
CMD_GET_CAPABILITIES = 0x0003
CMD_BEGIN_TRANSACTION = 0x0010
CMD_COMMIT_TRANSACTION = 0x0011
CMD_ABORT_TRANSACTION = 0x0012
CMD_CLEAR_ALL_RULES = 0x0013
CMD_UPSERT_SPEED_RULE = 0x0101
CMD_REMOVE_SPEED_RULE = 0x0102
CMD_CLEAR_SPEED_RULES = 0x0103
CMD_UPSERT_STATION_RULE = 0x0201
CMD_REMOVE_STATION_RULE = 0x0202
CMD_CLEAR_STATION_RULES = 0x0203
CMD_UPSERT_ROUTING_RULE = 0x0301
CMD_REMOVE_ROUTING_RULE = 0x0302
CMD_CLEAR_ROUTING_RULES = 0x0303
CMD_UPSERT_PATH_RULE = 0x0401
CMD_REMOVE_PATH_RULE = 0x0402
CMD_CLEAR_PATH_RULES = 0x0403

COMMAND_OK = 0
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE = 0xFFFFFFFF
SYNCHRONIZE = 0x00100000
_command_id_lock = threading.Lock()
_last_command_id = 0


def _kernel32():
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, ctypes.c_size_t)
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
    kernel.UnmapViewOfFile.restype = wintypes.BOOL
    kernel.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    return kernel


def _next_command_id() -> int:
    global _last_command_id
    with _command_id_lock:
        value = (time.time_ns() & 0x7FFFFFFFFFFFFFFF) or 1
        _last_command_id = max(value, _last_command_id + 1)
        return _last_command_id


def _valid_command_header(address: int) -> bool:
    magic, version, size, commands, replies, payload = struct.unpack_from(
        "<IIIIII", ctypes.string_at(address, 24)
    )
    return (magic == COMMAND_MAGIC and version == COMMAND_VERSION
            and size == COMMAND_STRUCTURE_SIZE and commands == COMMAND_RING_CAPACITY
            and replies == COMMAND_RING_CAPACITY and payload == COMMAND_PAYLOAD_CAPACITY)


def command_channel_available() -> bool:
    """Return whether a V2 Controller command channel is currently live."""
    kernel = _kernel32()
    if kernel is None:
        return False
    mapping = kernel.OpenFileMappingW(FILE_MAP_READ, False, COMMAND_MAPPING_NAME)
    if not mapping:
        return False
    view = kernel.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, COMMAND_STRUCTURE_SIZE)
    try:
        return bool(view and _valid_command_header(view))
    finally:
        if view:
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(mapping)


def command_channel_epoch() -> int | None:
    """Return the live Controller instance token, or None for a V1/absent DLL."""
    kernel = _kernel32()
    if kernel is None:
        return None
    mapping = kernel.OpenFileMappingW(FILE_MAP_READ, False, COMMAND_MAPPING_NAME)
    if not mapping:
        return None
    view = kernel.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, COMMAND_STRUCTURE_SIZE)
    try:
        if not view or not _valid_command_header(view):
            return None
        return struct.unpack("<Q", ctypes.string_at(view + 64, 8))[0]
    finally:
        if view:
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(mapping)


def pack_rule_key(rule_id: int) -> bytes:
    return struct.pack("<Q", int(rule_id))


def pack_speed_rule(rule_id: int, item: dict[str, Any]) -> bytes:
    edges = [int(value) for value in item.get("edge_ids", [])]
    if not 1 <= len(edges) <= 2048:
        raise ValueError("speed rule requires 1..2048 edge_ids")
    edge_data = struct.pack("<2048I", *(edges + [0] * (2048 - len(edges))))
    return (struct.pack("<QIfIiiqI", int(rule_id), int(item["vehicle_id"]), float(item["speed_mps"]),
                        1 if item.get("hold") else 0, int(item.get("path_index_start", -1)),
                        int(item.get("path_index_end", -1)), int(item.get("expires_at") or 0), len(edges))
            + edge_data)


def pack_station_rule(rule_id: int, item: dict[str, Any]) -> bytes:
    return struct.pack("<QIIIIq", int(rule_id), int(item["vehicle_id"]), int(item.get("station_group_id") or 0),
                       int(item["station_index"]), int(item["terminal_index"]), int(item.get("expires_at") or 0))


def pack_routing_rule(rule_id: int, item: dict[str, Any]) -> bytes:
    entity_kind = 1 if str(item.get("entity_kind", "")).upper() == "PERSON" else 2
    return struct.pack("<QIIiiiiiiq", int(rule_id), int(item["source_line"]), int(item["target_line"]),
                       int(item["source_stop0"]), int(item["source_stop1"]), int(item["target_stop0"]),
                       int(item["target_stop1"]), int(item["max_assignments"]), entity_kind,
                       int(item.get("expires_at") or 0))


def pack_path_rule(rule_id: int, item: dict[str, Any]) -> bytes:
    edges = [int(value) for value in item.get("edge_ids", [])]
    if not 1 <= len(edges) <= 2048:
        raise ValueError("path rule requires 1..2048 edge_ids")
    edge_data = struct.pack("<2048I", *(edges + [0] * (2048 - len(edges))))
    return (struct.pack("<QIfqI", int(rule_id), int(item["vehicle_id"]), float(item["penalty_seconds"]),
                        int(item.get("expires_at") or 0), len(edges)) + edge_data)


class ControllerCommandError(RuntimeError):
    """A command reached the Controller but was rejected by its dispatcher."""

    def __init__(self, reply: dict[str, Any]):
        self.reply = reply
        super().__init__(f"Controller rejected opcode {reply.get('opcode')}: {reply.get('detail')}")


class ControllerCommandClient:
    """Typed V2 command client for every Python-to-Controller control operation."""

    def __init__(self, *, timeout: float = 2.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = float(timeout)

    @staticmethod
    def available() -> bool:
        return command_channel_available()

    @staticmethod
    def epoch() -> int | None:
        return command_channel_epoch()

    @staticmethod
    def require_ok(reply: dict[str, Any]) -> dict[str, Any]:
        if int(reply.get("result", -1)) != COMMAND_OK:
            raise ControllerCommandError(reply)
        return reply

    def send(self, opcode: int, payload: bytes = b"", *, transaction_id: int = 0,
             cmd_id: int | None = None, timeout: float | None = None,
             require_ok: bool = False) -> dict[str, Any]:
        """Publish one command and synchronously receive its cmd_id-matched reply."""
        if not isinstance(payload, bytes) or len(payload) > COMMAND_PAYLOAD_CAPACITY:
            raise ValueError("invalid command payload")
        effective_timeout = self.timeout if timeout is None else float(timeout)
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        kernel = _kernel32()
        if kernel is None:
            raise OSError("native Controller commands are only available on Windows")
        command_id = int(cmd_id or _next_command_id())
        mutex = kernel.CreateMutexW(None, False, COMMAND_MUTEX_NAME)
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        mapping = event = reply_event = view = None
        mutex_owned = False
        try:
            wait_ms = max(1, min(0xFFFFFFFE, int(effective_timeout * 1000)))
            if kernel.WaitForSingleObject(mutex, wait_ms) != WAIT_OBJECT_0:
                raise TimeoutError("Controller command publisher is busy")
            mutex_owned = True
            mapping = kernel.OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, False, COMMAND_MAPPING_NAME)
            if not mapping:
                raise FileNotFoundError("Controller V2 command mapping is unavailable")
            view = kernel.MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, COMMAND_STRUCTURE_SIZE)
            if not view or not _valid_command_header(view):
                raise RuntimeError("Controller V2 command mapping has an incompatible layout")
            event = kernel.OpenEventW(EVENT_MODIFY_STATE, False, COMMAND_EVENT_NAME)
            reply_event = kernel.OpenEventW(SYNCHRONIZE, False, REPLY_EVENT_NAME)
            if not event or not reply_event:
                raise FileNotFoundError("Controller V2 command events are unavailable")
            write, read = struct.unpack_from("<qq", ctypes.string_at(view + 32, 16))
            if write - read >= COMMAND_RING_CAPACITY:
                raise BufferError("Controller command ring is full")
            slot = view + COMMAND_HEADER_SIZE + (write % COMMAND_RING_CAPACITY) * COMMAND_SLOT_SIZE
            header = struct.pack("<QIIQII", command_id, int(opcode), len(payload),
                                 int(transaction_id), 0, 0)
            ctypes.memmove(slot, header, len(header))
            if payload:
                ctypes.memmove(slot + 32, payload, len(payload))
            ctypes.c_longlong.from_address(view + 32).value = write + 1
            if not kernel.SetEvent(event):
                raise ctypes.WinError(ctypes.get_last_error())

            deadline = time.monotonic() + effective_timeout
            while True:
                reply_write, reply_read = struct.unpack_from("<qq", ctypes.string_at(view + 48, 16))
                while reply_read < reply_write:
                    offset = (COMMAND_HEADER_SIZE + COMMAND_RING_CAPACITY * COMMAND_SLOT_SIZE
                              + (reply_read % COMMAND_RING_CAPACITY) * COMMAND_REPLY_SIZE)
                    raw = ctypes.string_at(view + offset, COMMAND_REPLY_SIZE)
                    rid, ropcode, result, rtransaction, generation, detail = struct.unpack("<QIIQQ256s", raw)
                    reply_read += 1
                    ctypes.c_longlong.from_address(view + 56).value = reply_read
                    if rid == command_id:
                        reply = {"cmd_id": rid, "opcode": ropcode, "result": result,
                                 "transaction_id": rtransaction,
                                 "controller_generation": generation,
                                 "detail": detail.split(b"\0", 1)[0].decode("utf-8", errors="replace")}
                        return self.require_ok(reply) if require_ok else reply
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Controller did not reply to command {command_id}")
                waited = kernel.WaitForSingleObject(reply_event, max(1, int(remaining * 1000)))
                if waited == WAIT_TIMEOUT:
                    raise TimeoutError(f"Controller did not reply to command {command_id}")
                if waited != WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if view:
                kernel.UnmapViewOfFile(view)
            for handle in (reply_event, event, mapping):
                if handle:
                    kernel.CloseHandle(handle)
            if mutex_owned:
                kernel.ReleaseMutex(mutex)
            kernel.CloseHandle(mutex)

    def ping(self) -> dict[str, Any]:
        return self.send(CMD_PING, require_ok=True)

    def get_status(self) -> dict[str, Any]:
        return self.send(CMD_GET_STATUS, require_ok=True)

    def get_capabilities(self) -> dict[str, Any]:
        return self.send(CMD_GET_CAPABILITIES, require_ok=True)

    def upsert_speed_rule(self, rule_id: int, item: dict[str, Any], *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_UPSERT_SPEED_RULE, pack_speed_rule(rule_id, item),
                         transaction_id=transaction_id, require_ok=True)

    def upsert_station_rule(self, rule_id: int, item: dict[str, Any], *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_UPSERT_STATION_RULE, pack_station_rule(rule_id, item),
                         transaction_id=transaction_id, require_ok=True)

    def upsert_routing_rule(self, rule_id: int, item: dict[str, Any], *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_UPSERT_ROUTING_RULE, pack_routing_rule(rule_id, item),
                         transaction_id=transaction_id, require_ok=True)

    def upsert_path_rule(self, rule_id: int, item: dict[str, Any], *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_UPSERT_PATH_RULE, pack_path_rule(rule_id, item),
                         transaction_id=transaction_id, require_ok=True)

    def remove_speed_rule(self, rule_id: int, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_REMOVE_SPEED_RULE, pack_rule_key(rule_id),
                         transaction_id=transaction_id, require_ok=True)

    def remove_station_rule(self, rule_id: int, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_REMOVE_STATION_RULE, pack_rule_key(rule_id),
                         transaction_id=transaction_id, require_ok=True)

    def remove_routing_rule(self, rule_id: int, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_REMOVE_ROUTING_RULE, pack_rule_key(rule_id),
                         transaction_id=transaction_id, require_ok=True)

    def remove_path_rule(self, rule_id: int, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_REMOVE_PATH_RULE, pack_rule_key(rule_id),
                         transaction_id=transaction_id, require_ok=True)

    def clear_all_rules(self, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_CLEAR_ALL_RULES, transaction_id=transaction_id, require_ok=True)

    def clear_speed_rules(self, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_CLEAR_SPEED_RULES, transaction_id=transaction_id, require_ok=True)

    def clear_station_rules(self, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_CLEAR_STATION_RULES, transaction_id=transaction_id, require_ok=True)

    def clear_routing_rules(self, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_CLEAR_ROUTING_RULES, transaction_id=transaction_id, require_ok=True)

    def clear_path_rules(self, *, transaction_id: int = 0) -> dict[str, Any]:
        return self.send(CMD_CLEAR_PATH_RULES, transaction_id=transaction_id, require_ok=True)

    def transaction(self, transaction_id: int | None = None) -> "ControllerCommandTransaction":
        tx_id = int(transaction_id or _next_command_id())
        self.send(CMD_BEGIN_TRANSACTION, transaction_id=tx_id, require_ok=True)
        return ControllerCommandTransaction(self, tx_id)

class ControllerCommandTransaction:
    """Atomic staging transaction created by ControllerCommandClient.transaction()."""

    def __init__(self, client: ControllerCommandClient, transaction_id: int):
        self.client = client
        self.transaction_id = transaction_id
        self.active = True

    def __enter__(self) -> "ControllerCommandTransaction":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if not self.active:
            return False
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                if self.active:
                    try:
                        self.abort()
                    except Exception:
                        pass
                raise
        else:
            self.abort()
        return False

    def send(self, opcode: int, payload: bytes = b"") -> dict[str, Any]:
        if not self.active:
            raise RuntimeError("Controller transaction is no longer active")
        return self.client.send(opcode, payload, transaction_id=self.transaction_id, require_ok=True)

    def upsert_speed_rule(self, rule_id: int, item: dict[str, Any]) -> dict[str, Any]:
        return self.client.upsert_speed_rule(rule_id, item, transaction_id=self.transaction_id)

    def upsert_station_rule(self, rule_id: int, item: dict[str, Any]) -> dict[str, Any]:
        return self.client.upsert_station_rule(rule_id, item, transaction_id=self.transaction_id)

    def upsert_routing_rule(self, rule_id: int, item: dict[str, Any]) -> dict[str, Any]:
        return self.client.upsert_routing_rule(rule_id, item, transaction_id=self.transaction_id)

    def upsert_path_rule(self, rule_id: int, item: dict[str, Any]) -> dict[str, Any]:
        return self.client.upsert_path_rule(rule_id, item, transaction_id=self.transaction_id)

    def remove_speed_rule(self, rule_id: int) -> dict[str, Any]:
        return self.client.remove_speed_rule(rule_id, transaction_id=self.transaction_id)

    def remove_station_rule(self, rule_id: int) -> dict[str, Any]:
        return self.client.remove_station_rule(rule_id, transaction_id=self.transaction_id)

    def remove_routing_rule(self, rule_id: int) -> dict[str, Any]:
        return self.client.remove_routing_rule(rule_id, transaction_id=self.transaction_id)

    def remove_path_rule(self, rule_id: int) -> dict[str, Any]:
        return self.client.remove_path_rule(rule_id, transaction_id=self.transaction_id)

    def clear_all_rules(self) -> dict[str, Any]:
        return self.client.clear_all_rules(transaction_id=self.transaction_id)

    def clear_speed_rules(self) -> dict[str, Any]:
        return self.client.clear_speed_rules(transaction_id=self.transaction_id)

    def clear_station_rules(self) -> dict[str, Any]:
        return self.client.clear_station_rules(transaction_id=self.transaction_id)

    def clear_routing_rules(self) -> dict[str, Any]:
        return self.client.clear_routing_rules(transaction_id=self.transaction_id)

    def clear_path_rules(self) -> dict[str, Any]:
        return self.client.clear_path_rules(transaction_id=self.transaction_id)

    def commit(self) -> dict[str, Any]:
        if not self.active:
            raise RuntimeError("Controller transaction is no longer active")
        reply = self.client.send(CMD_COMMIT_TRANSACTION, transaction_id=self.transaction_id, require_ok=True)
        self.active = False
        return reply

    def abort(self) -> dict[str, Any]:
        if not self.active:
            raise RuntimeError("Controller transaction is no longer active")
        try:
            return self.client.send(CMD_ABORT_TRANSACTION, transaction_id=self.transaction_id, require_ok=True)
        finally:
            self.active = False


_default_command_client = ControllerCommandClient()


def send_command(opcode: int, payload: bytes = b"", *, transaction_id: int = 0,
                 cmd_id: int | None = None, timeout: float = 2.0) -> dict[str, Any]:
    """Compatibility wrapper; new control code should use ControllerCommandClient."""
    return _default_command_client.send(opcode, payload, transaction_id=transaction_id,
                                        cmd_id=cmd_id, timeout=timeout)


def request_controller_hot_reload() -> None:
    """Signal the process-lifetime Loader to unload and reload the Controller."""
    kernel = _kernel32()
    if kernel is None:
        raise OSError("Controller hot reload is only available on Windows")
    event = kernel.OpenEventW(EVENT_MODIFY_STATE, False, LOADER_HOT_RELOAD_EVENT_NAME)
    if not event:
        raise FileNotFoundError("Loader hot-reload event is unavailable")
    try:
        if not kernel.SetEvent(event):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(event)


def _valid_header(address: int) -> bool:
    magic, version, size, config_capacity, status_capacity = struct.unpack_from(
        "<IIIII", ctypes.string_at(address, 20)
    )
    return (magic == MAGIC and version == VERSION and size == STRUCTURE_SIZE
            and config_capacity == CONFIG_CAPACITY and status_capacity == STATUS_CAPACITY)


def publish_config(payload: bytes) -> bool:
    """Publish UTF-8 ``section.key=value`` lines and notify the DLL listener."""
    if not payload or len(payload) >= CONFIG_CAPACITY:
        return False
    kernel = _kernel32()
    if kernel is None:
        return False
    mapping = kernel.OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, False, MAPPING_NAME)
    if not mapping:
        return False
    view = kernel.MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, STRUCTURE_SIZE)
    try:
        if not view or not _valid_header(view):
            return False
        sequence = ctypes.c_long.from_address(view + CONFIG_SEQUENCE_OFFSET)
        length = ctypes.c_long.from_address(view + CONFIG_LENGTH_OFFSET)
        current = int(sequence.value)
        sequence.value = current + 1 if not current & 1 else current + 2
        ctypes.memmove(view + CONFIG_OFFSET, payload, len(payload))
        length.value = len(payload)
        sequence.value += 1
    finally:
        if view:
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(mapping)
    event = kernel.OpenEventW(EVENT_MODIFY_STATE, False, CONFIG_EVENT_NAME)
    if not event:
        return False
    try:
        return bool(kernel.SetEvent(event))
    finally:
        kernel.CloseHandle(event)


def _coerce(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def read_status() -> dict[str, Any]:
    """Read one consistent key-value status snapshot using its sequence guard."""
    kernel = _kernel32()
    if kernel is None:
        return {}
    mapping = kernel.OpenFileMappingW(FILE_MAP_READ, False, MAPPING_NAME)
    if not mapping:
        return {}
    view = kernel.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, STRUCTURE_SIZE)
    payload = b""
    try:
        if not view or not _valid_header(view):
            return {}
        sequence = ctypes.c_long.from_address(view + STATUS_SEQUENCE_OFFSET)
        length_field = ctypes.c_long.from_address(view + STATUS_LENGTH_OFFSET)
        for _ in range(4):
            before = int(sequence.value)
            if before & 1:
                continue
            length = int(length_field.value)
            if length <= 0 or length >= STATUS_CAPACITY:
                return {}
            candidate = ctypes.string_at(view + STATUS_OFFSET, length)
            after = int(sequence.value)
            if before == after and not after & 1:
                payload = candidate
                break
    finally:
        if view:
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(mapping)
    result: dict[str, Any] = {}
    for raw_line in payload.decode("utf-8", errors="replace").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key:
            result[key] = _coerce(value)
    return result
