"""Independent junction candidate recognition from a prepared rail network.

Station throats are an upstream exclusion mask, not proof of station limits.
All direction groups and classifications are derived evidence, not railway names.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import heapq
import math

from tpf2_mcp.algorithms.rail_topology import RailGraph, topology_id
from tpf2_mcp.algorithms.station_throats import identify_station_throats
from tpf2_mcp.algorithms.junction_sites import build_sites

ALGORITHM_VERSION = 'junctions-v3'


@dataclass(frozen=True)
class JunctionConfig:
    switch_gap_m: float = 250.
    cluster_radius_m: float = 600.
    branch_probe_m: float = 1200.
    corridor_angle_deg: float = 30.
    destination_probe_m: float = 20000.

    def validate(self):
        if not all(math.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError('junction thresholds must be finite and positive')
        if self.corridor_angle_deg >= 90 or self.cluster_radius_m < self.switch_gap_m:
            raise ValueError('angle must be <90 and cluster radius >= switch gap')


def _station_mask(network, throats, graph):
    owners = {cid for s in network.get('stations', []) for cid in s.get('construction_entity_ids', [])}
    edges = {eid for s in network.get('stations', []) for t in s.get('terminals', [])
             for eid in t.get('platform_edge_ids', []) if eid in graph.edges}
    edges.update(eid for eid, e in graph.edges.items() if e.get('construction_entity_id') in owners)
    nodes = {t['node_id'] for s in network.get('stations', []) for t in s.get('terminals', []) if t.get('node_id') in graph.nodes}
    for region in throats['regions']:
        edges.update(region['edge_ids']); nodes.update(region['switch_node_ids'])
    nodes.update(graph.edges[eid][k] for eid in edges for k in ('node0', 'node1'))
    return nodes, edges


def _direction_groups(ports, angle):
    """Complete-link grouping: parallel tracks count once, opposite directions do not."""
    groups = []
    def difference(a, b):
        return abs((a-b+180) % 360-180)
    for port in sorted(ports, key=lambda p: p['id']):
        heading = port['heading_deg']
        if heading is None:
            continue
        group = next((g for g in groups if all(difference(heading, p['heading_deg']) <= angle for p in g)), None)
        if group is None:
            groups.append([port])
        else:
            group.append(port)
    return [{'id': f'direction-{i+1}', 'port_ids': [p['id'] for p in g]} for i, g in enumerate(groups)]


def _add_destination_evidence(network, graph, regions, throats, station_nodes, station_edges, depot_edges, config):
    """Audit beyond the display window; geometry alone cannot distinguish shallow forks."""
    station_at = {}
    station_names = {s['entity_id']: s.get('name', str(s['entity_id'])) for s in network.get('stations', [])}
    for station in network.get('stations', []):
        for terminal in station.get('terminals', []):
            for eid in terminal.get('platform_edge_ids', []):
                if eid in graph.edges:
                    for key in ('node0', 'node1'):
                        station_at.setdefault(graph.edges[eid][key], set()).add(station['entity_id'])
    for throat in throats['regions']:
        nodes = set(throat['switch_node_ids']) | {graph.edges[eid][k] for eid in throat['edge_ids'] for k in ('node0', 'node1')}
        for node in nodes:
            station_at.setdefault(node, set()).update(throat['station_group_ids'])
    region_at = {node: r['id'] for r in regions for node in r['switch_node_ids']}
    for region in regions:
        destinations = {}
        for port in region['ports']:
            path, end, length, reason = graph.walk(port['node_id'], port['outside_edge_id'], config.destination_probe_m,
                                                   station_nodes, station_edges, depot_edges)
            key, label = None, None
            if reason == 'STATION_BOUNDARY' and station_at.get(end):
                key = 'station:' + ','.join(map(str, sorted(station_at[end])))
                label = ' / '.join(station_names.get(s, str(s)) for s in sorted(station_at[end]))
            elif reason == 'SWITCH' and end in region_at and region_at[end] != region['id']:
                key = region_at[end]
                label = key
            port['destination'] = dict(key=key, label=label, stop_reason=reason, node_id=end, distance_m=round(length,3), edge_ids=path)
            if key: destinations.setdefault(key, []).append(port['id'])
        region['destination_groups'] = [dict(destination=key, port_ids=ids) for key, ids in sorted(destinations.items())]
        region['geometric_classification'] = region['classification']
        if len(destinations) >= 3:
            region['classification'] = 'JUNCTION_CANDIDATE'
            region['evidence'].append('THREE_DISTINCT_TOPOLOGICAL_DESTINATIONS')
            if len(region['through_direction_groups']) < 3:
                region['flags'].append('SHALLOW_FORK_MERGED_BY_ANGLE')
        region['parallel_peer_ids'] = []
    # Suggest peers only; never invent a traversable connection across separate tracks.
    def compatible(a, b):
        if len(a['ports']) != len(b['ports']): return False
        def center(r):
            return tuple(sum(graph.nodes[n]['position'].get(k,0) for n in r['switch_node_ids'])/len(r['switch_node_ids']) for k in ('x','y','z'))
        ca, cb = center(a), center(b)
        if math.dist(ca[:2],cb[:2]) > 30 or abs(ca[2]-cb[2]) > 3: return False
        headings = [p['heading_deg'] for p in b['ports']]
        for port in a['ports']:
            if port['heading_deg'] is None or any(h is None for h in headings): return False
            best = min(range(len(headings)), key=lambda i: abs((headings[i]-port['heading_deg']+180)%360-180))
            if abs((headings[best]-port['heading_deg']+180)%360-180) > 15: return False
            headings.pop(best)
        return True
    for i, a in enumerate(regions):
        for b in regions[i+1:]:
            if compatible(a,b):
                a['parallel_peer_ids'].append(b['id']); b['parallel_peer_ids'].append(a['id'])
    for region in regions:
        if region['parallel_peer_ids']: region['flags'].append('POSSIBLE_PARALLEL_HALF')


def identify_junctions(network: dict, config: JunctionConfig | None = None) -> dict:
    config = config or JunctionConfig(); config.validate()
    graph = RailGraph(network)
    throats = identify_station_throats(network)
    station_nodes, station_edges = _station_mask(network, throats, graph)
    switches = {n for n, adj in graph.adjacency.items() if len(adj) > 2 and n not in station_nodes}
    depot_edges = {d['nearest_edge_id'] for d in network.get('depots', [])
                   if d.get('track_connection_source') and d.get('nearest_edge_id') in graph.edges
                   and d.get('rail_assigned_vehicle_count', 0) > 0}
    links = {n: [] for n in switches}
    for node in sorted(switches):
        for eid, _ in graph.adjacency[node]:
            path, end, distance, reason = graph.walk(node, eid, config.switch_gap_m, station_nodes, station_edges, depot_edges)
            if reason == 'SWITCH' and end in switches:
                links[node].append((end, path, distance))
    remaining, regions = set(switches), []
    while remaining:
        seed = min(remaining); members = {seed}; queue = [(0., seed)]; distances = {seed: 0.}
        # Radius bound prevents arbitrarily long chains becoming one junction.
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            for end, _, length in links[node]:
                candidate = distance + length
                if end in remaining and candidate <= config.cluster_radius_m and candidate < distances.get(end, math.inf):
                    distances[end] = candidate; members.add(end); heapq.heappush(queue, (candidate, end))
        remaining -= members
        internal = {eid for node in members for end, path, _ in links[node] if end in members for eid in path}
        ports, context = [], set(internal)
        for node in sorted(members):
            for eid, _ in graph.adjacency[node]:
                if eid in internal:
                    continue
                path, end, length, reason = graph.walk(node, eid, config.branch_probe_m, station_nodes, station_edges, depot_edges)
                context.update(path)
                # Use outward tangent when the first long edge exceeds the probe budget.
                samples = graph.samples(eid)
                if graph.edges[eid]['node1'] == node:
                    samples.reverse()
                a = graph.nodes[node]['position']; b = graph.nodes[end]['position']
                dx, dy = b['x']-a['x'], b['y']-a['y']
                if math.hypot(dx, dy) < 1e-6:
                    dx, dy = samples[1][0]-samples[0][0], samples[1][1]-samples[0][1]
                heading = math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) > 1e-6 else None
                ports.append(dict(id=f'port-{node}-{eid}', node_id=node, outside_edge_id=eid,
                                  position=a, probe_edge_ids=path, end_node_id=end, probe_length_m=round(length, 3),
                                  stop_reason=reason, heading_deg=heading))
        groups = _direction_groups(ports, config.corridor_angle_deg)
        through_ports = [p for p in ports if p['stop_reason'] not in ('DEAD_END', 'DEPOT_CONNECTION', 'LOOP')]
        through_groups = _direction_groups(through_ports, config.corridor_angle_deg)
        reasons = {p['stop_reason'] for p in ports}
        flags = []
        if 'STATION_BOUNDARY' in reasons: flags.append('NEAR_STATION_BOUNDARY')
        if any(end not in members for n in members for end, _, _ in links[n]): flags.append('CLUSTER_SIZE_LIMIT')
        if 'LOOP' in reasons: flags.append('LOOP_BRANCH')
        if 'DEPOT_CONNECTION' in reasons: flags.append('HAS_DEPOT_BRANCH')
        if 'DEAD_END' in reasons: flags.append('HAS_DEAD_END_BRANCH')
        if len(through_groups) >= 3:
            kind = 'JUNCTION_CANDIDATE'
        elif len(through_groups) == 2 and len(through_ports) >= 4:
            kind = 'CROSSOVER_CANDIDATE'
        elif 'DEPOT_CONNECTION' in reasons:
            kind = 'DEPOT_ACCESS'
        elif 'DEAD_END' in reasons:
            kind = 'SIDING_OR_UNFINISHED'
        else:
            kind = 'UNRESOLVED_SWITCH_GROUP'
        if not internal: flags.append('SINGLE_SWITCH_NO_INTERNAL_EDGE')
        if any(len(graph.adjacency[node]) > 3 for node in members): flags.append('MULTIWAY_NODE_ROUTE_UNKNOWN')
        region_id = f'junction-{seed}'
        regions.append(dict(id=region_id, suggested_name=f'道岔组 {seed}', classification=kind,
                            status='REVIEW_REQUIRED', switch_node_ids=sorted(members), edge_ids=sorted(internal),
                            ports=ports, direction_groups=groups, through_direction_groups=through_groups, flags=flags,
                            evidence=['OUTSIDE_STATION_MASK', 'CONNECTED_SWITCH_CLUSTER', 'GEOMETRIC_DIRECTION_GROUPS'],
                            route_validation='NOT_PERFORMED', context_edge_ids=sorted(context)))
    _add_destination_evidence(network, graph, regions, throats, station_nodes, station_edges, depot_edges, config)
    missing_core = [s['entity_id'] for s in network.get('stations', [])
                    if not any(t.get('platform_edge_ids') for t in s.get('terminals', []))]
    quality = dict(stations_without_core=missing_core, unresolved_throat_stations=throats['unresolved_stations'],
                   station_mask_is_heuristic=True)
    sites, classifications = build_sites(regions, quality, graph)
    return dict(schema_version=1, algorithm_version=ALGORITHM_VERSION, save_id=network.get('save_id'),
                topology_id=topology_id(network), parameters=asdict(config), game_write=False,
                regions=regions, sites=sites, station_mask=dict(edge_ids=sorted(station_edges), node_ids=sorted(station_nodes)),
                quality=quality,
                counts=dict(outside_switches=len(switches), regions=len(regions), sites=len(sites),
                            planning_ready_sites=0, classifications=classifications),
                limitations=['Geometric directions are not named railway lines.',
                             'Station mask may hide adjoining junctions or leave long throats outside.',
                             'Depot detection requires observed rail-depot evidence; absence is not proof.',
                             'IDs are scoped to save_id and survive only while switch entities remain unchanged.'])
