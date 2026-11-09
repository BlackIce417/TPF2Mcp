const $ = id => document.getElementById(id);
const svg = $('throat-map'), ns = 'http://www.w3.org/2000/svg';
let manifest, data, selected = null, version = 0, box = [0,0,1100,700], drag;
const el = (tag, attrs, parent=svg) => {const node=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));parent.append(node);return node;};
async function json(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error(`${url}: ${r.status}`);return r.json();}
function view(){svg.setAttribute('viewBox',box.join(' '));}
function render(fit=false){
  svg.replaceChildren();if(!data)return;
  const regions=data.throat_model?.regions || [], active=selected?regions.filter(r=>r.id===selected):regions;
  const core=new Set(data.station_groups.flatMap(s=>s.terminals.flatMap(t=>t.platform_edge_ids||[])));
  const candidate=new Set(active.flatMap(r=>r.edge_ids)), disputed=new Set(active.flatMap(r=>r.contested_edge_ids));
  const edges=new Map([...data.edges,...(data.throat_geometry?.edges||[])].map(e=>[e.entity_id,e]));
  const nodes=new Map([...data.nodes,...(data.throat_geometry?.nodes||[])].map(n=>[n.entity_id,n.position]));
  const bounds=[];
  for(const [id,e] of edges){
    if(!$('throat-context').checked&&!core.has(id)&&!candidate.has(id))continue;
    const a=nodes.get(e.node0), b=nodes.get(e.node1);if(!a||!b)continue;
    const delta={x:b.x-a.x,y:b.y-a.y},t=e.tangent0||delta,u=e.tangent1||delta;
    const p=[[a.x,-a.y],[a.x+t.x/3,-a.y-t.y/3],[b.x-u.x/3,-b.y+u.y/3],[b.x,-b.y]];bounds.push(...p);
    const kind=disputed.has(id)?'ambiguous':core.has(id)?'core':candidate.has(id)?'candidate':'';
    const path=el('path',{d:`M${p[0]}C${p[1]} ${p[2]} ${p[3]}`,class:`track ${kind}`});
    path.addEventListener('click',()=>{$('throat-selection').textContent=`轨道 ${id} · ${kind==='core'?'站台核心':kind==='candidate'?'咽喉候选':kind==='ambiguous'?'归属争议':'周边轨道'} · 节点 ${e.node0} → ${e.node1}`;});
  }
  const span=bounds.length?Math.max(...bounds.map(p=>p[0]))-Math.min(...bounds.map(p=>p[0])):100;
  const radius=Math.max(2,Math.min(8,span/150));
  for(const n of new Set(active.flatMap(r=>r.switch_node_ids))){const p=nodes.get(n);if(p)el('circle',{cx:p.x,cy:-p.y,r:radius*.55,class:'switch'});}
  for(const port of new Map(active.flatMap(r=>r.ports).map(p=>[p.node_id,p])).values()){
    const p=port.position;const mark=el('circle',{cx:p.x,cy:-p.y,r:radius,class:'port'});
    mark.addEventListener('click',()=>{$('throat-selection').textContent=`边界节点 ${port.node_id} · ${port.kind==='PLATFORM_INTERFACE'?'站台侧接口':'外部接口，待核验'} · 外接轨道 ${port.outside_edge_ids.join(', ')}`;});
  }
  if(fit&&bounds.length){const xs=bounds.map(p=>p[0]),ys=bounds.map(p=>p[1]);const x=Math.min(...xs),y=Math.min(...ys);box=[x-35,y-35,Math.max(...xs)-x+70,Math.max(...ys)-y+70];}view();
}
async function loadStation(){
 const ticket=++version;selected=null;data=null;svg.replaceChildren();$('throat-regions').replaceChildren();$('throat-status').textContent='正在加载车站…';
 try{
  const id=$('throat-station').value,p=await json(`/api/station-previews/${id}`);if(ticket!==version)return;
  if(p.save_id!==manifest.save_id)throw Error('存档缓存不一致，请重新读取缓存');
  data=p;const regions=p.throat_model?.regions||[];
  $('throat-status').textContent=`${p.station.name} · ${regions.length} 个候选区域 · 缓存 ${new Date(p.generated_at*1000).toLocaleString()} · ${p.save_id}`;
  $('throat-evidence').textContent=regions.length?'站台核心边界 → 连续轨道追踪 → 相连道岔聚合。候选不代表最终边界。':'没有识别到候选；不代表该站没有咽喉。请检查缓存版本及核心数据。';
  const params=p.throat_model?.parameters||{};$('throat-parameters').textContent=`核心至首道岔上限 ${params.approach_limit_m??'—'} m；道岔间搜索上限 ${params.switch_gap_m??'—'} m。`;
  $('throat-local-link').href=`/?view=local&station=${id}`;
  regions.forEach((region,i)=>{const fragment=$('throat-region-template').content.cloneNode(true),button=fragment.querySelector('button');
   fragment.querySelector('[data-field=name]').textContent=`候选区域 ${i+1}`;
   fragment.querySelector('[data-field=summary]').textContent=`${region.switch_node_ids.length} 道岔 · ${region.edge_ids.length} 轨道边 · ${region.ports.length} 接口${region.status==='AMBIGUOUS_SHARED_REGION'?' · 存在归属争议':''}`;
   button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>{selected=selected===region.id?null:region.id;document.querySelectorAll('.region-choice').forEach(b=>b.setAttribute('aria-pressed','false'));button.setAttribute('aria-pressed',String(selected===region.id));$('throat-selection').textContent=`${region.id} · 边界依据：${region.boundary_reasons.join(', ')} · 核心：${region.core_quality}`;render();});$('throat-regions').append(fragment);
  });render(true);
 }catch(e){if(ticket===version)$('throat-status').textContent=`加载失败：${e.message}`;}
}
async function refresh(){try{manifest=await json('/api/station-throats');const old=$('throat-station').value;$('throat-station').replaceChildren();for(const s of manifest.stations){const o=document.createElement('option');o.value=s.station_id;o.textContent=`${s.name} · ${s.throat_region_count??'?'} 区域`;$('throat-station').append(o);}if(manifest.stations.some(s=>String(s.station_id)===old))$('throat-station').value=old;await loadStation();}catch(e){$('throat-status').textContent=`读取失败：${e.message}`;}}
$('throat-refresh').addEventListener('click',refresh);$('throat-station').addEventListener('change',loadStation);$('throat-context').addEventListener('change',()=>render());$('throat-fit').addEventListener('click',()=>render(true));
function zoom(f){box=[box[0]+box[2]*(1-f)/2,box[1]+box[3]*(1-f)/2,box[2]*f,box[3]*f];view();}
$('throat-zoom-in').addEventListener('click',()=>zoom(.8));$('throat-zoom-out').addEventListener('click',()=>zoom(1.25));
svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.12:.89);},{passive:false});
svg.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,...box];svg.setPointerCapture(e.pointerId);});
svg.addEventListener('pointermove',e=>{if(!drag)return;const scale=Math.max(drag[4]/svg.clientWidth,drag[5]/svg.clientHeight);box=[drag[2]-(e.clientX-drag[0])*scale,drag[3]-(e.clientY-drag[1])*scale,drag[4],drag[5]];view();});
svg.addEventListener('pointerup',()=>{drag=null;});svg.addEventListener('pointercancel',()=>{drag=null;});
refresh();
