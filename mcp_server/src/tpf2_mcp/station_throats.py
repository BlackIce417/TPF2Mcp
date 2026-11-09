"""Offline, conservative throat candidates; not a legal train-route model."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


def identify_station_throats(network, approach_limit_m=800.0, switch_gap_m=250.0):
    if not all(math.isfinite(v) and v > 0 for v in (approach_limit_m, switch_gap_m)):
        raise ValueError('limits must be finite and positive')
    nodes = {n['entity_id']: n for n in network.get('nodes', [])}
    edges = {e['entity_id']: e for e in network.get('edges', [])}
    adj, lengths = defaultdict(list), {}
    for eid, e in sorted(edges.items()):
        u, v = e['node0'], e['node1']
        if u not in nodes or v not in nodes:
            raise ValueError(f'missing endpoint for edge {eid}')
        a, b = nodes[u]['position'], nodes[v]['position']
        delta = {k: b.get(k, 0)-a.get(k, 0) for k in ('x', 'y', 'z')}
        t0, t1 = e.get('tangent0') or delta, e.get('tangent1') or delta
        points = []
        for i in range(25):
            t = i/24
            points.append(tuple((2*t**3-3*t*t+1)*a.get(k, 0)+(t**3-2*t*t+t)*t0.get(k, 0)
                                +(-2*t**3+3*t*t)*b.get(k, 0)+(t**3-t*t)*t1.get(k, 0)
                                for k in ('x', 'y', 'z')))
        lengths[eid] = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
        adj[u].append((eid, v)); adj[v].append((eid, u))
    groups = []
    for s in sorted(network.get('stations', []), key=lambda s: s['entity_id']):
        owners, members = set(s.get('construction_entity_ids', [])), [s]
        for g in list(groups):
            if owners & g['owners']:
                owners |= g['owners']; members += g['members']; groups.remove(g)
        groups.append(dict(owners=owners, members=members))
    terminal_owners = defaultdict(set)
    construction_owners = {}
    core_owners = defaultdict(set)
    core_nodes = set()
    for g in groups:
        g['id'] = min(s['entity_id'] for s in g['members'])
        g['seeds'] = {t['node_id'] for s in g['members'] for t in s.get('terminals', []) if t.get('node_id') in nodes}
        for n in g['seeds']: terminal_owners[n].add(g['id'])
        for owner in g['owners']: construction_owners[owner] = g['id']
        g['core_edges'] = {eid for s in g['members'] for t in s.get('terminals', [])
                           for eid in t.get('platform_edge_ids', []) if eid in edges}
        for eid in g['core_edges']:
            core_owners[eid].add(g['id'])
            core_nodes.update((edges[eid]['node0'], edges[eid]['node1']))
        if g['core_edges']:
            g['seeds'] = {edges[eid][k] for eid in g['core_edges'] for k in ('node0', 'node1')
                          if any(other not in g['core_edges'] for other, _ in adj[edges[eid][k]])}

    def trace(start, eid, target, limit, gid):
        path, distance, seen, current = [], 0., {start}, start
        while True:
            if eid in core_owners:
                return path, current, 'PLATFORM_CORE'
            if distance + lengths[eid] > limit: return path, target, 'DISTANCE_LIMIT'
            owner = construction_owners.get(edges[eid].get('construction_entity_id'))
            if terminal_owners.get(target, set()) - {gid} or owner not in (None, gid):
                return path, target, 'OTHER_STATION'
            path.append(eid); distance += lengths[eid]
            if target in core_nodes: return path, target, 'PLATFORM_CORE'
            if target in terminal_owners: return path, target, 'PLATFORM_CORE'
            if target in seen: return path, target, 'LOOP'
            seen.add(target)
            if len(adj[target]) != 2:
                return path, target, 'SWITCH' if len(adj[target]) > 2 else 'DEAD_END'
            current = target
            eid, target = next(pair for pair in adj[target] if pair[0] != eid)

    regions = []
    for g in sorted(groups, key=lambda g: g['id']):
        approaches = [([], n) for n in g['seeds'] if len(adj[n]) > 2]
        for seed in sorted(g['seeds']):
            for eid, target in adj[seed]:
                if eid in core_owners: continue
                path, end, reason = trace(seed, eid, target, approach_limit_m, g['id'])
                if reason == 'SWITCH': approaches.append((path, end))
        for approach, first in approaches:
            switches, included, queue, reasons = {first}, set(approach), [first], set()
            while queue:
                root = queue.pop()
                for eid, target in adj[root]:
                    path, end, reason = trace(root, eid, target, switch_gap_m, g['id'])
                    if reason in ('SWITCH', 'PLATFORM_CORE'): included.update(path)
                    if reason == 'SWITCH' and end not in switches:
                        switches.add(end); queue.append(end)
                    if reason != 'SWITCH': reasons.add(reason)
            c = dict(station_id=g['id'], station_group_ids=sorted(s['entity_id'] for s in g['members']),
                     switch_node_ids=switches, edge_ids=included, boundary_reasons=reasons,
                     core_edge_ids=sorted(g['core_edges']), core_quality='PLATFORM_EDGES_DERIVED' if g['core_edges'] else 'CORE_UNAVAILABLE')
            for old in list(regions):
                if old['station_id'] == g['id'] and old['switch_node_ids'] & switches:
                    for key in ('switch_node_ids', 'edge_ids', 'boundary_reasons'): c[key] |= old[key]
                    regions.remove(old)
            regions.append(c)
    claims, switch_claims = defaultdict(set), defaultdict(set)
    for c in regions:
        for eid in c['edge_ids']: claims[eid].add(c['station_id'])
        for n in c['switch_node_ids']: switch_claims[n].add(c['station_id'])
    for c in regions:
        members = c['switch_node_ids'] | {edges[eid][k] for eid in c['edge_ids'] for k in ('node0', 'node1')}
        c['ports'] = [dict(node_id=n, position=nodes[n]['position'],
                           outside_edge_ids=sorted(eid for eid, _ in adj[n] if eid not in c['edge_ids']),
                           kind='PLATFORM_INTERFACE' if n in terminal_owners or n in core_nodes else 'UNRESOLVED_EXTERNAL_INTERFACE')
                      for n in sorted(members) if any(eid not in c['edge_ids'] for eid, _ in adj[n])]
        c['contested_edge_ids'] = sorted(eid for eid in c['edge_ids'] if len(claims[eid]) > 1)
        c['contested_switch_node_ids'] = sorted(n for n in c['switch_node_ids'] if len(switch_claims[n]) > 1)
        c['status'] = 'AMBIGUOUS_SHARED_REGION' if c['contested_edge_ids'] or c['contested_switch_node_ids'] else 'CANDIDATE'
        c['route_validation'] = 'NOT_PERFORMED'
        c['evidence'] = ['TERMINAL_ANCHORED', 'CONNECTED_SWITCH_CLUSTER', 'BOUNDED_SEARCH']
        for key in ('switch_node_ids', 'edge_ids', 'boundary_reasons'): c[key] = sorted(c[key])
        c['id'] = f"station-{c['station_id']}-throat-{min(c['switch_node_ids'])}"
    digest = hashlib.sha256(json.dumps(network, sort_keys=True).encode()).hexdigest()[:20]
    return dict(schema_version=1, save_id=network.get('save_id'), topology_id=digest,
                source='DERIVED_THROAT_CANDIDATES', game_write=False,
                parameters=dict(approach_limit_m=approach_limit_m, switch_gap_m=switch_gap_m),
                limitations=['Heuristic boundaries; not legal routes.', 'Long throats may be split; nearby junctions may be included.',
                             'IDs remain stable only while source entities are unchanged.'],
                regions=sorted(regions, key=lambda c: c['id']),
                unresolved_stations=[g['id'] for g in groups if not any(c['station_id']==g['id'] for c in regions)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('network', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(Path(__file__).resolve().parents[3]):
        parser.error('output must be within project or bundled Mod root')
    result = identify_station_throats(json.loads(args.network.read_text(encoding='utf-8')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(regions=len(result['regions']), unresolved=result['unresolved_stations'])))


if __name__ == '__main__': main()
