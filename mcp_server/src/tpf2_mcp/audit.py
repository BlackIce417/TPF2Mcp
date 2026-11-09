"""One append-only JSONL audit file per MCP process start."""
from datetime import datetime
import json
import os
from pathlib import Path
import threading

_started = datetime.now().astimezone()
_path = Path(__file__).resolve().parents[3] / 'logs' / 'mcp' / (_started.strftime('%Y-%m-%d_%H-%M-%S_%f') + '.jsonl')
_lock = threading.Lock()


def write_audit(event: dict) -> None:
    with _lock:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with _path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'timestamp': datetime.now().astimezone().isoformat(), **event},
                                    ensure_ascii=False, allow_nan=False, default=str) + '\n')


def start_audit() -> None:
    write_audit({'event': 'server_started', 'started_at': _started.isoformat(), 'pid': os.getpid()})


def safe_arguments(value):
    if isinstance(value, dict):
        return {key: ('[REDACTED]' if key.lower() in {'confirmation', 'token', 'authorization', 'password', 'api_key'}
                      else safe_arguments(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_arguments(item) for item in value]
    if isinstance(value, float):
        import math
        return value if math.isfinite(value) else None
    return value
