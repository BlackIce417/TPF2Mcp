"""Inspect the Changsha--Shenyang corridor from the saved topology."""
import heapq
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp_server'/'src'))
from tpf2_mcp.rail_topology import RailGraph


def main():
    root = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'diagnostics'/'topology-live-20261111'
    g = json.loads((root/'topology.json').read_text(encoding='utf-8'))
    report = json.loads((root/'validation.json').read_text(encoding='utf-8'))
    raw = json.loads(Path(report['source_network']).read_text(encoding='utf-8'))
    physical = RailGraph(raw)
    nodes = {n['id']: n for n in g['nodes']}
    edges = {e['id']: e for e in g['edges']}
    starts = [n['id'] for n in nodes.values() if n['type']=='station' and n['display_name']=='Changsha']
    ends = [n['id'] for n in nodes.values() if n['type']=='station' and n['display_name']=='Shenyang']
    adjacency = {}
    for e in edges.values():
        adjacency.setdefault(e['from_node_id'], []).append(e)
    highlighted = set()
    paths = []
    for source in starts:
        distances, previous, queue = {source: 0}, {}, [(0,source)]
        while queue:
            distance, nid = heapq.heappop(queue)
            if distance != distances[nid]: continue
            for e in adjacency.get(nid,[]):
                target, candidate = e['to_node_id'], distance+e['length_m']
                if candidate < distances.get(target,float('inf')):
                    distances[target],previous[target] = candidate,e['id']
                    heapq.heappush(queue,(candidate,target))
        for target in ends:
            if target not in distances: continue
            route, current = [], target
            while current != source:
                eid = previous[current]
                route.append(eid)
                current = edges[eid]['from_node_id']
            paths.append((source,target,distances[target],route))
    # Show shortest candidate routes for each departure terminal. Extra remote
    # platform pairs may take huge detours; do not highlight those as corridor.
    for source in starts:
        candidates=[p for p in paths if p[0]==source]
        if candidates:
            highlighted.update(min(candidates,key=lambda p:p[2])[3])
    route_nodes={n for eid in highlighted for n in (edges[eid]['from_node_id'],edges[eid]['to_node_id'])}
    route_resources={edges[eid]['track_resource_id'] for eid in highlighted}
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    fig=plt.figure(figsize=(17,17))
    grid=fig.add_gridspec(2,2,width_ratios=[1.65,1],hspace=.18,wspace=.18)
    overview=fig.add_subplot(grid[:,0])
    detail_a=fig.add_subplot(grid[0,1])
    detail_b=fig.add_subplot(grid[1,1])
    xs=[nodes[n]['position']['x']/1000 for n in route_nodes]
    ys=[nodes[n]['position']['y']/1000 for n in route_nodes]
    limits=(min(xs)-.5,max(xs)+.5,min(ys)-.5,max(ys)+.5)
    physical_ids=set()
    for e in edges.values():
        if e['track_resource_id'] in route_resources:
            physical_ids.update(s['game_edge_id'] for s in e['track_segments'])
    signal_numbers={nid:i+1 for i,nid in enumerate(sorted((n for n in route_nodes if nodes[n]['type']=='signal'),key=lambda n:-nodes[n]['position']['y']))}

    def draw(ax, title, bounds, detail=False):
        for n in nodes.values():
            wrapper=n.get('station_wrapper')
            if not wrapper: continue
            points=sorted(set((p['position']['x']/1000,p['position']['y']/1000) for p in wrapper['internal_nodes']))
            def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            lower=[];upper=[]
            for p in points:
                while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:lower.pop()
                lower.append(p)
            for p in reversed(points):
                while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:upper.pop()
                upper.append(p)
            hull=lower[:-1]+upper[:-1]
            if len(hull)>=3:
                ax.add_patch(Polygon(hull,facecolor='#ee9028',edgecolor='#cc7700',alpha=.16,zorder=2))
        for eid in sorted(physical.edges):
            points=physical.samples(eid,steps=32)
            px=[p[0]/1000 for p in points]; py=[p[1]/1000 for p in points]
            if max(px)<bounds[0] or min(px)>bounds[1] or max(py)<bounds[2] or min(py)>bounds[3]:continue
            ax.plot(px,py,color='#2475b9' if eid in physical_ids else '#bdc5ce',lw=1.2 if eid in physical_ids else .65,zorder=1)
        for nid,n in nodes.items():
            x,y=n['position']['x']/1000,n['position']['y']/1000
            if not bounds[0]<x<bounds[1] or not bounds[2]<y<bounds[3]:continue
            station=n['type']=='station'; signal=n['type']=='signal'
            ax.scatter(x,y,s=65 if station else 20 if signal else 13,
                       marker='s' if station else '^' if signal else 'o',
                       c='#ee9028' if station else '#21966f' if signal else '#84669c',zorder=4)
            if station:
                label=f"{n['display_name']}\n车站节点 {nid}" if n.get('station_wrapper') else f"{n['display_name']}\n终端 {nid}"
            elif nid in signal_numbers:
                label=f"S{signal_numbers[nid]}" + (f" · {n['signal_ids'][0]}" if detail else '')
            elif detail:
                label=f"J{nid}"
            else:continue
            ax.annotate(label,(x,y),xytext=(6,4),textcoords='offset points',fontsize=7 if detail else 8,
                        fontproperties=font,color='#333333',zorder=5)
        ax.set_xlim(bounds[:2]); ax.set_ylim(bounds[2:]); ax.set_aspect('equal')
        ax.set_facecolor('#f7f9fc'); ax.grid(alpha=.15)
        ax.set_title(title,fontproperties=font,fontsize=13)
        ax.set_xlabel('X (km)');ax.set_ylabel('Y (km)')
    draw(overview,'Changsha → Shenyang · 区间全貌',limits)
    for ax,ids,title in [(detail_a,starts,'Changsha 站端放大'),(detail_b,ends,'Shenyang 站端放大')]:
        x=sum(nodes[n]['position']['x'] for n in ids)/len(ids)/1000
        y=sum(nodes[n]['position']['y'] for n in ids)/len(ids)/1000
        draw(ax,title,(x-.55,x+.55,y-.55,y+.55),True)
    lengths=[min(p[2] for p in paths if p[0]==s)/1000 for s in starts if any(p[0]==s for p in paths)]
    fig.suptitle('Changsha—Shenyang 区间详图',fontproperties=font,fontsize=22,y=.975)
    fig.text(.5,.945,f"站界到站界候选路径：{' / '.join(f'{v:.2f} km' for v in lengths)}；区间信号节点 {len(signal_numbers)} 个；橙色区域已归入车站 wrapper",
             ha='center',fontproperties=font,fontsize=11)
    handles=[Line2D([],[],color='#2475b9',label='候选区间路径'),Line2D([],[],color='#bdc5ce',label='邻接轨道'),
             Line2D([],[],marker='s',color='#ee9028',ls='None',label='车站及咽喉节点'),
             Line2D([],[],marker='^',color='#21966f',ls='None',label='信号机'),
             Line2D([],[],marker='o',color='#84669c',ls='None',label='分岔/端点')]
    fig.legend(handles=handles,ncol=5,loc='lower center',bbox_to_anchor=(.5,.035),prop=font)
    fig.text(.5,.02,'使用保存的同批路网/信号数据；轨道曲线按物理几何绘制。蓝线是物理最短候选路径，尚未施加上下行及道岔进路约束。',
             ha='center',fontproperties=font,fontsize=10)
    fig.subplots_adjust(top=.91,bottom=.085)
    output=root/'changsha-shenyang.png'
    fig.savefig(output,dpi=200,facecolor='white');plt.close(fig)
    print(output)


if __name__=='__main__':
    main()
