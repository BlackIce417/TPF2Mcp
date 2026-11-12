"""Parser for the tpf2_loader train wrapper binary shared-memory protocol."""
from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from enum import IntFlag


FRAME_MAGIC = 0x52545054
PROTOCOL_VERSION = 1
CHANNEL_KEY = "train-wrappers-v1.bin"
IDENTITY_CHANNEL_KEY = "train-identities.json"
TRAIN_FOOTPRINT_CHANNEL_KEY = "operational-telemetry-train_footprints.json"
CONTROL_MAPPING_NAME = "Local\\tpf2mcp_lua_bus_control_v1"


class PartFlags(IntFlag):
    POWERED = 1 << 0
    HAS_CAB = 1 << 1
    PASSENGER_CAPABLE = 1 << 2
    CARGO_CAPABLE = 1 << 3
    REVERSED = 1 << 4
    ROLE_VERIFIED = 1 << 16
    CARGO_VERIFIED = 1 << 17
    EDGE_VERIFIED = 1 << 18


class TrainFlags(IntFlag):
    PASSENGER = 1 << 0
    FREIGHT = 1 << 1
    MIXED_LOAD = 1 << 2
    REVERSIBLE = 1 << 3
    HAS_SPEED_COMMAND = 1 << 8
    EMERGENCY_BRAKING = 1 << 9
    PARTS_COMPLETE = 1 << 16
    CARGO_COMPLETE = 1 << 17
    EDGE_MAPPING_COMPLETE = 1 << 18


class Vec3f(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float)]


class Aabb3f(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("minimum", Vec3f), ("maximum", Vec3f)]


class EdgeLocation(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("edge_entity_id", ctypes.c_uint64), ("position01", ctypes.c_float),
        ("direction", ctypes.c_int8), ("valid", ctypes.c_uint8),
        ("reserved", ctypes.c_uint16),
    ]


class PassengerLoadEntry(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("compartment_index", ctypes.c_uint16), ("reserved", ctypes.c_uint16),
        ("passenger_count", ctypes.c_uint32), ("passenger_capacity", ctypes.c_uint32),
    ]


class FreightLoadEntry(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("cargo_type_id", ctypes.c_uint32), ("compartment_index", ctypes.c_uint16),
        ("load_config_index", ctypes.c_uint16), ("cargo_amount", ctypes.c_uint32),
        ("cargo_capacity", ctypes.c_uint32), ("cargo_unit_weight_kg", ctypes.c_float),
        ("current_cargo_weight_kg", ctypes.c_float),
    ]


class VehiclePartWrapper(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("struct_version", ctypes.c_uint32), ("struct_size", ctypes.c_uint32),
        ("entity_id", ctypes.c_uint64), ("train_entity_id", ctypes.c_uint64),
        ("model_id", ctypes.c_uint32), ("part_index", ctypes.c_uint16),
        ("part_count", ctypes.c_uint16), ("flags", ctypes.c_uint32),
        ("model_length_m", ctypes.c_float), ("model_width_m", ctypes.c_float),
        ("model_height_m", ctypes.c_float), ("empty_weight_t", ctypes.c_float),
        ("technical_max_speed_mps", ctypes.c_float), ("engine_power_kw", ctypes.c_float),
        ("tractive_effort_kn", ctypes.c_float), ("center", Vec3f), ("front", Vec3f),
        ("rear", Vec3f), ("world_aabb", Aabb3f), ("front_edge", EdgeLocation),
        ("center_edge", EdgeLocation), ("rear_edge", EdgeLocation),
        ("passenger_count", ctypes.c_uint32), ("passenger_capacity", ctypes.c_uint32),
        ("passenger_load_offset", ctypes.c_uint32), ("passenger_load_count", ctypes.c_uint16),
        ("passenger_compartment_count", ctypes.c_uint16), ("freight_amount", ctypes.c_uint32),
        ("freight_capacity", ctypes.c_uint32), ("freight_weight_t", ctypes.c_float),
        ("freight_load_offset", ctypes.c_uint32), ("freight_load_count", ctypes.c_uint16),
        ("freight_compartment_count", ctypes.c_uint16), ("sample_sequence", ctypes.c_uint64),
        ("sample_time_us", ctypes.c_uint64),
    ]


