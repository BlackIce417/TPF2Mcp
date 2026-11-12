"""Shared movement input contracts."""
from tpf2_mcp.services.stop_control import COMMON, TRAIN

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
