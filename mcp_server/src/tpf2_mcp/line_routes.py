"""Join line stop plans, live train identities and observed topology routes."""
from __future__ import annotations

import time

from .loader_telemetry import read_train_frame, read_train_identities, read_train_footprints

LOAD_MODES = {
    0: ('LOAD_IF_AVAILABLE', '能装就装'),
    1: ('FULL_LOAD_ANY', '满载任意一种货物类型'),
    2: ('FULL_LOAD_ALL', '满载全部货物类型'),
}


class RouteTopologyIndex:
    def __init__(self, topology):
        self.raw = {}
        self.station_nodes = {}
        for node in topology['nodes']:
            wrapper = node.get('station_wrapper')
            if wrapper:
                for station_id in wrapper.get('station_ids') or [wrapper['entry_id']]:
                    self.station_nodes[station_id] = node['id']
                for edge in wrapper['internal_edges']:
                    for segment in edge['track_segments']:
                        self.raw.setdefault(segment['game_edge_id'], []).append({
                            'kind':'station','node_id':node['id'],
                            'start':segment['begin_position01'],'end':segment['end_position01']})
        for edge in topology['edges']:
            for segment in edge['track_segments']:
                self.raw.setdefault(segment['game_edge_id'], []).append({
                    'kind':'edge','edge_id':edge['id'],'section_id':edge['track_resource_id'],
                    'from_node_id':edge['from_node_id'],'to_node_id':edge['to_node_id'],
                    'start':segment['begin_position01'],'end':segment['end_position01']})

    def map_window(self, route, physical_edges):
        ids=route.get('edge_ids') or []
        directions=route.get('directions') or []
        transport=route.get('transport_indices') or []
        start=route.get('start_index')
        if not isinstance(start,int) or not ids:
            return {'status':'UNAVAILABLE','scope':'OBSERVED_PATH_WINDOW','full_line_path':False,'steps':[]}
        # Adjacent transport subedges can share one BASE_EDGE entity. Retain
        # their occurrence indices, but do not count the physical edge twice.
        groups=[]
        for i,eid in enumerate(ids):
            if groups and groups[-1]['raw_edge_id']==eid:
                groups[-1]['end_index']=start+i
            else:
                groups.append({'raw_edge_id':eid,'start_index':start+i,'end_index':start+i})
        steps=[]
        ambiguous=0
        for i,group in enumerate(groups):
            raw=physical_edges.get(group['raw_edge_id'])
            entries=set(); exits=set()
            if raw:
                endpoints={raw['node0'],raw['node1']}
                if i:
                    prev=physical_edges.get(groups[i-1]['raw_edge_id'])
                    if prev:entries=endpoints & {prev['node0'],prev['node1']}
                if i+1<len(groups):
                    nxt=physical_edges.get(groups[i+1]['raw_edge_id'])
                    if nxt:exits=endpoints & {nxt['node0'],nxt['node1']}
            candidates=[]
            if raw:
                for forward in (True,False):
                    a,b=(raw['node0'],raw['node1']) if forward else (raw['node1'],raw['node0'])
                    if (not entries or a in entries) and (not exits or b in exits):candidates.append(forward)
            mappings=self.raw.get(group['raw_edge_id'],[])
            if len(candidates)!=1 or not mappings:
                ambiguous+=1
                steps.append({'kind':'unresolved','raw_edge_id':group['raw_edge_id'],
                              'path_index_start':group['start_index'],'path_index_end':group['end_index'],
                              'reason':'DIRECTION_AMBIGUOUS' if mappings else 'RAW_EDGE_NOT_IN_TOPOLOGY'})
                continue
            forward=candidates[0]
            selected=[m for m in mappings if (m['end']>m['start'])==forward]
            selected.sort(key=lambda m:min(m['start'],m['end']),reverse=not forward)
            if not selected:
                ambiguous+=1
                steps.append({'kind':'unresolved','raw_edge_id':group['raw_edge_id'],
                              'path_index_start':group['start_index'],'path_index_end':group['end_index'],
                              'reason':'DIRECTION_NOT_IN_TOPOLOGY'})
                continue
            for mapping in selected:
                step={k:v for k,v in mapping.items() if k not in ('start','end')}
                step.update({'path_index_start':group['start_index'],'path_index_end':group['end_index']})
                key=('edge',step.get('edge_id')) if step['kind']=='edge' else ('station',step['node_id'])
                previous=steps[-1] if steps else {}
                old_key=('edge',previous.get('edge_id')) if previous.get('kind')=='edge' else ('station',previous.get('node_id'))
                if key==old_key:
                    previous['path_index_end']=group['end_index']
                else:steps.append(step)
        return {'status':'PARTIAL' if ambiguous else 'MAPPED_WINDOW','scope':'OBSERVED_PATH_WINDOW',
                'full_line_path':False,'current_path_index':route.get('current_index'),
                'path_index_start':start,'path_index_end':start+len(ids)-1,
                'unresolved_raw_edge_groups':ambiguous,'steps':steps,
                'raw_edge_ids':ids,'raw_transport_directions':directions,'raw_transport_indices':transport,
                'direction_basis':'ADJACENT_PHYSICAL_EDGE_ENDPOINTS',
                'coverage_note':'Window endpoints and transport subedges may cover only part of a physical edge; no shortest-path completion is used.'}


