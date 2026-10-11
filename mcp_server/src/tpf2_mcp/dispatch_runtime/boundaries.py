"""Coordinate anchors and disposable directional-signal calibration."""
from collections import Counter, defaultdict
import hashlib
import json
import math

from .geometry import RailGraph, vector, dot


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _positions(geometry):
    if not isinstance(geometry, dict): return None
    if len(geometry.get('pos', [])) == 2: return geometry['pos']
    for key in ('params', 'straight', 'cubicSpline', 'cubicOffsetSpline', 'geometry'):
        found = _positions(geometry.get(key))
        if found: return found
    return None


def normalize_directional_signals(raw, graph):
    """Correlate exact getSignal receipts; project transport orientation onto base rail.

    Unknown geometry or a mismatched transport entity cannot establish base direction.
    Missing XYZ elevation on transport geometry is resolved on the known physical edge.
    """
    result = []
    for item in raw.get('signal_edge_objects', []):
        eid = item.get('edge_entity_id')
        if eid not in graph.edges or not item.get('position'): continue
        t, _, _ = graph.project(eid, item['position'])
        directions = set()
        bindings = []
        for evidence in item.get('direction_evidence', []):
            if evidence.get('status') != 'ENGINE_QUERY_CONFIRMED' or evidence.get('transport_entity') != eid:
                continue
            receipts = evidence.get('queries', [])
            matches = [q for q in receipts if q.get('ok') is True and q.get('matched') is True
                       and q.get('signal_entity') == item.get('object_entity_id')
                       and q.get('signal_index') == evidence.get('signal_index')]
            if len(matches) != 1 or type(matches[0].get('reversed')) is not bool: continue
            if len(receipts) != 2 or any(q.get('ok') is not True for q in receipts): continue
            if {q.get('reversed') for q in receipts} != {False, True}: continue
            positions = _positions(evidence.get('geometry'))
            if not positions: continue
            projected = []
            for p in positions:
                p = dict(p)
                if p.get('z') is None:
                    # Transport-network geometry is often XY-only.  Reusing
                    # the signal's elevation for both ends makes an ordinary
                    # graded edge look more than five metres off its own base
                    # rail.  Seed once, then lift each endpoint onto the base
                    # curve at its own projected parameter.
                    p['z'] = graph.point(eid, t)[2]
                    guessed_t = graph.project(eid, p)[0]
                    p['z'] = graph.point(eid, guessed_t)[2]
                projected.append(graph.project(eid, p))
            if max(p[2] for p in projected) > 5 or abs(projected[1][0]-projected[0][0]) < 1e-6:
                continue
            increasing = projected[1][0] > projected[0][0]
            directions.add(increasing != matches[0]['reversed'])
            bindings.append({'signal_index': evidence.get('signal_index'),
                             'transport_index': evidence.get('transport_index'),
                             'forward': increasing != matches[0]['reversed']})
        result.append({'entity_id': item['object_entity_id'], 'edge_id': eid, 'edge_param': t,
                       'signal_types': item.get('signal_types', []),
                       'directions': sorted(directions),
                       'direction_bindings': bindings,
                       'direction_status': 'ENGINE_QUERY_CONFIRMED' if directions else 'UNKNOWN'})
    return result


