"""Unique physical resource ownership and exhaustive cross-region coverage audit."""
from collections import defaultdict
import math
from .geometry import vector


class TerritoryIndex:
    def __init__(self, document, graph):
        self.document, self.graph = document, graph
        self.by_edge = defaultdict(list)
        for s in document['segments']:
            if s['region'] not in document['regions']: raise ValueError('unknown region')
            self.by_edge[s['edge_id']].append(s)
        if set(self.by_edge) != set(graph.edges): raise ValueError('unassigned or foreign rail edge')
        for rows in self.by_edge.values():
            rows.sort(key=lambda s: s['start'])
            if rows[0]['start'] != 0 or rows[-1]['end'] != 1: raise ValueError('incomplete rail coverage')
            if any(not 0 <= s['start'] < s['end'] <= 1 for s in rows): raise ValueError('invalid rail interval')
            if any(a['end'] != b['start'] for a, b in zip(rows, rows[1:])): raise ValueError('overlap or hole')

    def segment(self, eid, t):
        if type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 1: return None
        return next((s for s in self.by_edge.get(eid, []) if s['start'] <= t < s['end'] or t == 1 and s['end'] == 1), None)

    def owner(self, eid, t):
        s = self.segment(eid, t)
        return s['region'] if s else None

    def resource(self, eid, t):
        s = self.segment(eid, t)
        return f"rail:{eid}:{s['start']:.9f}:{s['end']:.9f}" if s else None

    def locate(self, position, xy_radius=20., vertical_radius=8., ambiguity_delta=1.25):
        """Resolve a body coordinate to a region without guessing a track.

        Parallel tracks owned by the same controller are harmless for regional
        occupancy.  Competing tracks owned by different controllers remain
        explicit ambiguity and cannot prove a handover or tail release.
        """
        try: p = vector(position)
        except (TypeError, ValueError, AttributeError):
            return {'status': 'POSITION_MISSING', 'region': None, 'candidates': []}
        candidates = []
        for eid in self.graph.near_precise(p, xy_radius):
            t, q, distance = self.graph.approximate_project(eid, p)
            xy = math.hypot(q[0]-p[0], q[1]-p[1])
            vertical = abs(q[2]-p[2])
            region = self.owner(eid, t)
            if region and xy <= xy_radius and vertical <= vertical_radius:
                candidates.append({'edge_id': eid, 'edge_param': t, 'distance_m': distance,
                                   'xy_distance_m': xy, 'vertical_distance_m': vertical,
                                   'region': region, 'resource': self.resource(eid, t)})
        if not candidates:
            return {'status': 'POSITION_UNRESOLVED', 'region': None, 'candidates': []}
        candidates.sort(key=lambda c: (c['distance_m'], c['edge_id']))
        plausible = [c for c in candidates if c['distance_m'] <= candidates[0]['distance_m']+ambiguity_delta]
        regions = {c['region'] for c in plausible}
        # Near an administrative cut, a 32-segment projection is intentionally
        # treated as both sides.  Body bounds provide the stronger crossing
        # proof; a rounded centre parameter must never release a reservation.
        for c in plausible:
            edge_length = max(self.graph.lengths[c['edge_id']], 1.)
            for a, b in zip(self.by_edge[c['edge_id']], self.by_edge[c['edge_id']][1:]):
                if a['region'] != b['region'] and abs(c['edge_param']-a['end'])*edge_length <= 2:
                    regions.update((a['region'], b['region']))
        regions = sorted(regions)
        if len(regions) != 1:
            return {'status': 'REGION_AMBIGUOUS', 'region': None, 'regions': regions, 'candidates': plausible}
        return {'status': 'REGION_CONFIRMED', 'region': regions[0], 'best': candidates[0],
                'regions': regions, 'candidates': plausible}

    def audit(self, calibration):
        bindings = [(r['anchor_id'], r['binding']) for r in calibration['anchors'] if r['binding']['status'] == 'BOUND']
        transitions, gaps = [], []
        for eid, rows in self.by_edge.items():
            for a, b in zip(rows, rows[1:]):
                if a['region'] == b['region']: continue
                match = [aid for aid, c in bindings if c['edge_id'] == eid and abs(c['edge_param']-a['end']) < 1e-4]
                item = {'edge_id': eid, 'edge_param': a['end'], 'regions': [a['region'], b['region']], 'anchor_ids': match}
                transitions.append(item)
                if len(match) != 1: gaps.append(item)
        for nid, eids in self.graph.incident.items():
            owners = {self.owner(eid, 0 if self.graph.edges[eid]['node0'] == nid else 1) for eid in eids}
            if len(owners) < 2: continue
            match = [aid for aid, c in bindings if c['edge_id'] in eids and
                     math.dist(self.graph.point(c['edge_id'], c['edge_param']), self.graph.nodes[nid]) < .5]
            item = {'node_id': nid, 'regions': sorted(owners), 'anchor_ids': match}
            transitions.append(item)
            if len(match) != 1: gaps.append(item)
        return {'edge_count': len(self.by_edge), 'assigned_edge_count': len(self.graph.edges),
                'administrative_coverage_complete': True, 'crossings': transitions,
                'unanchored_crossings': gaps, 'boundary_coverage_complete': not gaps,
                'review_required': bool(self.document.get('review_events')) or bool(gaps)}


