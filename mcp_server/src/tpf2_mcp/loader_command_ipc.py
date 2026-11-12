"""Windows x64 Loader command ABI: one serialized request, numeric opcode."""
import ctypes
from ctypes import wintypes
import json
import os
import struct
import time

from .bridge import BridgeError
from .native_ipc import _kernel32

MAGIC = 0x434C4654
VERSION = 1
HEADER = struct.Struct('<IIIIIIIIQQQQ')
CAPACITY = 16384
MAPPING = 'Local\\tpf2mcp_loader_cmd_v1'
MUTEX = 'Local\\tpf2mcp_loader_cmd_mutex_v1'
REPLY_EVENT = 'Local\\tpf2mcp_loader_cmd_reply_v1'
IDLE, READY, TAKEN, COMPLETE, REJECTED, CANCELLED = range(6)
READ_OPCODES = {'ping': 1, 'get_control_state': 2, 'get_game_state': 3, 'get_operational_telemetry': 4}
WRITE_OPCODES = {'SET_LINE_STOP_POLICY': 0x101, 'HOLD_VEHICLE_AT_TERMINAL': 0x102,
                 'RELEASE_VEHICLE_FROM_HOLD': 0x103, 'STOP_VEHICLE': 0x104, 'START_VEHICLE': 0x105}


def command_opcode(command, params):
    opcode = WRITE_OPCODES.get(params.get('operation_type')) if command == 'execute_operation' else READ_OPCODES.get(command)
    if opcode is None: raise ValueError('UNSUPPORTED_LOADER_COMMAND')
    return opcode


class LoaderCommandTransport:
    def __init__(self, *, mapping=MAPPING, mutex=MUTEX, reply_event=REPLY_EVENT):
        self.names = mapping, mutex, reply_event

    def exchange(self, opcode, payload, *, timeout, reader, session_check):
        if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise BridgeError('LOADER_COMMAND_REQUIRES_WINDOWS_X64')
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if not 0 < len(encoded) <= CAPACITY: raise ValueError('LOADER_COMMAND_PAYLOAD_TOO_LARGE')
        kernel = _kernel32()
        mapping = mutex = event = view = None
        locked = False
        try:
            mapping = kernel.OpenFileMappingW(6, False, self.names[0])
            if not mapping: raise BridgeError('LOADER_COMMAND_CHANNEL_UNAVAILABLE: install the new Loader and restart the game')
            view = kernel.MapViewOfFile(mapping, 6, 0, 0, HEADER.size+CAPACITY)
            if not view: raise BridgeError('LOADER_COMMAND_MAP_FAILED')
            mutex = kernel.CreateMutexW(None, False, self.names[1])
            event = kernel.OpenEventW(0x00100000, False, self.names[2])
            if not mutex or not event: raise BridgeError('LOADER_COMMAND_SYNC_UNAVAILABLE')
            wait = kernel.WaitForSingleObject(mutex, max(1, int(timeout*1000)))
            if wait not in (0, 0x80): raise BridgeError('LOADER_COMMAND_BUSY')
            locked = True
            session_check()
            initial = HEADER.unpack(ctypes.string_at(view, HEADER.size))
            if initial[:4] != (MAGIC, VERSION, HEADER.size, CAPACITY) or not initial[4]:
                raise BridgeError('LOADER_COMMAND_ABI_MISMATCH')
            if initial[5] not in (IDLE, COMPLETE, REJECTED, CANCELLED):
                raise BridgeError('LOADER_COMMAND_IN_FLIGHT: previous request has not finished; no overwrite permitted')
            sequence = max(1, time.time_ns() & ((1 << 53)-1))
            if sequence == initial[8]: sequence = sequence % ((1 << 53)-1)+1
            deadline_ms = int((time.time()+timeout)*1000)
            # The named mutex serializes producers. On Windows x64, the final
            # aligned 32-bit state store publishes the preceding payload stores;
            # Loader acquires it with InterlockedCompareExchange.
            ctypes.memmove(view+HEADER.size, encoded, len(encoded))
            ctypes.memmove(view+24, struct.pack('<IIQQQQ', opcode, len(encoded), sequence, deadline_ms, 0, 0), 40)
            ctypes.c_uint32.from_address(view+20).value = READY
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                header = HEADER.unpack(ctypes.string_at(view, HEADER.size))
                if header[4] != initial[4] or header[8] != sequence:
                    raise BridgeError('LOADER_COMMAND_HOST_CHANGED: outcome unknown')
                if header[5] == REJECTED and header[10] == sequence:
                    raise BridgeError('LOADER_COMMAND_REJECTED: invalid opcode/payload or expired request')
                if header[5] == COMPLETE and header[10] == sequence:
                    try: reply = reader('command-response.json')
                    except KeyError: reply = {}
                    if reply.get('request_id') == payload['request_id']:
                        return reply
                kernel.WaitForSingleObject(event, 25)
            # A READY/TAKEN request is deliberately left intact. No second
            # producer may overwrite it; Loader expires READY before dispatch.
            raise BridgeError('LUA_COMMAND_OUTCOME_UNKNOWN: timeout; retry with the same command_id')
        finally:
            if locked: kernel.ReleaseMutex(mutex)
            if view: kernel.UnmapViewOfFile(view)
            for handle in (event, mutex, mapping):
                if handle: kernel.CloseHandle(handle)
