"""Independently follow every branch to its next physical endpoint and render evidence."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mcp_server/src'))
from tpf2_mcp.algorithms.rail_topology import RailGraph


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    network=json.loads((ROOT/'var/rail-map/rail-network-data.json').read_text(encoding='utf-8'))
    model=json.loads((ROOT/'var/rail-map/junctions.json').read_text(encoding='utf-8'))
    graph=RailGraph(network)
    blocked_nodes=set(model['station_mask']['node_ids']);blocked_edges=set(model['station_mask']['edge_ids'])
    output=ROOT/'diagnostics/junction-review';output.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(3,3,figsize=(21,18));rows=[]
    for region,ax in zip(model['regions'],axes.flat):
        row=dict(id=region['id'],classification=region['classification'],geometric_classification=region['geometric_classification'],
                 parallel_peers=region['parallel_peer_ids'],branches=[])
        for i,port in enumerate(region['ports']):
            # Independent terminal-chain audit, no recognition distance or angle threshold.
            node,eid=port['node_id'],port['outside_edge_id'];seen=set();path=[]
            while True:
                if eid in blocked_edges:reason='STATION_BOUNDARY';break
                if eid in seen:reason='LOOP';break
                seen.add(eid);path.append(eid);edge=graph.edges[eid]
                node=edge['node1'] if edge['node0']==node else edge['node0']
                if node in blocked_nodes:reason='STATION_BOUNDARY';break
                adjacent=graph.adjacency[node]
                if len(adjacent)!=2:reason='SWITCH' if len(adjacent)>2 else 'DEAD_END';break
                eid=next(e for e,_ in adjacent if e!=eid)
            destination=port['destination'];matches=(destination['node_id']==node and destination['edge_ids']==path)
            row['branches'].append(dict(port=port['id'],end_node=node,stop_reason=reason,
                                       length_m=round(sum(graph.lengths[e] for e in path),1),
                                       destination=destination['label'],matches_model=matches))
            color=plt.get_cmap('tab10')(i%10)
            for e in path:
                pts=graph.samples(e);ax.plot([p[0] for p in pts],[p[1] for p in pts],color=color,lw=1.5)
            end=graph.nodes[node]['position']
            ax.annotate(destination['label'] or reason,(end['x'],end['y']),fontsize=7)
        for eid in region['edge_ids']:
            pts=graph.samples(eid);ax.plot([p[0] for p in pts],[p[1] for p in pts],color='black',lw=3)
        for node in region['switch_node_ids']:
            p=graph.nodes[node]['position'];ax.plot(p['x'],p['y'],'ko',ms=4)
        ax.set_title(f"{region['id']} / {len(region['destination_groups'])} destinations\npeers: {','.join(region['parallel_peer_ids']) or 'none'}",fontsize=10)
        ax.set_aspect('equal');ax.tick_params(labelsize=7);rows.append(row)
    fig.suptitle('Independent full-branch review: colored branches stop at station / switch / dead end',fontsize=16)
    fig.tight_layout();fig.savefig(output/'full-branches.png',dpi=160);plt.close(fig)
    report=dict(save_id=model['save_id'],algorithm_version=model['algorithm_version'],regions=rows,
                branch_count=sum(len(r['branches']) for r in rows),
                mismatches=sum(not b['matches_model'] for r in rows for b in r['branches']))
    (output/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='regions'}))


if __name__=='__main__':main()
