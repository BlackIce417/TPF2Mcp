"""Persist successfully read static Loader payloads for offline analysis."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import threading

CHANNELS = frozenset({
    'state.json', 'rail-network.json', 'operational-telemetry-signals.json',
    'station-geometry.json',
})
_lock = threading.Lock()
_started = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')


def cache_root() -> Path:
    # A bundled service lives directly under the Mod; source execution stays
    # under the repository. Neither route writes to AppData or the user home.
    return Path(__file__).resolve().parents[3] / 'var' / 'rail-map' / 'asset-cache' / _started


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_asset(key: str, value: dict, *, root: Path | None = None) -> Path | None:
    """Archive changed content. Separate channel reads are NOT a coherent batch."""
    if key not in CHANNELS:
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    root = cache_root() if root is None else root
    with _lock:
        directory = root / key.removesuffix('.json') / digest
        payload_path = directory / key
        if not (directory / 'metadata.json').is_file():
            directory.mkdir(parents=True, exist_ok=True)
            _atomic_json(payload_path, value)
            if key == 'state.json':
                for collection in ('towns', 'industries', 'stations', 'lines', 'cargo_types'):
                    if isinstance(value.get(collection), list):
                        _atomic_json(directory / f'{collection}.json', {
                            'items': value[collection], 'snapshot_sequence': value.get('sequence'),
                            'snapshot_timestamp': value.get('timestamp'),
                            'session_id': (value.get('metadata') or {}).get('session_id'),
                        })
            _atomic_json(directory / 'metadata.json', {
                'channel': key, 'sha256': digest,
                'captured_at': datetime.now().astimezone().isoformat(),
                'source': 'loader_shared_memory', 'schema_version': value.get('schema_version'),
                'session_id': value.get('session_id') or (value.get('metadata') or {}).get('session_id'),
                'source_timestamp': value.get('generated_at', value.get('timestamp')),
                'source_sequence': value.get('sequence'),
                'capture_id': value.get('capture_id'),
                'coherent_batch_verified': False,
            })
        pointer = root / key.removesuffix('.json') / 'latest.json'
        current = {'sha256': digest, 'payload': str(payload_path.relative_to(root))}
        if not pointer.is_file() or json.loads(pointer.read_text(encoding='utf-8')) != current:
            _atomic_json(pointer, current)
    return payload_path