class TrainWrapper(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("struct_version", ctypes.c_uint32), ("struct_size", ctypes.c_uint32),
        ("entity_id", ctypes.c_uint64), ("line_entity_id", ctypes.c_uint64),
        ("flags", ctypes.c_uint32), ("state", ctypes.c_uint32),
        ("parts_offset", ctypes.c_uint32), ("parts_count", ctypes.c_uint16),
        ("powered_parts_count", ctypes.c_uint16), ("total_length_m", ctypes.c_float),
        ("empty_weight_t", ctypes.c_float), ("passenger_weight_t", ctypes.c_float),
        ("freight_weight_t", ctypes.c_float), ("gross_weight_t", ctypes.c_float),
        ("passenger_count", ctypes.c_uint32), ("passenger_capacity", ctypes.c_uint32),
        ("freight_amount", ctypes.c_uint32), ("freight_capacity", ctypes.c_uint32),
        ("freight_summary_offset", ctypes.c_uint32), ("freight_summary_count", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16), ("technical_max_speed_mps", ctypes.c_float),
        ("track_speed_limit_mps", ctypes.c_float), ("commanded_speed_limit_mps", ctypes.c_float),
        ("effective_speed_limit_mps", ctypes.c_float), ("current_speed_mps", ctypes.c_float),
        ("acceleration_mps2", ctypes.c_float), ("brake_deceleration_mps2", ctypes.c_float),
        ("center", Vec3f), ("front", Vec3f), ("rear", Vec3f),
        ("front_edge", EdgeLocation), ("center_edge", EdgeLocation), ("rear_edge", EdgeLocation),
        ("path_edge_index", ctypes.c_uint32), ("path_edge_count", ctypes.c_uint32),
        ("sample_sequence", ctypes.c_uint64), ("sample_time_us", ctypes.c_uint64),
    ]


class TrainTelemetryFrameHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("magic", ctypes.c_uint32), ("protocol_version", ctypes.c_uint32),
        ("header_size", ctypes.c_uint32), ("total_size", ctypes.c_uint32),
        ("sample_sequence", ctypes.c_uint64), ("sample_time_us", ctypes.c_uint64),
        ("train_count", ctypes.c_uint32), ("part_count", ctypes.c_uint32),
        ("passenger_load_count", ctypes.c_uint32), ("freight_load_count", ctypes.c_uint32),
        ("trains_offset", ctypes.c_uint32), ("parts_offset", ctypes.c_uint32),
        ("passenger_loads_offset", ctypes.c_uint32), ("freight_loads_offset", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
    ]


assert ctypes.sizeof(TrainTelemetryFrameHeader) == 72
assert ctypes.sizeof(TrainWrapper) == 220
assert ctypes.sizeof(VehiclePartWrapper) == 224
assert ctypes.sizeof(PassengerLoadEntry) == 12
assert ctypes.sizeof(FreightLoadEntry) == 24


@dataclass(frozen=True)
class TrainTelemetryFrame:
    header: TrainTelemetryFrameHeader
    trains: tuple[TrainWrapper, ...]
    parts: tuple[VehiclePartWrapper, ...]
    passenger_loads: tuple[PassengerLoadEntry, ...]
    freight_loads: tuple[FreightLoadEntry, ...]


@dataclass(frozen=True)
class TrainIdentity:
    entity_id: int
    display_name: str | None
    line_id: int | None


def parse_train_identities(data: bytes) -> tuple[TrainIdentity, ...]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported train identity payload")
    rows = value.get("trains")
    if not isinstance(rows, list):
        raise ValueError("train identity payload has no trains array")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("entity_id"), int):
            raise ValueError("invalid train identity record")
        display_name = row.get("display_name")
        line_id = row.get("line_id")
        if display_name is not None and not isinstance(display_name, str):
            raise ValueError("invalid train display_name")
        if line_id is not None and not isinstance(line_id, int):
            raise ValueError("invalid train identity line_id")
        result.append(TrainIdentity(row["entity_id"], display_name, line_id))
    return tuple(result)


def _array(data: bytes, offset: int, count: int, item_type: type[ctypes.Structure]):
    size = ctypes.sizeof(item_type)
    end = offset + count * size
    if offset < 0 or count < 0 or end > len(data):
        raise ValueError(f"invalid {item_type.__name__} range: offset={offset}, count={count}")
    return tuple(item_type.from_buffer_copy(data, offset + index * size) for index in range(count))


def parse_train_frame(data: bytes) -> TrainTelemetryFrame:
    if len(data) < ctypes.sizeof(TrainTelemetryFrameHeader):
        raise ValueError("train telemetry frame is shorter than its header")
    header = TrainTelemetryFrameHeader.from_buffer_copy(data)
    if header.magic != FRAME_MAGIC:
        raise ValueError(f"unexpected train telemetry magic 0x{header.magic:08x}")
    if header.protocol_version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported train telemetry protocol {header.protocol_version}")
    if header.header_size != ctypes.sizeof(TrainTelemetryFrameHeader):
        raise ValueError(f"unexpected train telemetry header size {header.header_size}")
    if header.total_size < header.header_size or header.total_size > len(data):
        raise ValueError(f"invalid train telemetry total size {header.total_size}")
    frame = data[:header.total_size]
    trains = _array(frame, header.trains_offset, header.train_count, TrainWrapper)
    parts = _array(frame, header.parts_offset, header.part_count, VehiclePartWrapper)
    passengers = _array(frame, header.passenger_loads_offset, header.passenger_load_count, PassengerLoadEntry)
    freight = _array(frame, header.freight_loads_offset, header.freight_load_count, FreightLoadEntry)
    for train in trains:
        if train.struct_version != 1 or train.struct_size != ctypes.sizeof(TrainWrapper):
            raise ValueError("incompatible TrainWrapper record")
        if train.parts_offset + train.parts_count > len(parts):
            raise ValueError("TrainWrapper parts range exceeds frame")
    for part in parts:
        if part.struct_version != 1 or part.struct_size != ctypes.sizeof(VehiclePartWrapper):
            raise ValueError("incompatible VehiclePartWrapper record")
        if part.passenger_load_offset + part.passenger_load_count > len(passengers):
            raise ValueError("VehiclePartWrapper passenger range exceeds frame")
        if part.freight_load_offset + part.freight_load_count > len(freight):
            raise ValueError("VehiclePartWrapper freight range exceeds frame")
    return TrainTelemetryFrame(header, trains, parts, passengers, freight)