def repartition(reference, graph, calibration, topology_version):
    """Rebuild after construction using frozen cuts and station coordinate seeds.

    Conflicting/disconnected components get a maintenance owner plus an explicit
    review event; that assignment never confers automatic dispatch authority.
    """
    cuts, events = defaultdict(list), []
    for a in calibration['anchors']:
        b = a['binding']
        if b['status'] == 'BOUND' and 1e-6 < b['edge_param'] < 1-1e-6:
            cuts[b['edge_id']].append(b['edge_param'])
        elif b['status'] != 'BOUND': events.append({'code': 'ANCHOR_UNBOUND', 'anchor_id': a['anchor_id']})
    segments, incident, edge_rows = [], defaultdict(list), defaultdict(list)
    for eid, edge in sorted(graph.edges.items()):
        ts = [0., *sorted(set(cuts[eid])), 1.]
        for start, end in zip(ts, ts[1:]):
            row = {'segment_id': len(segments), 'edge_id': eid, 'start': start, 'end': end}
            segments.append(row); edge_rows[eid].append(row['segment_id'])
        incident[edge['node0']].append(edge_rows[eid][0]); incident[edge['node1']].append(edge_rows[eid][-1])
    parents = list(range(len(segments)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    endpoint_cuts = set()
    for a in calibration['anchors']:
        b = a['binding']
        if b['status'] != 'BOUND': continue
        e, t = graph.edges[b['edge_id']], b['edge_param']
        if t <= 1e-6: endpoint_cuts.add(e['node0'])
        if t >= 1-1e-6: endpoint_cuts.add(e['node1'])
    for nid, items in incident.items():
        if nid in endpoint_cuts: continue
        for i in items[1:]: parents[root(i)] = root(items[0])
    seeds = defaultdict(set)
    # Station references are coordinates, not stale IDs.
    for station in reference['stations']:
        p = vector(station['center'])
        candidates = [(graph.project(eid, p)[2], eid) for eid in graph.near(p, 500)]
        if not candidates:
            events.append({'code': 'STATION_TRACK_NOT_FOUND', 'station': station['name']}); continue
        _, eid = min(candidates)
        t = graph.project(eid, p)[0]
        sid = next(sid for sid in edge_rows[eid] if segments[sid]['start'] <= t <= segments[sid]['end'])
        seeds[root(sid)].add(station['region'])
    # Anchor-side labels remain authoritative when track orientation is reversed.
    for a in calibration['anchors']:
        b = a['binding']
        if b['status'] != 'BOUND': continue
        directions = a.get('directions', {})
        if not directions: continue
        negative, positive = directions['negative_to_positive']['from_region'], directions['negative_to_positive']['to_region']
        eid, t = b['edge_id'], b['edge_param']
        if 1e-6 < t < 1-1e-6:
            for sid in edge_rows[eid]:
                s = segments[sid]
                if abs(s['start']-t) > 1e-6 and abs(s['end']-t) > 1e-6: continue
                side_positive = (s['start'] >= t) == b['positive_forward']
                seeds[root(sid)].add(positive if side_positive else negative)
        else:
            nid = graph.edges[eid]['node0' if t <= 1e-6 else 'node1']
            axis = graph.point(eid, t, True)
            for sid in incident[nid]:
                s = segments[sid]; e = graph.edges[s['edge_id']]
                q = graph.point(s['edge_id'], (s['start']+s['end'])/2)
                sign = sum((q[k]-graph.nodes[nid][k])*axis[k] for k in range(3))
                side_positive = (sign > 0) == b['positive_forward']
                seeds[root(sid)].add(positive if side_positive else negative)
    components = defaultdict(list)
    for s in segments: components[root(s['segment_id'])].append(s)
    for cid, rows in components.items():
        labels = seeds[cid]
        if len(labels) != 1:
            q = graph.point(rows[0]['edge_id'], (rows[0]['start']+rows[0]['end'])/2)
            nearest = min(reference['stations'], key=lambda s: math.dist(q, vector(s['center'])))
            owner = min(labels) if labels else nearest['region']
            events.append({'code': 'CONFLICTING_REGION_SEEDS' if labels else 'ISOLATED_TRACK_REVIEW',
                           'component': cid, 'maintenance_owner': owner, 'regions': sorted(labels), 'edge_count': len(rows)})
        else: owner = next(iter(labels))
        for row in rows: row['region'] = owner
    return {**reference, 'topology_sha256': topology_version, 'segments': segments, 'review_events': events}