def export_train_routes(repository, line_id, *, vehicle_id=None, clock=time.time,
                        frame_reader=read_train_frame, identity_reader=read_train_identities,
                        footprint_reader=read_train_footprints):
    topology=repository.get_full_network_topology()
    world=repository._read_current('state.json')
    line=next((r for r in world.get('lines',[]) if r.get('entity_id')==line_id),None)
    if line is None:raise ValueError(f'LINE_NOT_FOUND: {line_id}')
    physical=repository._read_current('rail-network.json')
    if physical.get('capture_id')!=topology['capture_id']:
        raise ValueError('ASSET_CAPTURE_CHANGED: retry route export')
    session=(world.get('metadata') or {}).get('session_id')
    if not session or session!=topology.get('session_id'):
        raise ValueError('WORLD_SESSION_MISMATCH: refresh world snapshot')
    index=RouteTopologyIndex(topology)
    stations={s['entity_id']:s for s in physical.get('stations',[])}
    world_names={s['entity_id']:s.get('name') for s in world.get('stations',[])}

    def terminal_ref(station_id, station_index, terminal_index):
        terminal=next((t for t in stations.get(station_id,{}).get('terminals',[])
                       if t.get('station_index')==station_index and t.get('terminal_index')==terminal_index),None)
        return {'station_index':station_index,'terminal_index':terminal_index,
                'platform_number':terminal_index+1 if isinstance(terminal_index,int) else None,
                'platform_number_source':'TERMINAL_INDEX_PLUS_ONE_NOT_CUSTOM_UI_LABEL',
                'game_node_id':terminal.get('node_id') if terminal else None,
                'mapping_status':'MAPPED' if terminal else 'UNAVAILABLE'}
    stops=[]
    for stop in line.get('raw_stops') or line.get('stops',[]):
        sid=stop.get('station_id'); policy=stop.get('policy') or {}
        code,label=LOAD_MODES.get(policy.get('load_mode'),('UNKNOWN','未知'))
        primary=terminal_ref(sid,stop.get('station_index'),stop.get('terminal_id'))
        allowed=[primary] if primary['terminal_index'] is not None else []
        for alt in stop.get('alternative_terminals',[]):
            item=terminal_ref(sid,alt.get('station_index'),alt.get('terminal_id'))
            if item not in allowed:allowed.append(item)
        stops.append({'stop_index':stop.get('sequence_index',stop.get('index')),
                      'station_id':sid,'station_name':world_names.get(sid) or stations.get(sid,{}).get('name'),
                      'topology_station_node_id':index.station_nodes.get(sid),
                      'primary_terminal':primary,'allowed_terminals':allowed,
                      'policy':{'raw_load_mode':policy.get('load_mode'),'load_mode':code,'load_mode_label':label,
                                'min_waiting_time_seconds':policy.get('min_waiting_time'),
                                'max_waiting_time_seconds':policy.get('max_waiting_time'),
                                'cargo_service':stop.get('service'),
                                'waiting_time_note':'Configured waiting limits, not a measured total dwell time.'}})
    frame=frame_reader(); identities={r.entity_id:r for r in identity_reader()}
    payload=footprint_reader()
    if payload.get('session_id')!=topology.get('session_id'):
        raise ValueError('PATH_SESSION_MISMATCH')
    age=clock()-payload.get('generated_at',0)
    footprints={r['entity_id']:r for r in payload.get('vehicles',[])}
    members=[t for t in frame.trains if int(t.line_entity_id)==line_id]
    if not members and line_id not in {r['entity_id'] for r in physical.get('lines',[])}:
        raise ValueError('NOT_A_RAIL_LINE: route mapping supports rail lines only')
    all_ids=[int(t.entity_id) for t in members]
    if vehicle_id is not None and vehicle_id not in all_ids:raise ValueError('VEHICLE_NOT_ON_LINE')
    trains=[]
    physical_edges={e['entity_id']:e for e in physical['edges']}
    for train in members:
        eid=int(train.entity_id)
        if vehicle_id is not None and eid!=vehicle_id:continue
        row=footprints.get(eid,{})
        mapped=index.map_window(row.get('route_window') or {},physical_edges)
        mapped['fresh']=0<=age<=3
        if not mapped['fresh']:mapped['status']='STALE'
        trains.append({'vehicle_id':eid,'display_name':identities[eid].display_name if eid in identities else None,
                       'line_id':line_id,'sample_sequence':int(train.sample_sequence),'observed_route':mapped})
    repository.assert_session(session)
    return {'schema_version':1,'topology_id':topology['topology_id'],'capture_id':topology['capture_id'],
            'session_id':session,'observed_at':clock(),'world_snapshot_timestamp':world.get('timestamp'),
            'world_snapshot_age_seconds':clock()-world.get('timestamp',0),
            'world_snapshot_fresh':0<=clock()-world.get('timestamp',0)<=120,
            'world_snapshot_max_age_seconds':120,
            'line':{'line_id':line_id,'display_name':line.get('name'),'vehicle_ids':all_ids,
                    'frequency_seconds':line.get('frequency_seconds'),'throughput':line.get('throughput'),
                    'stops':stops,'topology_station_sequence':[s['topology_station_node_id'] for s in stops],
                    'stop_order_is_cyclic':True,
                    'platform_number_note':'Platform numbers are 1-based terminal ordinals within station_index, not verified custom UI labels.'},
            'trains':trains,'path_sampled_at':payload.get('generated_at'),'path_age_seconds':age,
            'full_line_track_path_available':False,
            'limitations':['Actual paths are per-train observed windows, not a full-line track assignment.',
                           'Station contraction does not validate ingress-to-egress routes.',
                           'Full load ANY is per cargo type, not per carriage.']}


