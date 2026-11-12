"""demand business service."""
from copy import deepcopy
import time
from tpf2_mcp.transport.bridge import BridgeError
from tpf2_mcp.services.dispatch import station_waiting_state
from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient
from tpf2_mcp.repositories.snapshot import SnapshotIndex

class DemandService:
    def __init__(self, repository, *, client=None, clock=time.time):
        self.repository = repository
        self.client = client or LoaderLuaCommandClient.for_simulation()
        self.clock = clock
        self._cache = {}

    def _read(self, section, params, session):
        result = self.client.call('get_operational_telemetry', {'section':section,**params}, expected_session=session)
        if not isinstance(result,dict) or result.get('status') == 'ERROR':
            raise BridgeError(f'DEMAND_COLLECTION_FAILED: {result}')
        if result.get('session_id') != session:
            raise BridgeError('DEMAND_SESSION_MISMATCH')
        sampled = result.get('generated_at')
        if not isinstance(sampled,(int,float)) or not 0 <= self.clock()-sampled <= 10:
            raise BridgeError('DEMAND_SAMPLE_STALE')
        self.repository.assert_session(session)
        return result

    def _line_raw(self, line_id, maximum, session, force):
        key = session,line_id,maximum
        cached = self._cache.get(key)
        if not force and cached and 0 <= self.clock()-cached['generated_at'] <= 2:
            self.repository.assert_session(session)
            return deepcopy(cached)
        result = self._read('line_demand',{'line_id':line_id,'maximum_entities':maximum},session)
        if result.get('line_id') != line_id or not result.get('line_metadata',{}).get('available'):
            raise BridgeError('LINE_DEMAND_METADATA_UNAVAILABLE')
        if not any(self._available(result,kind) for kind in ('passengers','cargo')):
            raise BridgeError('LINE_DEMAND_UNAVAILABLE: '+str(result.get('errors')))
        self._cache = {k:v for k,v in self._cache.items() if k[0]==session and 0<=self.clock()-v['generated_at']<=2}
        self._cache[key] = deepcopy(result)
        return result

    @staticmethod
    def _available(raw,kind):
        bucket = raw.get(kind)
        errors = raw.get('errors') or {}
        if not isinstance(errors,dict) or any(value for key,value in errors.items() if key not in ('persons','cargo')):
            return False
        return (not errors.get('persons' if kind=='passengers' else 'cargo')
                and isinstance(bucket,dict) and bucket.get('status')!='UNAVAILABLE'
                and all(isinstance(bucket.get(k),int) and not isinstance(bucket[k],bool) and bucket[k]>=0 for k in ('waiting','onboard')))

    @staticmethod
    def _signature(line):
        stops = line.get('raw_stops')
        if stops is not None:
            return [(s.get('sequence_index'),s.get('station_id')) for s in stops]
        return [(s.get('stop_index'),s.get('station_id')) for s in line.get('stops',[])]

    def _normalize_line(self, raw, world):
        names = {s['entity_id']:s.get('name') for s in world.get('stations',[])}
        cargo_types = {c['cargo_id']:c for c in world.get('cargo_types',[])}
        stops = raw['line_metadata']['stops']
        stop_ids = {s['stop_index'] for s in stops if s.get('station_id') in names}
        result = deepcopy(raw)
        result.update(schema_version=3,source='tpf2_loader_shared_memory',sampled_at=raw['generated_at'],
                      sample_age_seconds=round(self.clock()-raw['generated_at'],3),
                      scope='LINE_ASSIGNED_ENTITIES',cargo_amount_unit='SIM_CARGO_ENTITY_COUNT',
                      cargo_physical_unit_verified=False)
        result.pop('generated_at',None)
        result['line'] = {'line_id':raw['line_id'],'display_name':raw['line_metadata'].get('display_name')}
        result['stops'] = []
        result['quality'] = {}
        for kind in ('passengers','cargo'):
            bucket = result.get(kind) or {}
            available = self._available(raw,kind)
            mapped = sum(j.get('waiting',0) for j in bucket.get('by_journey',[]) if j.get('line_stop_0') in stop_ids)
            unknown = max(0,bucket.get('waiting',0)-mapped) if available else None
            classified=bucket.get('classified')
            source_count_complete=(isinstance(classified,int) and classified==bucket.get('total_for_line')
                and classified==sum(bucket.get(k,0) for k in ('waiting','onboard','other')))
            complete = available and not bucket.get('truncated',False) and source_count_complete
            bucket['available'] = available
            if not available:
                bucket.update(waiting=None,onboard=None,average_waiting_seconds=None)
            result[kind] = bucket
            result['quality'][kind] = {'available':available,'complete':complete,
                'waiting_station_attribution_complete':complete and unknown==0,'unmapped_waiting':unknown,
                'truncated':bucket.get('truncated',False),'classification_complete':source_count_complete}
            if kind=='cargo':
                result['quality'][kind]['type_classification_complete']=available and bucket.get('cargo_type_unknown',0)==0
                for cargo in bucket.get('by_cargo',[]):
                    info=cargo_types.get(cargo.get('cargo_id'),{})
                    cargo.update(cargo_name=info.get('display_name'),cargo_key=info.get('cargo_key'))
        for stop in stops:
            row = {**stop,'station_name':names.get(stop.get('station_id'))}
            for kind in ('passengers','cargo'):
                bucket=result[kind]
                journeys=[j for j in bucket.get('by_journey',[]) if j.get('line_stop_0')==stop['stop_index']]
                row[kind+'_waiting']=sum(j.get('waiting',0) for j in journeys) if bucket['available'] else None
                if kind=='cargo':
                    amounts={}
                    for journey in journeys:
                        for cargo in journey.get('by_cargo',[]):
                            cid=cargo['cargo_id'];amounts[cid]=amounts.get(cid,0)+cargo.get('waiting',0)
                    row['cargo_by_type']=[{'cargo_id':cid,'cargo_name':cargo_types.get(cid,{}).get('display_name'),'waiting':n} for cid,n in sorted(amounts.items())]
            result['stops'].append(row)
        vehicle_names={v['entity_id']:v.get('name') for v in world.get('vehicles',[])}
        onboard_ids={int(key) for kind in ('passengers','cargo') for key in (result[kind].get('vehicles') or {})}
        fleet_ids={v['entity_id'] for v in world.get('vehicles',[]) if v.get('line_id')==raw['line_id']}|onboard_ids
        result['vehicles']=[{'vehicle_id':eid,'display_name':vehicle_names.get(eid),
            'passengers_onboard':(result['passengers'].get('vehicles') or {}).get(str(eid),0) if result['passengers']['available'] else None,
            'cargo_onboard':(result['cargo'].get('vehicles') or {}).get(str(eid),0) if result['cargo']['available'] else None} for eid in sorted(fleet_ids)]
        result['limitations']=['Counts cover line-assigned entities only; unassigned station inventory is not collected.',
            'A truncated count is a scanned subset, not an exact total. Unmapped waiting entities cannot be assigned to a station.',
            'Waiting and onboard values are observations, not predicted arrivals or guaranteed boarding.']
        return result

    def call(self,name,args):
        allowed={'get_cargo_types':set(),'get_line_demand':{'line_id','maximum_entities','force_refresh'},
                 'get_station_waiting_state':{'station_id','line_id','maximum_entities','force_refresh'}}[name]
        if not isinstance(args,dict) or set(args)-allowed: raise ValueError('INVALID_ARGUMENTS')
        maximum=args.get('maximum_entities',20000);force=args.get('force_refresh',False)
        if not isinstance(maximum,int) or isinstance(maximum,bool) or not 100<=maximum<=50000:raise ValueError('maximum_entities must be integer 100..50000')
        if not isinstance(force,bool):raise ValueError('force_refresh must be boolean')
        for key in ('line_id','station_id'):
            if key in args and (not isinstance(args[key],int) or isinstance(args[key],bool) or args[key]<=0):raise ValueError(key+' must be a positive integer')
        if name=='get_line_demand' and 'line_id' not in args:raise ValueError('line_id required')
        if name=='get_station_waiting_state' and 'station_id' not in args:raise ValueError('station_id required')
        world=self.repository._read_current('state.json');session=world['metadata']['session_id']
        if name=='get_cargo_types':
            status=(world['metadata'].get('collector_status') or {}).get('cargo_types') or {}
            if status.get('ok') is False:raise BridgeError('CARGO_TYPES_UNAVAILABLE')
            items=world.get('cargo_types')
            if not isinstance(items,list):raise BridgeError('CARGO_TYPES_UNAVAILABLE')
            return {'schema_version':1,'session_id':session,'snapshot_timestamp':world.get('timestamp'),'items':items,'total':len(items)}
        if name=='get_line_demand':
            if not any(l['entity_id']==args['line_id'] for l in world.get('lines',[])):raise BridgeError('LINE_NOT_FOUND')
            result=self._normalize_line(self._line_raw(args['line_id'],maximum,session,force),world)
            self.repository.assert_session(session)
            return result
        return self._station(args,world,maximum,force)

    def _station(self,args,world,maximum,force):
        station_id=args['station_id'];session=world['metadata']['session_id']
        station=next((s for s in world.get('stations',[]) if s['entity_id']==station_id),None)
        if station is None:raise BridgeError('STATION_NOT_FOUND: use a station group ID')
        discovery=self._read('station_demand_lines',{'station_id':station_id},session)
        lines=discovery['lines']
        if 'line_id' in args:
            lines=[l for l in lines if l['entity_id']==args['line_id']]
            if not lines:raise BridgeError('LINE_NOT_CONNECTED_TO_STATION')
        demands={};normalized={}
        for line in lines:
            lid=line['entity_id']
            try:
                raw=self._line_raw(lid,maximum,session,force)
                if self._signature(line)!=self._signature(raw['line_metadata']):
                    raw=self._line_raw(lid,maximum,session,True)
                if self._signature(line)!=self._signature(raw['line_metadata']):raise BridgeError('LINE_ROUTE_CHANGED_DURING_COLLECTION')
                normalized[lid]=self._normalize_line(raw,world)
                valid_origins={s['stop_index'] for s in raw['line_metadata']['stops'] if s.get('station_id') in {w['entity_id'] for w in world.get('stations',[])}}
                filtered=deepcopy(raw)
                for kind in ('passengers','cargo'):
                    if not self._available(raw,kind):
                        filtered[kind]={'status':'UNAVAILABLE'}
                    elif isinstance(filtered.get(kind),dict):
                        filtered[kind]['by_journey']=[j for j in filtered[kind].get('by_journey',[]) if j.get('line_stop_0') in valid_origins]
                demands[lid]=filtered
            except BridgeError as exc:
                demands[lid]={'errors':{'collector':str(exc)},'passengers':{'status':'UNAVAILABLE'},'cargo':{'status':'UNAVAILABLE'}}
        check=self._read('station_demand_lines',{'station_id':station_id},session)
        before={l['entity_id']:self._signature(l) for l in discovery['lines']}
        after={l['entity_id']:self._signature(l) for l in check['lines']}
        if before!=after:raise BridgeError('STATION_CONNECTIONS_CHANGED: retry station query')
        index=SnapshotIndex({**world,'lines':lines})
        waiting=station_waiting_state(index,station_id,demands)
        for row in waiting['lines']:
            value=normalized.get(row['line_id'])
            row['sampled_at']=value['sampled_at'] if value else None
            row['stops']=[s for s in value['stops'] if s.get('station_id')==station_id] if value else []
            amounts={}
            for stop in row['stops']:
                for cargo in stop.get('cargo_by_type',[]):
                    key=cargo['cargo_id']
                    if key not in amounts:amounts[key]={'cargo_id':key,'cargo_name':cargo.get('cargo_name'),'waiting':0}
                    amounts[key]['waiting']+=cargo['waiting']
            row['cargo_by_type']=[amounts[key] for key in sorted(amounts)]
            row['cargo_type_unknown_waiting']=max(0,row['cargo_waiting']-sum(v['waiting'] for v in amounts.values())) if row['cargo_waiting'] is not None else None
            row['quality']=value['quality'] if value else {'available':False}
            if value and not all(value['quality'][kind]['waiting_station_attribution_complete'] for kind in ('passengers','cargo')):
                row['complete']=False
                waiting['quality']['complete']=False
        if not lines:
            waiting['source_status']='ENGINE_OBSERVED_NO_ASSIGNED_LINES'
            waiting['quality']['complete']=True
        sampled=[value['sampled_at'] for value in normalized.values()]
        self.repository.assert_session(session)
        return {'schema_version':1,'session_id':session,'station':station,'waiting':waiting,
                'sampled_at_start':min(sampled) if sampled else discovery['generated_at'],
                'sampled_at_end':max(sampled) if sampled else check['generated_at'],
                'observed_at':self.clock(),'atomic_snapshot':False,'line_filter':args.get('line_id'),
                'cargo_amount_unit':'SIM_CARGO_ENTITY_COUNT','cargo_physical_unit_verified':False}
