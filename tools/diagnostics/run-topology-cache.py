"""Build and validate a topology from an offline rail-network cache."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mcp_server' / 'src'))
from tpf2_mcp.algorithms.generate_topology.gen_topology import generate_topology, Edge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('network', type=Path)
    parser.add_argument('--signals', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw_bytes = args.network.read_bytes()
    raw = json.loads(raw_bytes.decode('utf-8-sig'))
    signals = json.loads(args.signals.read_text(encoding='utf-8-sig')) if args.signals else None
    started = time.perf_counter()
    graph = generate_topology(raw, signals)
    elapsed = time.perf_counter() - started
    coverage = defaultdict(list)
    all_edges = dict(graph.edges)
    for node in graph.nodes.values():
        for row in (node.station_wrapper or {}).get('internal_edges', []):
            all_edges[row['id']] = Edge(**row)
    for edge in all_edges.values():
        reverse = all_edges[edge.reverse_edge_id]
        assert reverse.from_node_id == edge.to_node_id
        assert reverse.to_node_id == edge.from_node_id
        assert reverse.track_resource_id == edge.track_resource_id
        assert abs(reverse.length_m - edge.length_m) < 1e-9
        if edge.id in graph.edges:
            assert edge.id in graph.outgoing[edge.from_node_id]
            assert edge.id in graph.incoming[edge.to_node_id]
        if edge.id > edge.reverse_edge_id:
            continue
        for part in edge.track_segments:
            coverage[part['game_edge_id']].append(sorted((part['begin_position01'], part['end_position01'])))
    assert set(coverage) == {e['entity_id'] for e in raw['edges']}
    for intervals in coverage.values():
        end = 0.0
        for a, b in sorted(intervals):
            assert abs(a-end) < 1e-9, 'duplicate or missing track interval'
            end = b
        assert abs(end-1.0) < 1e-9
    report = {
        'source_network': str(args.network.resolve()),
        'source_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'source_signals': str(args.signals.resolve()) if args.signals else None,
        'raw_nodes': len(raw['nodes']), 'raw_edges': len(raw['edges']),
        'raw_stations': len(raw.get('stations', [])),
        'topology_nodes': len(graph.nodes), 'directed_edges': len(graph.edges),
        'node_types': dict(Counter(n.type.value for n in graph.nodes.values())),
        'boundary_kinds': dict(Counter(n.boundary_kind for n in graph.nodes.values())),
        'signal_inventory_objects': len((signals or {}).get('signal_edge_objects', [])),
        'mapped_signal_ids': len({s for n in graph.nodes.values() for s in n.signal_ids} |
                                {s for n in graph.nodes.values() for raw_node in (n.station_wrapper or {}).get('internal_nodes', []) for s in raw_node['signal_ids']}),
        'station_wrappers': sum(n.station_wrapper is not None for n in graph.nodes.values()),
        'physical_length_m': sum(e.length_m for e in all_edges.values()) / 2,
        'covered_raw_edges': len(coverage), 'coverage_validated': True,
        'generation_seconds': round(elapsed, 4),
        'warnings': graph.warnings, 'dispatch_ready': graph.dispatch_ready,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in [('topology.json', graph.to_dict()), ('validation.json', report)]:
        (args.output / name).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
