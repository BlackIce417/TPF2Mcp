"""Station selectors and postconditions for incremental platform edits."""
from copy import deepcopy

PLATFORM_OPERATIONS = {
    'add_line_stop_platform': 'ADD_LINE_STOP_PLATFORM',
    'remove_line_stop_platform': 'REMOVE_LINE_STOP_PLATFORM',
}
PLATFORM_PROPERTIES = {
    'line_id': {'type': 'integer', 'minimum': 1},
    'stop_index': {'type': 'integer', 'minimum': 0, 'description': '线路停站序号，从0开始；重复经停同一站时用于精确定位。'},
    'station_id': {'type': 'integer', 'minimum': 1, 'description': '车站组ID，必须与该次停站一致。'},
    'station_index': {'type': 'integer', 'minimum': 0, 'description': '车站组内子站索引，从0开始，使用get_train_routes返回的值。'},
    'platform_number': {'type': 'integer', 'minimum': 1, 'description': 'terminal_index+1，与get_train_routes一致；不是自定义UI站台标签。'},
}


def platform_configuration(stop):
    return {'station_id': stop.get('station_id'), 'station_index': stop.get('station_index'),
            'terminal_id': stop.get('terminal_id'),
            'alternative_terminals': deepcopy(stop.get('alternative_terminals') or [])}


def expected_platforms(name, parameters, before):
    result = platform_configuration(before)
    if result['station_id'] != parameters['station_id']:
        raise ValueError('STOP_STATION_MISMATCH')
    primary = (result['station_index'], result['terminal_id'])
    alternatives = [(a['station_index'], a['terminal_id']) for a in result['alternative_terminals']]
    selected = (parameters['station_index'], parameters['terminal_id'])
    if name == 'add_line_stop_platform':
        if selected != primary and selected not in alternatives:
            alternatives.append(selected)
    else:
        alternatives = [a for a in alternatives if a != selected and a != primary]
        if selected == primary:
            if not alternatives:
                raise ValueError('CANNOT_REMOVE_LAST_PLATFORM')
            primary = alternatives.pop(0)
    result.update(station_index=primary[0], terminal_id=primary[1],
                  alternative_terminals=[{'station_index': s, 'terminal_id': t} for s, t in alternatives])
    return result


def platforms_match(expected, stop):
    actual = platform_configuration(stop)
    return (all(actual[k] == expected[k] for k in ('station_id', 'station_index', 'terminal_id'))
            and {(a['station_index'], a['terminal_id']) for a in actual['alternative_terminals']}
            == {(a['station_index'], a['terminal_id']) for a in expected['alternative_terminals']})


def platform_postcondition(expected, before_stops, after_stops, stop_index):
    desired = deepcopy(before_stops)
    selected = next((s for s in desired if s.get('sequence_index') == stop_index), None)
    if selected is None or len(desired) != len(after_stops):
        return False
    selected.update(expected)
    for old, new in zip(desired, after_stops):
        if not platforms_match(platform_configuration(old), new):
            return False
        if {k: v for k, v in old.items() if k != 'alternative_terminals'} != {
                k: v for k, v in new.items() if k != 'alternative_terminals'}:
            return False
    return True
