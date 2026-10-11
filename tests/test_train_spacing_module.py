import configparser
import copy
import math
from pathlib import Path
import tempfile
import unittest

from test_train_spacing import NETWORK, train
from tpf2_mcp.algorithms.train_spacing import TrainSpacingController, native_batch_sink
from tpf2_mcp.algorithms.train_spacing.engine import _body_samples
from tpf2_mcp.control_system import NativeLeaseWriter


def frame():
    return {'sampled_at': 1000, 'vehicles': [train(1, 10, 0, .8, 20, [70, 80]),
                                          train(2, 11, 1, .5, 12, [130, 150])]}


class SpacingModuleTests(unittest.TestCase):
    def evaluate(self, live=None, **kwargs):
        return TrainSpacingController(NETWORK).step(live or frame(), now=1000, **kwargs)

    def test_actual_both_body_ends_and_equation(self):
        command = self.evaluate()['commands'][0]
        self.assertAlmostEqual(40, command['gap_m'], places=3)
        self.assertAlmostEqual(85, command['head_chainage_m'], places=3)
        self.assertAlmostEqual(125, command['leader_tail_chainage_m'], places=3)
        v = command['speed_mps']
        self.assertLessEqual(v*3 + v*v/(2*.35), 15)

    def test_nearest_leader_tail_diagnostic_not_last_leader(self):
        live = frame()
        live['vehicles'].append(train(3, 12, 2, .8, 20, [270, 280]))
        command = self.evaluate(live)['commands'][0]
        self.assertEqual(2, command['leader_vehicle_id'])
        self.assertAlmostEqual(125, command['leader_tail_chainage_m'], places=3)

    def test_no_brake_on_leader_does_not_hide_it(self):
        live = frame()
        live['vehicles'][1].pop('brake_decel_mps2')
        self.assertEqual(2, self.evaluate(live)['commands'][0]['leader_vehicle_id'])

    def test_missing_body_blocks_clear_track_interpretation(self):
        live = frame()
        live['vehicles'][1]['body_samples'] = []
        result = self.evaluate(live)
        self.assertFalse(result['commands'])
        self.assertIn('TRAFFIC_OBSERVATION_INCOMPLETE', [d['reason'] for d in result['decisions']])

    def test_stale_frame_and_body(self):
        for change in ('frame', 'body'):
            live = frame()
            if change == 'frame':
                live['sampled_at'] = 990
            else:
                live['vehicles'][1]['footprint_sampled_at'] = 990
            self.assertFalse(self.evaluate(live)['commands'])

    def test_unknown_direction_and_discontinuous_route(self):
        for directions in ([True, None, True], [True, False, True]):
            live = frame()
            live['vehicles'][0]['path_edge_directions'] = directions
            self.assertFalse(self.evaluate(live)['commands'])

    def test_overlap_requires_stop_instead_of_clear_track(self):
        live = frame()
        live['vehicles'][1] = train(2, 10, 0, .95, 10, [80, 95])
        result = self.evaluate(live)
        decision = next(x for x in result['decisions'] if x['vehicle_id'] == 1)
        self.assertEqual('NATIVE_STOP_REQUIRED', decision['reason'])
        self.assertLess(decision['gap_m'], 0)
        self.assertFalse(result['commands'])

    def test_below_target_speed_still_retains_limit(self):
        live = frame()
        live['vehicles'][0]['speed_mps'] = 0
        self.assertTrue(self.evaluate(live)['commands'])

    def test_reverse_direction_uses_reverse_chainage(self):
        live = {'sampled_at': 1000, 'vehicles': [train(1, 12, 0, .2, 20, [220, 230]),
                                               train(2, 11, 1, .5, 10, [150, 170])]}
        for v in live['vehicles']:
            v['path_edge_ids'], v['path_edge_directions'] = [12, 11, 10], [False]*3
        command = self.evaluate(live)['commands'][0]
        self.assertEqual(2, command['leader_vehicle_id'])
        self.assertAlmostEqual(40, command['gap_m'], places=3)

    def test_curve_uses_arc_distance_not_chord(self):
        network = {'nodes': [{'entity_id': 1, 'position': {'x': 0, 'y': 0, 'z': 0}},
                             {'entity_id': 2, 'position': {'x': 100, 'y': 100, 'z': 20}}],
                   'edges': [{'entity_id': 10, 'node0': 1, 'node1': 2,
                              'tangent0': {'x': 180, 'y': 0, 'z': 20},
                              'tangent1': {'x': 0, 'y': 180, 'z': 20}}]}
        controller = TrainSpacingController(network)
        vehicles = []
        for vid, t in [(1, .1), (2, .9)]:
            v = train(vid, 10, 0, t, 10, [])
            v['path_edge_ids'], v['path_edge_directions'] = [10], [True]
            v['body_samples'] = [{'position': dict(zip(('x', 'y', 'z'), controller.graph.point(10, t))), 'radius_m': 2}]
            vehicles.append(v)
        command = controller.step({'sampled_at': 1000, 'vehicles': vehicles}, now=1000)['commands'][0]
        expected = controller.graph.along(10, .9)-controller.graph.along(10, .1)-4
        chord = math.dist(controller.graph.point(10, .1), controller.graph.point(10, .9))-4
        self.assertAlmostEqual(expected, command['gap_m'], places=2)
        self.assertGreater(command['gap_m'], chord+5)

    def test_diagonal_bounds_use_circumscribed_radius(self):
        v = {'train_envelope': {'complete': True, 'expected_parts': 1, 'parts': [
            {'position': {'x': 0, 'y': 0, 'z': 0}, 'bounds': {
                'min': {'x': -3, 'y': -4, 'z': 0}, 'max': {'x': 3, 'y': 4, 'z': 0}}}]}}
        self.assertEqual(5, _body_samples(v)[0]['radius_m'])

    def test_relaxation_is_slow_and_reduction_immediate(self):
        controller = TrainSpacingController(NETWORK, release_rate_kmh_per_second=1)
        first = controller.step(frame(), now=1000)['commands'][0]
        live = frame()
        live['sampled_at'] = 1001
        for v in live['vehicles']: v['footprint_sampled_at'] = 1001
        live['vehicles'][1] = train(2, 12, 2, .8, 10, [270, 280])
        live['vehicles'][1]['footprint_sampled_at'] = 1001
        second = controller.step(live, now=1001)['commands'][0]
        self.assertLessEqual(second['speed_mps'], first['speed_mps'] + 1/3.6)
        live = frame()
        live['sampled_at'] = 1002
        for v in live['vehicles']: v['footprint_sampled_at'] = 1002
        third = controller.step(live, now=1002)['commands'][0]
        self.assertAlmostEqual(first['speed_mps'], third['speed_mps'])
        self.assertEqual(1007, third['expires_at'])

    def test_sink_receives_empty_batch_on_clear_and_errors_propagate(self):
        controller = TrainSpacingController(NETWORK)
        batches = []
        controller.step(frame(), now=1000, sink=batches.append)
        live = frame()
        live['vehicles'] = live['vehicles'][:1]
        controller.step(live, now=1000, sink=batches.append)
        self.assertEqual([], batches[-1])
        def fail(batch): raise OSError('publisher unavailable')
        with self.assertRaises(OSError): controller.step(frame(), now=1001, sink=fail)
        self.assertEqual(1000, controller._last_time)

    def test_native_interface_writes_scopes_preserves_other_leases_and_clears(self):
        root = Path(__file__).resolve().parents[1] / '.tmp-spacing-tests'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            writer = NativeLeaseWriter(Path(directory))
            other = [{'kind': 'station', 'lease_id': 'station:9', 'vehicle_id': 9, 'expires_at': 1010}]
            sink = native_batch_sink(writer, generation=7, other_leases=other, now=1000)
            result = self.evaluate(sink=sink)
            self.assertTrue(result['submitted'])
            ini = configparser.ConfigParser()
            ini.read(writer.path)
            self.assertEqual('10,11', ini['speed_0']['edge_ids'])
            self.assertEqual('0', ini['speed_0']['path_index_start'])
            self.assertEqual('1', ini['speed_0']['path_index_end'])
            self.assertEqual('1', ini['meta']['station_count'])
            sink([])
            cleared = configparser.ConfigParser()
            cleared.read(writer.path)
            self.assertEqual('0', cleared['meta']['speed_count'])
            self.assertEqual('1', cleared['meta']['station_count'])


if __name__ == '__main__':
    unittest.main()
