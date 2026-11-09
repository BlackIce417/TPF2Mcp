const NS='http://www.w3.org/2000/svg';
export class JunctionMap {
  constructor(svg,{onSite,onBranch,onScale}){
    Object.assign(this,{svg,onSite,onBranch,onScale,box:[0,0,1100,700],anchors:[],frame:null,drag:null});
    svg.addEventListener('wheel',e=>{e.preventDefault();this.zoom(e.deltaY>0?1.15:1/1.15,e);},{passive:false});
    svg.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('[data-interactive]'))return;this.drag=[e.clientX,e.clientY,...this.box];svg.setPointerCapture(e.pointerId);});
    svg.addEventListener('pointermove',e=>{if(!this.drag)return;const d=this.drag,s=d[4]/svg.clientWidth;this.box=[d[2]-(e.clientX-d[0])*s,d[3]-(e.clientY-d[1])*s,d[4],d[5]];this.view();});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])svg.addEventListener(event,()=>{this.drag=null;});
    new ResizeObserver(()=>{if(this.bounds)this.fit();}).observe(svg);
  }
  el(tag,attrs={},parent=this.svg){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.append(n);return n;}
  action(node,action,label){node.setAttribute('data-interactive','true');node.setAttribute('tabindex','0');node.setAttribute('role','button');node.setAttribute('aria-label',label);node.addEventListener('click',action);node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action();}});}
  anchor(x,y,cls){const node=this.el('g',{class:cls});this.anchors.push({node,x,y});return node;}
  text(parent,text,x,y,cls){const t=this.el('text',{x,y,class:cls},parent);t.textContent=text;return t;}
  clear(){this.svg.replaceChildren();this.anchors=[];this.bounds=null;}
  view(){if(this.frame!==null)return;this.frame=requestAnimationFrame(()=>{this.svg.setAttribute('viewBox',this.box.join(' '));const scale=this.box[2]/Math.max(this.svg.clientWidth,1);for(const a of this.anchors)a.node.setAttribute('transform',`translate(${a.x},${a.y}) scale(${scale})`);this.onScale?.(`${Math.round(scale*100).toLocaleString()} m / 100 px`);this.frame=null;});}
  zoom(f,event){if(this.box[2]*f<10||this.box[2]*f>200000)return;const rect=this.svg.getBoundingClientRect(),rx=event?(event.clientX-rect.left)/rect.width:.5,ry=event?(event.clientY-rect.top)/rect.height:.5;this.box=[this.box[0]+this.box[2]*(1-f)*rx,this.box[1]+this.box[3]*(1-f)*ry,this.box[2]*f,this.box[3]*f];this.view();}
  fit(){if(!this.bounds)return;const[x,y,w,h]=this.bounds,cw=Math.max(this.svg.clientWidth,1),ch=Math.max(this.svg.clientHeight,1),reserve=this.detail&&cw>650?330:40,aw=Math.max(160,cw-reserve-70),bottom=this.detail&&cw<=650?240:70,ah=Math.max(130,ch-120-bottom),s=Math.max(w/aw,h/ah,.15);this.box=[x+w/2-(aw/2+35)*s,y+h/2-(120+ah/2)*s,cw*s,ch*s];this.view();}
  extent(points){const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),x=Math.min(...xs),y=Math.min(...ys);this.bounds=[x,y,Math.max(20,Math.max(...xs)-x),Math.max(20,Math.max(...ys)-y)];this.fit();}
  overview(network,sites){this.clear();this.detail=false;
    const segments=network.physical_overview_segments||[];this.el('path',{class:'overview-track',d:segments.map(s=>s.map((p,i)=>`${i?'L':'M'}${p[0]},${-p[1]}`).join('')).join('')});
    for(const station of network.stations||[]){const p=station.center;if(!p)continue;const a=this.anchor(p.x,-p.y,'station-marker');this.el('circle',{r:3,class:'station-dot'},a);this.text(a,station.name,9,4,'station-label');}
    for(const site of sites){const a=this.anchor(site.center.x,-site.center.y,'map-marker');a.dataset.site=site.id;this.el('circle',{r:23,class:'marker-halo'},a);this.el('circle',{r:13,class:'marker-body'},a);this.text(a,String(site.number),0,0,'marker-number');const title=this.el('title',{},a);title.textContent=site.displayName;this.action(a,()=>this.onSite(site.id),`打开${site.displayName}`);}
    const b=network.bounds;this.extent([[b.min.x,-b.min.y],[b.max.x,-b.max.y]]);
  }
  draw(detail,branches,mode){this.clear();this.detail=true;const full=mode==='connections',nodes=new Map((full?detail.trace_nodes:detail.nodes).map(n=>[n.entity_id,n.position])),edges=full?detail.trace_edges:detail.edges,internal=new Set(detail.region.edge_ids),protectedEdges=new Set(detail.station_edge_ids),edgeBranch=new Map(),points=[];
    for(const b of branches)for(const p of b.ports)for(const id of p.destination.edge_ids)edgeBranch.set(id,b);
    for(const e of edges){const a=nodes.get(e.node0),b=nodes.get(e.node1);if(!a||!b)continue;const delta={x:b.x-a.x,y:b.y-a.y},u=e.tangent0||delta,v=e.tangent1||delta,p=[[a.x,-a.y],[a.x+u.x/3,-a.y-u.y/3],[b.x-v.x/3,-b.y+v.y/3],[b.x,-b.y]];points.push(...p);const branch=edgeBranch.get(e.entity_id),d=`M${p[0]}C${p[1]} ${p[2]} ${p[3]}`;
      const path=this.el('path',{d,class:`junction-track ${internal.has(e.entity_id)?'internal':protectedEdges.has(e.entity_id)?'station':branch?`branch c${branch.color}`:''}`});if(branch){path.dataset.branch=branch.key;const hit=this.el('path',{d,class:'track-hit'});hit.dataset.branch=branch.key;this.action(hit,()=>this.onBranch(branch.key),`高亮通往${branch.name}的轨道`);}}
    for(const id of detail.region.switch_node_ids){const p=nodes.get(id);if(!p)continue;points.push([p.x,-p.y]);const a=this.anchor(p.x,-p.y,'switch-anchor');this.el('circle',{r:3,class:'junction-switch'},a);}
    for(const branch of branches){if(full){const p=branch.ports[0],end=nodes.get(p.destination.node_id)||p.position;const a=this.anchor(end.x,-end.y,`branch-marker c${branch.color}`);a.dataset.branch=branch.key;this.el('circle',{r:5,class:'branch-end'},a);this.text(a,branch.name,11,-9,'branch-label');this.action(a,()=>this.onBranch(branch.key),`选择${branch.name}`);}else{for(const p of branch.ports){const a=this.anchor(p.position.x,-p.position.y,`branch-marker c${branch.color}`);a.dataset.branch=branch.key;this.el('circle',{r:6,class:'branch-end'},a);this.action(a,()=>this.onBranch(branch.key),`选择${branch.name}的外接接口`);}}}
    if(!full){const local=detail.region.switch_node_ids.map(id=>nodes.get(id)).filter(Boolean);points.length=0;for(const p of local)points.push([p.x-70,-p.y-70],[p.x+70,-p.y+70]);}
    if(points.length)this.extent(points);
  }
  highlight(key){for(const p of this.svg.querySelectorAll('.junction-track')){p.classList.toggle('dimmed',Boolean(key)&&p.dataset.branch!==key);p.classList.toggle('highlighted',Boolean(key)&&p.dataset.branch===key);}for(const node of this.svg.querySelectorAll('.branch-marker'))node.setAttribute('opacity',key&&node.dataset.branch!==key?'.25':'1');}
}
