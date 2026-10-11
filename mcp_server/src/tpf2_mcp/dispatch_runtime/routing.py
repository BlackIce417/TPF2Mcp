"""Resolve a train's engine path through fixed regional boundary anchors."""
from __future__ import annotations


def _physical_route(train, graph):
    route = train.get('route') or {}
    ids, directions = route.get('edge_ids') or [], route.get('directions') or []
    start, current = route.get('start_index'), route.get('current_index')
    if (route.get('status') != 'ENGINE_PATH_CURRENT' or len(ids) != len(directions)
            or not isinstance(start, int) or not isinstance(current, int)):
        return None, 'ENGINE_ROUTE_UNAVAILABLE'
    raw_current = current-start
    if not 0 <= raw_current < len(ids): return None, 'ENGINE_ROUTE_INDEX_INVALID'
    groups = []
    for raw_index, (eid, forward) in enumerate(zip(ids, directions)):
        if eid not in graph.edges or type(forward) is not bool:
            # MOVE_PATH also contains BASE_NODE transport entities.  Drop them
            # here; BoundaryCalibrator.search still proves that the remaining
            # physical edges are directly incident and direction-compatible,
            # so an unknown construction edge cannot be jumped silently.
            continue
        item = {'edge_id': eid, 'forward': forward, 'first': raw_index, 'last': raw_index, 'known': True}
        if groups and groups[-1]['edge_id'] == eid and groups[-1]['forward'] == forward:
            groups[-1]['last'] = raw_index
            groups[-1]['known'] = groups[-1]['known'] and item['known']
        else: groups.append(item)
    group_current = next((i for i, g in enumerate(groups) if g['first'] <= raw_current <= g['last']), None)
    return ({'groups': groups, 'current_group': group_current} if group_current is not None else None,
            None if group_current is not None else 'ENGINE_ROUTE_INDEX_INVALID')


def _distance_to_anchor(train, groups, current_group, anchor_group, binding, graph):
    current_param = train.get('edge_param')
    if not isinstance(current_param, (int, float)): return None
    current = groups[current_group]
    if anchor_group == current_group:
        signed = (binding['edge_param']-current_param)*(1 if current['forward'] else -1)
        return graph.lengths[current['edge_id']]*signed if signed >= -1e-6 else None
    distance = graph.lengths[current['edge_id']]*((1-current_param) if current['forward'] else current_param)
    for group in groups[current_group+1:anchor_group]: distance += graph.lengths[group['edge_id']]
    target = groups[anchor_group]
    distance += graph.lengths[target['edge_id']]*(binding['edge_param'] if target['forward'] else 1-binding['edge_param'])
    return distance


def _physically_contiguous(groups, start, stop, graph):
    selected = groups[start:stop]
    if not selected: return False
    for left, right in zip(selected, selected[1:]):
        a, b = graph.edges[left['edge_id']], graph.edges[right['edge_id']]
        exit_node = a['node1'] if left['forward'] else a['node0']
        entry_node = b['node0'] if right['forward'] else b['node1']
        if exit_node != entry_node: return False
    return True


def _outward_length(binding, forward, path, graph):
    if not path: return 0.
    length = graph.lengths[path[0]]*((1-binding['edge_param']) if forward else binding['edge_param'])
    return length+sum(graph.lengths[eid] for eid in path[1:] if eid in graph.edges)


def boundary_candidates(train, calibration, calibrator, territory, maximum_distance_m=3000):
    """Return legal-path evidence; this function never grants admission itself."""
    physical, reason = _physical_route(train, territory.graph)
    if physical is None: return [], [reason]
    groups, current_group = physical['groups'], physical['current_group']
    candidates, observations = [], []
    for anchor in calibration.get('anchors', []):
        binding = anchor.get('binding') or {}
        if binding.get('status') != 'BOUND': continue
        occurrences = [i for i in range(current_group, len(groups)) if groups[i]['edge_id'] == binding['edge_id']]
        for index in occurrences:
            distance = _distance_to_anchor(train, groups, current_group, index, binding, territory.graph)
            if distance is None or distance > maximum_distance_m: continue
            travel_forward = groups[index]['forward']
            positive = travel_forward == binding['positive_forward']
            name = 'negative_to_positive' if positive else 'positive_to_negative'
            direction = (anchor.get('directions') or {}).get(name) or {}
            outward_entry = [[binding['edge_id'], not travel_forward]]
            # The fresh route window includes up to 96 entries already passed
            # by the train.  They are still valid evidence for the approach
            # signal and legal turnout chain; braking admissibility separately
            # uses the train's current distance to the boundary.
            outward_entry += [[g['edge_id'], not g['forward']] for g in reversed(groups[:index])]
            outward_exit = [[binding['edge_id'], travel_forward]]
            outward_exit += [[g['edge_id'], g['forward']] for g in groups[index+1:]]
            limit = 3000
            entry = calibrator.search(binding, not travel_forward, False, limit, outward_entry)
            exit_signal = calibrator.search(binding, travel_forward, True, limit, outward_exit)
            legal = index+1 < len(groups) and _physically_contiguous(groups, current_group, index+2, territory.graph)
            signal_protection = entry.get('status') == exit_signal.get('status') == 'FOUND'
            path_edges = []
            for eid in [*(entry.get('path') or []), *(exit_signal.get('path') or [])]:
                if eid not in path_edges: path_edges.append(eid)
            resources = []
            for eid in path_edges:
                for segment in territory.by_edge.get(eid, []):
                    resource = f"rail:{eid}:{segment['start']:.9f}:{segment['end']:.9f}"
                    if resource not in resources: resources.append(resource)
            value = {'anchor_id': anchor['anchor_id'], 'label': anchor['label'], 'direction': name,
                     'from_region': direction.get('from_region'), 'to_region': direction.get('to_region'),
                     'distance_m': round(distance, 3), 'legal_route_verified': legal,
                     'signal_protection_verified': signal_protection,
                     'entry': entry, 'exit': exit_signal, 'resources': resources,
                     'receiving_edge_ids': list(dict.fromkeys(exit_signal.get('path') or [])),
                     'receiving_length_m': round(_outward_length(binding, travel_forward,
                                                                  exit_signal.get('path') or [], territory.graph), 3),
                     'blockers': [] if legal else ['LEGAL_ROUTE']}
            candidates.append(value)
            if not legal:
                observations.append({'code': 'BOUNDARY_ROUTE_UNRESOLVED', 'vehicle_id': train['vehicle_id'],
                                     'anchor_id': anchor['anchor_id'], 'entry': entry['status'], 'exit': exit_signal['status']})
            elif not signal_protection:
                observations.append({'code': 'BOUNDARY_SIGNAL_PROTECTION_UNAVAILABLE', 'vehicle_id': train['vehicle_id'],
                                     'anchor_id': anchor['anchor_id'], 'entry': entry['status'], 'exit': exit_signal['status']})
            break
    candidates.sort(key=lambda c: (c['distance_m'], c['anchor_id']))
    return candidates, observations
