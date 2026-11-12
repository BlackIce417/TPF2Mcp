"""MCP boundary for experimentally verified native train movement commands."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time

from .bridge import BridgeError, _atomic_json_write, _mailbox_lock
from .loader_telemetry import read_train_frame, read_train_footprints, read_train_identities
from .lua_commands import LoaderLuaCommandClient, LuaCommandRejected
from .native_ipc import (ControllerCommandClient, ControllerCommandError, pack_train_movement_distance,
                         pack_train_movement_route)
from .stop_control import COMMON, TRAIN


HANDLE = {'type': 'string', 'pattern': '^[1-9][0-9]{0,19}$',
          'description': '原样传回的十进制字符串；不要转成浮点数，避免64位编号精度丢失。'}
MOTION = {
    'speed_kmh': {'type': 'number', 'minimum': 0.001, 'maximum': 500},
    'expires_in_seconds': {'type': 'integer', 'minimum': 5, 'maximum': 600, 'default': 120,
                          'description': '包含等待、移动及到点扣停；到期尝试恢复，不保证不可达目标能自动脱困。'},
}
EDGE = {'type': 'object', 'properties': {
    'entity': {'type': 'integer', 'minimum': 1, 'maximum': 1073741823},
    'index': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647},
    'direction': {'type': 'integer', 'enum': [0, 1]},
}, 'required': ['entity', 'index', 'direction'], 'additionalProperties': False}
WRITE_SPECS = {
    'reverse_train': ('列车换向',
        '先请求停车，确认零速后调用游戏reverseVehicle换向。异步返回WAITING_STOP，须查询get_train_direction直到REVERSED。'
        '换向后保持手动停车，120秒看门狗解除。继续移动前先resume_train解除停车，再重新读取原生路径；解除停车可能改变下一站及路径。'
        '换向会使原移动接管因路径变化退出；不会自动清理其他列车。', {}, []),
    'move_train_distance': ('列车定距移动',
        '沿列车当前朝向及当前引擎路径，以指定速度上限移动distance_m，到点扣停，以整列车中心计量。'
        '仅支持在途铁路列车；先解除手动停车。保留游戏信号和轨道占用保护，不保证能立即移动。',
        {**MOTION, 'distance_m': {'type': 'number', 'minimum': 0.001, 'maximum': 100000}},
        ['speed_kmh', 'distance_m']),
    'move_train_route': ('列车指定进路移动',
        '使用有序原生{entity,index,direction}子边走指定道岔分支并到点扣停。不是简化拓扑图边ID。'
        'edges[0]须为当前中心所在有向子边，保持前半列车已占用路径；target_index是所传数组0起始下标，'
        'target_offset_m沿有向子边从入口计米。目标后须留前半列车长度加10米及末端保护边。'
        '退行路径应收短到目标及必要余量，避免无顺向信号时预留整个长区段。'
        '仅支持在途铁路列车，先解除手动停车。保留信号/占用保护，不自动规划回程。',
        {**MOTION, 'edges': {'type': 'array', 'minItems': 1, 'maxItems': 512, 'items': EDGE},
         'target_index': {'type': 'integer', 'minimum': 0, 'maximum': 511},
         'target_offset_m': {'type': 'number', 'minimum': 0, 'maximum': 100000},
         'require_resumable_route': {'type': 'boolean', 'default': False,
             'description': '可选原线路前向恢复预检，需要DLL声明movement_return_check能力。调车默认false，调用方负责回程。'}},
        ['speed_kmh', 'edges', 'target_index', 'target_offset_m']),
    'release_train_movement': ('解除列车移动接管',
        '请求解除一个本服务发布的移动接管。查询get_train_movement直到RELEASED；改过路径时须从当前位置重算原线路。'
        'RESTORING/WAITING_FOR_NORMAL_ROUTE表示尚未恢复且仍扣停，不能当作成功。不会清除独立的手动停车或限速。',
        {'movement_id': HANDLE}, ['movement_id']),
}
READ_SPECS = {
    'get_train_movement_context': ('读取列车原生移动上下文',
        '读取当前存档的新鲜路径窗口、中心在窗口中的位置、车长、速度、手动停车、下一站和原生能力。'
        '供构造move_train_route使用。原生子边不是简化拓扑边；换向/解除停车后必须重新读取。'
        '换向前可保存窗口用于规划退路，换向后游戏可能仅保留车身附近的短路径。', TRAIN, ['display_name']),
    'get_train_direction': ('查询列车换向状态',
        '读取该列车最新一次换向的WAITING_STOP/REVERSING/REVERSED/FAILED状态、operation_id和实际速度。'
        'REVERSED只代表换向已确认，不表示已经移动或恢复原线路。', TRAIN, ['display_name']),
    'get_train_movement': ('查询列车移动接管',
        '按本服务返回的movement_id查询当前存档及Controller实例中的实时接管状态、剩余米数和实际速度。'
        'PENDING只表示受理；MOVING代表接管激活，实际速度可因信号/占用而为零。HELD才表示到点停车。',
        {'movement_id': HANDLE}, ['movement_id']),
}
MOVEMENT_WRITES = set(WRITE_SPECS)
MOVEMENT_TOOL_NAMES = MOVEMENT_WRITES | READ_SPECS.keys()
MOVEMENT_TOOLS = []
for name, (title, description, fields, required) in {**WRITE_SPECS, **READ_SPECS}.items():
    write = name in MOVEMENT_WRITES
    properties = {**COMMON, **({} if name == 'release_train_movement' else TRAIN), **fields} if write else fields
    MOVEMENT_TOOLS.append({'name': name, 'title': title,
        'description': description + (' 默认dry_run=true；实际执行需工具名大写:command_id确认串。相同command_id不会重复执行。' if write else ''),
        'inputSchema': {'type': 'object', 'properties': properties,
            'required': (['command_id', 'reason'] + ([] if name == 'release_train_movement' else ['display_name']) + required) if write else required,
            'additionalProperties': False},
        'outputSchema': {'type': 'object', 'properties': {'schema_version': {'type': 'integer'}, 'status': {'type': 'string'}},
                         'required': ['schema_version', 'status']}})


class MovementService:
    def __init__(self, *, client=None, lua=None, frame_reader=read_train_frame,
                 footprint_reader=read_train_footprints, identities=read_train_identities,
                 journal=None, clock=time.time):
        self.client = client or ControllerCommandClient()
        self.lua = lua or LoaderLuaCommandClient.for_simulation()
        self.frame_reader, self.footprint_reader, self.identities = frame_reader, footprint_reader, identities
        self.journal = Path(journal or Path(__file__).resolve().parents[3]/'var'/'train-movement-commands').resolve()
        self.clock = clock

    @staticmethod
    def _hash(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    @staticmethod
    def _handle(value):
        if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,19}', value) is None or int(value) >= 2**64:
            raise ValueError('INVALID_MOVEMENT_ID: pass the decimal string returned by a movement tool')
        return int(value)

    def _context(self, args, heartbeat):
        label, vehicle = args['display_name'], args.get('vehicle_id')
        if not isinstance(label, str) or not 1 <= len(label) <= 256:
            raise ValueError('INVALID_DISPLAY_NAME')
        if vehicle is not None and (type(vehicle) is not int or not 1 <= vehicle <= 0x3fffffff):
            raise ValueError('INVALID_VEHICLE_ID')
        identities = [t for t in self.identities() if t.display_name == label and (vehicle is None or t.entity_id == vehicle)]
        if len(identities) != 1: raise BridgeError('TRAIN_NOT_FOUND_OR_AMBIGUOUS')
        vehicle = int(identities[0].entity_id)
        frame, footprint = self.frame_reader(), self.footprint_reader()
        age = self.clock()-footprint.get('generated_at', 0)
        if not 0 <= age <= 3 or footprint.get('session_id') != heartbeat['session_id']:
            raise BridgeError('MOVEMENT_TELEMETRY_STALE_OR_SESSION_CHANGED')
        if footprint.get('source_status') != 'ENGINE_OBSERVED_DYNAMIC':
            raise BridgeError('MOVEMENT_TELEMETRY_NOT_ENGINE_OBSERVED')
        train = next((t for t in frame.trains if int(t.entity_id) == vehicle), None)
        observed = next((v for v in footprint.get('vehicles', []) if v.get('entity_id') == vehicle), None)
        if train is None or observed is None: raise BridgeError('TRAIN_TELEMETRY_UNAVAILABLE')
        if not math.isfinite(train.current_speed_mps) or not math.isfinite(train.total_length_m):
            raise BridgeError('TRAIN_MOTION_VALUES_UNAVAILABLE')
        state = self.lua.call('get_control_state', {'vehicle_id': vehicle}, expected_session=heartbeat['session_id'])
        if state.get('session_id') != heartbeat['session_id'] or not 0 <= self.clock()-state.get('observed_at', 0) <= 3:
            raise BridgeError('CONTROL_STATE_STALE_OR_SESSION_CHANGED')
        control = state['vehicle']
        if control.get('name') != label or control.get('carrier') != 1 or control.get('line_id') != int(train.line_entity_id):
            raise BridgeError('TRAIN_IDENTITY_CHANGED_OR_NOT_RAIL')
        return {'display_name': label, 'vehicle_id': vehicle, 'line_id': control['line_id'],
                'length_m': float(train.total_length_m), 'actual_speed_kmh': float(train.current_speed_mps)*3.6,
                'route_window': observed.get('route_window'), 'control': control, 'age_seconds': age,
                'wrapper_path_index': int(train.path_edge_index),
                'direction_control_protocol': state.get('direction_control_protocol')}

    def _record(self, mid, session):
        directory = self.journal/self._hash(session)
        path = directory/('movement-'+str(mid)+'.json')
        if not path.is_file(): raise BridgeError('MOVEMENT_NOT_ISSUED_IN_CURRENT_SESSION')
        record = json.loads(path.read_text(encoding='utf-8'))
        if record['controller_epoch'] != str(self.client.epoch()):
            raise BridgeError('CONTROLLER_RELOADED: this movement belongs to an earlier instance')
        return record

    def call(self, name, args):
        spec = next(t for t in MOVEMENT_TOOLS if t['name'] == name)['inputSchema']
        if not isinstance(args, dict) or set(args)-spec['properties'].keys() or any(k not in args for k in spec['required']):
            raise ValueError('INVALID_ARGUMENTS: missing or unexpected argument')
        write = name in MOVEMENT_WRITES
        if write:
            cid, reason = args['command_id'], args['reason']
            if not isinstance(cid, str) or re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', cid) is None:
                raise ValueError('INVALID_COMMAND_ID')
            if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512: raise ValueError('INVALID_REASON')
            dry = args.get('dry_run', True)
            if not isinstance(dry, bool): raise ValueError('INVALID_DRY_RUN')
            if 'confirmation' in args and not isinstance(args['confirmation'], str): raise ValueError('INVALID_CONFIRMATION')
            if not dry and args.get('confirmation') != name.upper()+':'+cid:
                raise ValueError('CONFIRMATION_REQUIRED: '+name.upper()+':'+cid)
        heartbeat = self.lua.heartbeat()
        session = heartbeat['session_id']
        record = None
        if name in ['get_train_movement', 'release_train_movement']:
            mid = self._handle(args['movement_id']);record = self._record(mid, session)
            target = self._context(record['target'], heartbeat)
        else:
            target = self._context(args, heartbeat)
        base = {'schema_version': 1, 'session_id': session, 'display_name': target['display_name'],
                'vehicle_id': target['vehicle_id']}
        if not write:
            if name == 'get_train_movement':
                motion = self.client.get_train_movement(mid)['movement']
                return {**base, **motion, 'movement_id': str(mid), 'status': motion['state'],
                        'actual_speed_kmh': target['actual_speed_kmh'], 'is_moving': target['actual_speed_kmh'] > .036}
            if name == 'get_train_direction':
                return {**base, 'status': (target['control'].get('direction_control') or {}).get('state', 'NO_REVERSAL'),
                        'direction': target['control'].get('direction_control'), 'actual_speed_kmh': target['actual_speed_kmh'],
                        'user_stopped': target['control'].get('raw_userStopped')}
            route = target['route_window']
            if not isinstance(route, dict): raise BridgeError('ROUTE_WINDOW_UNAVAILABLE')
            arrays = [route.get(k) for k in ('edge_ids', 'transport_indices', 'directions')]
            if any(not isinstance(a, list) for a in arrays) or len({len(a) for a in arrays}) != 1:
                raise BridgeError('NATIVE_ROUTE_WINDOW_INVALID')
            if target['wrapper_path_index'] != route.get('current_index'):
                raise BridgeError('ROUTE_WINDOW_STALE: retry after the next sample')
            edges = [{'entity': e, 'index': i, 'direction': int(d)} for e,i,d in zip(*arrays)]
            return {**base, 'status': 'OBSERVED', 'length_m': target['length_m'], 'line_id': target['line_id'],
                    'actual_speed_kmh': target['actual_speed_kmh'], 'control': target['control'],
                    'sample_age_seconds': target['age_seconds'], 'native_capabilities': self.client.get_capabilities()['detail'],
                    'route_window': {'start_path_index': route['start_index'], 'current_path_index': route['current_index'],
                        'current_window_index': route['current_index']-route['start_index'], 'edges': edges}}
        parameters = {}
        if name.startswith('move_train_'):
            parameters = {k: args[k] for k in ['speed_kmh'] + (['distance_m'] if name.endswith('distance') else ['edges','target_index','target_offset_m'])}
            parameters['expires_in_seconds'] = args.get('expires_in_seconds', 120)
            if name.endswith('route'):
                parameters['require_resumable_route'] = args.get('require_resumable_route', False)
                if type(parameters['require_resumable_route']) is not bool: raise ValueError('INVALID_REQUIRE_RESUMABLE_ROUTE')
                pack_train_movement_route(1,target['vehicle_id'],**{k:v for k,v in parameters.items() if k!='require_resumable_route'})
            else: pack_train_movement_distance(1,target['vehicle_id'],**parameters)
        elif name == 'release_train_movement': parameters = {'movement_id': str(mid)}
        required = {'STOP_VEHICLE'} if name=='reverse_train' else {'START_VEHICLE'}
        if name.startswith('move_train_'): required.add('STOP_VEHICLE')
        ready = heartbeat.get('allow_write_operations') is True and required.issubset(heartbeat.get('allowed_operations', []))
        preview = {**base, 'status': 'PREVIEW', 'command_id': cid, 'reason': reason,
                   'parameters': parameters, 'write_enabled': ready,
                   'actual_speed_kmh': target['actual_speed_kmh'], 'user_stopped': target['control'].get('raw_userStopped')}
        canonical = [name, session, target['vehicle_id'], parameters, reason]
        fingerprint = self._hash(json.dumps(canonical,sort_keys=True,allow_nan=False))
        directory = self.journal/self._hash(session)
        path = directory/('command-'+self._hash(cid)+'.json')
        if dry: return preview
        directory.mkdir(parents=True,exist_ok=True)
        with _mailbox_lock(directory,20,.05):
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'))
                if saved['fingerprint'] != fingerprint: raise BridgeError('COMMAND_ID_CONFLICT')
                return {**saved['result'],'replayed':True,'verification_is_historical':True}
            if not ready: raise BridgeError('WRITE_DISABLED: Mod write permissions/allowlist required')
            if name in ['reverse_train','move_train_distance','move_train_route'] and target['control'].get('raw_state') != 1:
                raise BridgeError('REQUIRES_EN_ROUTE_RAIL_TRAIN')
            if name.startswith('move_train_'):
                if target['control'].get('raw_userStopped') is True:
                    raise BridgeError('TRAIN_MANUALLY_STOPPED: resume_train, then refresh movement context')
                if target['wrapper_path_index'] != (target['route_window'] or {}).get('current_index'):
                    raise BridgeError('ROUTE_WINDOW_STALE: retry after the next sample')
                capabilities = self.client.get_capabilities()['detail'].split(';')
                if 'train_movement_experimental' not in capabilities:
                    raise BridgeError('CONTROLLER_MOVEMENT_UNAVAILABLE')
                if parameters.get('require_resumable_route') and 'movement_return_check' not in capabilities:
                    raise BridgeError('CONTROLLER_RETURN_CHECK_UNAVAILABLE')
            if name=='reverse_train' and target['direction_control_protocol'] != 1:
                raise BridgeError('MOD_REVERSE_CONTROL_UNAVAILABLE')
            self.lua.call('get_control_state', {'vehicle_id':target['vehicle_id']},expected_session=session)
            result={**preview,'status':'OUTCOME_UNKNOWN'}
            if name.startswith('move_train_'):
                mid=int(self._hash(session+':'+cid)[:16],16) or 1
                epoch=self.client.epoch()
                if epoch is None: raise BridgeError('CONTROLLER_UNAVAILABLE')
                result['movement_id']=str(mid)
            elif name=='reverse_train':
                result['operation_id']='mcp-reverse-'+self._hash(session+':'+cid)
            else: result['movement_id']=str(mid)
            saved={'fingerprint':fingerprint,'result':result}
            _atomic_json_write(path,saved)  # Intent first: uncertain reversal must never be sent twice.
            try:
                if name.startswith('move_train_'):
                    binding={'target':{'display_name':target['display_name'],'vehicle_id':target['vehicle_id']},
                             'controller_epoch':str(epoch),'command_id':cid}
                    _atomic_json_write(directory/('movement-'+str(mid)+'.json'),binding)
                    result['movement_id']=str(mid)
                    ack=getattr(self.client,name)(mid,target['vehicle_id'],**parameters)['movement']
                    result.update({**ack,'movement_id':str(mid),'status':ack['state']})
                elif name=='reverse_train':
                    result['acknowledgement']=self.client.reverse_train(target['vehicle_id'],operation_id=result['operation_id'],
                        lua_client=self.lua,expected_session=session,
                        precondition={'display_name':target['display_name'],'line_id':target['line_id']})
                    result['status']=result['acknowledgement']['state']
                else:
                    result['movement_id']=str(mid)
                    ack=self.client.release_train_movement(mid)['movement']
                    result.update({**ack,'movement_id':str(mid),'status':ack['state']})
            except (ControllerCommandError,LuaCommandRejected) as exc:
                result['status']='REJECTED'
                result['error']=str(exc)
            except (OSError,KeyError,RuntimeError,ValueError) as exc:
                result['error']=str(exc)
            saved['result']=result
            _atomic_json_write(path,saved)
            return result
