"""Render a cached dispatch topology as a static inspection image."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch


def main():
    root = Path(sys.argv[1]).resolve()
    graph = json.loads((root / 'topology.json').read_text(encoding='utf-8'))
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['axes.unicode_minus'] = False
    nodes = {n['id']: n for n in graph['nodes']}
    edges = graph['edges']
    station_nodes = [n for n in nodes.values() if n['type'] == 'station']
    center = max(station_nodes, key=lambda n: sum(e['from_node_id'] == n['id'] for e in edges))
    fig, axes = plt.subplots(1, 2, figsize=(19, 13), gridspec_kw={'width_ratios': [1.25, 1]})
    colors = {'station': '#ef8d23', 'switch_candidate': '#3678b5', 'endpoint': '#98a5af', 'cycle_anchor': '#8762a8', 'signal': '#209b76'}

    for ax, detail in zip(axes, (False, True)):
        ax.set_facecolor('#f6f8fa')
        for e in edges:
            # Both directed arcs exist; show a double arrow once per resource.
            if e['id'] > e['reverse_edge_id']:
                continue
            a, b = nodes[e['from_node_id']]['position'], nodes[e['to_node_id']]['position']
            p, q = (a['x']/1000, a['y']/1000), (b['x']/1000, b['y']/1000)
            if detail:
                cx, cy = center['position']['x']/1000, center['position']['y']/1000
                if not (min(p[0],q[0]) <= cx+1.1 and max(p[0],q[0]) >= cx-1.1
                        and min(p[1],q[1]) <= cy+1.1 and max(p[1],q[1]) >= cy-1.1):
                    continue
            patch = FancyArrowPatch(p, q, arrowstyle='<->', mutation_scale=7 if detail else 4,
                                    linewidth=1 if detail else .6, color='#687988', alpha=.7,
                                    connectionstyle='arc3,rad=0.08', shrinkA=3, shrinkB=3)
            ax.add_patch(patch)
            if detail and abs(p[0]-cx)<1.1 and abs(p[1]-cy)<1.1 and abs(q[0]-cx)<1.1 and abs(q[1]-cy)<1.1:
                ax.text((p[0]+q[0])/2, (p[1]+q[1])/2, f"{e['length_m']:.0f}m",
                        fontsize=6, color='#495560', bbox={'facecolor':'white','edgecolor':'none','alpha':.75,'pad':1})
        for kind, marker in [('switch_candidate','o'), ('endpoint','x'), ('cycle_anchor','o'), ('station_terminal','s'), ('station_with_throats','s'), ('signal','^')]:
            group = [n for n in nodes.values() if n['boundary_kind'] == kind]
            color = colors['station'] if kind in ('station_terminal', 'station_with_throats') else colors[kind]
            ax.scatter([n['position']['x']/1000 for n in group], [n['position']['y']/1000 for n in group],
                       c=color, marker=marker, s=32 if kind in ('station_terminal', 'station_with_throats') else 12,
                       zorder=4, linewidths=.8)
        labeled = set()
        for n in station_nodes:
            x, y = n['position']['x']/1000, n['position']['y']/1000
            if n['display_name'] in labeled:
                continue
            if detail and not (abs(x-cx)<1.1 and abs(y-cy)<1.1):
                continue
            labeled.add(n['display_name'])
            ax.annotate(n['display_name'], (x,y), xytext=(5,6), textcoords='offset points',
                        fontsize=8, fontproperties=font, color='#9d5110', zorder=5)
        ax.set_aspect('equal')
        ax.grid(alpha=.15)
        ax.set_xlabel('X (km)')
        ax.set_ylabel('Y (km)')
        if detail:
            ax.set_xlim(cx-1.1,cx+1.1)
            ax.set_ylim(cy-1.1,cy+1.1)
            ax.set_title('局部结构与边长（车站包含咽喉区）', fontproperties=font, fontsize=12)
        else:
            xs=[n['position']['x']/1000 for n in nodes.values()]
            ys=[n['position']['y']/1000 for n in nodes.values()]
            ax.set_xlim(min(xs)-1,max(xs)+1)
            ax.set_ylim(min(ys)-1,max(ys)+1)
            ax.set_title('全网连接关系 · 平面坐标布局',fontproperties=font,fontsize=12)
    fig.suptitle(f"缓存路网生成结果：{len(nodes)} 个节点 / {len(edges)} 条有向边",fontproperties=font,fontsize=19,y=.975)
    legend = [Line2D([],[],marker=m,color=c,linestyle='None',label=l) for m,c,l in
              [('s','#ef8d23','车站节点'),('o','#3678b5','道岔候选'),('x','#98a5af','轨道端点'),('^','#209b76','信号机')]]
    fig.legend(handles=legend,loc='lower center',ncol=3,prop=font,bbox_to_anchor=(.5,.045))
    fig.text(.5,.02,'双箭头表示候选双向连接，尚未验证上下行与道岔进路。仅接入通过所属边投影残差校验的信号机。\n连线为拓扑示意，非原始轨道曲线；标注长度使用轨道曲线计算值。',
             ha='center',fontproperties=font,fontsize=10,color='#555555')
    fig.subplots_adjust(top=.93,bottom=.1,wspace=.22)
    output = root / 'topology-overview.png'
    fig.savefig(output,dpi=160,facecolor='white')
    plt.close(fig)
    print(output)


if __name__ == '__main__':
    main()