def _read_bus_payload(key: str) -> bytes:
    if os.name != "nt":
        raise OSError("tpf2_loader shared memory is only available on Windows")
    from ctypes import wintypes

    class ControlEntry(ctypes.Structure):
        _fields_ = [("key", ctypes.c_char * 96), ("mapping_name", ctypes.c_wchar * 128),
                    ("capacity", ctypes.c_uint32), ("generation", ctypes.c_uint32),
                    ("publish_count", ctypes.c_uint64)]

    class ControlBlock(ctypes.Structure):
        _fields_ = [("magic", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
                    ("process_id", ctypes.c_uint32), ("entry_count", ctypes.c_uint32),
                    ("sequence", ctypes.c_int64), ("entries", ControlEntry * 64)]

    class ValueHeader(ctypes.Structure):
        _fields_ = [("magic", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
                    ("capacity", ctypes.c_uint32), ("active_buffer", ctypes.c_long),
                    ("sequence", ctypes.c_int64 * 2), ("length", ctypes.c_uint32 * 2),
                    ("reserved", ctypes.c_uint32 * 2), ("timestamp_qpc", ctypes.c_uint64 * 2)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    file_map_read = 0x0004

    def mapping_bytes(name: str, size: int):
        handle = kernel.OpenFileMappingW(file_map_read, False, name)
        if not handle:
            raise FileNotFoundError(ctypes.get_last_error(), f"shared mapping not found: {name}")
        view = kernel.MapViewOfFile(handle, file_map_read, 0, 0, size)
        if not view:
            error = ctypes.get_last_error(); kernel.CloseHandle(handle)
            raise OSError(error, f"cannot map shared memory: {name}")
        return handle, view

    handle, view = mapping_bytes(CONTROL_MAPPING_NAME, ctypes.sizeof(ControlBlock))
    try:
        descriptor = None
        for _ in range(8):
            first = ctypes.c_int64.from_address(view + 16).value
            if first & 1:
                continue
            snapshot = ctypes.string_at(view, ctypes.sizeof(ControlBlock))
            second = ctypes.c_int64.from_address(view + 16).value
            if first != second or second & 1:
                continue
            control = ControlBlock.from_buffer_copy(snapshot)
            for entry in control.entries[:min(control.entry_count, 64)]:
                if bytes(entry.key).split(b"\0", 1)[0].decode("utf-8") == key:
                    descriptor = (entry.mapping_name, entry.capacity)
                    break
            if descriptor:
                break
        if descriptor is None:
            raise KeyError(f"loader channel is not published: {key}")
    finally:
        kernel.UnmapViewOfFile(view); kernel.CloseHandle(handle)

    mapping_name, capacity = descriptor
    total = ctypes.sizeof(ValueHeader) + capacity * 2
    handle, view = mapping_bytes(mapping_name, total)
    try:
        for _ in range(16):
            header = ValueHeader.from_buffer_copy(ctypes.string_at(view, ctypes.sizeof(ValueHeader)))
            active = header.active_buffer
            if active not in (0, 1) or header.sequence[active] & 1:
                continue
            length = header.length[active]
            if length > capacity:
                raise ValueError("loader channel length exceeds capacity")
            payload = ctypes.string_at(view + ctypes.sizeof(ValueHeader) + active * capacity, length)
            after = ValueHeader.from_buffer_copy(ctypes.string_at(view, ctypes.sizeof(ValueHeader)))
            if after.active_buffer == active and after.sequence[active] == header.sequence[active] and not after.sequence[active] & 1:
                return payload
        raise RuntimeError("loader channel changed continuously while reading")
    finally:
        kernel.UnmapViewOfFile(view); kernel.CloseHandle(handle)


def read_train_frame() -> TrainTelemetryFrame:
    """Read and parse the latest stable train wrapper frame."""
    return parse_train_frame(_read_bus_payload(CHANNEL_KEY))


def read_train_identities() -> tuple[TrainIdentity, ...]:
    """Read the low-frequency entity-to-display_name mapping."""
    return parse_train_identities(_read_bus_payload(IDENTITY_CHANNEL_KEY))


def read_json_channel(key: str) -> dict:
    """Read one Loader JSON channel without falling back to Bridge files."""
    value = json.loads(_read_bus_payload(key).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"loader JSON channel is not an object: {key}")
    from tpf2_mcp.repositories.asset_cache import persist_asset
    persist_asset(key, value)
    return value


def read_train_footprints() -> dict:
    """Read the route-window/envelope payload used to scope train controls."""
    return read_json_channel(TRAIN_FOOTPRINT_CHANNEL_KEY)

