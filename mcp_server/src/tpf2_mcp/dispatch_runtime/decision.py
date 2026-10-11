"""Pure regional decision module. Inputs and outputs are JSON values only."""
from .boundaries import digest


def decide(frame, state, now):
    scope = {k: frame[k] for k in ('save_id', 'session_id', 'topology_version')}
    commands, observations = [], []
    owners = {t['id']: t['owner'] for t in state['trains']}
    active = {h['train']: h for h in state['handovers'] if h['state'] not in ('RELEASED', 'CANCELLED')}
    def command(action, train, actor, **parameters):
        value = {'schema_version': 1, **scope, 'based_on_sequence': frame['sequence'],
                 'type': action, 'vehicle_id': train['vehicle_id'], 'actor_region': actor,
                 'expires_at': now+2, **parameters}
        value['command_id'] = digest(value)
        commands.append(value)
    if (not frame['quality']['fresh'] or not frame['quality']['session_verified']
            or not frame['quality'].get('simulation_running') or not frame['quality'].get('territory_verified')):
        return {'commands': [], 'observations': [{'code': issue} for issue in frame['quality']['issues']]}
    for t in frame['trains']:
        tid, head = t['vehicle_id'], t['head_region']
        if not head:
            observations.append({'code': 'POSITION_UNRESOLVED', 'vehicle_id': tid}); continue
        if tid not in owners:
            command('REGISTER_TRAIN', t, head); continue
        h = active.get(tid)
        if h:
            args = {'handover_id': h['id']}
            if h['state'] == 'REQUESTED': command('ACCEPT_HANDOVER', t, h['target'], **args)
            elif h['state'] == 'ACCEPTED' and t.get('crossed_anchor_id') == h['anchor']:
                command('ENTER_REGION', t, h['target'], **args)
            elif h['state'] in ('ENTERED', 'CLEARING') and t.get('footprint_complete') and t.get('cleared_anchor_id') == h['anchor']:
                command('RELEASE_TAIL', t, h['target'], **args)
            elif h['state'] == 'FROZEN': observations.append({'code': 'HANDOVER_FROZEN', 'vehicle_id': tid, 'handover_id': h['id']})
            continue
        if owners[tid] != head:
            observations.append({'code': 'UNRESERVED_CROSSING', 'vehicle_id': tid,
                                 'controller_region': owners[tid], 'head_region': head})
            # The game still moves trains while this shadow controller refuses
            # unsafe admissions.  Reconcile the read-only authority ledger only
            # after two distinct complete-footprint samples prove the whole
            # train has entered one region; the executor persists the proof.
            if t.get('footprint_complete') is True and set(t.get('occupied_regions', [])) == {head}:
                command('RECONCILE_OBSERVED_OWNER', t, owners[tid], target_region=head)
            continue
        a = t.get('admission') or {}
        if a.get('verified'):
            command('REQUEST_HANDOVER', t, owners[tid], handover_id=digest([scope, tid, frame['sequence'], a['anchor_id']]),
                    target_region=a['to_region'], anchor_id=a['anchor_id'], resources=a['resources'], lease_seconds=15)
    return {'commands': commands, 'observations': observations}
