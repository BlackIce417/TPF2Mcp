"""movement business service."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import time
from tpf2_mcp.transport.bridge import BridgeError, _atomic_json_write, _mailbox_lock
from tpf2_mcp.transport.loader_telemetry import read_train_frame, read_train_footprints, read_train_identities
from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient, LuaCommandRejected
from tpf2_mcp.transport.native_ipc import (ControllerCommandClient, ControllerCommandError, pack_train_movement_distance,
                         pack_train_movement_route)
from tpf2_mcp.services.stop_control import COMMON, TRAIN
from tpf2_mcp.common.contracts.movement import MOVEMENT_TOOLS, MOVEMENT_WRITES
from tpf2_mcp.common.paths import runtime_path

class MovementService:
    def __init__(self, *, client=None, lua=None, frame_reader=read_train_frame,
                 footprint_reader=read_train_footprints, identities=read_train_identities,
                 journal=None, clock=time.time):
        self.client = client or ControllerCommandClient()
        self.lua = lua or LoaderLuaCommandClient.for_simulation()
        self.frame_reader, self.footprint_reader, self.identities = frame_reader, footprint_reader, identities
        self.journal = Path(journal or runtime_path('var/train-movement-commands')).resolve()
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
                from tpf2_mcp.common.dispatch_log import submitted
                submitted(command_id=cid,
                          target={key: target.get(key) for key in ('display_name', 'vehicle_id', 'line_id')},
                          parameters=parameters, reason=reason,
                          location={'session_id': session, 'wrapper_path_index': target['wrapper_path_index']})
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
