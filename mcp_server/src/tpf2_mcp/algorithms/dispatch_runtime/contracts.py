"""Dependency-free validation for the regional coordination protocol."""
import math

TYPES = {'REGISTER_TRAIN', 'RECONCILE_OBSERVED_OWNER', 'REQUEST_HANDOVER', 'ACCEPT_HANDOVER',
         'ENTER_REGION', 'RELEASE_TAIL', 'CANCEL_HANDOVER'}
BASE = {'schema_version', 'command_id', 'save_id', 'session_id', 'topology_version', 'based_on_sequence', 'expires_at', 'type', 'vehicle_id', 'actor_region'}
OPTIONAL = {'handover_id', 'anchor_id', 'target_region', 'resources', 'lease_seconds'}


def validate_command(value):
    if not isinstance(value, dict) or not BASE <= value.keys() or value.keys()-BASE-OPTIONAL:
        raise ValueError('invalid regional command fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['type'] not in TYPES: raise ValueError('invalid regional command type/version')
    for key in ('command_id', 'save_id', 'session_id', 'topology_version', 'actor_region'):
        if not isinstance(value[key], str) or not 0 < len(value[key]) <= 256: raise ValueError('invalid '+key)
    for key, minimum in (('vehicle_id', 0), ('based_on_sequence', 1)):
        if type(value[key]) is not int or value[key] < minimum: raise ValueError('invalid '+key)
    if type(value['expires_at']) not in (float, int) or not math.isfinite(value['expires_at']): raise ValueError('invalid expiry')
    if value['type'] not in ('REGISTER_TRAIN', 'RECONCILE_OBSERVED_OWNER'):
        if not isinstance(value.get('handover_id'), str) or not value['handover_id']: raise ValueError('missing handover identity')
    if value['type'] == 'RECONCILE_OBSERVED_OWNER':
        if not isinstance(value.get('target_region'), str) or not value['target_region']:
            raise ValueError('missing target_region')
        if value['target_region'] == value['actor_region']: raise ValueError('cannot reconcile to self')
    if value['type'] == 'REQUEST_HANDOVER':
        for key in ('anchor_id', 'target_region'):
            if not isinstance(value.get(key), str) or not value[key]: raise ValueError('missing '+key)
        resources = value.get('resources')
        if (not isinstance(resources, list) or not resources or not all(isinstance(r, str) and r for r in resources)
                or len(resources) != len(set(resources))): raise ValueError('invalid resources')
        lease = value.get('lease_seconds')
        if type(lease) not in (float, int) or not math.isfinite(lease) or not 0 < lease <= 30: raise ValueError('invalid lease')
        if value['target_region'] == value['actor_region']: raise ValueError('cannot hand over to self')
