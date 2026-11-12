"""Station wrappers containing terminal tracks and bounded switch groups.

Works on the signal-split topology. Boundaries are physical interfaces, not
permission to route between arbitrary station ports.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import math
from typing import Any
from dataclasses import replace

from tpf2_mcp.algorithms.generate_topology.gen_topology import NetworkTopology, NodeType, generate_topology

DEFAULT_SIGNAL_SEARCH_M = 500.0


@dataclass
class StationBoundary:
    node_id: int
    throat_node_id: int
    outside_edge_ids: list[int]
    reason: str
    signal_ids: list[int] = field(default_factory=list)
    signal_distance_m: float | None = None
    search_stop_reason: str = ""

@dataclass
class StationTopologyNode:
    station_name: str
    entry_id: int
    terminal_node_ids: list[int] = field(default_factory=list)
    switch_node_ids: list[int] = field(default_factory=list)
    internal_node_ids: list[int] = field(default_factory=list)
    internal_edge_ids: list[int] = field(default_factory=list)
    boundaries: list[StationBoundary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    contested_node_ids: list[int] = field(default_factory=list)
    route_validation: str = "NOT_PERFORMED"
    signal_search_m: float = DEFAULT_SIGNAL_SEARCH_M
    station_ids: list[int] = field(default_factory=list)
    station_group_names: dict[int, str] = field(default_factory=dict)
    overlap_resolution: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_throat_range(
    topology: NetworkTopology,
    station_id: int,
    station_name: str | None = None,
    *,
    signal_search_m: float = DEFAULT_SIGNAL_SEARCH_M,
    approach_limit_m: float = 800.0,
    switch_gap_m: float = 250.0,
    station_ids: set[int] | None = None,
) -> StationTopologyNode:
    """Expand terminal approaches, switch clusters, then inbound signals.

    Each external interface searches independently. A missing/unverified inbound
    signal within signal_search_m falls back to the switch-group interface;
    the unsuccessful search path is NOT included in the station.
    """
    if any(not math.isfinite(x) or x <= 0 for x in (signal_search_m, approach_limit_m, switch_gap_m)):
        raise ValueError('search distances must be finite and positive')
    nodes, edges = topology.nodes, topology.edges
    own_ids = set(station_ids) if station_ids is not None else {station_id}
    own_ids.add(station_id)
    seeds = {nid for nid, n in nodes.items() if own_ids.intersection(n.station_ids)}
    result = StationTopologyNode(station_name or str(station_id), station_id,
                                 terminal_node_ids=sorted(seeds), signal_search_m=signal_search_m,
                                 station_ids=sorted(own_ids))
    if not seeds:
        result.warnings.append('TERMINAL_NODES_UNAVAILABLE')
        return result

    def foreign(nid):
        return bool(set(nodes[nid].station_ids) - own_ids)

    def is_switch(nid):
        return (nodes[nid].type == NodeType.SWITCH or len(topology.outgoing[nid]) > 2
                or nodes[nid].boundary_kind in ('branch_candidate', 'switch_candidate'))

    def walk(first, limit, *, stop_at_signals=False):
        path, distance, arc = [], 0.0, edges[first]
        seen = {arc.from_node_id}
        while True:
            end = arc.to_node_id
            if distance + arc.length_m > limit + 1e-8:
                return path, arc.from_node_id, distance, 'DISTANCE_LIMIT', []
            if foreign(end):
                return path, arc.from_node_id, distance, 'OTHER_STATION', []
            path.append(arc.id)
            distance += arc.length_m
            if end in seen:
                return path, end, distance, 'LOOP', []
            seen.add(end)
            node = nodes[end]
            if stop_at_signals and node.signal_ids:
                # Last raw segment is oriented from station toward outside.
                # The entry signal must face the opposite direction.
                segment = arc.track_segments[-1] if arc.track_segments else None
                inbound = []
                if segment:
                    outward = segment['end_position01'] > segment['begin_position01']
                    for binding in node.signal_bindings:
                        if (binding.get('edge_id') == segment['game_edge_id']
                                and binding.get('direction_status') == 'ENGINE_QUERY_CONFIRMED'
                                and (not outward) in binding.get('directions', [])):
                            inbound.append(binding['entity_id'])
                if inbound:
                    return path, end, distance, 'ENTRY_SIGNAL', sorted(set(inbound))
            if end in seeds:
                return path, end, distance, 'OWN_TERMINAL', []
            if is_switch(end):
                return path, end, distance, 'SWITCH', []
            options = [eid for eid in topology.outgoing[end] if eid != arc.reverse_edge_id]
            if len(options) != 1:
                return path, end, distance, 'ENDPOINT' if not options else 'BRANCH', []
            arc = edges[options[0]]

    included, switches, members = set(), set(), set(seeds)

    def include(path):
        for eid in path:
            arc = edges[eid]
            included.update((eid, arc.reverse_edge_id))
            members.update((arc.from_node_id, arc.to_node_id))

    for seed in sorted(seeds):
        if is_switch(seed):
            switches.add(seed)
        for eid in topology.outgoing[seed]:
            path, end, _, reason, _ = walk(eid, approach_limit_m)
            if reason in ('SWITCH', 'OWN_TERMINAL', 'ENDPOINT'):
                include(path)
            if reason == 'SWITCH':
                switches.add(end)
    pending, expanded = sorted(switches), set()
    while pending:
        switch = pending.pop()
        if switch in expanded:
            continue
        expanded.add(switch)
        members.add(switch)
        for eid in topology.outgoing[switch]:
            path, end, _, reason, _ = walk(eid, switch_gap_m)
            if reason in ('SWITCH', 'OWN_TERMINAL', 'ENDPOINT'):
                include(path)
            if reason == 'SWITCH' and end not in expanded:
                switches.add(end)
                pending.append(end)
    if not switches:
        result.warnings.append('NO_SWITCH_GROUP_FOUND: boundaries may be terminal fallbacks')
    result.warnings.append('SWITCH_GROUP_HEURISTIC: approach and switch-gap limits apply')

    # Snapshot interfaces before extending successful signal searches.
    interfaces = [(nid, eid) for nid in sorted(members)
                  for eid in topology.outgoing[nid] if eid not in included]
    for root, eid in interfaces:
        if eid in included:
            continue
        path, end, distance, reason, signal_ids = walk(eid, signal_search_m, stop_at_signals=True)
        if reason == 'ENTRY_SIGNAL':
            include(path)
            outside = [x for x in topology.outgoing[end] if x != edges[path[-1]].reverse_edge_id]
            result.boundaries.append(StationBoundary(end, root, sorted(outside), 'ENTRY_SIGNAL',
                                                       signal_ids, distance, reason))
        else:
            result.boundaries.append(StationBoundary(root, root, [eid], 'SWITCH_GROUP_END_FALLBACK',
                                                       search_stop_reason=reason))
    result.switch_node_ids = sorted(switches)
    result.internal_node_ids = sorted(members)
    result.internal_edge_ids = sorted(included)
    return result


def generate_station_topology_nodes(
    raw_network: dict[str, Any], raw_signals: dict[str, Any] | None = None,
    *, topology: NetworkTopology | None = None, **limits,
) -> list[StationTopologyNode]:
    """Build station wrappers; report shared claims instead of hiding conflicts."""
    topology = topology if topology is not None else generate_topology(raw_network, raw_signals, collapse_stations=False)
    # Passenger/freight station groups in the SAME construction share a physical
    # station. Names alone are not evidence: unrelated stations may share names.
    rows = sorted(raw_network.get('stations', []), key=lambda r: r['entity_id'])
    parents = {row['entity_id']: row['entity_id'] for row in rows}
    def find(sid):
        while parents[sid] != sid:
            parents[sid] = parents[parents[sid]]
            sid = parents[sid]
        return sid
    buildings = {}
    for row in rows:
        constructions = set(row.get('construction_entity_ids') or [])
        constructions.update(t['construction_entity_id'] for t in row.get('terminals', [])
                             if t.get('construction_entity_id'))
        for building in sorted(c for c in constructions if c):
            if building in buildings:
                a, b = find(row['entity_id']), find(buildings[building])
                parents[max(a, b)] = min(a, b)
            else:
                buildings[building] = row['entity_id']
    groups = {}
    for row in rows:
        groups.setdefault(find(row['entity_id']), []).append(row)
    wrappers = []
    for group in groups.values():
        names = {row['entity_id']: row.get('name') or str(row['entity_id']) for row in group}
        wrapper = calculate_throat_range(topology, group[0]['entity_id'],
            ' / '.join(dict.fromkeys(names.values())), station_ids=set(names), **limits)
        wrapper.station_group_names = names
        wrappers.append(wrapper)
    claims: dict[int, set[int]] = {}
    for wrapper in wrappers:
        for nid in wrapper.internal_node_ids:
            claims.setdefault(nid, set()).add(wrapper.entry_id)
    for wrapper in wrappers:
        wrapper.contested_node_ids = [nid for nid in wrapper.internal_node_ids if len(claims[nid]) > 1]
        if wrapper.contested_node_ids:
            wrapper.warnings.append('STATION_BOUNDARY_OVERLAP: manual review required')
    return wrappers


def _retain_exclusive_interiors(topology: NetworkTopology, wrappers: list[StationTopologyNode]) -> None:
    """Keep disputed track explicit; never assign it by station iteration order."""
    for wrapper in wrappers:
        if not wrapper.contested_node_ids:
            continue
        disputed = set(wrapper.contested_node_ids)
        if disputed.intersection(wrapper.terminal_node_ids):
            wrapper.overlap_resolution = 'SHARED_TERMINAL_UNCOLLAPSED'
            wrapper.warnings.append('STATION_COLLAPSE_SKIPPED: shared terminal ownership is unresolved')
            continue
        allowed = set(wrapper.internal_node_ids) - disputed
        original_edges = set(wrapper.internal_edge_ids)
        retained = set(wrapper.terminal_node_ids)
        pending = list(sorted(retained))
        while pending:
            nid = pending.pop()
            for eid in topology.outgoing[nid]:
                target = topology.edges[eid].to_node_id
                if eid in original_edges and target in allowed and target not in retained:
                    retained.add(target)
                    pending.append(target)
        internal = {eid for eid in original_edges if topology.edges[eid].from_node_id in retained
                    and topology.edges[eid].to_node_id in retained}
        old_boundaries = {(b.node_id, eid): b for b in wrapper.boundaries for eid in b.outside_edge_ids}
        boundaries = []
        for nid in sorted(retained):
            for eid in sorted(topology.outgoing[nid]):
                if eid in internal:
                    continue
                old = old_boundaries.get((nid, eid))
                boundaries.append(replace(old, outside_edge_ids=[eid]) if old else
                    StationBoundary(nid, nid, [eid], 'SHARED_AREA_BOUNDARY',
                                    search_stop_reason='SHARED_STATION_THROAT'))
        wrapper.internal_node_ids = sorted(retained)
        wrapper.internal_edge_ids = sorted(internal)
        wrapper.switch_node_ids = sorted(set(wrapper.switch_node_ids) & retained)
        wrapper.boundaries = boundaries
        wrapper.overlap_resolution = 'SHARED_AREA_EXTERNAL'
        wrapper.warnings.append('SHARED_THROAT_RETAINED: disputed tracks remain explicit outside station wrappers')


def collapse_station_nodes(topology: NetworkTopology, raw_network: dict[str, Any]) -> NetworkTopology:
    """Replace station interiors by one wrapper node while retaining port IDs.

    Internal arcs are archived in each wrapper, not lost. External lengths start
    at the station boundary, excluding station traversal. The aggregate node
    does not prove that arbitrary ingress/egress port pairs are legal routes.
    """
    from tpf2_mcp.algorithms.generate_topology.gen_topology import Node
    wrappers = generate_station_topology_nodes(raw_network, topology=topology)
    _retain_exclusive_interiors(topology, wrappers)
    graph = NetworkTopology(warnings=list(topology.warnings))
    mapping = {}
    next_id = max(topology.nodes, default=0)+1
    for wrapper in wrappers:
        if wrapper.overlap_resolution == 'SHARED_TERMINAL_UNCOLLAPSED':
            graph.warnings.append(f'STATION_COLLAPSE_SKIPPED_SHARED_TERMINAL:{wrapper.entry_id}')
            continue
        if not wrapper.internal_node_ids:
            graph.warnings.append(f'STATION_COLLAPSE_SKIPPED:{wrapper.entry_id}')
            continue
        nid = next_id
        next_id += 1
        for member in wrapper.internal_node_ids:
            mapping[member] = nid
        terminals = [topology.nodes[t].position for t in wrapper.terminal_node_ids]
        position = {axis:sum(p.get(axis,0) for p in terminals)/len(terminals) for axis in ('x','y','z')}
        payload = wrapper.to_dict()
        members = set(wrapper.internal_node_ids)
        payload['internal_nodes'] = [asdict(topology.nodes[n]) for n in wrapper.internal_node_ids]
        payload['internal_edges'] = [asdict(e) for e in topology.edges.values()
                                     if e.from_node_id in members and e.to_node_id in members]
        payload['ports'] = []
        graph.nodes[nid] = Node(nid, NodeType.STATION, wrapper.station_name, position,
                                station_ids=wrapper.station_ids, boundary_kind='station_with_throats',
                                station_wrapper=payload)
        if wrapper.contested_node_ids:
            graph.warnings.append(f'SHARED_STATION_THROAT_EXTERNAL:{wrapper.entry_id}')
    for nid, node in topology.nodes.items():
        if nid not in mapping:
            graph.nodes[nid] = node
    for eid, edge in topology.edges.items():
        source, target = mapping.get(edge.from_node_id, edge.from_node_id), mapping.get(edge.to_node_id, edge.to_node_id)
        if source == target and edge.from_node_id in mapping and edge.to_node_id in mapping:
            continue
        graph.edges[eid] = replace(edge, from_node_id=source, to_node_id=target)
        for station, original, flow in ((source,edge.from_node_id,'outgoing'),(target,edge.to_node_id,'incoming')):
            if graph.nodes[station].station_wrapper is not None:
                graph.nodes[station].station_wrapper['ports'].append({
                    'edge_id':eid,'boundary_node_id':original,'flow':flow})
    graph.outgoing = {nid:[] for nid in graph.nodes}
    graph.incoming = {nid:[] for nid in graph.nodes}
    for eid, edge in graph.edges.items():
        graph.outgoing[edge.from_node_id].append(eid)
        graph.incoming[edge.to_node_id].append(eid)
    graph.warnings.append('STATIONS_COLLAPSED: external edge lengths exclude internal traversal; port legality unverified')
    return graph
