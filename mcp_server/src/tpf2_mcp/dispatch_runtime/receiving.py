"""Conservative full-body occupancy check for a train-specific receiving path."""
from __future__ import annotations
import math


def receiving_evidence(frame, candidate, territory, vehicle_id):
    edges = {eid for eid in candidate.get('receiving_edge_ids', []) if eid in territory.graph.edges}
    if not edges or frame.get('quality', {}).get('footprint') != 'FRESH':
        return {'verified': False, 'source': 'FULL_BODY_SPATIAL_ROUTE', 'clear_length_m': None,
                'conflicting_vehicle_ids': [], 'reason': 'RECEIVING_PATH_OR_FOOTPRINT_UNAVAILABLE'}
    conflicts = set()
    for train in frame.get('trains', []):
        if train.get('vehicle_id') == vehicle_id: continue
        if train.get('footprint_complete') is not True:
            return {'verified': False, 'source': 'FULL_BODY_SPATIAL_ROUTE', 'clear_length_m': None,
                    'conflicting_vehicle_ids': sorted(conflicts), 'reason': 'OTHER_TRAIN_FOOTPRINT_INCOMPLETE'}
        for body in train.get('body_samples', []):
            p = body.get('position') or {}; radius = body.get('radius_m')
            if not isinstance(radius, (int, float)): continue
            try: point = tuple(float(p[k]) for k in ('x', 'y', 'z'))
            except (KeyError, TypeError, ValueError): continue
            nearby = edges.intersection(territory.graph.near_precise(point, radius+4))
            for eid in nearby:
                _, q, _ = territory.graph.approximate_project(eid, point)
                if math.hypot(q[0]-point[0], q[1]-point[1]) <= radius+3 and abs(q[2]-point[2]) <= 8:
                    conflicts.add(train['vehicle_id']); break
            if train['vehicle_id'] in conflicts: break
    return {'verified': True, 'source': 'FULL_BODY_SPATIAL_ROUTE',
            'clear_length_m': candidate.get('receiving_length_m'),
            'conflicting_vehicle_ids': sorted(conflicts)}
