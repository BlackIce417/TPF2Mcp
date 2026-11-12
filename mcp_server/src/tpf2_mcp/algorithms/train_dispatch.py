"""Dynamic occupancy overlay; never modifies the static topology."""
from dataclasses import asdict, dataclass, field
import math


@dataclass
class TrainDispatchState:
    vehicle_id: int
    display_name: str | None
    topology_id: str | None
    sampled_at: float
    sample_sequence: int
    occupied_section_ids: list[int] = field(default_factory=list)
    occupied_station_ids: list[int] = field(default_factory=list)
    head_section_id: int | None = None
    tail_section_id: int | None = None
    center_section_id: int | None = None
    occupancy_status: str = 'UNKNOWN'
    reasons: list[str] = field(default_factory=list)


class OccupancyIndex:
    """Index raw edge intervals by shared physical section or station wrapper.

    Section IDs are track_resource_id, NOT directed edge IDs. Identical IDs on
    two reverse arcs refer to the same track. IDs only apply to topology_id.
    """
    def __init__(self, topology):
        self.topology_id = topology['topology_id']
        self.sections = {}
        self.intervals = {}
        self.stations = {}
        for edge in topology['edges']:
            resource = edge['track_resource_id']
            self.sections.setdefault(resource, []).append(edge['id'])
            if edge['id'] > edge['reverse_edge_id']:
                continue
            for segment in edge['track_segments']:
                self._add(segment, resource, None)
        for node in topology['nodes']:
            wrapper = node.get('station_wrapper')
            if not wrapper:
                continue
            self.stations[node['id']] = wrapper['entry_id']
            for edge in wrapper['internal_edges']:
                if edge['id'] < edge['reverse_edge_id']:
                    for segment in edge['track_segments']:
                        self._add(segment, None, node['id'])

    def _add(self, segment, section, station):
        a, b = sorted((segment['begin_position01'], segment['end_position01']))
        self.intervals.setdefault(segment['game_edge_id'], []).append((a,b,section,station))

    def locate(self, location):
        if not isinstance(location, dict):
            return set(), set()
        t = location.get('position01')
        if not isinstance(t, (int,float)) or not math.isfinite(t) or not 0 <= t <= 1:
            return set(), set()
        matches = [row for row in self.intervals.get(location.get('edge_id'), [])
                   if row[0]-1e-7 <= t <= row[1]+1e-7]
        return {row[2] for row in matches if row[2] is not None}, {row[3] for row in matches if row[3] is not None}

    def train_state(self, train, *, sampled_at, source_fresh):
        result = TrainDispatchState(train['vehicle_id'], train['display_name'],self.topology_id,
                                    sampled_at,train['sample_sequence'])
        all_sections, all_stations = set(), set()
        for label, field_name in (('head','front_edge'),('tail','rear_edge'),('center','center_edge')):
            sections, stations = self.locate(train['position'].get(field_name))
            setattr(result,label+'_section_id',next(iter(sections)) if len(sections)==1 and not stations else None)
            all_sections.update(sections)
            all_stations.update(stations)
        result.occupied_section_ids = sorted(all_sections)
        result.occupied_station_ids = sorted(all_stations)
        # Point locations are positive observations, not proof of complete body
        # coverage. Even two endpoints cannot prove the connecting route.
        if all_sections or all_stations:
            result.occupancy_status = 'PARTIAL' if source_fresh else 'UNKNOWN'
        if not train['position'].get('front_edge'):
            result.reasons.append('HEAD_TRACK_LOCATION_UNAVAILABLE')
        if not train['position'].get('rear_edge'):
            result.reasons.append('TAIL_TRACK_LOCATION_UNAVAILABLE')
        result.reasons.append('FULL_BODY_ROUTE_COVERAGE_UNVERIFIED')
        if not source_fresh:
            result.reasons.append('TELEMETRY_FRESHNESS_UNVERIFIED')
        if not all_sections and not all_stations:
            result.reasons.append('TRACK_LOCATION_NOT_MAPPED')
        return asdict(result)

    def overlay(self, trains, *, sampled_at, source_fresh, fleet_complete):
        for train in trains:
            train['dispatch'] = self.train_state(train,sampled_at=sampled_at,source_fresh=source_fresh)
        complete = fleet_complete and all(t['dispatch']['occupancy_status']=='CONFIRMED' for t in trains)
        sections = []
        for section_id, arc_ids in sorted(self.sections.items()):
            occupants = [{'vehicle_id':t['vehicle_id'],'display_name':t['display_name']}
                         for t in trains if section_id in t['dispatch']['occupied_section_ids']]
            sections.append({'section_id':section_id,'directed_edge_ids':sorted(arc_ids),
                             'occupying_trains':occupants,
                             'status':'OCCUPIED' if occupants and source_fresh else 'CLEAR' if complete else 'UNKNOWN'})
        return sections, complete
