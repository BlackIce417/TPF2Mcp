"""Transactional cross-region authority transfer. No game commands are issued here."""
import json
import math
from .boundaries import digest


def scope_key(frame):
    return digest({k: frame[k] for k in ('save_id', 'session_id', 'topology_version')})


def annotate_transfer_evidence(frame, state):
    """Attach boundary facts only when they agree with an active reservation.

    The active handover identifies the otherwise ambiguous administrative
    anchor.  A complete engine footprint then proves head entry and tail
    clearance independently of worker restarts.
    """
    active = {h['train']: h for h in state['handovers']
              if h['state'] not in ('RELEASED', 'CANCELLED')}
    for train in frame.get('trains', []):
        train.pop('crossed_anchor_id', None)
        train.pop('cleared_anchor_id', None)
        handover = active.get(train.get('vehicle_id'))
        if not handover or train.get('footprint_complete') is not True:
            continue
        occupied = set(train.get('occupied_regions', []))
        if (handover['state'] == 'ACCEPTED' and train.get('head_region') == handover['target']
                and handover['target'] in occupied):
            train['crossed_anchor_id'] = handover['anchor']
        if (handover['state'] in ('ENTERED', 'CLEARING')
                and train.get('head_region') == handover['target']
                and occupied == {handover['target']}):
            train['cleared_anchor_id'] = handover['anchor']
    return frame


class Rejected(ValueError): pass


