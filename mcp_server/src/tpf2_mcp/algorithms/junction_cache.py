"""Versioned single-file publication for junction index and detail geometry."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from tpf2_mcp.algorithms.junctions import JunctionConfig, identify_junctions


def build_junction_cache(network: dict, source_generation: int, config: JunctionConfig | None = None) -> dict:
    model = identify_junctions(network, config)
    model['recognition_id'] = hashlib.sha256(json.dumps(model,sort_keys=True).encode()).hexdigest()[:24]
    edges = {e['entity_id']: e for e in network.get('edges', [])}
    nodes = {n['entity_id']: n for n in network.get('nodes', [])}
    model['source_generation'] = source_generation
    details = {}
    station_edges = set(model['station_mask']['edge_ids'])
    adjacency = {}
    for eid in station_edges:
        for key in ('node0', 'node1'):
            adjacency.setdefault(edges[eid][key], set()).add(eid)
    for region in model['regions']:
        # Outside edge is context only, including when longer than probe budget.
        ids = set(region['context_edge_ids']) | {p['outside_edge_id'] for p in region['ports']}
        protected = {eid for p in region['ports'] if p['stop_reason'] == 'STATION_BOUNDARY'
                     for eid in adjacency.get(p['end_node_id'], set())}
        ids.update(protected)
        node_ids = {edges[eid][key] for eid in ids for key in ('node0', 'node1')} | set(region['switch_node_ids'])
        details[region['id']] = dict(region=region, station_edge_ids=sorted(protected), edges=[edges[eid] for eid in sorted(ids)],
                                     nodes=[nodes[nid] for nid in sorted(node_ids)])
        trace_ids = ids | {eid for p in region['ports'] for eid in p['destination']['edge_ids']}
        trace_nodes = {edges[eid][k] for eid in trace_ids for k in ('node0','node1')} | node_ids
        details[region['id']]['trace_edges'] = [edges[eid] for eid in sorted(trace_ids)]
        details[region['id']]['trace_nodes'] = [nodes[nid] for nid in sorted(trace_nodes)]
    model['details'] = details
    return model


def write_junction_cache(network: dict, directory: Path, source_generation: int, config: JunctionConfig | None = None) -> dict:
    model = build_junction_cache(network, source_generation, config)
    directory.mkdir(parents=True, exist_ok=True)
    # Unique same-directory temporary file permits concurrent exporters without torn JSON.
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='junctions-', suffix='.tmp', delete=False) as stream:
            name = stream.name
            json.dump(model, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, directory / 'junctions.json')
    finally:
        if name and Path(name).exists(): Path(name).unlink()
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path, default=Path(__file__).resolve().parents[4] / 'var/rail-map')
    args = parser.parse_args()
    directory = args.data_directory.resolve()
    if not directory.is_relative_to(Path(__file__).resolve().parents[4]):
        parser.error('data directory must be inside the project or bundled Mod')
    network = json.loads((directory / 'rail-network-data.json').read_text(encoding='utf-8'))
    manifest = json.loads((directory / 'rail-network-manifest.json').read_text(encoding='utf-8'))
    if not network.get('save_id') or network['save_id'] != manifest.get('save_id'):
        parser.error('network and manifest must have the same nonempty save_id')
    result = write_junction_cache(network, directory, manifest['generated_at'])
    print(json.dumps(result['counts']))


if __name__ == '__main__': main()
