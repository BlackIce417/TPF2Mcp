"""Bounded stop-policy and vehicle commands using the existing Lua dispatcher."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time

from .bridge import BridgeError, _atomic_json_write, _mailbox_lock
from .loader_telemetry import read_train_identities
from .lua_commands import LoaderLuaCommandClient, LuaCommandRejected


OPERATIONS = {
    'set_line_stop_policy': 'SET_LINE_STOP_POLICY',
    'hold_train_at_station': 'HOLD_VEHICLE_AT_TERMINAL',
    'release_train_from_hold': 'RELEASE_VEHICLE_FROM_HOLD',
    'stop_train': 'STOP_VEHICLE',
    'resume_train': 'START_VEHICLE',
}
MODES = {'LOAD_IF_AVAILABLE': 0, 'FULL_LOAD_ANY': 1, 'FULL_LOAD_ALL': 2}


def _number(value, lower, upper, *, integer=False):
    return (not isinstance(value, bool) and isinstance(value, int if integer else (int, float))
            and lower <= value <= upper and math.isfinite(value))


COMMON = {
    'command_id': {'type': 'string', 'pattern': '^[A-Za-z0-9._:-]{1,128}$'},
    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 512},
    'dry_run': {'type': 'boolean', 'default': True, 'description': '默认只预览；false 才会发送写命令。'},
    'confirmation': {'type': 'string', 'description': '实际执行必须精确等于工具名大写:command_id。'},
}
TRAIN = {
    'display_name': {'type': 'string', 'minLength': 1, 'maxLength': 256},
    'vehicle_id': {'type': 'integer', 'minimum': 1, 'description': '可选，在显示名称重复时精确选择列车。'},
}
SPECS = {
    'set_line_stop_policy': (
        '修改线路停站策略',
        '按line_id和0起始stop_index修改一次停站的装载模式、最小/最大等待秒数，影响该线路全部列车。FULL_LOAD_ANY按货物类型判定，不是任意车厢。等待上限不是精确的到发时刻。执行后回读验证，返回修改前配置。',
        {'line_id': {'type': 'integer', 'minimum': 1}, 'stop_index': {'type': 'integer', 'minimum': 0},
         'load_mode': {'type': 'string', 'enum': list(MODES)},
         'min_waiting_time_seconds': {'type': 'number', 'minimum': 0, 'maximum': 86400},
         'max_waiting_time_seconds': {'type': 'number', 'minimum': 0, 'maximum': 86400}},
        ['line_id', 'stop_index', 'load_mode', 'min_waiting_time_seconds', 'max_waiting_time_seconds']),
    'hold_train_at_station': (
        '站内扣停列车', '仅对已经处于站内等待状态的列车禁止自动发车。10..600秒后Lua看门狗解除；不负责让途中列车到指定车站再停车。',
        {**TRAIN, 'max_hold_seconds': {'type': 'integer', 'minimum': 10, 'maximum': 600}},
        ['display_name', 'max_hold_seconds']),
    'release_train_from_hold': (
        '解除站内扣停', '解除指定列车的手动发车限制，并请求发车；不保证信号、装卸等条件已允许立即开行。', TRAIN, ['display_name']),
    'stop_train': (
        '临时停车', '通过游戏setUserStopped命令请求指定列车停车，5..120秒后Lua看门狗恢复。回读验证停止标志，不代表列车已瞬间制动至零速。',
        {**TRAIN, 'max_stop_seconds': {'type': 'integer', 'minimum': 5, 'maximum': 120}},
        ['display_name', 'max_stop_seconds']),
    'resume_train': (
        '恢复列车运行', '清除游戏userStopped标志；不会撤销站内扣停、信号约束或Controller限速。', TRAIN, ['display_name']),
}
STOP_CONTROL_TOOLS = [
    {'name': name, 'title': title, 'description': description + ' 默认dry_run=true；受Mod写权限开关和操作白名单约束。相同command_id重试不会重复下发。',
     'inputSchema': {'type': 'object', 'properties': {**COMMON, **properties},
                     'required': ['command_id', 'reason', *required], 'additionalProperties': False},
     'outputSchema': {'type': 'object', 'properties': {'schema_version': {'type': 'integer'}, 'status': {'type': 'string'}},
                      'required': ['schema_version', 'status']}}
    for name, (title, description, properties, required) in SPECS.items()
]


class StopControlService:
    def __init__(self, *, client=None, identities=read_train_identities, journal=None):
        self.client = client or LoaderLuaCommandClient.for_simulation()
        self.identities = identities
        self.journal = Path(journal or Path(__file__).resolve().parents[3]/'var'/'lua-control-commands').resolve()

    def _state(self, target, session):
        value = self.client.call('get_control_state', target, expected_session=session)
        if value.get('session_id') != session or not 0 <= time.time()-value.get('observed_at', 0) <= 10:
            raise BridgeError('CONTROL_STATE_STALE_OR_SESSION_CHANGED')
        return value

    def call(self, name, args):
        properties = {**COMMON, **SPECS[name][2]}
        required = ['command_id', 'reason', *SPECS[name][3]]
        if not isinstance(args, dict) or set(args)-set(properties) or any(k not in args for k in required):
            raise ValueError('INVALID_ARGUMENTS: missing or unexpected argument')
        cid = args['command_id']
        if not isinstance(cid, str) or re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', cid) is None:
            raise ValueError('INVALID_COMMAND_ID')
        if not isinstance(args['reason'], str) or not 1 <= len(args['reason'].strip()) <= 512:
            raise ValueError('INVALID_REASON')
        dry_run = args.get('dry_run', True)
        if not isinstance(dry_run, bool): raise ValueError('INVALID_DRY_RUN')
        if not dry_run and args.get('confirmation') != f'{name.upper()}:{cid}':
            raise ValueError('CONFIRMATION_REQUIRED: ' + f'{name.upper()}:{cid}')
        if name == 'set_line_stop_policy':
            if not _number(args['line_id'], 1, 2**53-1, integer=True) or not _number(args['stop_index'], 0, 2**31-1, integer=True):
                raise ValueError('INVALID_LINE_OR_STOP_INDEX')
            if not isinstance(args['load_mode'], str) or args['load_mode'] not in MODES:
                raise ValueError('INVALID_LOAD_MODE')
            minimum, maximum = args['min_waiting_time_seconds'], args['max_waiting_time_seconds']
            if not _number(minimum, 0, 86400) or not _number(maximum, 0, 86400) or minimum > maximum:
                raise ValueError('INVALID_WAITING_TIME: 0 <= minimum <= maximum <= 86400')
            target = {'line_id': args['line_id']}
            parameters = {'stop_index': args['stop_index'], 'load_mode': MODES[args['load_mode']],
                          'min_waiting_time': minimum, 'max_waiting_time': maximum}
        else:
            label = args['display_name']
            if not isinstance(label, str) or not 1 <= len(label) <= 256: raise ValueError('INVALID_DISPLAY_NAME')
            vehicle_id = args.get('vehicle_id')
            if vehicle_id is not None and not _number(vehicle_id, 1, 2**53-1, integer=True): raise ValueError('INVALID_VEHICLE_ID')
            ids = [int(t.entity_id) for t in self.identities() if t.display_name == label and (vehicle_id is None or t.entity_id == vehicle_id)]
            if len(ids) != 1: raise BridgeError('TRAIN_NOT_FOUND_OR_AMBIGUOUS')
            target = {'vehicle_id': ids[0]}
            parameters = {}
            for field, lower, upper in [('max_hold_seconds', 10, 600), ('max_stop_seconds', 5, 120)]:
                if field in properties:
                    if not _number(args[field], lower, upper, integer=True): raise ValueError('INVALID_' + field.upper())
                    parameters[field] = args[field]
        heartbeat = self.client.heartbeat()
        session = heartbeat['session_id']
        operation = OPERATIONS[name]
        state = self._state(target, session)
        if name == 'set_line_stop_policy':
            stops = state['line'].get('raw_stops') or []
            stop = next((s for s in stops if s.get('sequence_index') == args['stop_index']), None)
            if stop is None: raise BridgeError('STOP_NOT_FOUND')
            before = stop.get('policy')
            precondition = {'station_id': stop.get('station_id'), 'station_index': stop.get('station_index'),
                            'terminal_id': stop.get('terminal_id'), 'policy': before}
        else:
            before = state['vehicle']
            if before.get('name') != args['display_name'] or before.get('carrier') != 1:
                raise BridgeError('TRAIN_IDENTITY_CHANGED_OR_NOT_RAIL')
            precondition = {'display_name': args['display_name'], 'line_id': before.get('line_id')}
        ready = heartbeat.get('allow_write_operations') is True and operation in heartbeat.get('allowed_operations', [])
        preview = {'schema_version': 1, 'status': 'PREVIEW', 'command_id': cid, 'session_id': session,
                   'operation_type': operation, 'target': target, 'parameters': parameters, 'before': before,
                   'reason': args['reason'], 'write_enabled': ready}
        fingerprint = hashlib.sha256(json.dumps([name, target, parameters, args['reason']], sort_keys=True).encode()).hexdigest()
        directory = self.journal/hashlib.sha256(session.encode()).hexdigest()
        path = directory/(hashlib.sha256(cid.encode()).hexdigest()+'.json')
        if dry_run:
            preview['preconditions_met'] = name != 'hold_train_at_station' or before.get('raw_state') == 2
            return preview
        directory.mkdir(parents=True, exist_ok=True)
        with _mailbox_lock(directory, 20, .05):
            if path.exists():
                record = json.loads(path.read_text(encoding='utf-8'))
                if record['fingerprint'] != fingerprint: raise BridgeError('COMMAND_ID_CONFLICT')
                return {**record['result'], 'replayed': True, 'verification_is_historical': True}
            if not ready: raise BridgeError('WRITE_DISABLED: enable this operation in the Mod permission allowlist')
            if name == 'hold_train_at_station' and before.get('raw_state') != 2:
                raise BridgeError('TRAIN_NOT_WAITING_AT_STATION')
            result = {**preview, 'status': 'OUTCOME_UNKNOWN', 'verification': None}
            record = {'fingerprint': fingerprint, 'result': result}
            _atomic_json_write(path, record)
            envelope = {'schema_version': 1, 'operation_id': 'mcp-stop-'+hashlib.sha256((session+':'+cid).encode()).hexdigest(),
                        'operation_type': operation, 'target': target, 'parameters': parameters,
                        '_control_precondition': precondition}
            try:
                acknowledgement = self.client.call('execute_operation', envelope, expected_session=session)
                result['acknowledgement'] = acknowledgement
                if not acknowledgement or not acknowledgement.get('accepted'):
                    raise BridgeError('COMMAND_NOT_ACCEPTED')
                result['status'] = 'ACCEPTED_UNVERIFIED'
                deadline = time.monotonic()+3
                while True:
                    observed = self._state(target, session)
                    result['verification'] = observed
                    if self._matches(name, parameters, observed):
                        result['status'] = 'POSTCONDITION_VERIFIED'
                        break
                    if time.monotonic() >= deadline: break
                    time.sleep(.1)
            except LuaCommandRejected as exc:
                if 'acknowledgement' not in result:
                    result['status'] = 'REJECTED'
                result['error'] = str(exc)
            except (BridgeError, OSError, KeyError, RuntimeError, ValueError) as exc:
                result['error'] = str(exc)
            record['result'] = result
            _atomic_json_write(path, record)
            return result

    @staticmethod
    def _matches(name, parameters, observed):
        if name == 'set_line_stop_policy':
            stop = next((s for s in observed['line'].get('raw_stops', []) if s.get('sequence_index') == parameters['stop_index']), {})
            return stop.get('policy') == {k: v for k, v in parameters.items() if k != 'stop_index'}
        vehicle = observed['vehicle']
        if name in ('hold_train_at_station', 'release_train_from_hold'):
            control = vehicle.get('departure_control') or {}
            manual = name == 'hold_train_at_station'
            return control.get('command_confirmed') is True and control.get('manual') is manual and vehicle.get('raw_autoDeparture') is (not manual)
        control = vehicle.get('movement_control') or {}
        stopped = name == 'stop_train'
        return control.get('command_confirmed') is True and control.get('stopped') is stopped and vehicle.get('raw_userStopped') is stopped
