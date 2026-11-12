"""Read-only live game -> exported network -> recognition -> API cache validation."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mcp_server/src'))
from tpf2_mcp.transport.bridge import BridgeClient
from tpf2_mcp.repositories.save_scope import snapshot_save_id


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    output=ROOT/'diagnostics/live-junctions'/time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True,exist_ok=False)
    bridge=BridgeClient(timeout_seconds=60)
    health=bridge.status()
    if not health.get('connected'): raise RuntimeError('Bridge is not live')
    baseline=read(ROOT/'var/rail-map/junctions.json')
    (output/'baseline.json').write_text(json.dumps(baseline,ensure_ascii=False),encoding='utf-8')
    report=dict(bridge_directory=str(bridge.directory.resolve()),started_at=time.time(),health=health,
                ping=bridge.ping(),samples=[])
    for index in range(2):
        before=bridge.game_state(force_refresh=True)
        source=bridge.directory/'rail-network.json'
        old_stamp=source.stat().st_mtime_ns if source.exists() else None
        started=time.time();response=bridge.export_rail_network()
        stamp=source.stat().st_mtime_ns
        if stamp==old_stamp: raise RuntimeError('Game export did not refresh the rail-network sidecar')
        raw=read(source)
        after=bridge.game_state(force_refresh=True)
        save_id=snapshot_save_id(before)
        if save_id!=snapshot_save_id(after): raise RuntimeError('Save changed during live capture')
        path=output/f'sample-{index}.json'
        path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
        for label,value in [('before',before),('after',after)]:
            (output/f'snapshot-{index}-{label}.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        compiled=output/f'compiled-{index}'
        subprocess.run([sys.executable,'-B',str(ROOT/'tools/visualization/export-rail-network-map.py'),'--input',str(path),
                        '--output-directory',str(compiled),'--save-id',save_id],cwd=ROOT,check=True)
        model=read(compiled/'junctions.json')
        mask_edges=set(model['station_mask']['edge_ids']);mask_nodes=set(model['station_mask']['node_ids'])
        overlap=sum(len(set(r['edge_ids'])&mask_edges)+len(set(r['switch_node_ids'])&mask_nodes) for r in model['regions'])
        invalid=[r['id'] for r in model['regions'] if r['boundary_validation']['status']!='COMPLETE_TOPOLOGICAL_CUT']
        if overlap or invalid: raise RuntimeError(f'Invalid live recognition: overlap={overlap}, invalid={invalid}')
        sample=dict(index=index,started_at=started,elapsed_seconds=round(time.time()-started,2),save_id=save_id,
                    before_sequence=before.get('sequence'),after_sequence=after.get('sequence'),
                    game_before=before.get('game'),game_after=after.get('game'),export_response=response,
                    source_mtime_ns=stamp,counts=model['counts'],topology_id=model['topology_id'],
                    recognition_id=model['recognition_id'],station_overlap=overlap,invalid_boundaries=invalid)
        report['samples'].append(sample)
        print(json.dumps(sample,ensure_ascii=False),flush=True)
    first,second=report['samples']
    report['same_save_between_samples']=first['save_id']==second['save_id']
    report['same_topology_between_samples']=first['topology_id']==second['topology_id']
    report['same_recognition_between_samples']=first['recognition_id']==second['recognition_id']
    report['baseline_counts']=baseline['counts']
    report['same_topology_as_baseline']=baseline['topology_id']==second['topology_id']
    if not report['same_save_between_samples']: raise RuntimeError('Save changed between samples')
    # Publish only after both live samples passed consistency and boundary checks.
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/visualization/export-rail-network-map.py'),'--input',str(output/'sample-1.json'),
                    '--output-directory',str(ROOT/'var/rail-map'),'--save-id',second['save_id']],cwd=ROOT,check=True)
    report['published_recognition_id']=read(ROOT/'var/rail-map/junctions.json')['recognition_id']
    report['finished_at']=time.time()
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(output/'report.json'),same_topology=report['same_topology_between_samples'],
                         same_recognition=report['same_recognition_between_samples'],published=report['published_recognition_id']),ensure_ascii=False))


if __name__=='__main__':main()