class BoundaryCalibrator:
    def __init__(self, graph, signals, topology_version):
        self.graph, self.version = graph, topology_version
        self.signals = defaultdict(list)
        for signal in signals:
            if signal.get('edge_id') in graph.edges and any(t in (0, 1) for t in signal.get('signal_types', [])):
                self.signals[signal['edge_id']].append(signal)

    def bind(self, anchor):
        g, policy, p = self.graph, anchor['search_policy'], vector(anchor['position'])
        axis = vector(anchor['positive_tangent'])
        radius = policy['xy_radius_m']
        candidates = []
        for eid in g.near(p, radius):
            t, q, dist = g.project(eid, p)
            tangent = g.point(eid, t, True)
            norm = math.sqrt(dot(tangent, tangent)*dot(axis, axis))
            if not norm: continue
            cosine = dot(tangent, axis)/norm
            if (math.hypot(q[0]-p[0], q[1]-p[1]) <= radius and abs(q[2]-p[2]) <= policy['max_vertical_offset_m']
                    and abs(cosine) >= math.cos(math.radians(policy['max_axis_angle_degrees']))):
                candidates.append({'edge_id': eid, 'edge_param': t, 'distance_m': round(dist, 4),
                                   'positive_forward': cosine > 0})
        seed = anchor.get('seed_evidence', {})
        # Old ID is evidence only when the ENTIRE original topology hash still matches.
        exact = [c for c in candidates if c['edge_id'] == seed.get('edge_id') and c['distance_m'] < .5]
        if seed.get('topology_sha256') == self.version and len(exact) == 1:
            return {'status': 'BOUND', 'method': 'SAME_TOPOLOGY_COORDINATE_VALIDATED', **exact[0]}
        if len(candidates) == 1 and candidates[0]['distance_m'] < .5:
            return {'status': 'BOUND', 'method': 'UNIQUE_SPATIAL_CORRIDOR', **candidates[0]}
        # A split exactly at the anchor has two equivalent endpoints on one chain.
        if len(candidates) == 2 and all(c['distance_m'] < .5 for c in candidates):
            ends = []
            for c in candidates:
                e, t = g.edges[c['edge_id']], c['edge_param']
                ends.append(e['node0'] if t < 1e-5 else e['node1'] if t > 1-1e-5 else None)
            if ends[0] is not None and ends[0] == ends[1] and len(g.incident[ends[0]]) == 2:
                return {'status': 'BOUND', 'method': 'SPLIT_AT_FIXED_COORDINATE', **candidates[0]}
        return {'status': 'AMBIGUOUS' if candidates else 'NO_TRACK', 'candidates': candidates}

    def search(self, binding, outward_forward, travel_outward, limit, route=None):
        """Walk away from the cut, searching signals facing the requested travel.

        Stop at junctions: physical incidence alone cannot prove a legal turnout route.
        A route-specific transport-port adapter may resolve those branches later.
        """
        g = self.graph
        eid, t, distance, seen, path = binding['edge_id'], binding['edge_param'], 0., set(), []
        forward = outward_forward
        route_index = 0
        if route is not None and (not route or route[0] != [eid, forward]):
            return {'status': 'ROUTE_MISMATCH', 'path': []}
        while distance <= limit:
            if (eid, forward) in seen: return {'status': 'LOOP', 'path': path}
            seen.add((eid, forward))
            wanted = forward if travel_outward else not forward
            candidates = []
            for s in self.signals[eid]:
                st = s.get('edge_param')
                if not isinstance(st, (float, int)) or not 0 <= st <= 1: continue
                if (st-t)*(1 if forward else -1) < -1e-6: continue
                d = distance+abs(g.along(eid, st)-g.along(eid, t))
                if d <= limit: candidates.append((d, s['entity_id'], s))
            for d, _, s in sorted(candidates):
                if s.get('direction_status') != 'ENGINE_QUERY_CONFIRMED':
                    return {'status': 'DIRECTION_UNKNOWN', 'candidate_signal_id': s['entity_id'], 'distance_m': d, 'path': path+[eid]}
                if wanted in s.get('directions', []):
                    return {'status': 'FOUND', 'signal_id': s['entity_id'], 'edge_id': eid,
                            'edge_param': s['edge_param'], 'forward': wanted, 'distance_m': d, 'path': path+[eid]}
                if 1 in s.get('signal_types', []):
                    return {'status': 'DIRECTION_PROHIBITED', 'signal_id': s['entity_id'], 'path': path+[eid]}
            distance += abs(g.along(eid, 1 if forward else 0)-g.along(eid, t))
            path.append(eid)
            if distance > limit: break
            e = g.edges[eid]
            end = e['node1'] if forward else e['node0']
            next_edges = [x for x in g.incident[end] if x != eid]
            if not next_edges: return {'status': 'NO_SUITABLE_SIGNAL', 'path': path}
            if route is not None:
                route_index += 1
                if route_index >= len(route): return {'status': 'ROUTE_ENDED', 'path': path}
                next_id, expected_forward = route[route_index]
                if next_id not in next_edges or (g.edges[next_id]['node0'] == end) != expected_forward:
                    return {'status': 'ROUTE_MISMATCH', 'path': path}
            else:
                if len(next_edges) != 1: return {'status': 'AMBIGUOUS_ROUTE', 'node_id': end, 'branches': sorted(next_edges), 'path': path}
                next_id = next_edges[0]
            next_forward = g.edges[next_id]['node0'] == end
            arrival = g.point(eid, 1 if forward else 0, True)
            departure = g.point(next_id, 0 if next_forward else 1, True)
            if dot(arrival, departure)*(1 if forward == next_forward else -1) <= 0:
                return {'status': 'ILLEGAL_TURN', 'node_id': end, 'path': path}
            eid, forward, t = next_id, next_forward, 0 if next_forward else 1
        return {'status': 'NO_SUITABLE_SIGNAL', 'path': path}

    def calibrate(self, anchor):
        binding = self.bind(anchor)
        result = {'anchor_id': anchor['anchor_id'], 'anchor_revision': anchor['revision'],
                  'anchor_fingerprint': digest(anchor), 'label': anchor['label'],
                  'binding': binding, 'status': binding['status'], 'control_ready': False,
                  'up_down_mapping': anchor.get('up_down_mapping'), 'directions': {}}
        if binding['status'] != 'BOUND': return result
        limit = anchor['search_policy']['max_signal_path_distance_m']
        for name, positive in (('negative_to_positive', True), ('positive_to_negative', False)):
            forward = binding['positive_forward'] == positive
            entry = self.search(binding, not forward, False, limit)
            exit_signal = self.search(binding, forward, True, limit)
            status = 'CALIBRATED' if entry['status'] == exit_signal['status'] == 'FOUND' else next(
                r['status'] for r in (entry, exit_signal) if r['status'] != 'FOUND')
            result['directions'][name] = {'status': status, 'entry': entry, 'exit': exit_signal,
                                          'from_region': anchor['negative_region' if positive else 'positive_region'],
                                          'to_region': anchor['positive_region' if positive else 'negative_region']}
        statuses = [d['status'] for d in result['directions'].values()]
        result['status'] = 'CALIBRATED' if all(s == 'CALIBRATED' for s in statuses) else 'PARTIAL' if 'CALIBRATED' in statuses else statuses[0]
        # Direction discovery alone does not establish train length/braking/locked route.
        result['control_requirements'] = ['CURRENT_SESSION', 'LEGAL_ROUTE', 'FULL_TRAIN_FOOTPRINT', 'RECEIVING_SPACE', 'BRAKING_ENVELOPE']
        return result


def calibrate_all(anchors, graph, signals, scope):
    compiler = BoundaryCalibrator(graph, signals, scope['topology_version'])
    results = [compiler.calibrate(a) for a in anchors['anchors']]
    return {'schema_version': 1, **scope, 'signals_fingerprint': digest(signals),
            'anchors': results, 'counts': dict(Counter(a['status'] for a in results))}
