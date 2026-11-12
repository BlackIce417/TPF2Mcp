"""Generate station/throat wrappers from an existing asset capture report."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mcp_server'/'src'))
from tpf2_mcp.algorithms.generate_topology.station_topology_node import generate_station_topology_nodes, DEFAULT_SIGNAL_SEARCH_M


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('capture_report',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.capture_report.read_text(encoding='utf-8'))
    network=json.loads(Path(report['paths']['rail-network.json']).read_text(encoding='utf-8'))
    signals=json.loads(Path(report['paths']['operational-telemetry-signals.json']).read_text(encoding='utf-8'))
    if not network.get('capture_id') or network['capture_id']!=signals.get('capture_id'):
        raise ValueError('rail and signal capture IDs do not match')
    wrappers=generate_station_topology_nodes(network,signals)
    summary={'stations':len(wrappers),
             'boundaries':dict(Counter(b.reason for s in wrappers for b in s.boundaries)),
             'overlapping_stations':[s.station_name for s in wrappers if s.contested_node_ids],
             'stations_without_switches':[s.station_name for s in wrappers if not s.switch_node_ids]}
    payload={'schema_version':1,'capture_id':network['capture_id'],
             'parameters':{'signal_search_m':DEFAULT_SIGNAL_SEARCH_M,'approach_limit_m':800,'switch_gap_m':250},
             'summary':summary,'stations':[s.to_dict() for s in wrappers]}
    output=args.output.resolve()
    if not output.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError('output must stay inside project root')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))
    for s in wrappers:
        if s.station_name in ('Changsha','Shenyang'):
            print(json.dumps({'station':s.station_name,'switches':len(s.switch_node_ids),
                              'internal_nodes':len(s.internal_node_ids),'internal_arcs':len(s.internal_edge_ids),
                              'boundaries':[as_boundary.__dict__ for as_boundary in s.boundaries]},ensure_ascii=True))


if __name__=='__main__':
    main()
