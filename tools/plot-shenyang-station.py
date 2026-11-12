"""Render Shenyang station interiors and station-wrapper boundary evidence."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'/'src'))
from tpf2_mcp.rail_topology import RailGraph


def main():
    root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'diagnostics'/'topology-station-wrappers-20261111'
    graph=json.loads((root/'topology.json').read_text(encoding='utf-8'))
    report=json.loads((root/'validation.json').read_text(encoding='utf-8'))
    raw=json.loads(Path(report['source_network']).read_text(encoding='utf-8'))
    station=next(n for n in graph['nodes'] if n['display_name']=='Shenyang')
    wrapper=station['station_wrapper']
    physical=RailGraph(raw)
    internal={n['id']:n for n in wrapper['internal_nodes']}
    external={n['id']:n for n in graph['nodes'] if n['id']!=station['id']}
    all_nodes={**external,**internal}
    center=np.array([station['position']['x'],station['position']['y']])
    points=np.array([[n['position']['x'],n['position']['y']] for n in internal.values()])
    _,_,vectors=np.linalg.svd(points-center)
    longitudinal=vectors[0]
    if longitudinal[1]<0:longitudinal=-longitudinal
    lateral=np.array([-longitudinal[1],longitudinal[0]])
    def xy(point):
        delta=np.array(point[:2])-center
        return float(delta@longitudinal),float(delta@lateral)
    def node_xy(n):return xy([n['position']['x'],n['position']['y']])
    coords={nid:node_xy(n) for nid,n in all_nodes.items()}
    station_coords=[coords[n] for n in internal]
    lo=min(p[0] for p in station_coords); hi=max(p[0] for p in station_coords)
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    fig=plt.figure(figsize=(20,12))
    grid=fig.add_gridspec(3,2,height_ratios=[1.3,1,.65],hspace=.55,wspace=.17)
    overview=fig.add_subplot(grid[0,:]); left=fig.add_subplot(grid[1,0]); right=fig.add_subplot(grid[1,1])
    text=fig.add_subplot(grid[2,:]);text.axis('off')
    segments=[]
    for e in wrapper['internal_edges']:
        if e['id']<e['reverse_edge_id']:segments.extend(e['track_segments'])
    def curve(eid,start=0,end=1):
        raw_points=np.array(physical.samples(eid,steps=128))
        if start==0 and end==1:
            points=raw_points[:,:2]
        else:
            ts=np.linspace(min(start,end),max(start,end),max(3,int(abs(end-start)*128)+2))
            points=np.column_stack([np.interp(ts,np.linspace(0,1,129),raw_points[:,axis]) for axis in range(2)])
        delta=points-center
        return np.column_stack((delta@longitudinal,delta@lateral))
    boundary_numbers={b['node_id']:i+1 for i,b in enumerate(wrapper['boundaries'])}
    terminals={nid:i+1 for i,nid in enumerate(wrapper['terminal_node_ids'])}

    def draw(ax,bounds,title):
        for eid in physical.edges:
            line=curve(eid)
            if line[:,0].max()<bounds[0] or line[:,0].min()>bounds[1] or line[:,1].max()<bounds[2] or line[:,1].min()>bounds[3]:continue
            ax.plot(line[:,0],line[:,1],color='#bcc6d0',lw=.8,zorder=1)
        for seg in segments:
            line=curve(seg['game_edge_id'],seg['begin_position01'],seg['end_position01'])
            ax.plot(line[:,0],line[:,1],color='#e59125',lw=2,zorder=2)
        for nid,n in all_nodes.items():
            x,y=coords[nid]
            if not bounds[0]<=x<=bounds[1] or not bounds[2]<=y<=bounds[3]:continue
            if nid in terminals:
                ax.scatter(x,y,c='#ee9028',marker='s',s=70,zorder=5)
                ax.annotate(f'T{terminals[nid]}',(x,y),xytext=(-12,-18-terminals[nid]*4),textcoords='offset points',fontsize=9)
            elif n['signal_ids']:
                ax.scatter(x,y,c='#169b77',marker='^',s=50,zorder=5)
                if nid not in boundary_numbers:
                    ax.annotate(str(n['signal_ids'][0]),(x,y),xytext=(3,8),textcoords='offset points',fontsize=7)
            elif nid in wrapper['switch_node_ids']:
                ax.scatter(x,y,c='#8463aa',s=25,zorder=4)
        for b in wrapper['boundaries']:
            x,y=coords[b['node_id']]
            if bounds[0]<=x<=bounds[1] and bounds[2]<=y<=bounds[3]:
                color='#167b62' if b['reason']=='ENTRY_SIGNAL' else '#c43939'
                ax.scatter(x,y,facecolors='none',edgecolors=color,marker='o',s=180,lw=2,zorder=6)
                i=boundary_numbers[b['node_id']]
                ax.annotate(f'B{i}',(x,y),xytext=(10,20 if i%2 else -27),textcoords='offset points',
                            fontsize=11,color=color,arrowprops={'arrowstyle':'-','color':color})
        ax.set_xlim(bounds[:2]);ax.set_ylim(bounds[2:])
        ax.set_facecolor('#f7f9fc');ax.grid(alpha=.18)
        ax.set_title(title,fontproperties=font,fontsize=13)
        ax.set_xlabel('沿站场主轴距离 (m)',fontproperties=font)
        ax.set_ylabel('横向距离 (m)',fontproperties=font)
    transverse=max(65,max(abs(p[1]) for p in station_coords)+25)
    draw(overview,(lo-250,hi+250,-transverse,transverse),'沈阳站完整范围：橙色轨道属于车站 wrapper，灰色为站外或邻接轨道')
    draw(left,(lo-150,lo+420,-transverse,transverse),'主轴负向站端放大')
    draw(right,(hi-420,hi+150,-transverse,transverse),'主轴正向站端放大')
    lines=[]
    for i,b in enumerate(wrapper['boundaries'],1):
        reason=f"进站信号 {b['signal_ids'][0]}，道岔群外 {b['signal_distance_m']:.1f} m" if b['reason']=='ENTRY_SIGNAL' else f"{wrapper.get('signal_search_m',100):g} m 内未找到已确认朝向本站的信号，回退到道岔群出口"
        lines.append(f"B{i}：{reason}（原节点 {b['node_id']}）")
    lines.append('T1/T2/T3：三个终端停车点；紫点：归入本站的17个道岔候选。横纵显示比例不同，便于看清平行轨道。')
    text.text(0,1,'\n'.join(lines),va='top',fontproperties=font,fontsize=11,linespacing=1.7)
    legend=[Line2D([],[],color='#e59125',lw=2,label='车站内部轨道'),Line2D([],[],color='#bcc6d0',label='站外/邻接轨道'),
            Line2D([],[],marker='o',color='#8463aa',ls='None',label='道岔候选'),Line2D([],[],marker='^',color='#169b77',ls='None',label='信号机')]
    fig.legend(handles=legend,ncol=4,loc='lower center',bbox_to_anchor=(.5,.015),prop=font)
    fig.suptitle('Shenyang 沈阳站 · 车站与咽喉范围检查',fontproperties=font,fontsize=21,y=.975)
    fig.subplots_adjust(top=.92,bottom=.08)
    output=root/'shenyang-station-detail.png'
    fig.savefig(output,dpi=180,facecolor='white');plt.close(fig)
    print(output)


if __name__=='__main__':main()
