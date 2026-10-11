from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp_server/src'))
from tpf2_mcp.dispatch_runtime.geometry import RailGraph
from tpf2_mcp.dispatch_runtime.boundaries import BoundaryCalibrator, calibrate_all, normalize_directional_signals
from tpf2_mcp.dispatch_runtime.territory import TerritoryIndex, repartition
from tpf2_mcp.dispatch_runtime.storage import RegionalStore, SnapshotStore, atomic_json
from tpf2_mcp.dispatch_runtime.contracts import validate_command
from tpf2_mcp.dispatch_runtime.handover import HandoverExecutor, annotate_transfer_evidence, scope_key
from tpf2_mcp.dispatch_runtime.decision import decide
from tpf2_mcp.dispatch_runtime.collector import RegionalCollector
from tpf2_mcp.dispatch_runtime.routing import boundary_candidates
from tpf2_mcp.dispatch_runtime.admission import evaluate_admission, stopping_distance
from tpf2_mcp.dispatch_runtime.receiving import receiving_evidence
from tpf2_mcp.save_scope import snapshot_save_id
from tests.test_dispatch_regions import fixture


def anchor():
    return {'anchor_id': 'fixed', 'label': 'B1', 'revision': 1, 'position': {'x': 50, 'y': 0, 'z': 0},
            'positive_tangent': {'x': 1, 'y': 0, 'z': 0}, 'negative_region': 'A', 'positive_region': 'B',
            'search_policy': {'xy_radius_m': 10, 'max_vertical_offset_m': 5, 'max_axis_angle_degrees': 25, 'max_signal_path_distance_m': 500}}


def signal(sid, eid, param, forward):
    return {'entity_id': sid, 'edge_id': eid, 'edge_param': param, 'signal_types': [0],
            'direction_status': 'ENGINE_QUERY_CONFIRMED', 'directions': [forward]}


