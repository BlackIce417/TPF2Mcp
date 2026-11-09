"""Validated, undirected physical rail graph; never implies legal train routes."""
from __future__ import annotations

import hashlib
import json
import math


def topology_id(network: dict) -> str:
    """Fingerprint recognition inputs, independent of export/list ordering."""
    value = {key: sorted(network.get(key, []), key=lambda row: row['entity_id'])
             for key in ('nodes', 'edges', 'stations', 'depots')}
    value['save_id'] = network.get('save_id')
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


class RailGraph:
    def __init__(self, network: dict):
        self.nodes = self._index(network.get('nodes', []))
        self.edges = self._index(network.get('edges', []))
        self.adjacency = {node: [] for node in self.nodes}
        self.lengths = {}
        for node in self.nodes.values():
            if not all(math.isfinite(node['position'].get(axis, 0)) for axis in ('x', 'y', 'z')):
                raise ValueError('non-finite node position')
        for eid, edge in sorted(self.edges.items()):
            a, b = edge['node0'], edge['node1']
            if a not in self.nodes or b not in self.nodes:
                raise ValueError(f'missing endpoint for edge {eid}')
            points = self.samples(eid)
            length = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
            if not math.isfinite(length):
                raise ValueError(f'non-finite geometry for edge {eid}')
            self.lengths[eid] = length
            self.adjacency[a].append((eid, b))
            self.adjacency[b].append((eid, a))

    @staticmethod
    def _index(rows):
        result = {row['entity_id']: row for row in rows}
        if len(result) != len(rows):
            raise ValueError('duplicate entity id')
        return result

    def samples(self, eid, steps=24):
        edge = self.edges[eid]
        a, b = (self.nodes[edge[k]]['position'] for k in ('node0', 'node1'))
        delta = {k: b.get(k, 0)-a.get(k, 0) for k in ('x', 'y', 'z')}
        u, v = edge.get('tangent0') or delta, edge.get('tangent1') or delta
        return [tuple((2*t**3-3*t*t+1)*a.get(k, 0)+(t**3-2*t*t+t)*u.get(k, 0)
                      +(-2*t**3+3*t*t)*b.get(k, 0)+(t**3-t*t)*v.get(k, 0)
                      for k in ('x', 'y', 'z')) for t in (i/steps for i in range(steps+1))]

    def walk(self, start, eid, limit, blocked_nodes=frozenset(), blocked_edges=frozenset(), depot_edges=frozenset()):
        """Follow a degree-two chain, stopping BEFORE excluded or over-budget edges."""
        path, distance, current, seen = [], 0., start, {start}
        while True:
            if eid in blocked_edges:
                return path, current, distance, 'STATION_BOUNDARY'
            if distance + self.lengths[eid] > limit:
                return path, current, distance, 'DISTANCE_LIMIT'
            edge = self.edges[eid]
            target = edge['node1'] if edge['node0'] == current else edge['node0']
            path.append(eid); distance += self.lengths[eid]
            if eid in depot_edges:
                return path, target, distance, 'DEPOT_CONNECTION'
            if target in blocked_nodes:
                return path, target, distance, 'STATION_BOUNDARY'
            if target in seen:
                return path, target, distance, 'LOOP'
            seen.add(target)
            degree = len(self.adjacency[target])
            if degree != 2:
                return path, target, distance, 'SWITCH' if degree > 2 else 'DEAD_END'
            current = target
            eid = next(e for e, _ in self.adjacency[current] if e != eid)
