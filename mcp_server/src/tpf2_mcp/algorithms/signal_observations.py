"""Join dynamic API evidence to static signal directions without guessing aspects."""
import math


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def merge_signal_states(signals, payload, *, session_id, now, maximum_age=2.5,
                        inventory_generated_at=None):
    sampled = payload.get('generated_at')
    reason = None
    if not session_id or payload.get('session_id') != session_id:
        reason = 'SESSION_MISMATCH'
    elif inventory_generated_at is None or payload.get('inventory_generated_at') != inventory_generated_at:
        reason = 'SIGNAL_INVENTORY_MISMATCH'
    elif not _number(sampled) or not 0 <= now - sampled <= maximum_age:
        reason = 'SIGNAL_STATE_STALE'
    by_id = {x.get('entity_id'): x for x in payload.get('signal_states', [])} if not reason else {}
    output = []
    for signal in signals:
        observation = by_id.get(signal['entity_id'])
        bindings = {x['signal_index']: x for x in signal.get('direction_bindings', [])}
        entries = []
        for entry in (observation or {}).get('entries', []):
            raw = entry.get('raw_state')
            observed = entry.get('status') == 'RAW_ANIMATION_OBSERVED' and _number(raw)
            binding = bindings.get(entry.get('signal_index'), {})
            entries.append({'signal_index': entry.get('signal_index'),
                            'signal_type': entry.get('signal_type'),
                            'forward': binding.get('forward'),
                            'raw_state': raw if observed else None,
                            'state_time': entry.get('state_time') if _number(entry.get('state_time')) else None,
                            'status': 'RAW_ANIMATION_OBSERVED' if observed else 'API_FIELD_UNAVAILABLE',
                            'aspect': 'UNKNOWN', 'aspect_status': 'ANIMATION_MAPPING_UNVERIFIED'})
        output.append({**signal, 'aspect': 'UNKNOWN', 'state_entries': entries,
                       'state_sampled_at': sampled if not reason else None,
                       'state_source': 'SIGNAL_LIST.signals',
                       'state_status': reason or ('RAW_ANIMATION_OBSERVED' if any(
                           x['status'] == 'RAW_ANIMATION_OBSERVED' for x in entries) else 'API_FIELD_UNAVAILABLE')})
    return output
