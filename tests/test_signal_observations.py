import copy
import unittest

from test_rail_live import NETWORK, MANIFEST
from tpf2_mcp.rail_live import RailSpatialIndex, normalize_signals, normalize_live_state
from tpf2_mcp.signal_observations import merge_signal_states


def telemetry():
    return {'session_id': 'session', 'signal_inventory_generated_at': 90,
            'signal_edge_objects': [{'object_entity_id': 50, 'edge_entity_id': 10,
                'position': {'x': 50, 'y': 0, 'z': 0}, 'signal_types': [0],
                'operational_signal_observed': True, 'direction_evidence': [{
                    'status': 'ENGINE_QUERY_CONFIRMED', 'transport_entity': 10,
                    'transport_index': 0, 'signal_index': 0,
                    'queries': [{'ok': True, 'matched': True, 'reversed': False,
                                 'signal_entity': 50, 'signal_index': 0},
                                {'ok': True, 'matched': False, 'reversed': True}],
                    'geometry': {'pos': [{'x': 0, 'y': 0}, {'x': 100, 'y': 0}]}}]}]}


def payload(state=0):
    return {'session_id': 'session', 'generated_at': 100, 'inventory_generated_at': 90,
            'signal_states': [{'entity_id': 50, 'entries': [{'signal_index': 0,
                'signal_type': 0, 'raw_state': state, 'state_time': 0,
                'status': 'RAW_ANIMATION_OBSERVED'}]}]}


class SignalObservationTests(unittest.TestCase):
    def test_direction_reaches_main_live_frame(self):
        raw = telemetry()
        raw['signal_state_payload'] = payload()
        signal = normalize_live_state(raw, NETWORK, MANIFEST, sampled_at=100)['signals'][0]
        self.assertEqual([True], signal['directions'])
        self.assertEqual('ENGINE_QUERY_CONFIRMED', signal['direction_status'])
        self.assertTrue(signal['state_entries'][0]['forward'])
        self.assertEqual(0, signal['state_entries'][0]['raw_state'])
        self.assertEqual('UNKNOWN', signal['aspect'])

    def test_reverse_transport_geometry_is_not_left_side_guess(self):
        raw = telemetry()
        signal = raw['signal_edge_objects'][0]
        signal['left'] = False
        signal['direction_evidence'][0]['geometry']['pos'].reverse()
        self.assertEqual([False], normalize_signals(raw, RailSpatialIndex(NETWORK))[0]['directions'])

    def test_failed_opposite_query_cannot_confirm_direction(self):
        raw = telemetry()
        raw['signal_edge_objects'][0]['direction_evidence'][0]['queries'][1]['ok'] = False
        self.assertEqual('UNKNOWN', normalize_signals(raw, RailSpatialIndex(NETWORK))[0]['direction_status'])

    def test_missing_geometry_cannot_confirm_direction(self):
        raw = telemetry()
        raw['signal_edge_objects'][0]['direction_evidence'][0].pop('geometry')
        self.assertEqual([], normalize_signals(raw, RailSpatialIndex(NETWORK))[0]['directions'])

    def test_reject_stale_future_wrong_session_and_inventory(self):
        signals = normalize_signals(telemetry(), RailSpatialIndex(NETWORK))
        for key, value, reason in [('generated_at', 95, 'SIGNAL_STATE_STALE'),
                                   ('generated_at', 101, 'SIGNAL_STATE_STALE'),
                                   ('session_id', 'other', 'SESSION_MISMATCH'),
                                   ('inventory_generated_at', 89, 'SIGNAL_INVENTORY_MISMATCH')]:
            with self.subTest(reason=reason):
                data = payload(); data[key] = value
                result = merge_signal_states(signals, data, session_id='session', now=100,
                                             inventory_generated_at=90)[0]
                self.assertEqual(reason, result['state_status'])
                self.assertEqual([], result['state_entries'])

    def test_dynamic_state_not_frozen_in_static_cache(self):
        signals = normalize_signals(telemetry(), RailSpatialIndex(NETWORK))
        before = copy.deepcopy(signals)
        for state in (0, 1, 0):
            result = merge_signal_states(signals, payload(state), session_id='session', now=100,
                                         inventory_generated_at=90)[0]
            self.assertEqual(state, result['state_entries'][0]['raw_state'])
            self.assertEqual('UNKNOWN', result['aspect'])
        self.assertEqual(before, signals)

    def test_nonfinite_and_boolean_state_not_treated_as_animation(self):
        signals = normalize_signals(telemetry(), RailSpatialIndex(NETWORK))
        for raw in (float('nan'), True, None):
            result = merge_signal_states(signals, payload(raw), session_id='session', now=100,
                                         inventory_generated_at=90)[0]
            self.assertEqual('API_FIELD_UNAVAILABLE', result['state_status'])


if __name__ == '__main__':
    unittest.main()
