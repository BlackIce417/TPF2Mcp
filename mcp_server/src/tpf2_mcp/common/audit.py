"""Service lifecycle logs; per-tool-call audit is temporarily disabled."""
from datetime import datetime
import json
import os
import threading
from tpf2_mcp.common.paths import runtime_path

_started = datetime.now().astimezone()
_path = runtime_path('logs/mcp') / (_started.strftime('%Y-%m-%d_%H-%M-%S_%f') + '.jsonl')
_lock = threading.Lock()


def write_audit(event: dict) -> None:
    if str(event.get('event', '')).startswith('tool_call_'):
        return
    with _lock:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with _path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'timestamp': datetime.now().astimezone().isoformat(), **event},
                                    ensure_ascii=False, allow_nan=False, default=str) + '\n')


def start_audit() -> None:
    write_audit({'event': 'server_started', 'started_at': _started.isoformat(), 'pid': os.getpid()})


def http_logging_config() -> dict:
    """Console and service/error logs share the session's start-time name."""
    _path.parent.mkdir(parents=True, exist_ok=True)
    return {
        'version': 1, 'disable_existing_loggers': False,
        'formatters': {'standard': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'}},
        'handlers': {
            'console': {'class': 'logging.StreamHandler', 'stream': 'ext://sys.stderr', 'formatter': 'standard'},
            'file': {'class': 'logging.FileHandler', 'filename': str(_path.with_suffix('.http.log')),
                     'encoding': 'utf-8', 'formatter': 'standard'},
        },
        'root': {'handlers': ['console', 'file'], 'level': 'INFO'},
        'loggers': {name: {'handlers': [], 'propagate': True, 'level': 'INFO'}
                    for name in ('uvicorn', 'uvicorn.error')},
    }


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
