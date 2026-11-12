"""Capture matching live rail/signal inventories and a world snapshot."""
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mcp_server' / 'src'))
from tpf2_mcp.repositories.asset_cache import cache_root, persist_asset
from tpf2_mcp.transport.loader_telemetry import read_json_channel
from tpf2_mcp.transport.lua_commands import LoaderLuaCommandClient


def main():
    heartbeat = read_json_channel('heartbeat.json')
    if not heartbeat.get('bridge_ready') or not 0 <= time.time()-heartbeat.get('last_update', 0) <= 10:
        raise RuntimeError('Loader heartbeat is not fresh')
    for _ in range(10):
        network = read_json_channel('rail-network.json')
        signals = read_json_channel('operational-telemetry-signals.json')
        if network.get('capture_id') and network['capture_id'] == signals.get('capture_id'):
            break
        time.sleep(.1)
    else:
        raise RuntimeError('Unable to obtain a matching rail/signal capture')
    LoaderLuaCommandClient(timeout=20).call('get_game_state', {'force_refresh': True})
    world = read_json_channel('state.json')
    paths = {key: str(persist_asset(key, value)) for key, value in (
        ('rail-network.json', network), ('operational-telemetry-signals.json', signals), ('state.json', world))}
    report = {'capture_id': network['capture_id'], 'rail_signal_batch_matched': True,
              'world_snapshot_same_batch': False, 'paths': paths,
              'network_counts': network.get('counts'), 'signal_counts': signals.get('counts'),
              'world_counts': {key: len(world.get(key, [])) for key in ('towns','industries','stations','lines')},
              'network_errors': network.get('errors'), 'signal_errors': signals.get('errors')}
    (cache_root()/'capture-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