TRAIN_ROUTES_TOOL = {
    'name':'get_train_routes','title':'获取列车线路与实际路线',
    'description':'按line_id导出铁路线路的名称、全部所属列车vehicle_id（可关联get_train_control_snapshot）、停站顺序、主选/备选站台终端、装载模式及最小/最大等待时间。提供停站对应的拓扑车站序列，以及各列车实际路径窗口映射的有向拓扑边/车站序列。actual路线只覆盖已采窗口，不以最短路伪造全线；无法确定的方向和映射保留unresolved。',
    'inputSchema':{'type':'object','properties':{
        'line_id':{'type':'integer','minimum':1},
        'vehicle_id':{'type':'integer','minimum':1,'description':'可选，仅返回本线路指定列车的实际路径。'}},
        'required':['line_id'],'additionalProperties':False},
    'outputSchema':{'type':'object','properties':{
        'schema_version':{'type':'integer'},'topology_id':{'type':'string'},'capture_id':{'type':'string'},
        'line':{'type':'object'},'trains':{'type':'array','items':{'type':'object'}},
        'full_line_track_path_available':{'type':'boolean'},'limitations':{'type':'array','items':{'type':'string'}}},
        'required':['schema_version','topology_id','capture_id','line','trains','full_line_track_path_available','limitations']},
}