class CalibrationTests(unittest.TestCase):
    def setUp(self): self.territories, _, self.net = fixture()

    def test_projection_uses_curve_and_height(self):
        self.net['edges'][0].update(tangent0={'x': 100, 'y': 100, 'z': 0}, tangent1={'x': 100, 'y': -100, 'z': 0})
        g = RailGraph(self.net); p = g.point(11, .4)
        t, _, distance = g.project(11, p)
        self.assertAlmostEqual(.4, t, places=5); self.assertLess(distance, .001)

    def test_endpoints_reversed_keep_region_orientation(self):
        self.net['edges'][0].update(node0=2, node1=1)
        result = BoundaryCalibrator(RailGraph(self.net), [], 'changed').bind(anchor())
        self.assertEqual('BOUND', result['status']); self.assertFalse(result['positive_forward'])

    def test_parallel_line_ambiguity_and_grade_separation(self):
        self.net['nodes'] += [{'entity_id': 8, 'position': {'x': 0, 'y': 4, 'z': 0}}, {'entity_id': 9, 'position': {'x': 100, 'y': 4, 'z': 0}}]
        self.net['edges'].append({'entity_id': 19, 'node0': 8, 'node1': 9})
        self.assertEqual('AMBIGUOUS', BoundaryCalibrator(RailGraph(self.net), [], 'changed').bind(anchor())['status'])
        for n in self.net['nodes'][-2:]: n['position']['z'] = 20
        self.assertEqual('BOUND', BoundaryCalibrator(RailGraph(self.net), [], 'changed').bind(anchor())['status'])

    def test_original_id_requires_same_hash_and_coordinate(self):
        a = anchor(); a['seed_evidence'] = {'topology_sha256': 'hash', 'edge_id': 11}
        self.net['nodes'] += [{'entity_id': 8, 'position': {'x': 0, 'y': 4}}, {'entity_id': 9, 'position': {'x': 100, 'y': 4}}]
        self.net['edges'].append({'entity_id': 19, 'node0': 8, 'node1': 9})
        g = RailGraph(self.net)
        self.assertEqual('BOUND', BoundaryCalibrator(g, [], 'hash').bind(a)['status'])
        self.assertEqual('AMBIGUOUS', BoundaryCalibrator(g, [], 'different').bind(a)['status'])

    def test_split_track_rematches_without_id(self):
        self.net['nodes'].append({'entity_id': 4, 'position': {'x': 50, 'y': 0}})
        self.net['edges'] = [self.net['edges'][1], {'entity_id': 20, 'node0': 1, 'node1': 4}, {'entity_id': 21, 'node0': 4, 'node1': 2}]
        self.assertEqual('SPLIT_AT_FIXED_COORDINATE', BoundaryCalibrator(RailGraph(self.net), [], 'new').bind(anchor())['method'])

    def test_directional_walk_ignores_nearby_disconnected_signal(self):
        g = RailGraph(self.net)
        signals = [signal(1, 11, .2, True), signal(2, 12, .4, True), signal(3, 12, .6, False), signal(4, 11, .1, False)]
        result = BoundaryCalibrator(g, signals, 'hash').calibrate(anchor())
        self.assertEqual('CALIBRATED', result['status'])
        self.assertEqual(2, result['directions']['negative_to_positive']['exit']['signal_id'])
        self.assertFalse(result['control_ready'])
        # Delete/replace signal IDs without moving the administrative anchor.
        signals[0]['entity_id'] = 900
        result = BoundaryCalibrator(g, signals, 'hash').calibrate(anchor())
        self.assertEqual(900, result['directions']['negative_to_positive']['entry']['signal_id'])
        self.assertEqual('fixed', result['anchor_id'])

    def test_unknown_direction_and_junction_are_not_permission(self):
        s = signal(1, 11, .3, True); s['direction_status'] = 'UNKNOWN'
        self.assertEqual('DIRECTION_UNKNOWN', BoundaryCalibrator(RailGraph(self.net), [s], 'h').calibrate(anchor())['status'])
        self.net['nodes'].append({'entity_id': 4, 'position': {'x': 150, 'y': 30}})
        self.net['edges'].append({'entity_id': 13, 'node0': 2, 'node1': 4})
        result = BoundaryCalibrator(RailGraph(self.net), [signal(1, 11, .2, True)], 'h').calibrate(anchor())
        self.assertEqual('AMBIGUOUS_ROUTE', result['directions']['negative_to_positive']['exit']['status'])

    def test_branch_can_follow_explicit_train_route_but_not_jump_tracks(self):
        self.net['nodes'].append({'entity_id': 4, 'position': {'x': 150, 'y': 30}})
        self.net['edges'].append({'entity_id': 13, 'node0': 2, 'node1': 4})
        c = BoundaryCalibrator(RailGraph(self.net), [signal(1, 13, .8, True)], 'h')
        binding = c.bind(anchor())
        self.assertEqual('FOUND', c.search(binding, True, True, 500, [[11, True], [13, True]])['status'])
        self.assertEqual('ROUTE_MISMATCH', c.search(binding, True, True, 500, [[11, True], [13, False]])['status'])

    def test_current_engine_route_resolves_train_specific_boundary_signals(self):
        g = RailGraph(self.net)
        signals = [signal(1, 11, .2, True), signal(2, 12, .4, True),
                   signal(3, 12, .6, False), signal(4, 11, .1, False)]
        compiler = BoundaryCalibrator(g, signals, 'hash')
        calibration = {'anchors': [compiler.calibrate(anchor())]}
        train = {'vehicle_id': 9, 'edge_id': 11, 'edge_param': .3,
                 'route': {'status': 'ENGINE_PATH_CURRENT', 'edge_ids': [11, 12],
                           'directions': [True, True], 'start_index': 0, 'current_index': 0}}
        rows, observations = boundary_candidates(train, calibration, compiler,
                                                  TerritoryIndex(self.territories, g))
        self.assertEqual([], observations)
        self.assertTrue(rows[0]['legal_route_verified'])
        self.assertTrue(rows[0]['signal_protection_verified'])
        self.assertEqual('A', rows[0]['from_region'])
        self.assertEqual('B', rows[0]['to_region'])
        self.assertAlmostEqual(20, rows[0]['distance_m'], places=1)

    def test_engine_route_ignores_node_entities_but_still_uses_physical_adjacency(self):
        g = RailGraph(self.net)
        compiler = BoundaryCalibrator(g, [signal(1, 11, .2, True), signal(2, 12, .4, True)], 'hash')
        calibration = {'anchors': [compiler.calibrate(anchor())]}
        train = {'vehicle_id': 9, 'edge_id': 11, 'edge_param': .3,
                 'route': {'status': 'ENGINE_PATH_CURRENT', 'edge_ids': [11, 2, 12],
                           'directions': [True, True, True], 'start_index': 0, 'current_index': 0}}
        rows, _ = boundary_candidates(train, calibration, compiler, TerritoryIndex(self.territories, g))
        self.assertTrue(rows[0]['legal_route_verified'])

    def test_engine_route_legality_is_distinct_from_signal_protection(self):
        g = RailGraph(self.net); compiler = BoundaryCalibrator(g, [], 'hash')
        calibration = {'anchors': [compiler.calibrate(anchor())]}
        train = {'vehicle_id': 9, 'edge_id': 11, 'edge_param': .3,
                 'route': {'status': 'ENGINE_PATH_CURRENT', 'edge_ids': [11, 12],
                           'directions': [True, True], 'start_index': 0, 'current_index': 0}}
        rows, observations = boundary_candidates(train, calibration, compiler, TerritoryIndex(self.territories, g))
        self.assertTrue(rows[0]['legal_route_verified'])
        self.assertFalse(rows[0]['signal_protection_verified'])
        self.assertEqual('BOUNDARY_SIGNAL_PROTECTION_UNAVAILABLE', observations[0]['code'])

    def test_normalization_requires_engine_receipt_and_geometry(self):
        item = {'object_entity_id': 1, 'edge_entity_id': 11, 'position': {'x': 20, 'y': 0}, 'signal_types': [0],
                'direction_evidence': [{'status': 'ENGINE_QUERY_CONFIRMED', 'transport_entity': 11, 'signal_index': 0,
                    'queries': [{'ok': True, 'matched': True, 'reversed': False, 'signal_entity': 1, 'signal_index': 0},
                                {'ok': True, 'matched': False, 'reversed': True}],
                    'geometry': {'params': {'pos': [{'x': 0, 'y': 0}, {'x': 100, 'y': 0}]}}}]}
        raw = {'signal_edge_objects': [item]}; graph = RailGraph(self.net)
        self.assertEqual([True], normalize_directional_signals(raw, graph)[0]['directions'])
        item['direction_evidence'][0]['queries'][0]['signal_entity'] = 2
        self.assertEqual([], normalize_directional_signals(raw, graph)[0]['directions'])

    def test_xy_only_transport_geometry_follows_base_edge_grade(self):
        self.net['nodes'][1]['position']['z'] = 20
        item = {'object_entity_id': 1, 'edge_entity_id': 11, 'position': {'x': 5, 'y': 0, 'z': 1}, 'signal_types': [0],
                'direction_evidence': [{'status': 'ENGINE_QUERY_CONFIRMED', 'transport_entity': 11, 'signal_index': 0,
                    'queries': [{'ok': True, 'matched': True, 'reversed': False, 'signal_entity': 1, 'signal_index': 0},
                                {'ok': True, 'matched': False, 'reversed': True}],
                    'geometry': {'params': {'pos': [{'x': 0, 'y': 0}, {'x': 100, 'y': 0}]}}}]}
        result = normalize_directional_signals({'signal_edge_objects': [item]}, RailGraph(self.net))[0]
        self.assertEqual('ENGINE_QUERY_CONFIRMED', result['direction_status'])
        self.assertEqual([True], result['directions'])

    def test_coverage_detects_missing_cut_and_new_bypass(self):
        g = RailGraph(self.net)
        cal = calibrate_all({'anchors': [anchor()]}, g, [], {'topology_version': 'hash'})
        self.assertTrue(TerritoryIndex(self.territories, g).audit(cal)['boundary_coverage_complete'])
        cal['anchors'] = []
        self.assertFalse(TerritoryIndex(self.territories, g).audit(cal)['boundary_coverage_complete'])
        self.net['edges'].append({'entity_id': 15, 'node0': 1, 'node1': 3})
        with self.assertRaises(ValueError): TerritoryIndex(self.territories, RailGraph(self.net))
        g = RailGraph(self.net)
        cal = calibrate_all({'anchors': [anchor()]}, g, [], {'topology_version': 'new'})
        doc = repartition(self.territories, g, cal, 'new')
        audit = TerritoryIndex(doc, g).audit(cal)
        self.assertTrue(audit['administrative_coverage_complete'])
        self.assertTrue(audit['review_required'])

    def test_body_coordinate_resolves_region_but_refuses_cross_region_parallel_ambiguity(self):
        territory = TerritoryIndex(self.territories, RailGraph(self.net))
        self.assertEqual('A', territory.locate({'x': 20, 'y': 1, 'z': 0})['region'])
        self.net['nodes'] += [{'entity_id': 8, 'position': {'x': 0, 'y': 2, 'z': 0}},
                              {'entity_id': 9, 'position': {'x': 100, 'y': 2, 'z': 0}}]
        self.net['edges'].append({'entity_id': 19, 'node0': 8, 'node1': 9})
        self.territories['segments'].append({'edge_id': 19, 'start': 0, 'end': 1, 'region': 'B'})
        result = TerritoryIndex(self.territories, RailGraph(self.net)).locate({'x': 20, 'y': 1, 'z': 0})
        self.assertEqual('REGION_AMBIGUOUS', result['status'])


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.store = RegionalStore(self.root); self.executor = HandoverExecutor(self.store); self.n = 0
        self.frame = {'schema_version': 1, 'save_id': 's', 'session_id': 'session', 'topology_version': 'v', 'sequence': 1, 'sampled_at': 100.,
                      'quality': {'fresh': True, 'session_verified': True, 'simulation_running': True, 'territory_verified': True, 'issues': []},
                      'trains': [{'vehicle_id': 1, 'head_region': 'A', 'footprint_complete': True,
                                  'footprint_update_count': 1, 'occupied_regions': ['A']}]}

    def tearDown(self): self.store.close(); self.tmp.cleanup()

    def cmd(self, action, actor='A', **extra):
        self.n += 1
        return {'schema_version': 1, 'command_id': str(self.n), 'save_id': 's', 'session_id': 'session', 'topology_version': 'v',
                'based_on_sequence': self.frame['sequence'], 'expires_at': 110., 'vehicle_id': 1, 'actor_region': actor, 'type': action, **extra}

    def execute(self, action, actor='A', **extra): return self.executor.execute(self.cmd(action, actor, **extra), self.frame, 100.)

    def reserve(self):
        self.execute('REGISTER_TRAIN')
        self.frame['trains'][0]['admission'] = {'verified': True, 'sequence': self.frame['sequence'], 'expires_at': 120,
            'anchor_id': 'b1', 'from_region': 'A', 'to_region': 'B', 'resources': ['approach', 'exit'], 'conflicting_vehicle_ids': []}
        return self.execute('REQUEST_HANDOVER', handover_id='h1', anchor_id='b1', target_region='B', resources=['approach', 'exit'], lease_seconds=15)

    def enter(self):
        self.assertEqual('REQUESTED', self.reserve()['status'])
        self.assertEqual('ACCEPTED', self.execute('ACCEPT_HANDOVER', 'B', handover_id='h1')['status'])
        self.frame['sequence'] = 2
        self.frame['trains'][0].update(head_region='B', crossed_anchor_id='b1', occupied_regions=['A', 'B'], footprint_update_count=2)
        self.assertEqual('ENTERED', self.execute('ENTER_REGION', 'B', handover_id='h1')['status'])

    def test_transfer_owner_but_keep_resources_until_two_tail_samples(self):
        self.enter()
        self.assertFalse(self.executor.authority(self.frame, 1, 'A', 100))
        self.assertTrue(self.executor.authority(self.frame, 1, 'B', 100))
        self.assertEqual('REJECTED', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])
        self.frame['sequence'] = 3
        self.frame['trains'][0].update(occupied_regions=['B'], cleared_anchor_id='b1', footprint_update_count=3)
        self.assertEqual('CLEARING', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])
        self.assertEqual(2, len(self.store.view(scope_key(self.frame))['reservations']))
        self.assertEqual('REJECTED', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])
        self.frame['sequence'] = 4
        self.frame['trains'][0]['footprint_update_count'] = 4
        self.assertEqual('RELEASED', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])
        self.assertEqual([], self.store.view(scope_key(self.frame))['reservations'])

    def test_replay_and_restart_are_idempotent(self):
        command = self.cmd('REGISTER_TRAIN')
        first = self.executor.execute(command, self.frame, 100)
        self.store.close(); self.store = RegionalStore(self.root); self.executor = HandoverExecutor(self.store)
        self.assertEqual(first, self.executor.execute(command, self.frame, 100))
        command['actor_region'] = 'B'
        with self.assertRaises(ValueError): self.executor.execute(command, self.frame, 100)

    def test_scope_and_stale_frames_reject(self):
        for change in ({'session_id': 'other'}, {'topology_version': 'other'}, {'expires_at': 99}):
            c = self.cmd('REGISTER_TRAIN'); c.update(change)
            self.assertEqual('REJECTED', self.executor.execute(c, self.frame, 100)['status'])
        self.frame['sampled_at'] = 90
        self.assertEqual('OBSERVATION_STALE', self.execute('REGISTER_TRAIN')['reason'])

    def test_conflicting_reservation_is_atomic(self):
        self.reserve()
        train = deepcopy(self.frame['trains'][0]); train['vehicle_id'] = 2
        self.frame['trains'].append(train)
        c = self.cmd('REGISTER_TRAIN', vehicle_id=2); self.executor.execute(c, self.frame, 100)
        result = self.execute('REQUEST_HANDOVER', vehicle_id=2, handover_id='h2', anchor_id='b1', target_region='B', resources=['approach', 'exit'], lease_seconds=15)
        self.assertEqual('RESOURCE_RESERVED', result['reason'])
        self.assertEqual(1, len(self.store.view(scope_key(self.frame))['handovers']))

    def test_expiry_does_not_free_possibly_occupied_track(self):
        self.reserve(); self.executor.expire(self.frame, 116)
        view = self.store.view(scope_key(self.frame))
        self.assertEqual('FROZEN', view['handovers'][0]['state']); self.assertEqual(2, len(view['reservations']))
        self.assertFalse(self.executor.authority(self.frame, 1, 'A', 100))

    def test_missing_tail_after_first_clear_sample_resets_proof(self):
        self.enter(); self.frame['sequence'] = 3
        t = self.frame['trains'][0]; t.update(occupied_regions=['B'], cleared_anchor_id='b1', footprint_update_count=3)
        self.execute('RELEASE_TAIL', 'B', handover_id='h1')
        t['footprint_complete'] = False; self.executor.expire(self.frame, 100)
        t['footprint_complete'] = True; t['footprint_update_count'] = 4; self.frame['sequence'] = 4
        self.assertEqual('CLEARING', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])

    def test_cancel_requires_complete_source_occupancy(self):
        self.reserve(); self.frame['trains'][0]['footprint_complete'] = False
        self.assertEqual('REJECTED', self.execute('CANCEL_HANDOVER', handover_id='h1')['status'])
        self.frame['trains'][0]['footprint_complete'] = True
        self.assertEqual('CANCELLED', self.execute('CANCEL_HANDOVER', handover_id='h1')['status'])

    def test_decision_uses_protocol_and_refuses_legacy_session(self):
        before = deepcopy(self.frame)
        out = decide(self.frame, self.store.view(scope_key(self.frame)), 100)
        self.assertEqual('REGISTER_TRAIN', out['commands'][0]['type']); self.assertEqual(before, self.frame)
        self.frame['quality']['session_verified'] = False
        self.assertEqual([], decide(self.frame, self.store.view(scope_key(self.frame)), 100)['commands'])

    def test_active_handover_derives_crossing_and_tail_clearance_from_complete_body(self):
        self.reserve()
        self.assertEqual('ACCEPTED', self.execute('ACCEPT_HANDOVER', 'B', handover_id='h1')['status'])
        train = self.frame['trains'][0]
        train.update(head_region='B', occupied_regions=['A', 'B'], footprint_update_count=2)
        annotate_transfer_evidence(self.frame, self.store.view(scope_key(self.frame)))
        self.assertEqual('b1', train['crossed_anchor_id'])
        self.assertEqual('ENTERED', self.execute('ENTER_REGION', 'B', handover_id='h1')['status'])
        train.update(occupied_regions=['B'], footprint_update_count=3)
        annotate_transfer_evidence(self.frame, self.store.view(scope_key(self.frame)))
        self.assertEqual('b1', train['cleared_anchor_id'])

    def test_uncontrolled_crossing_reconciles_shadow_owner_after_two_footprint_updates(self):
        self.execute('REGISTER_TRAIN')
        train = self.frame['trains'][0]
        train.update(head_region='B', occupied_regions=['B'], footprint_update_count=2)
        first = decide(self.frame, self.store.view(scope_key(self.frame)), 100)
        self.assertEqual('RECONCILE_OBSERVED_OWNER', first['commands'][0]['type'])
        self.assertEqual('RECONCILE_OBSERVATION_PENDING',
                         self.executor.execute(first['commands'][0], self.frame, 100)['status'])
        # Repeating the same footprint frame cannot manufacture confirmation.
        self.frame['sequence'] = 2
        repeated = decide(self.frame, self.store.view(scope_key(self.frame)), 100)
        self.assertEqual('RECONCILE_OBSERVATION_PENDING',
                         self.executor.execute(repeated['commands'][0], self.frame, 100)['status'])
        train['footprint_update_count'] = 3
        self.frame['sequence'] = 3
        confirmed = decide(self.frame, self.store.view(scope_key(self.frame)), 100)
        self.assertEqual('OBSERVED_OWNER_RECONCILED',
                         self.executor.execute(confirmed['commands'][0], self.frame, 100)['status'])
        self.assertEqual('B', self.store.view(scope_key(self.frame))['trains'][0]['owner'])

    def test_atomic_snapshot_scope_and_retention(self):
        snapshots = SnapshotStore(self.root, keep=2)
        for seq in range(1, 5): self.frame['sequence'] = seq; snapshots.publish(self.frame)
        self.assertEqual(4, snapshots.read()['sequence']); self.assertEqual(2, len(list((self.root/'frames').glob('*.json'))))
        (self.root/'current.json').write_text(json.dumps({'frame': '../outside.json'}))
        with self.assertRaises(ValueError): snapshots.read()

    def test_windows_reader_collision_retries_without_truncating(self):
        import os
        real_replace = os.replace
        attempts = []
        def replace(source, target):
            attempts.append(target)
            if len(attempts) == 1: raise PermissionError('reader denied delete sharing')
            return real_replace(source, target)
        atomic_json(self.root, 'test.json', {'value': 'old'})
        with patch('tpf2_mcp.dispatch_runtime.storage.os.replace', side_effect=replace):
            atomic_json(self.root, 'test.json', {'value': 'new'})
        self.assertEqual(2, len(attempts))
        self.assertEqual({'value': 'new'}, json.loads((self.root/'test.json').read_text()))

    def test_command_contract_rejects_malformed_and_duplicate_resources(self):
        for change in ({'vehicle_id': True}, {'based_on_sequence': -1}, {'expires_at': float('nan')}, {'extra': 2}):
            c = self.cmd('REGISTER_TRAIN'); c.update(change)
            with self.assertRaises(ValueError): validate_command(c)
        c = self.cmd('REQUEST_HANDOVER', handover_id='h', anchor_id='a', target_region='B', resources=['x','x'], lease_seconds=10)
        with self.assertRaises(ValueError): validate_command(c)

    def test_json_schema_matches_real_protocol(self):
        try: import jsonschema
        except ImportError: self.skipTest('install tests/requirements-regional.txt')
        directory = Path(__file__).resolve().parents[1]/'protocol/dispatch'
        c = self.cmd('REGISTER_TRAIN')
        for name, value in [('regional-command', c), ('regional-frame', self.frame),
                            ('regional-result', self.executor.execute(c, self.frame, 100))]:
            schema = json.loads((directory/(name+'.schema.json')).read_text())
            jsonschema.Draft202012Validator(schema).validate(value)

    def test_pause_and_missing_train_cannot_release_resources(self):
        self.enter(); self.frame['sequence'] = 3
        train = self.frame['trains'][0]; train.update(occupied_regions=['B'], cleared_anchor_id='b1', footprint_update_count=3)
        self.execute('RELEASE_TAIL', 'B', handover_id='h1')
        self.frame['trains'] = []; self.executor.expire(self.frame, 100)
        self.frame['trains'] = [train]; self.frame['sequence'] = 4
        self.assertEqual('CLEARING', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['status'])
        self.frame['quality']['simulation_running'] = False
        self.frame['sequence'] = 5
        self.assertEqual('SIMULATION_NOT_RUNNING', self.execute('RELEASE_TAIL', 'B', handover_id='h1')['reason'])

    def test_collection_requires_world_and_signals_from_same_session(self):
        territory, _, net = fixture()
        state = {'towns': [], 'game': {'world_entity': '1'}, 'metadata': {'session_id': 'current'}}
        territory['save_id'] = snapshot_save_id(state)
        collector = RegionalCollector(self.root, TerritoryIndex(territory, RailGraph(net)), 'hash')
        raw = {'generated_at': 100, 'session_id': 'current', 'simulation_clock': {'speedup': 1, 'update_count': 10},
               'vehicles': [{'entity_id': 1, 'current_edge_id': 11, 'current_edge_param': .2}]}
        for filename, value in [('state.json', state), ('heartbeat.json', {'bridge_ready': True, 'last_update': 100}),
                ('operational-telemetry-signals.json', {'session_id': 'current'}), ('operational-telemetry-vehicle_positions.json', raw)]:
            atomic_json(self.root, 'bridge/'+filename, value)
        first = collector.collect(100)
        self.assertTrue(first['quality']['session_verified']); self.assertEqual('A', first['trains'][0]['head_region'])
        self.assertEqual(first['sequence'], collector.collect(100.2)['sequence'])
        state['metadata']['session_id'] = 'old'
        atomic_json(self.root, 'bridge/state.json', state)
        self.assertFalse(collector.collect(100.4)['quality']['session_verified'])

    def test_collection_uses_fresh_complete_body_frame_and_marks_boundary_overlap(self):
        territory, _, net = fixture()
        state = {'towns': [], 'game': {'world_entity': '1'}, 'metadata': {'session_id': 'current'}}
        territory['save_id'] = snapshot_save_id(state)
        collector = RegionalCollector(self.root, TerritoryIndex(territory, RailGraph(net)), 'hash')
        raw = {'generated_at': 100, 'session_id': 'current',
               'simulation_clock': {'speedup': 1, 'update_count': 10},
               'vehicles': [{'entity_id': 1, 'current_edge_id': 11, 'current_edge_param': .55,
                             'current_edge_index': 0, 'position': {'x': 55, 'y': 0, 'z': 0}}]}
        body = {'generated_at': 100, 'session_id': 'current', 'simulation_clock': {'update_count': 9}, 'vehicles': [{'entity_id': 1,
                'route_window': {'start_index': 0, 'current_index': 0, 'edge_ids': [11, 12],
                                 'directions': [True, True], 'transport_indices': [0, 0]},
                'train_envelope': {'complete': True, 'expected_parts': 2, 'parts': [
                    {'entity_id': 10, 'position': {'x': 45, 'y': 0, 'z': 0},
                     'bounds': {'min': {'x': 40, 'y': -2, 'z': -1}, 'max': {'x': 50, 'y': 2, 'z': 1}}},
                    {'entity_id': 11, 'position': {'x': 60, 'y': 0, 'z': 0},
                     'bounds': {'min': {'x': 50, 'y': -2, 'z': -1}, 'max': {'x': 65, 'y': 2, 'z': 1}}}]}}]}
        values = [('state.json', state), ('heartbeat.json', {'bridge_ready': True, 'last_update': 100}),
                  ('operational-telemetry-signals.json', {'session_id': 'current'}),
                  ('operational-telemetry-vehicle_positions.json', raw),
                  ('operational-telemetry-train_footprints.json', body),
                  ('live-rail-state.json', {'save_id': territory['save_id'], 'vehicles': [{'entity_id': 1}]})]
        for filename, value in values: atomic_json(self.root, 'bridge/'+filename, value)
        train = collector.collect(100)['trains'][0]
        self.assertTrue(train['footprint_complete'])
        self.assertEqual(['A', 'B'], train['occupied_regions'])
        self.assertEqual('ENGINE_PATH_CURRENT', train['route']['status'])
        self.assertEqual([11, 12], train['route']['edge_ids'])
        self.assertEqual(9, train['footprint_update_count'])
        self.assertGreater(train['train_length_m'], 20)
        raw['generated_at'] = 101
        raw['simulation_clock']['update_count'] = 11
        raw['vehicles'][0].update(current_edge_id=12, current_edge_index=1, current_edge_param=.1,
                                  position={'x': 110, 'y': 0, 'z': 0})
        atomic_json(self.root, 'bridge/operational-telemetry-vehicle_positions.json', raw)
        self.assertEqual('ENGINE_PATH_CURRENT', collector.collect(101)['trains'][0]['route']['status'])
        body['generated_at'] = 90
        atomic_json(self.root, 'bridge/operational-telemetry-train_footprints.json', body)
        self.assertFalse(collector.collect(100.2)['trains'][0]['footprint_complete'])

    def test_admission_requires_explicit_braking_and_receiving_evidence(self):
        train = {'vehicle_id': 1, 'speed_mps': 20., 'footprint_complete': True, 'train_length_m': 200.}
        candidate = {'legal_route_verified': True, 'signal_protection_verified': True,
                     'distance_m': 1000., 'resources': ['x']}
        denied = evaluate_admission(train, candidate, {'verified': False, 'service_deceleration_mps2': .5},
                                    {'verified': False, 'clear_length_m': 500., 'conflicting_vehicle_ids': []}, 3, 100.)
        self.assertEqual(['BRAKING_ENVELOPE', 'RECEIVING_SPACE'], denied['blockers'])
        allowed = evaluate_admission(train, candidate, {'verified': True, 'service_deceleration_mps2': .5},
                                     {'verified': True, 'clear_length_m': 500., 'conflicting_vehicle_ids': []}, 3, 100.)
        self.assertTrue(allowed['verified'])
        self.assertAlmostEqual(490., stopping_distance(20., .5))

    def test_braking_evidence_requires_three_distinct_episodes(self):
        scope = scope_key(self.frame)
        self.store.observe_braking(scope, [(1, .8, 10), (1, .9, 10), (1, .7, 11)])
        self.assertFalse(self.store.braking(scope, 1)['verified'])
        self.store.observe_braking(scope, [(1, 0., 12), (1, .6, 13), (1, 0., 14), (1, .55, 15)])
        evidence = self.store.braking(scope, 1)
        self.assertTrue(evidence['verified'])
        self.assertEqual(3, evidence['samples'])
        self.assertEqual(.35, evidence['service_deceleration_mps2'])

    def test_receiving_space_uses_other_trains_complete_body_extent(self):
        territories, _, net = fixture(); territory = TerritoryIndex(territories, RailGraph(net))
        frame = {'quality': {'footprint': 'FRESH'}, 'trains': [
            {'vehicle_id': 1, 'footprint_complete': True, 'body_samples': []},
            {'vehicle_id': 2, 'footprint_complete': True,
             'body_samples': [{'position': {'x': 150, 'y': 0, 'z': 2}, 'radius_m': 12}]}]}
        candidate = {'receiving_edge_ids': [12], 'receiving_length_m': 100.}
        evidence = receiving_evidence(frame, candidate, territory, 1)
        self.assertEqual([2], evidence['conflicting_vehicle_ids'])
        frame['trains'][1]['body_samples'][0]['position']['y'] = 100
        self.assertEqual([], receiving_evidence(frame, candidate, territory, 1)['conflicting_vehicle_ids'])


if __name__ == '__main__': unittest.main()