class HandoverExecutor:
    def __init__(self, store): self.store = store

    def execute(self, command, frame, now):
        scope = scope_key(frame)
        self.store.enqueue(command, scope)
        with self.store.transaction() as db:
            prior = db.execute('SELECT result FROM commands WHERE id=?', (command['command_id'],)).fetchone()['result']
            if prior: return json.loads(prior)
            # A savepoint keeps rejected operations from committing partial mutations.
            db.execute('SAVEPOINT action')
            try:
                self._guard(command, frame, now)
                status = self._apply(db, scope, command, frame, now)
                result = {'command_id': command['command_id'], 'status': status, 'at': now,
                          'game_write': False, 'scope': scope, 'sequence': frame['sequence']}
            except Rejected as exc:
                db.execute('ROLLBACK TO action')
                result = {'command_id': command['command_id'], 'status': 'REJECTED', 'reason': str(exc), 'at': now, 'game_write': False}
            db.execute('RELEASE action')
            payload = json.dumps(result, separators=(',', ':'))
            db.execute('UPDATE commands SET result=? WHERE id=?', (payload, command['command_id']))
            db.execute('INSERT INTO events(scope,command,at,payload) VALUES (?,?,?,?)', (scope, command['command_id'], now, payload))
            return result

    @staticmethod
    def _guard(c, f, now):
        if c.get('schema_version') != 1: raise Rejected('SCHEMA_UNSUPPORTED')
        if any(c.get(k) != f.get(k) or not f.get(k) for k in ('save_id', 'session_id', 'topology_version')):
            raise Rejected('SCOPE_MISMATCH')
        expires = c.get('expires_at')
        if type(expires) not in (float, int) or not math.isfinite(expires) or expires <= now: raise Rejected('COMMAND_EXPIRED')
        if c.get('based_on_sequence', math.inf) > f['sequence']: raise Rejected('FUTURE_SEQUENCE')
        if not f.get('quality', {}).get('fresh') or not f.get('quality', {}).get('session_verified'):
            raise Rejected('OBSERVATION_UNVERIFIED')
        if f.get('quality', {}).get('simulation_running') is not True: raise Rejected('SIMULATION_NOT_RUNNING')
        if f.get('quality', {}).get('territory_verified') is not True: raise Rejected('TERRITORY_REVIEW_REQUIRED')
        if not 0 <= now-f['sampled_at'] <= 2: raise Rejected('OBSERVATION_STALE')

    def _apply(self, db, scope, c, f, now):
        tid, action = c.get('vehicle_id'), c.get('type')
        sample_sequence = f.get('simulation_clock', {}).get('update_count', f['sequence'])
        if type(sample_sequence) is not int: raise Rejected('OBSERVATION_SEQUENCE_UNKNOWN')
        train = next((t for t in f['trains'] if t['vehicle_id'] == tid), None)
        if train is None or not train.get('head_region'): raise Rejected('TRAIN_POSITION_UNKNOWN')
        if action == 'REGISTER_TRAIN':
            if c.get('actor_region') != train['head_region']: raise Rejected('WRONG_ACTOR')
            owner = db.execute('SELECT owner FROM trains WHERE scope=? AND id=?', (scope, tid)).fetchone()
            if owner: return 'ALREADY_REGISTERED'
            db.execute('INSERT INTO trains VALUES (?,?,?)', (scope, tid, train['head_region']))
            return 'REGISTERED'
        if action == 'RECONCILE_OBSERVED_OWNER':
            owner = db.execute('SELECT owner FROM trains WHERE scope=? AND id=?', (scope, tid)).fetchone()
            target = c.get('target_region')
            footprint_update = train.get('footprint_update_count')
            if not owner: raise Rejected('TRAIN_NOT_REGISTERED')
            if c.get('actor_region') != owner['owner']: raise Rejected('WRONG_OWNER')
            if target == owner['owner'] or target != train['head_region']: raise Rejected('OWNER_OBSERVATION_MISMATCH')
            if db.execute("SELECT 1 FROM handovers WHERE scope=? AND train=? AND state NOT IN ('RELEASED','CANCELLED')",
                          (scope, tid)).fetchone():
                raise Rejected('HANDOVER_IN_PROGRESS')
            if (train.get('footprint_complete') is not True or set(train.get('occupied_regions', [])) != {target}
                    or type(footprint_update) is not int):
                raise Rejected('FULL_BODY_TARGET_OCCUPANCY_REQUIRED')
            evidence = db.execute('SELECT * FROM owner_reconcile_evidence WHERE scope=? AND train=?',
                                  (scope, tid)).fetchone()
            if not evidence or evidence['source'] != owner['owner'] or evidence['target'] != target:
                db.execute('''INSERT INTO owner_reconcile_evidence VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(scope,train) DO UPDATE SET source=excluded.source,target=excluded.target,
                    samples=1,first_update=excluded.first_update,last_update=excluded.last_update''',
                           (scope, tid, owner['owner'], target, 1, footprint_update, footprint_update))
                return 'RECONCILE_OBSERVATION_PENDING'
            if footprint_update <= evidence['last_update']:
                return 'RECONCILE_OBSERVATION_PENDING'
            samples = evidence['samples'] + 1
            if samples < 2:
                db.execute('UPDATE owner_reconcile_evidence SET samples=?,last_update=? WHERE scope=? AND train=?',
                           (samples, footprint_update, scope, tid))
                return 'RECONCILE_OBSERVATION_PENDING'
            db.execute('UPDATE trains SET owner=? WHERE scope=? AND id=?', (target, scope, tid))
            db.execute('DELETE FROM owner_reconcile_evidence WHERE scope=? AND train=?', (scope, tid))
            return 'OBSERVED_OWNER_RECONCILED'
        hid = c.get('handover_id')
        h = db.execute('SELECT * FROM handovers WHERE scope=? AND id=?', (scope, hid)).fetchone()
        owner = db.execute('SELECT owner FROM trains WHERE scope=? AND id=?', (scope, tid)).fetchone()
        if not owner: raise Rejected('TRAIN_NOT_REGISTERED')
        if action == 'REQUEST_HANDOVER':
            if h: raise Rejected('HANDOVER_EXISTS')
            if c.get('actor_region') != owner['owner'] or train['head_region'] != owner['owner']: raise Rejected('WRONG_OWNER')
            if db.execute("SELECT 1 FROM handovers WHERE scope=? AND train=? AND state NOT IN ('RELEASED','CANCELLED')", (scope, tid)).fetchone():
                raise Rejected('HANDOVER_IN_PROGRESS')
            admission = train.get('admission') or {}
            if admission.get('verified') is not True or admission.get('anchor_id') != c.get('anchor_id'):
                raise Rejected('ADMISSION_UNVERIFIED')
            if admission.get('from_region') != owner['owner'] or admission.get('to_region') != c.get('target_region'):
                raise Rejected('ADMISSION_REGION_MISMATCH')
            required = set(admission.get('resources', []))
            if not required or set(c.get('resources', [])) != required: raise Rejected('RESOURCE_SET_MISMATCH')
            if admission.get('expires_at', 0) <= now or admission.get('sequence') != f['sequence']:
                raise Rejected('ADMISSION_STALE')
            if set(admission.get('conflicting_vehicle_ids', [])) - {tid}: raise Rejected('RESOURCE_OCCUPIED')
            for r in sorted(required):
                if db.execute('SELECT 1 FROM reservations WHERE scope=? AND resource=?', (scope, r)).fetchone():
                    raise Rejected('RESOURCE_RESERVED')
            lease = c.get('lease_seconds')
            if type(lease) not in (int, float) or not 0 < lease <= 30: raise Rejected('INVALID_LEASE')
            db.execute('INSERT INTO handovers VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (scope, hid, tid, owner['owner'], c['target_region'], c['anchor_id'], 'REQUESTED', now+lease, None, None))
            for r in sorted(required): db.execute('INSERT INTO reservations VALUES (?,?,?,?)', (scope, r, hid, tid))
            return 'REQUESTED'
        if not h or h['train'] != tid: raise Rejected('HANDOVER_NOT_FOUND')
        if action == 'ACCEPT_HANDOVER':
            if c.get('actor_region') != h['target']: raise Rejected('WRONG_ACTOR')
            if h['state'] != 'REQUESTED' or now >= h['expires']: raise Rejected('RESERVATION_EXPIRED_OR_NOT_REQUESTED')
            admission = train.get('admission') or {}
            if not admission.get('verified') or admission.get('anchor_id') != h['anchor'] or admission.get('sequence') != f['sequence']:
                raise Rejected('ADMISSION_CHANGED')
            held = {r['resource'] for r in db.execute('SELECT resource FROM reservations WHERE scope=? AND handover=?', (scope, hid))}
            if (admission.get('from_region') != h['source'] or admission.get('to_region') != h['target']
                    or admission.get('expires_at', 0) <= now or set(admission.get('resources', [])) != held
                    or set(admission.get('conflicting_vehicle_ids', [])) - {tid}): raise Rejected('ADMISSION_CHANGED')
            db.execute("UPDATE handovers SET state='ACCEPTED' WHERE scope=? AND id=?", (scope, hid))
            return 'ACCEPTED'
        if action == 'ENTER_REGION':
            if c.get('actor_region') != h['target'] or h['state'] != 'ACCEPTED': raise Rejected('NOT_ACCEPTED')
            if now >= h['expires']: raise Rejected('RESERVATION_EXPIRED')
            if train['head_region'] != h['target'] or train.get('crossed_anchor_id') != h['anchor']:
                raise Rejected('CROSSING_NOT_OBSERVED')
            db.execute("UPDATE handovers SET state='ENTERED', entered_sequence=? WHERE scope=? AND id=?", (sample_sequence, scope, hid))
            db.execute('UPDATE trains SET owner=? WHERE scope=? AND id=?', (h['target'], scope, tid))
            return 'ENTERED'
        if action == 'RELEASE_TAIL':
            if c.get('actor_region') != h['target'] or h['state'] not in ('ENTERED', 'CLEARING'): raise Rejected('WRONG_RELEASE_STATE')
            footprint_sequence = train.get('footprint_update_count')
            if (train.get('footprint_complete') is not True or set(train.get('occupied_regions', [])) != {h['target']}
                    or train.get('cleared_anchor_id') != h['anchor'] or type(footprint_sequence) is not int
                    or footprint_sequence <= h['entered_sequence']):
                raise Rejected('TAIL_CLEARANCE_UNVERIFIED')
            if h['clear_sequence'] is None:
                db.execute("UPDATE handovers SET state='CLEARING',clear_sequence=? WHERE scope=? AND id=?", (footprint_sequence, scope, hid))
                return 'CLEARING'
            if footprint_sequence <= h['clear_sequence']: raise Rejected('NEED_NEW_CLEARANCE_SAMPLE')
            db.execute('DELETE FROM reservations WHERE scope=? AND handover=?', (scope, hid))
            db.execute("UPDATE handovers SET state='RELEASED' WHERE scope=? AND id=?", (scope, hid))
            return 'RELEASED'
        if action == 'CANCEL_HANDOVER':
            if c.get('actor_region') != h['source'] or h['state'] not in ('REQUESTED', 'ACCEPTED', 'FROZEN'): raise Rejected('CANNOT_CANCEL_ENTERED_TRAIN')
            if train.get('footprint_complete') is not True or set(train.get('occupied_regions', [])) != {h['source']}:
                raise Rejected('OCCUPANCY_UNKNOWN')
            db.execute('DELETE FROM reservations WHERE scope=? AND handover=?', (scope, hid))
            db.execute("UPDATE handovers SET state='CANCELLED' WHERE scope=? AND id=?", (scope, hid))
            return 'CANCELLED'
        raise Rejected('UNKNOWN_COMMAND')

    def expire(self, frame, now):
        """Expiry fences authority; it never treats an occupied resource as empty."""
        scope = scope_key(frame)
        with self.store.transaction() as db:
            db.execute("UPDATE handovers SET state='FROZEN' WHERE scope=? AND expires<=? AND state IN ('REQUESTED','ACCEPTED')", (scope, now))
            # A lost clearance observation invalidates the two-sample proof.
            trains = {t['vehicle_id']: t for t in frame['trains']}
            for h in db.execute("SELECT * FROM handovers WHERE scope=? AND state='CLEARING'", (scope,)).fetchall():
                t = trains.get(h['train'], {})
                if (not frame['quality'].get('fresh') or not t.get('footprint_complete')
                        or set(t.get('occupied_regions', [])) != {h['target']} or t.get('cleared_anchor_id') != h['anchor']):
                    db.execute("UPDATE handovers SET state='ENTERED',clear_sequence=NULL WHERE scope=? AND id=?", (scope, h['id']))

    def authority(self, frame, vehicle_id, region, now):
        if not frame.get('quality', {}).get('fresh') or not frame.get('quality', {}).get('session_verified') or not 0 <= now-frame['sampled_at'] <= 2:
            return False
        scope = scope_key(frame)
        owner = self.store.db.execute('SELECT owner FROM trains WHERE scope=? AND id=?', (scope, vehicle_id)).fetchone()
        frozen = self.store.db.execute("SELECT 1 FROM handovers WHERE scope=? AND train=? AND state='FROZEN'", (scope, vehicle_id)).fetchone()
        train = next((t for t in frame['trains'] if t['vehicle_id'] == vehicle_id), {})
        return bool(owner and owner['owner'] == region and not frozen and train.get('head_region') == region
                    and train.get('footprint_complete') is True and frame['quality'].get('territory_verified') is True
                    and frame['quality'].get('simulation_running') is True)
