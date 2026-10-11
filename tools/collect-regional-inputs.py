"""Slow read-only regional collection, separate from the fast decision worker."""
import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'mcp_server/src'))
from tpf2_mcp.bridge import BridgeClient
from tpf2_mcp.config import mod_dir
from tpf2_mcp.save_scope import snapshot_save_id
from tpf2_mcp.dispatch_runtime.collector import read_json
from tpf2_mcp.dispatch_runtime.storage import atomic_json


def collect(mod):
    bridge = mod/'bridge'
    before = read_json(bridge/'operational-telemetry-vehicle_positions.json')
    if not before.get('session_id'): raise ValueError('reload the new Lua collector before scope verification')
    client = BridgeClient(bridge, timeout_seconds=90)
    world = client.game_state(force_refresh=True)
    client.operational_telemetry('signals')
    signals = read_json(bridge/'operational-telemetry-signals.json')
    after = read_json(bridge/'operational-telemetry-vehicle_positions.json')
    if not before['session_id'] == after.get('session_id') == signals.get('session_id'):
        raise ValueError('game session changed during slow collection')
    evidence = {'schema_version': 1, 'session_id': after['session_id'], 'save_id': snapshot_save_id(world),
                'world_timestamp': world['timestamp'], 'signal_generated_at': signals.get('generated_at'),
                'collected_at': time.time(), 'verified': True, 'source': 'BRIDGE_REQUESTS_BRACKETED_BY_GAME_SESSION'}
    atomic_json(mod, 'bridge/dispatch/regional/input-scope.json', evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod-root', type=Path)
    args = parser.parse_args()
    mod = (args.mod_root or mod_dir()).resolve()
    if not (mod/'res/scripts/tpf2_mcp/runtime.lua').is_file(): raise ValueError('target is not an MCP Mod')
    print(collect(mod))


if __name__ == '__main__': main()
