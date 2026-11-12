"""Loader shared-memory command sender and correlated Lua replies."""
import time

from .bridge import BridgeError
from .loader_command_ipc import LoaderCommandTransport, command_opcode
from .loader_telemetry import read_json_channel, read_train_footprints
from .protocol import request


class LuaCommandRejected(BridgeError):
    """Lua returned a correlated negative acknowledgement."""


class LoaderLuaCommandClient:
    def __init__(self, *, reader=read_json_channel, timeout=15, clock=time.time, transport=None):
        self.reader, self.timeout, self.clock = reader, timeout, clock
        self.transport = transport or LoaderCommandTransport()

    @classmethod
    def for_simulation(cls, *, timeout=15):
        """Bind commands to the simulation session, excluding GUI LOADING heartbeats."""
        def reader(key):
            value = read_json_channel(key)
            if key == 'heartbeat.json':
                frame = read_train_footprints()
                if (frame.get('source_status') == 'ENGINE_OBSERVED_DYNAMIC'
                    and isinstance(frame.get('session_id'), str)
                    and 0 <= time.time()-frame.get('generated_at', 0) <= 2):
                    value = {**value, 'session_id':frame['session_id'],
                             'last_update':frame['generated_at'], 'bridge_ready':True}
            return value
        return cls(reader=reader, timeout=timeout)

    def heartbeat(self):
        heartbeat = self.reader('heartbeat.json')
        if not heartbeat.get('bridge_ready') or not 0 <= self.clock()-heartbeat.get('last_update', 0) <= 10:
            raise BridgeError('LUA_COMMAND_UNAVAILABLE: heartbeat missing or stale')
        if heartbeat.get('lua_command_protocol') != 2 or not heartbeat.get('session_id'):
            raise BridgeError('LUA_COMMAND_PROTOCOL_UNAVAILABLE: update/reload the Mod runtime')
        return heartbeat

    def call(self, command, params=None, *, expected_session=None):
        heartbeat = self.heartbeat()
        if expected_session is not None and heartbeat['session_id'] != expected_session:
            raise BridgeError('LUA_SESSION_CHANGED')
        session = heartbeat['session_id']
        payload = request(command, {**(params or {}), '_expected_session_id': session})
        def session_check():
            if self.heartbeat()['session_id'] != session:
                raise BridgeError('LUA_SESSION_CHANGED')
        reply = self.transport.exchange(command_opcode(command, params or {}), payload,
                                        timeout=self.timeout, reader=self.reader, session_check=session_check)
        if reply.get('request_id') != payload['request_id']:
            raise BridgeError('LUA_REPLY_REQUEST_MISMATCH')
        if reply.get('session_id') != session:
            raise BridgeError('LUA_SESSION_CHANGED')
        if not reply.get('ok'):
            error = reply.get('error') or reply.get('result') or {}
            raise LuaCommandRejected(f"{error.get('code', 'UNKNOWN')}: {error.get('message', '')}")
        return reply.get('result')
