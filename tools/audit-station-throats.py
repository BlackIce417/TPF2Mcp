"""Render current station candidates and quantify overlap/clipping for review."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp_server' / 'src'))
from tpf2_mcp.station_preview import _edge_samples


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    source = json.loads((ROOT/'var/rail-map/rail-network-data.json').read_text(encoding='utf-8'))
    nodes = {n['entity_id']: n for n in source['nodes']}
    edges = {e['entity_id']: e for e in source['edges']}
    out = ROOT/'diagnostics/station-throats-review'
    out.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(4, 4, figsize=(20, 20))
    rows = []
    for station, ax in zip(source['stations'], axes.flat):
        preview = json.loads((ROOT/f"var/rail-map/station-previews/station-{station['entity_id']}.json").read_text(encoding='utf-8'))
        regions = preview['throat_model']['regions']
        chosen = {e for r in regions for e in r['edge_ids']}
        platforms = {e for t in station['terminals'] for e in t.get('platform_edge_ids', [])}
        visible = {e['entity_id'] for e in preview['edges']}
        referenced = chosen | platforms | visible
        for eid in sorted(referenced):
            points = _edge_samples(edges[eid], nodes)
            ax.plot([p[0] for p in points], [p[1] for p in points],
                    color='magenta' if eid in platforms else 'teal' if eid in chosen else '#cccccc', linewidth=1)
        for r in regions:
            for port in r['ports']:
                p = port['position']; ax.plot(p['x'],p['y'],'o',mfc='none',mec='orange',ms=4)
        rows.append(dict(station=station['name'],station_id=station['entity_id'],regions=len(regions),
                         candidate_edges=len(chosen),platform_overlap=len(chosen & platforms),
                         outside_preview=len(chosen-visible)))
        ax.set_title(f"{station['name']} / {len(regions)} regions", fontsize=11)
        ax.set_aspect('equal'); ax.tick_params(labelsize=6)
    fig.suptitle('Throat review: teal=candidate, magenta=platform, orange=boundary',fontsize=16)
    fig.tight_layout(); fig.savefig(out/'all-stations.png',dpi=140); plt.close(fig)
    (out/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False))


if __name__ == '__main__': main()
