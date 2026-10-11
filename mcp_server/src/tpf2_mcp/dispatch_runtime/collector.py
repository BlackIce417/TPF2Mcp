"""Normalize game-produced files into an immutable regional observation frame."""
import json
import math
from pathlib import Path
from ..save_scope import snapshot_save_id


def read_json(path):
    try: return json.loads(Path(path).read_text('utf8'))
    except (OSError, ValueError): return {}


class RegionalCollector:
    def __init__(self, mod_root, territory, topology_version):
        self.root, self.territory, self.version = Path(mod_root).resolve(), territory, topology_version
        self.sequence = 0
        self.last_observation = None
        self.footprint_cache_sample = None
        self.footprint_cache = {}

    def _body_regions(self, envelope):
        """Conservatively map a complete, ordered engine train envelope."""
        if not isinstance(envelope, dict) or envelope.get('complete') is not True:
            return False, [], 'ENVELOPE_INCOMPLETE', []
        parts = envelope.get('parts')
        if (not isinstance(parts, list) or not parts
                or envelope.get('expected_parts') != len(parts)):
            return False, [], 'PART_COUNT_MISMATCH', []
        occupied, locations, previous = set(), [], None
        body_min = {k: float('inf') for k in ('x', 'y', 'z')}
        body_max = {k: float('-inf') for k in ('x', 'y', 'z')}
        for part in parts:
            position = part.get('position') or {}
            if not all(isinstance(position.get(k), (int, float)) and math.isfinite(position[k]) for k in ('x', 'y', 'z')):
                return False, sorted(occupied), 'BODY_POSITION_MISSING', locations
            current = tuple(position[k] for k in ('x', 'y', 'z'))
            if previous is not None and math.dist(previous, current) > 60:
                return False, sorted(occupied), 'TRAIN_PARTS_NOT_CONTIGUOUS', locations
            previous = current
            bounds = part.get('bounds') or {}
            low, high = bounds.get('min'), bounds.get('max')
            if not isinstance(low, dict) or not isinstance(high, dict):
                return False, sorted(occupied), 'BODY_BOUNDS_MISSING', locations
            if not all(isinstance(low.get(k), (int, float)) and isinstance(high.get(k), (int, float))
                       and math.isfinite(low[k]) and math.isfinite(high[k]) and low[k] <= high[k]
                       for k in ('x', 'y', 'z')):
                return False, sorted(occupied), 'BODY_BOUNDS_INVALID', locations
            for k in body_min:
                body_min[k] = min(body_min[k], low[k]); body_max[k] = max(body_max[k], high[k])
        # TRAIN.vehicles is an ordered, contiguous consist.  Mapping both ends
        # plus every fixed boundary inside the complete body extent establishes
        # regional occupancy without thousands of curve projections per second.
        for part in (parts[0], parts[-1]):
            located = self.territory.locate(part['position'])
            locations.append({'entity_id': part.get('entity_id'), **located})
            if located['status'] not in ('REGION_CONFIRMED', 'REGION_AMBIGUOUS'):
                return False, sorted(occupied), located['status'], locations
            occupied.update(located.get('regions', []))
        for boundary in self.territory.document.get('boundaries', []):
            p = boundary.get('position') or {}
            if all(isinstance(p.get(k), (int, float)) and body_min[k]-0.5 <= p[k] <= body_max[k]+0.5
                   for k in ('x', 'y', 'z')):
                occupied.update(boundary.get('regions', []))
        return True, sorted(occupied), 'FULL_BODY_ENGINE_CONFIRMED', locations

    @staticmethod
    def _train_length(envelope):
        parts = (envelope or {}).get('parts') or []
        if not parts: return None
        positions = [tuple(part['position'][k] for k in ('x', 'y', 'z')) for part in parts]
        centre_span = sum(math.dist(a, b) for a, b in zip(positions, positions[1:]))
        def half_length(part):
            bounds = part['bounds']
            return max(bounds['max']['x']-bounds['min']['x'], bounds['max']['y']-bounds['min']['y'])/2
        return round(centre_span+half_length(parts[0])+half_length(parts[-1]), 3)

    def collect(self, now):
        bridge = self.root/'bridge'
        heartbeat = read_json(bridge/'heartbeat.json')
        state = read_json(bridge/'state.json')
        raw = read_json(bridge/'operational-telemetry-vehicle_positions.json')
        footprint_path = bridge/'operational-telemetry-train_footprints.json'
        footprints = read_json(footprint_path)
        try: footprint_observed_at = footprint_path.stat().st_mtime
        except OSError: footprint_observed_at = 0
        details = read_json(bridge/'operational-telemetry-vehicles_live.json')
        signals = read_json(bridge/'operational-telemetry-signals.json')
        live = read_json(bridge/'live-rail-state.json')
        save_id = snapshot_save_id(state)
        expected_save = self.territory.document['save_id']
        sampled = raw.get('generated_at', 0)
        session_id = raw.get('session_id') or 'LEGACY_SESSION_UNVERIFIED'
        scope_evidence = read_json(bridge/'dispatch/regional/input-scope.json')
        world_verified = state.get('metadata', {}).get('session_id') == session_id or (
            scope_evidence.get('verified') is True and scope_evidence.get('session_id') == session_id
            and scope_evidence.get('save_id') == save_id
            and isinstance(state.get('timestamp'), (int, float))
            and isinstance(scope_evidence.get('world_timestamp'), (int, float))
            and state['timestamp'] >= scope_evidence['world_timestamp'])
        verified = (bool(raw.get('session_id')) and signals.get('session_id') == raw['session_id']
                    and world_verified)
        fresh = bool(heartbeat.get('bridge_ready')) and 0 <= now-heartbeat.get('last_update', 0) < 5 and 0 <= now-sampled <= 2
        issues = []
        if save_id != expected_save: issues.append('SAVE_MISMATCH')
        if not fresh: issues.append('TELEMETRY_STALE')
        if not verified: issues.append('SESSION_OR_SIGNAL_COLLECTION_REQUIRED')
        rail_ids = {v['entity_id'] for v in live.get('vehicles', []) if 'entity_id' in v} if live.get('save_id') == save_id else set()
        footprint_update_count = (footprints.get('simulation_clock') or {}).get('update_count')
        footprint_fresh = (footprints.get('session_id') == session_id
                           and isinstance(footprint_update_count, int)
                           and 0 <= now-footprints.get('generated_at', 0) <= 5)
        footprint_by_id = {v.get('entity_id'): v for v in footprints.get('vehicles', [])} if footprint_fresh else {}
        footprint_sample = (session_id, footprints.get('generated_at')) if footprint_fresh else None
        if footprint_sample != self.footprint_cache_sample:
            self.footprint_cache_sample, self.footprint_cache = footprint_sample, {}
        detail_by_id = {v.get('entity_id'): v for v in details.get('vehicles', [])} if details.get('session_id') == session_id else {}
        trains = []
        if save_id == expected_save:
            for v in raw.get('vehicles', []):
                eid, t = v.get('current_edge_id'), v.get('current_edge_param')
                if eid not in self.territory.graph.edges and v['entity_id'] not in rail_ids: continue
                owner = self.territory.owner(eid, t)
                head_resource = self.territory.resource(eid, t)
                head_location = None
                if owner is None and v.get('position'):
                    head_location = self.territory.locate(v['position'])
                    if head_location['status'] == 'REGION_CONFIRMED':
                        owner = head_location['region']
                        head_resource = head_location['best']['resource']
                envelope = (footprint_by_id.get(v['entity_id']) or {}).get('train_envelope')
                if v['entity_id'] not in self.footprint_cache:
                    self.footprint_cache[v['entity_id']] = self._body_regions(
                        envelope)
                complete, occupied, footprint_status, part_locations = self.footprint_cache[v['entity_id']]
                footprint_item = footprint_by_id.get(v['entity_id']) or {}
                route_window = footprint_item.get('route_window') or {}
                offset = ((v.get('current_edge_index') - route_window.get('start_index'))
                          if isinstance(v.get('current_edge_index'), int) and isinstance(route_window.get('start_index'), int) else None)
                window_ids = route_window.get('edge_ids') or []
                route_current = (isinstance(route_window.get('current_index'), int)
                                 and isinstance(offset, int) and 0 <= offset < len(window_ids)
                                 and v.get('current_edge_index') >= route_window.get('current_index')
                                 and window_ids[offset] == eid)
                detail = detail_by_id.get(v['entity_id']) or {}
                if route_current:
                    route_ids = window_ids
                    route_directions = route_window.get('directions') or []
                    route_indices = route_window.get('transport_indices') or []
                    route_start = route_window.get('start_index')
                    route_sampled = footprints.get('generated_at')
                else:
                    route_current = (detail.get('current_edge_id') == eid
                                     and detail.get('current_edge_index') == v.get('current_edge_index'))
                    route_ids = detail.get('path_edge_ids', []) if route_current else []
                    route_directions = detail.get('path_edge_directions', []) if route_current else []
                    route_indices = detail.get('path_transport_indices', []) if route_current else []
                    route_start = 0 if route_current else None
                    route_sampled = details.get('generated_at') if route_current else None
                route = {'status': 'ENGINE_PATH_CURRENT' if route_current else 'STALE_OR_MISMATCHED',
                         'edge_ids': route_ids, 'directions': route_directions,
                         'transport_indices': route_indices, 'start_index': route_start,
                         'current_index': v.get('current_edge_index') if route_current else None,
                         'sampled_at': route_sampled}
                trains.append({'vehicle_id': v['entity_id'], 'line_id': v.get('line_id'),
                               'edge_id': eid, 'edge_param': t, 'forward': v.get('current_edge_direction'),
                               'position': v.get('position'),
                               'head_region': owner, 'speed_mps': v.get('speed_mps'),
                               'brake_decel_mps2': footprint_item.get('brake_decel_mps2'),
                               'head_resource': head_resource,
                               'head_location_status': head_location['status'] if head_location else 'DIRECT_EDGE',
                               'footprint_complete': complete, 'occupied_regions': occupied,
                               'footprint_status': footprint_status,
                               'footprint_sampled_at': footprints.get('generated_at') if complete else None,
                               'footprint_observed_at': footprint_observed_at if complete else None,
                               'footprint_update_count': footprint_update_count if complete else None,
                               'train_length_m': self._train_length(envelope) if complete else None,
                               'body_samples': ([{'position': part['position'],
                                                  'radius_m': max(part['bounds']['max']['x']-part['bounds']['min']['x'],
                                                                  part['bounds']['max']['y']-part['bounds']['min']['y'])/2}
                                                 for part in (envelope or {}).get('parts', [])] if complete else []),
                               'part_locations': part_locations if complete else [], 'route': route,
                               'quality': 'FULL_BODY' if complete else ('HEAD_ONLY' if owner else 'POSITION_UNRESOLVED')})
        clock = raw.get('simulation_clock', {})
        observation = (session_id, sampled, clock.get('update_count'), clock.get('game_time'), clock.get('speedup'), save_id, verified, fresh)
        if observation != self.last_observation:
            self.sequence += 1; self.last_observation = observation
        simulation_running = isinstance(clock.get('speedup'), (float, int)) and clock['speedup'] > 0
        if not simulation_running: issues.append('SIMULATION_NOT_RUNNING')
        return {'schema_version': 1, 'save_id': save_id, 'session_id': session_id,
                'topology_version': self.version, 'sequence': self.sequence, 'sampled_at': sampled,
                'collected_at': now, 'simulation_clock': clock, 'trains': trains,
                'quality': {'fresh': fresh and save_id == expected_save, 'session_verified': verified,
                            'simulation_running': simulation_running,
                            'issues': issues, 'footprint': 'FRESH' if footprint_fresh else 'STALE_OR_UNAVAILABLE',
                            'footprint_sampled_at': footprints.get('generated_at'),
                            'footprint_observed_at': footprint_observed_at,
                            'signal_sampled_at': signals.get('generated_at')}}
