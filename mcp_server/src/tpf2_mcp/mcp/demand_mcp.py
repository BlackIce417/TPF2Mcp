"""Loader-backed line demand and station waiting queries; no legacy file RPC."""
from copy import deepcopy
import time

from tpf2_mcp.transport.bridge import BridgeError
from tpf2_mcp.services.dispatch import station_waiting_state
from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient
from tpf2_mcp.repositories.snapshot import SnapshotIndex

MAXIMUM = {'type':'integer','minimum':100,'maximum':50000,'default':20000,
           'description':'每条线路、每类实体的扫描上限。达到上限时标记截断，数量仅为已扫描部分。'}
FORCE = {'type':'boolean','default':False,'description':'跳过最长2秒的同会话线路需求缓存。'}


def _tool(name, title, description, properties, required):
    return {'name':name,'title':title,'description':description,
            'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False},
            'outputSchema':{'type':'object','properties':{'schema_version':{'type':'integer'},'session_id':{'type':'string'}},
                            'required':['schema_version','session_id']}}


DEMAND_TOOLS = [
    _tool('get_cargo_types','获取货物类型','读取游戏当前货物类型ID、资源键和显示名称，用于解释货物分类；不含各站库存数量。',{},[]),
    _tool('get_line_demand','获取线路客货需求',
          '按线路读取已分配旅客和货物的等待量、在车量、平均等待时间、车上数量、各停站等待量及起讫停站OD。货物按类型分类，车辆ID关联列车遥测。必须检查quality：截断值是已扫描数量，UNAVAILABLE不能当作0。统计单位是人和SIM_CARGO实体数，货物物理单位未实机核验。',
          {'line_id':{'type':'integer','minimum':1},'maximum_entities':MAXIMUM,'force_refresh':FORCE},['line_id']),
    _tool('get_station_waiting_state','获取车站各线路等待量',
          '按车站组ID导出每条连接线路的候车人数和待装货物数，含货物分类、停站索引和采样时间。可指定line_id只查某线路。仅覆盖已分配线路并能通过OD起点定位到本站的等待实体，不等于车站全部库存；质量不完整时只展示已知数量或null。各线路依次采样，不是原子全网快照。',
          {'station_id':{'type':'integer','minimum':1},'line_id':{'type':'integer','minimum':1},
           'maximum_entities':MAXIMUM,'force_refresh':FORCE},['station_id']),
]
DEMAND_TOOL_NAMES = {t['name'] for t in DEMAND_TOOLS}


from tpf2_mcp.services.demand import DemandService
