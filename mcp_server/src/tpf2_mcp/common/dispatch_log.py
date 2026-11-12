"""Log actual MCP dispatch submissions and their correlated outcomes."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import json
import threading
import time
from uuid import uuid4

from tpf2_mcp.common.audit import _started, safe_arguments
from tpf2_mcp.common.paths import runtime_path

_path = runtime_path('logs/dispatch') / (_started.strftime('%Y-%m-%d_%H-%M-%S_%f') + '.jsonl')
_current = ContextVar('mcp_dispatch_log', default=None)
_lock = threading.Lock()


def _append(record):
    with _lock:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with _path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'timestamp': datetime.now().astimezone().isoformat(), **record},
                                    ensure_ascii=False, allow_nan=False) + '\n')


@contextmanager
def capture(tool, request_id):
    context = {'tool': tool, 'request_id': request_id}
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def _command_text(tool, target, parameters):
    train = target.get('display_name', '未知列车')
    line = target.get('line_name') or f"线路{target.get('line_id')}"
    stop = parameters.get('stop_index', 0)
    if tool == 'set_train_speed_limit':
        speed = parameters['speed_kmh']
        action = '请求停车' if speed == 0 else f'限速{speed:g} km/h'
        return f"{train}，当前前方{parameters['lookahead_edges']}条路径边{action}，有效{parameters['expires_in_seconds']}秒"
    if tool == 'cancel_train_speed_limit': return f'{train}，取消限速命令'
    if tool == 'set_line_stop_policy':
        mode = {0: '能装就装', 1: '任一货物类型装满', 2: '全部货物类型装满'}.get(parameters['load_mode'])
        return (f"{line}，停站序号{stop}，最小等待{parameters['min_waiting_time']:g}秒，"
                f"最大等待{parameters['max_waiting_time']:g}秒，{mode}")
    if tool in ('add_line_stop_platform', 'remove_line_stop_platform'):
        action = '增加' if tool.startswith('add') else '删除'
        return (f"{line}，停站序号{stop}，车站{parameters['station_id']}，子站{parameters['station_index']}，"
                f"{action}允许停靠{parameters['terminal_id'] + 1}站台")
    if tool == 'hold_train_at_station': return f"{train}，站内扣停，最长{parameters['max_hold_seconds']}秒"
    if tool == 'release_train_from_hold': return f'{train}，解除站内扣停并请求发车'
    if tool == 'stop_train': return f"{train}，请求临时停车，最长{parameters['max_stop_seconds']}秒"
    if tool == 'resume_train': return f'{train}，清除手动停车标志'
    if tool == 'reverse_train': return f'{train}，停车后换向'
    if tool == 'move_train_distance':
        return f"{train}，沿当前路径以{parameters['speed_kmh']:g} km/h速度上限移动{parameters['distance_m']:g}米，到点扣停（按列车中心计）"
    if tool == 'move_train_route':
        return f"{train}，按指定原生路径以{parameters['speed_kmh']:g} km/h速度上限移动至子边下标{parameters['target_index']}的{parameters['target_offset_m']:g}米处，到点扣停（按列车中心计）"
    if tool == 'release_train_movement': return f'{train}，释放移动接管'
    return str(tool)


def submitted(*, command_id, target, parameters, reason, location=None):
    """Call immediately before the actual IPC send, after validation/dedup.

    A durable SUBMITTING record is intent, not proof that the game received it.
    Service calls outside an MCP invocation retain their existing journals.
    """
    context = _current.get()
    if context is None:
        return
    record = safe_arguments({
        'dispatch_id': uuid4().hex, 'request_id': context['request_id'],
        'command_id': command_id, 'tool': context['tool'], 'target': target,
        'parameters': parameters, 'reason': reason, 'location': location or {},
        'command_text': _command_text(context['tool'], target, parameters),
    })
    _append({'event': 'dispatch_submitting', 'status': 'SUBMITTING', **record})
    context['record'], context['started'] = record, time.monotonic()


def complete(context, response=None, error=None):
    record = context.get('record')
    if record is None:
        return
    result = (response or {}).get('result') or {}
    value = result.get('structuredContent') or {}
    if not isinstance(value, dict): value = {}
    rpc_error = (response or {}).get('error')
    receipt = {key: value[key] for key in (
        'status', 'result', 'error', 'rule_id', 'movement_id', 'operation_id',
        'controller_generation', 'expires_at', 'replayed', 'verification_is_historical') if key in value}
    status = value.get('status') or value.get('result') or 'OUTCOME_UNKNOWN'
    if error or rpc_error or result.get('isError'): status = 'OUTCOME_UNKNOWN'
    _append({'event': 'dispatch_finished', **record, 'status': status,
             'receipt': safe_arguments(receipt), 'error': error or rpc_error or value.get('error'),
             'duration_ms': round((time.monotonic() - context['started']) * 1000, 3)})
