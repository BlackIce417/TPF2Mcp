"""Independent regional shadow worker. Data exchange is JSON/SQLite; no game writes."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'mcp_server/src'))
from tpf2_mcp.dispatch_runtime.geometry import RailGraph
from tpf2_mcp.dispatch_runtime.boundaries import BoundaryCalibrator, calibrate_all, normalize_directional_signals, digest
from tpf2_mcp.dispatch_runtime.territory import TerritoryIndex, repartition
from tpf2_mcp.dispatch_runtime.collector import RegionalCollector, read_json
from tpf2_mcp.dispatch_runtime.storage import atomic_json, SnapshotStore, RegionalStore
from tpf2_mcp.dispatch_runtime.handover import HandoverExecutor, annotate_transfer_evidence, scope_key
from tpf2_mcp.dispatch_runtime.decision import decide
from tpf2_mcp.dispatch_runtime.routing import boundary_candidates
from tpf2_mcp.dispatch_runtime.admission import evaluate_admission
from tpf2_mcp.dispatch_runtime.receiving import receiving_evidence
from tpf2_mcp.config import mod_dir


@contextmanager
def instance_lock(root):
    path = (root/'worker.lock').resolve()
    if not path.is_relative_to(root): raise ValueError('lock escaped root')
    with path.open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: yield
        finally:
            if sys.platform == 'win32':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod-root', type=Path)
    parser.add_argument('--install-study', type=Path)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--duration', type=float, default=0)
    parser.add_argument('--stop', action='store_true', help='request graceful stop of this regional worker only')
    parser.add_argument('--no-collect', action='store_true', help='do not launch slow Bridge refresh on session changes')
    args = parser.parse_args()
    mod = (args.mod_root or mod_dir()).resolve()
    if not (mod/'res/scripts/tpf2_mcp/runtime.lua').is_file(): raise ValueError('not a verified MCP Mod root')
    runtime_root = (mod/'bridge/dispatch/regional').resolve()
    if not runtime_root.is_relative_to(mod): raise ValueError('runtime escaped Mod root')
    runtime_root.mkdir(parents=True, exist_ok=True)
    if args.stop:
        atomic_json(runtime_root, 'stop.json', {'requested_at': time.time()})
        return
    with instance_lock(runtime_root):
        if args.install_study:
            study = args.install_study.resolve()
            for file in ('territories.json', 'boundary-anchors.json'):
                value = read_json(study/file)
                if not value: raise ValueError('missing study '+file)
                atomic_json(runtime_root, 'definition/'+file, value)
        run(mod, runtime_root, args)


def run(mod, root, args):
    anchors = read_json(root/'definition/boundary-anchors.json')
    reference = read_json(root/'definition/territories.json')
    if not anchors or not reference: raise ValueError('install region definitions first')
    store, executor = RegionalStore(root), None
    executor = HandoverExecutor(store)
    snapshots = SnapshotStore(root)
    deadline = time.monotonic()+args.duration if args.duration else float('inf')
    graph = collector = territory = calibration = calibrator = None
    last_signature = None
    last_published = None
    sequence = read_json(root/'current.json').get('sequence', 0)
    started_at = time.time()
    collection_process, next_collection = None, 0
    previous_kinematics = None
    try:
        while True:
            if read_json(root/'stop.json').get('requested_at', 0) >= started_at: break
            now = time.time()
            try:
                net_path = mod/'var/rail-map/rail-network-data.json'
                sig_path = mod/'bridge/operational-telemetry-signals.json'
                signature = (net_path.stat().st_mtime_ns, sig_path.stat().st_mtime_ns)
                if signature != last_signature:
                    raw = net_path.read_bytes(); network = json.loads(raw)
                    version = hashlib.sha256(raw).hexdigest()
                    if network['save_id'] != reference['save_id'] or anchors['save_id'] != reference['save_id']:
                        raise ValueError('SAVE_MISMATCH')
                    if graph is None or last_signature is None or signature[0] != last_signature[0]:
                        graph = RailGraph(network)
                    signals_raw = read_json(sig_path)
                    signals = normalize_directional_signals(signals_raw, graph)
                    calibrator = BoundaryCalibrator(graph, signals, version)
                    calibration = calibrate_all(anchors, graph, signals, {'save_id': network['save_id'],
                        'session_id': signals_raw.get('session_id'), 'topology_version': version})
                    document = reference if version == reference['topology_sha256'] else repartition(reference, graph, calibration, version)
                    territory = TerritoryIndex(document, graph)
                    previous_collector = collector
                    collector = RegionalCollector(mod, territory, version); collector.sequence = sequence
                    if previous_collector is not None and previous_collector.version == version:
                        collector.last_observation = previous_collector.last_observation
                    audit = territory.audit(calibration)
                    atomic_json(root, 'calibration.json', calibration)
                    atomic_json(root, 'ownership.json', {'topology_version': version, 'segments': document['segments'], 'audit': audit,
                                                        'review_events': document.get('review_events', [])})
                    last_signature = signature
                frame = collector.collect(time.time()); sequence = frame['sequence']
                scope = scope_key(frame)
                current_update = frame.get('simulation_clock', {}).get('update_count')
                current_time = frame.get('simulation_clock', {}).get('game_time')
                current_kinematics = {t['vehicle_id']: {'speed': t.get('speed_mps'),
                    'position': t.get('position'), 'edge_id': t.get('edge_id'), 'line_id': t.get('line_id'),
                    'route_current': t.get('route', {}).get('status') == 'ENGINE_PATH_CURRENT'} for t in frame['trains']}
                braking_samples = []
                if (previous_kinematics and previous_kinematics['scope'] == scope
                        and isinstance(current_update, int) and isinstance(current_time, (int, float))):
                    dt = (current_time-previous_kinematics['game_time'])/1000
                    if 0 < dt <= 2:
                        for vehicle_id, current in current_kinematics.items():
                            old = previous_kinematics['trains'].get(vehicle_id)
                            if not old: continue
                            old_speed, speed = old.get('speed'), current.get('speed')
                            plausible = (isinstance(old_speed, (int, float)) and isinstance(speed, (int, float))
                                and old_speed > 5 and speed >= 0 and old.get('line_id') == current.get('line_id')
                                and old.get('route_current') and current.get('route_current'))
                            old_position, position = old.get('position'), current.get('position')
                            if plausible and isinstance(old_position, dict) and isinstance(position, dict):
                                try:
                                    distance = sum((float(position[k])-float(old_position[k]))**2 for k in ('x','y','z'))**.5
                                    plausible = distance <= max(150., (old_speed+speed)*dt*4+20)
                                except (KeyError, TypeError, ValueError): plausible = False
                            else: plausible = False
                            braking_samples.append((vehicle_id, (old_speed-speed)/dt if plausible else 0., current_update))
                store.observe_braking(scope, braking_samples)
                if isinstance(current_update, int) and isinstance(current_time, (int, float)):
                    previous_kinematics = {'scope': scope, 'game_time': current_time, 'trains': current_kinematics}
                route_observations = []
                for train in frame['trains']:
                    candidates, observations = boundary_candidates(train, calibration, calibrator, territory)
                    train['boundary_candidates'] = candidates
                    route_observations.extend(observations)
                    legal = next((candidate for candidate in candidates if candidate['legal_route_verified']), None)
                    if legal:
                        # brakeDecel is exposed as a dynamic engine field, but
                        # its service-braking semantics are not yet calibrated.
                        braking = store.braking(scope, train['vehicle_id'])
                        receiving = receiving_evidence(frame, legal, territory, train['vehicle_id'])
                        train['admission'] = evaluate_admission(train, legal, braking, receiving,
                                                                sequence, time.time())
                if (not args.no_collect and frame['quality']['fresh'] and not frame['quality']['session_verified']
                        and frame['session_id'] != 'LEGACY_SESSION_UNVERIFIED' and time.time() >= next_collection
                        and (collection_process is None or collection_process.poll() is not None)):
                    script = (mod/'tools/collect-regional-inputs.py').resolve()
                    log = (root/'collector.log').resolve()
                    if not script.is_relative_to(mod) or not log.is_relative_to(root): raise ValueError('collector path escaped Mod')
                    with log.open('w', encoding='utf8') as output:
                        collection_process = subprocess.Popen([sys.executable, str(script), '--mod-root', str(mod)],
                            cwd=mod, stdout=output, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                    next_collection = time.time()+60
                frame['quality']['territory_verified'] = not audit['review_required']
                if audit['review_required']: frame['quality']['issues'].append('TERRITORY_REVIEW_REQUIRED')
                executor.expire(frame, time.time())
                annotate_transfer_evidence(frame, store.view(scope_key(frame)))
                if last_published != sequence:
                    snapshots.publish(frame); last_published = sequence
                # Decision and executor deliberately reread the persisted protocol frame.
                decision_frame = snapshots.read()
                scope = scope_key(decision_frame)
                plan = decide(decision_frame, store.view(scope), time.time())
                plan['observations'].extend(route_observations)
                atomic_json(root, 'plan.json', {'schema_version': 1, 'scope': scope, 'sequence': sequence, **plan})
                for command in plan['commands']: store.enqueue(command, scope)
                for command in store.pending(scope): executor.execute(command, snapshots.read(), time.time())
                regional_state = store.view(scope)
                counts = Counter(t['head_region'] or 'UNKNOWN' for t in frame['trains'])
                status = {'schema_version': 1, 'mode': 'SHADOW', 'game_write_enabled': False,
                          'save_id': frame['save_id'], 'session_id': frame['session_id'], 'topology_version': version,
                          'topology_generation': read_json(mod/'var/rail-map/rail-network-manifest.json').get('generated_at'),
                          'updated_at': time.time(), 'sequence': sequence, 'quality': frame['quality'], 'train_counts': dict(counts),
                          'trains': frame['trains'], 'calibration': calibration, 'coverage': audit,
                          'control': regional_state, 'observations': plan['observations'],
                          'requirements': ['FULL_TRAIN_FOOTPRINT', 'LEGAL_ROUTE', 'BRAKING_ENVELOPE', 'RECEIVING_SPACE'],
                          'state': 'OBSERVING' if frame['quality']['fresh'] else 'STALE'}
                atomic_json(root, 'status.json', status)
                atomic_json(mod, 'var/rail-map/regional-status.json', status)
                if args.once: print(json.dumps({k: status[k] for k in ('state', 'quality', 'train_counts', 'sequence')}, ensure_ascii=False))
            except (OSError, ValueError, KeyError) as exc:
                error = {'schema_version': 1, 'mode': 'SHADOW', 'state': 'DEGRADED', 'updated_at': time.time(),
                         'error': str(exc), 'game_write_enabled': False}
                atomic_json(root, 'status.json', error)
                try: atomic_json(mod, 'var/rail-map/regional-status.json', error)
                except OSError: pass  # A blocked UI reader cannot terminate collection.
                if args.once: raise
            if args.once or time.monotonic() >= deadline: break
            time.sleep(.5)
    finally: store.close()


if __name__ == '__main__': main()
