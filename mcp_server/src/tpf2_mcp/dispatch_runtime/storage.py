"""Owned-path atomic JSON snapshots and transactional regional state."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from .contracts import validate_command


def atomic_json(root, relative, value):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root): raise ValueError('output escaped dispatch root')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+target.name, suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        # Windows HTTP readers may briefly deny delete-sharing on a static JSON.
        # Keep the old complete file until replacement succeeds; never truncate it.
        for attempt in range(8):
            try:
                os.replace(name, target); break
            except PermissionError:
                if attempt == 7: raise
                time.sleep(min(.2, .01 * 2**attempt))
    finally:
        if os.path.exists(name): os.unlink(name)


class SnapshotStore:
    def __init__(self, root, keep=40):
        self.root = Path(root).resolve(); self.keep = max(2, keep)

    def publish(self, frame):
        filename = f"frames/{frame['sequence']:016d}.json"
        atomic_json(self.root, filename, frame)
        atomic_json(self.root, 'current.json', {k: frame[k] for k in ('schema_version', 'save_id', 'session_id', 'topology_version', 'sequence')} | {'frame': filename})
        for p in sorted((self.root/'frames').glob('*.json'))[:-self.keep]:
            if not p.resolve().is_relative_to(self.root): raise ValueError('frame escaped root')
            p.unlink(missing_ok=True)

    def read(self):
        for _ in range(3):
            try:
                pointer = json.loads((self.root/'current.json').read_text('utf8'))
                p = (self.root/pointer['frame']).resolve()
                if not p.is_relative_to(self.root): raise ValueError('invalid snapshot pointer')
                frame = json.loads(p.read_text('utf8'))
                if any(frame[k] != pointer[k] for k in ('save_id', 'session_id', 'topology_version', 'sequence')):
                    raise ValueError('snapshot scope mismatch')
                return frame
            except FileNotFoundError: continue
        raise ValueError('snapshot unavailable')


class RegionalStore:
    def __init__(self, root):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        path = (self.root/'regional.sqlite').resolve()
        if not path.is_relative_to(self.root): raise ValueError('database escaped root')
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload TEXT NOT NULL, result TEXT);
          CREATE TABLE IF NOT EXISTS trains(scope TEXT, id INTEGER, owner TEXT NOT NULL, PRIMARY KEY(scope,id));
          CREATE TABLE IF NOT EXISTS handovers(scope TEXT, id TEXT, train INTEGER, source TEXT, target TEXT,
            anchor TEXT, state TEXT, expires REAL, entered_sequence INTEGER, clear_sequence INTEGER,
            PRIMARY KEY(scope,id));
          CREATE TABLE IF NOT EXISTS reservations(scope TEXT, resource TEXT, handover TEXT, train INTEGER,
            PRIMARY KEY(scope,resource));
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, command TEXT, at REAL, payload TEXT);
          CREATE TABLE IF NOT EXISTS braking_evidence(scope TEXT, train INTEGER, samples INTEGER NOT NULL,
            max_decel REAL NOT NULL, last_update INTEGER NOT NULL, PRIMARY KEY(scope,train));
          CREATE TABLE IF NOT EXISTS braking_episode_evidence(scope TEXT, train INTEGER, episodes INTEGER NOT NULL,
            max_decel REAL NOT NULL, last_update INTEGER NOT NULL, active INTEGER NOT NULL,
            PRIMARY KEY(scope,train));
          CREATE TABLE IF NOT EXISTS owner_reconcile_evidence(scope TEXT, train INTEGER, source TEXT NOT NULL,
            target TEXT NOT NULL, samples INTEGER NOT NULL, first_update INTEGER NOT NULL,
            last_update INTEGER NOT NULL, PRIMARY KEY(scope,train));
        ''')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self.db
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def close(self): self.db.close()

    def enqueue(self, command, scope):
        validate_command(command)
        content = json.dumps(command, sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.transaction() as db:
            old = db.execute('SELECT payload FROM commands WHERE id=?', (command['command_id'],)).fetchone()
            if old and old['payload'] != content: raise ValueError('idempotency key reused with different content')
            if not old:
                db.execute('INSERT INTO commands(id,scope,payload) VALUES (?,?,?)', (command['command_id'], scope, content))

    def pending(self, scope):
        return [json.loads(r['payload']) for r in self.db.execute('SELECT payload FROM commands WHERE scope=? AND result IS NULL ORDER BY rowid LIMIT 100', (scope,))]

    def observe_braking(self, scope, samples):
        """Persist separate, plausible braking episodes rather than frame counts."""
        with self.transaction() as db:
            for train, decel, update in samples:
                if type(train) is not int or type(update) is not int or not isinstance(decel, (int, float)):
                    continue
                prior = db.execute('SELECT * FROM braking_episode_evidence WHERE scope=? AND train=?',
                                   (scope, train)).fetchone()
                if prior and update <= prior['last_update']: continue
                valid = math.isfinite(decel) and 0.5 <= decel <= 30
                episodes = (prior['episodes'] if prior else 0) + (1 if valid and (not prior or not prior['active']) else 0)
                maximum = max(prior['max_decel'] if prior else 0, float(decel) if valid else 0)
                db.execute('''INSERT INTO braking_episode_evidence(scope,train,episodes,max_decel,last_update,active)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(scope,train) DO UPDATE SET episodes=excluded.episodes,
                    max_decel=excluded.max_decel,last_update=excluded.last_update,active=excluded.active''',
                    (scope, train, episodes, maximum, update, int(valid)))

    def braking(self, scope, train):
        row = self.db.execute('SELECT episodes,max_decel,last_update FROM braking_episode_evidence WHERE scope=? AND train=?',
                              (scope, train)).fetchone()
        if not row: return {'verified': False, 'source': 'EMPIRICAL_BRAKING_EPISODES', 'samples': 0,
                            'service_deceleration_mps2': None}
        # Consecutive samples from one stop are correlated.  Publish only a
        # conservative envelope after three independently observed episodes.
        return {'verified': row['episodes'] >= 3 and row['max_decel'] >= .5,
                'source': 'EMPIRICAL_BRAKING_EPISODES', 'samples': row['episodes'],
                'observed_max_deceleration_mps2': row['max_decel'], 'last_update': row['last_update'],
                'service_deceleration_mps2': .35 if row['episodes'] >= 3 and row['max_decel'] >= .5 else None}

    def view(self, scope):
        return {'trains': [dict(r) for r in self.db.execute('SELECT id,owner FROM trains WHERE scope=?', (scope,))],
                'handovers': [dict(r) for r in self.db.execute('SELECT id,train,source,target,anchor,state,expires FROM handovers WHERE scope=?', (scope,))],
                'reservations': [dict(r) for r in self.db.execute('SELECT resource,handover,train FROM reservations WHERE scope=?', (scope,))],
                'events': [json.loads(r['payload']) for r in self.db.execute('SELECT payload FROM events WHERE scope=? ORDER BY seq DESC LIMIT 30', (scope,))]}
