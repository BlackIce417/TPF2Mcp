window.renderRailNetwork = function renderRailNetwork() {
  const p = window.RAIL_NETWORK_DATA;
  const svg = document.querySelector('#board');
  const tooltip = document.querySelector('#track-tooltip');
  const boardWrap = document.querySelector('#board-wrap');
  document.querySelector('#local-view').classList.remove('selected');
  document.querySelector('#network-view').classList.add('selected');
  document.querySelector('#local-view').onclick = () => { window.location.search = ''; };
  document.querySelector('#network-view').onclick = () => {};
  if (!p || p.source_status !== 'ENGINE_OBSERVED') {
    document.querySelector('#station-name').textContent = '全路网';
    document.querySelector('#snapshot').textContent = '等待一次性铁路拓扑导出';
    document.querySelector('.mode').textContent = 'NETWORK CONTROL · PENDING';
    document.querySelector('#sidebar').innerHTML = '<div class="panel-title">全路网数据</div><div class="section"><div class="event warn"><em>PENDING</em> 尚未生成 rail-network-data.js</div></div>';
    const NS = 'http://www.w3.org/2000/svg';
    const message = document.createElementNS(NS, 'text');
    Object.entries({x:600,y:360,fill:'#ffbd52','font-size':16,'text-anchor':'middle','font-family':'Microsoft YaHei'}).forEach(([k,v]) => message.setAttribute(k,v));
    message.textContent = '全路网数据尚未导出'; svg.appendChild(message);
    return;
  }

  const NS = 'http://www.w3.org/2000/svg';
  const S = (tag, attrs = {}, text = '', parent = svg) => {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    parent.appendChild(node);
    return node;
  };
  const bounds = p.bounds, width = Math.max(1, bounds.max.x-bounds.min.x), height = Math.max(1, bounds.max.y-bounds.min.y);
  const baseScale = Math.min(1080/width, 620/height);
  const originX = 600-(bounds.min.x+bounds.max.x)*baseScale/2;
  const originY = 360+(bounds.min.y+bounds.max.y)*baseScale/2;
  const P = point => ({x:originX+point.x*baseScale,y:originY-point.y*baseScale});
  const T = value => ({x:value.x*baseScale,y:-value.y*baseScale});
  const edgePath = (edge,nodeById) => {
    const a=nodeById.get(edge.node0), b=nodeById.get(edge.node1), pa=P(a), pb=P(b);
    const fallback={x:b.x-a.x,y:b.y-a.y};
    const ta=T(edge.tangent0||fallback), tb=T(edge.tangent1||fallback);
    return `M${pa.x.toFixed(2)},${pa.y.toFixed(2)}C${(pa.x+ta.x/3).toFixed(2)},${(pa.y+ta.y/3).toFixed(2)} ${(pb.x-tb.x/3).toFixed(2)},${(pb.y-tb.y/3).toFixed(2)} ${pb.x.toFixed(2)},${pb.y.toFixed(2)}`;
  };
  const edgeCurve=(edge,nodeById)=>{const a=nodeById.get(edge.node0),b=nodeById.get(edge.node1),pa=P(a),pb=P(b),fallback={x:b.x-a.x,y:b.y-a.y},ta=T(edge.tangent0||fallback),tb=T(edge.tangent1||fallback);return{a:pa,c1:{x:pa.x+ta.x/3,y:pa.y+ta.y/3},c2:{x:pb.x-tb.x/3,y:pb.y-tb.y/3},b:pb};};
  const drawPixiEdge=(graphics,edge,nodeById)=>{const c=edgeCurve(edge,nodeById);graphics.moveTo(c.a.x,c.a.y).bezierCurveTo(c.c1.x,c.c1.y,c.c2.x,c.c2.y,c.b.x,c.b.y);};
  const mapLayer=S('g',{id:'network-map-layer'});
  const detailLayer=S('g',{id:'network-detail-layer'},'',mapLayer);
  const platformLayer=S('g',{id:'network-platform-layer'},'',mapLayer);
  let pixiApp=null;
  try{if(window.PIXI)pixiApp=new PIXI.Application({resizeTo:boardWrap,backgroundAlpha:0,antialias:true,autoDensity:true,resolution:Math.min(window.devicePixelRatio||1,2),powerPreference:'high-performance'});}catch(error){console.error('PixiJS rail renderer unavailable; using SVG fallback',error);}
  const pixiWorld=pixiApp?new PIXI.Container():null;
  if(pixiApp){pixiApp.view.id='rail-webgl';pixiApp.stage.addChild(pixiWorld);boardWrap.insertBefore(pixiApp.view,svg);}

  const palette=['#2fd5ff','#ffca57','#c995ff','#53e58e','#ff748b','#4f8dff','#f59a45','#9be35d','#f06de1','#79d8c9','#f2ef76','#a5b7ff'];
  const lineColor=new Map(p.lines.map((line,index)=>[line.entity_id,palette[index%palette.length]]));
  const physicalOverviewPath=(p.physical_overview_segments||[]).map(segment=>segment.map((point,index)=>{const q=P({x:point[0],y:point[1]});return `${index?'L':'M'}${q.x.toFixed(2)},${q.y.toFixed(2)}`;}).join('')).join('');
  const physicalOverview=physicalOverviewPath?S('path',{d:physicalOverviewPath,fill:'none',stroke:'#7593a6','stroke-width':1.15,opacity:1,'vector-effect':'non-scaling-stroke','pointer-events':'none','data-layer':'physical-overview'},'',mapLayer):null;
  const linePaths = new Map();
  p.lines.forEach((line,index) => {
    const d=line.overview_segments.map(segment=>segment.map((point,pointIndex)=>{const q=P({x:point[0],y:point[1]});return `${pointIndex?'L':'M'}${q.x.toFixed(2)},${q.y.toFixed(2)}`;}).join('')).join('');
    if (!d) return;
    const path=S('path',{d,fill:'none',stroke:palette[index%palette.length],'stroke-width':1.7,opacity:1,'vector-effect':'non-scaling-stroke','pointer-events':'stroke','data-line-id':line.entity_id},'',mapLayer);
    linePaths.set(line.entity_id,path);
  });

  const stationLayer=S('g',{id:'network-station-layer'});
  const depotLayer=S('g',{id:'network-depot-layer'});
  const liveLayer=S('g',{id:'network-live-layer'});
  const stationViews=[];
  const depotViews=[];
  const platformViews=[];
  const trainViews=new Map(),signalViews=new Map();
  const lineById=new Map(p.lines.map(line=>[line.entity_id,line]));
  const stationById=new Map(p.stations.map(station=>[station.entity_id,station]));
  const edgeById=new Map((p.edges||[]).map(edge=>[edge.entity_id,edge]));
  const stationsByPlatformEdge=new Map();
  p.stations.forEach(station=>(station.terminals||[]).forEach(terminal=>(terminal.platform_edge_ids||[]).forEach(edgeId=>{const values=stationsByPlatformEdge.get(edgeId)||[];if(!values.some(item=>item.entity_id===station.entity_id))values.push(station);stationsByPlatformEdge.set(edgeId,values);}))); 
  const normalizedStationName=station=>String(station.name||'').trim().toLocaleLowerCase('zh-CN');
  const terminalIsHighSpeed=terminal=>{
    if(terminal.cargo)return false;
    const speeds=(terminal.platform_edge_ids||[]).map(id=>edgeById.get(id)?.speed_limit_mps).filter(Number.isFinite);
    if(speeds.some(speed=>speed*3.6>=250))return true;
    return (terminal.track_resource_files||[]).some(file=>/(?:250|300|320|350|360|380|385|400|420)\s*(?:kph|kmh)?/i.test(file));
  };
  const stationYardClass=station=>{
    const terminals=station.terminals||[],hasHigh=terminals.some(terminalIsHighSpeed),hasNormal=terminals.some(terminal=>!terminalIsHighSpeed(terminal));
    return hasHigh&&hasNormal?'MIXED':hasHigh?'HIGH_SPEED':'CONVENTIONAL';
  };
  const sameLogicalYard=(station,other)=>normalizedStationName(other)===normalizedStationName(station)&&stationYardClass(other)===stationYardClass(station)&&Math.hypot(other.center.x-station.center.x,other.center.y-station.center.y)<=500;
  const relatedStations=station=>p.stations.filter(other=>sameLogicalYard(station,other));
  const logicalStations=p.stations.filter((station,index)=>!p.stations.slice(0,index).some(other=>sameLogicalYard(station,other)));
  const stationYardLabel=station=>{
    const terminals=relatedStations(station).flatMap(item=>item.terminals||[]),high=terminals.filter(terminalIsHighSpeed),normal=terminals.filter(terminal=>!terminalIsHighSpeed(terminal));
    const labels=[];
    if(high.length)labels.push('高速场（客）');
    if(normal.length){
      const passenger=normal.some(terminal=>!terminal.cargo),cargo=normal.some(terminal=>terminal.cargo);
      labels.push(passenger&&cargo?'普速场（客货混用）':cargo?'普速场（货）':'普速场（客）');
    }
    return labels.join(' / ');
  };
  const stationPreview=station=>{const yard=stationYardLabel(station);return yard?`${station.name}－${yard}`:station.name;};
  let liveState=null,operationsContext={lines:[]},aiAdvice={suggestions:[]},aiAdviceVisibleCount=10,aiAdviceGeneration=null,mcpWorkLog={entries:[]},selectedStation=null,selectedVehicleId=null,vehicleDetail=null,vehicleDetailPending=false,vehicleDetailLoadedAt=0;
  const operationLineById=new Map();
  let stationLogRows=[],stationLogRequestPending=false;
  let lastVehicleSampleAt=null;
  const servedStationIds=new Set(p.lines.flatMap(line=>line.stops.map(stop=>stop.station_group_id)));
  p.stations.forEach(station=>{
    const terminals=station.terminals||[];
    terminals.forEach(terminal=>{
      const platformLine=terminal.platform_centerline||[],hitLine=platformLine.length>=2?platformLine:(terminal.terminal_hit_centerline||[]);
      if(hitLine.length>=2){
        const makePath=line=>line.map((point,index)=>{const q=P({x:point[0],y:point[1]});return `${index?'L':'M'}${q.x.toFixed(5)},${q.y.toFixed(5)}`;}).join('');
        const platformPath=platformLine.length>=2?makePath(platformLine):'';
        const hitPath=makePath(hitLine);
        const outline=platformPath?S('path',{d:platformPath,fill:'none',stroke:'#26343d','stroke-width':8,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},'',platformLayer):null;
        const surface=platformPath?S('path',{d:platformPath,fill:'none',stroke:'#96a2a8','stroke-width':6,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},'',platformLayer):null;
        const hit=S('path',{d:hitPath,fill:'none',stroke:'transparent','stroke-width':10,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','pointer-events':'stroke',cursor:'pointer'},'',platformLayer);
        const show=()=>{tooltip.textContent=representedMeters()>=50?stationPreview(station):`${terminal.terminal_index+1}台`;tooltip.style.display='block';};
        hit.addEventListener('pointerenter',show);hit.addEventListener('pointermove',event=>{show();moveTooltip(event);});hit.addEventListener('pointerleave',()=>{tooltip.style.display='none';});
        platformViews.push({outline,surface,hit,station,terminal});
      }
    });
  });
  const moveTooltip=event=>{const rect=boardWrap.getBoundingClientRect();tooltip.style.left=`${event.clientX-rect.left+12}px`;tooltip.style.top=`${event.clientY-rect.top+12}px`;};
  const scaleBarPixels=92;
  let zoom=1,panX=0,panY=0,dragging=false,dragPointerId=null,lastX=0,lastY=0,dragStartX=0,dragStartY=0,suppressClick=false,selectedLine=null;
  let desiredTileKeys=new Set();
  const loadedTiles=new Map(),pendingTiles=new Map();
  const pixiDomScale=()=>{const rect=boardWrap.getBoundingClientRect();return Math.min(rect.width/1200,rect.height/720);};
  const syncPixiViewport=()=>{if(!pixiWorld)return;const rect=boardWrap.getBoundingClientRect(),scale=pixiDomScale(),offsetX=(rect.width-1200*scale)/2,offsetY=(rect.height-720*scale)/2;pixiWorld.scale.set(scale*zoom);pixiWorld.position.set(offsetX+scale*(600+panX-600*zoom),offsetY+scale*(360+panY-360*zoom));};
  const makePixiTile=(tile,nodeById)=>{if(!pixiWorld)return null;const container=new PIXI.Container(),track=new PIXI.Graphics(),selection=new PIXI.Graphics();track.lineStyle(1,0x83a9bd,1,.5,true);tile.edges.forEach(edge=>drawPixiEdge(track,edge,nodeById));container.addChild(track,selection);pixiWorld.addChild(container);return{container,selection,routeScale:null,selectedLine:null};};
  const redrawPixiSelection=entry=>{if(!entry.pixi)return;const screenScale=Math.max(.0001,pixiDomScale()*zoom);if(entry.pixi.routeScale===screenScale&&entry.pixi.selectedLine===selectedLine)return;entry.pixi.routeScale=screenScale;entry.pixi.selectedLine=selectedLine;entry.pixi.selection.clear();if(selectedLine===null)return;entry.pixi.selection.lineStyle(3/screenScale,PIXI.utils.string2hex(lineColor.get(selectedLine)),1,.5,false);entry.tile.edges.filter(edge=>(edge.line_ids||[]).includes(selectedLine)).forEach(edge=>drawPixiEdge(entry.pixi.selection,edge,entry.tileNodes));};
  window.RAIL_NETWORK_TILES={};
  const updateTileStatus=()=>{const value=document.querySelector('#loaded-tile-count');if(value)value.textContent=`${loadedTiles.size} / ${p.tiles.length}`;};
  const representedMeters=()=>scaleBarPixels/baseScale/zoom;
  const applyLineStyles=()=>{
    const detail=representedMeters()<p.detail_load_threshold_m;
    if(physicalOverview)physicalOverview.setAttribute('opacity',detail?0:1);
    linePaths.forEach((path,id)=>{
      const selected=id===selectedLine;
      path.setAttribute('opacity',detail?0:1);
      path.setAttribute('stroke-width',selected?4:1.7);
      path.setAttribute('pointer-events',detail&&!selected?'none':'stroke');
    });
    const showPlatforms=detail,closePlatforms=representedMeters()<120;
    loadedTiles.forEach(redrawPixiSelection);
    platformViews.forEach(view=>{if(view.outline){view.outline.style.display=showPlatforms?'block':'none';view.outline.setAttribute('stroke-width',closePlatforms?8:2.5);}if(view.surface){view.surface.style.display=showPlatforms?'block':'none';view.surface.setAttribute('stroke-width',closePlatforms?6:1.5);}view.hit.setAttribute('pointer-events',showPlatforms?'stroke':'none');});
  };
  const screenPoint=point=>{const q=P(point);return{x:600+(q.x-600)*zoom+panX,y:360+(q.y-360)*zoom+panY};};
  const worldPoint=(x,y)=>{
    const baseX=(x-panX-600)/zoom+600,baseY=(y-panY-360)/zoom+360;
    return{x:(baseX-originX)/baseScale,y:(originY-baseY)/baseScale};
  };
  logicalStations.forEach(station=>{
    const group=S('g',{'data-station-id':station.entity_id,cursor:'pointer'},'',stationLayer);
    const dot=S('circle',{r:3.2,fill:'#08141e',stroke:'#83ecff','stroke-width':1.2},'',group);
    const name=S('text',{fill:'#c8f3ff','font-size':7.5,'font-family':'Consolas, Microsoft YaHei','paint-order':'stroke','stroke':'#061019','stroke-width':2.5,'stroke-linejoin':'round'},station.name,group);
    const hit=S('circle',{r:10,fill:'transparent','pointer-events':'fill',cursor:'pointer'},'',group);
    const show=()=>{tooltip.textContent=stationPreview(station);tooltip.style.display='block';dot.setAttribute('fill','#56dcff');name.setAttribute('visibility','visible');};
    hit.addEventListener('pointerenter',show);hit.addEventListener('pointermove',event=>{show();moveTooltip(event);});hit.addEventListener('pointerleave',()=>{tooltip.style.display='none';dot.setAttribute('fill','#08141e');updateStations();});
    group.addEventListener('pointerdown',event=>{if(event.button===0)event.stopPropagation();});
    group.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();selectedVehicleId=null;vehicleDetail=null;selectedStation=station;stationLogRows=[];renderStationSidebar();loadStationLogs();updateStations();});
    hit.addEventListener('dblclick',()=>{const target=Math.min(256,Math.max(zoom,scaleBarPixels/baseScale/25));const q=P(station.center);zoom=target;panX=-(q.x-600)*zoom;panY=-(q.y-360)*zoom;updateViewport();});
    stationViews.push({station,group,dot,name,hit,served:relatedStations(station).some(item=>servedStationIds.has(item.entity_id))});
  });
  (p.depots||[]).forEach(depot=>{
    const connector=S('line',{stroke:'#5cc7d8','stroke-width':1,'stroke-dasharray':'3 2',opacity:.8,'pointer-events':'none'},'',depotLayer);
    const group=S('g',{'data-depot-id':depot.entity_id,cursor:'help'},'',depotLayer);
    const marker=S('path',{d:'M-5,-4 L5,-4 L5,4 L-5,4 Z M-2,4 L-2,-1 L2,-1 L2,4',fill:'#102936',stroke:'#62e0ec','stroke-width':1.2,'fill-rule':'evenodd'},'',group);
    S('text',{x:0,y:-7,fill:'#9ef4fa','font-size':6.5,'font-family':'Consolas','text-anchor':'middle','paint-order':'stroke',stroke:'#061019','stroke-width':2},'DEPOT',group);
    const show=event=>{
      const parked=depot.parked_vehicle_count_source==='UNKNOWN'?'场内车辆 UNKNOWN':`场内 ${depot.parked_vehicle_count}`;
      const classification=depot.rail_classification_source==='NEAREST_RAIL_EDGE_PROXIMITY_DERIVED'?'铁路候选（邻轨推导）':'铁路车辆段';
      tooltip.textContent=`${depot.name} · ${classification} · 配属 ${depot.assigned_vehicle_count} · ${parked}`;
      tooltip.style.display='block';marker.setAttribute('fill','#1f6170');moveTooltip(event);
    };
    group.addEventListener('pointerenter',show);group.addEventListener('pointermove',show);group.addEventListener('pointerleave',()=>{tooltip.style.display='none';marker.setAttribute('fill','#102936');});
    depotViews.push({depot,group,connector});
  });

  const barY=682,barX=58;
  S('line',{x1:barX,y1:barY,x2:barX+scaleBarPixels,y2:barY,stroke:'#dce7ef','stroke-width':3});
  S('line',{x1:barX,y1:barY-5,x2:barX,y2:barY+5,stroke:'#dce7ef','stroke-width':2});
  S('line',{x1:barX+scaleBarPixels,y1:barY-5,x2:barX+scaleBarPixels,y2:barY+5,stroke:'#dce7ef','stroke-width':2});
  const scaleText=S('text',{x:barX+scaleBarPixels/2,y:barY-9,fill:'#dce7ef','font-size':10,'font-family':'Consolas','text-anchor':'middle'});
  const formatDistance=value=>value>=1000?`${(value/1000).toFixed(value>=10000?0:1)} km`:`${value.toFixed(value<10?1:0)} m`;
  const renderTile=(key,tile,resource)=>{
    if(!desiredTileKeys.has(key)){resource.remove();return;}
    const group=S('g',{'data-tile-key':key},'',detailLayer);
    const tileNodes=new Map(tile.nodes.map(node=>[node.entity_id,node.position]));
    const paths=new Map(tile.edges.map(edge=>[edge.entity_id,edgePath(edge,tileNodes)]));
    if(!pixiApp)tile.edges.forEach(edge=>S('path',{d:paths.get(edge.entity_id),fill:'none',stroke:'#83a9bd','stroke-width':1,'vector-effect':'non-scaling-stroke','pointer-events':'none'},'',group));
    const entry={group,resource,tile,tileNodes,pixi:makePixiTile(tile,tileNodes)};loadedTiles.set(key,entry);redrawPixiSelection(entry);
    updateTileStatus();
  };
  window.addEventListener('rail-network-tile',event=>{
    const key=event.detail,tile=window.RAIL_NETWORK_TILES[key],script=pendingTiles.get(key);
    if(tile&&script)renderTile(key,tile,script);
    delete window.RAIL_NETWORK_TILES[key];pendingTiles.delete(key);
  });
  const unloadTile=key=>{const loaded=loadedTiles.get(key);if(loaded){loaded.group.remove();loaded.resource.remove();if(loaded.pixi){loaded.pixi.container.parent?.removeChild(loaded.pixi.container);loaded.pixi.container.destroy({children:true});}loadedTiles.delete(key);updateTileStatus();}const pending=pendingTiles.get(key);if(pending){pending.remove();pendingTiles.delete(key);}delete window.RAIL_NETWORK_TILES[key];};
  const loadTile=key=>{
    if(loadedTiles.has(key)||pendingTiles.has(key))return;
    if(location.protocol==='http:'||location.protocol==='https:'){
      const controller=new AbortController(),resource={remove:()=>controller.abort()};pendingTiles.set(key,resource);
      fetch(`/api/rail/tile/${key}`,{signal:controller.signal,cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`tile ${key}: ${response.status}`);return response.json();}).then(tile=>{pendingTiles.delete(key);renderTile(key,tile,resource);}).catch(error=>{pendingTiles.delete(key);if(error.name!=='AbortError')console.error(error);});
      return;
    }
    const script=document.createElement('script');script.async=true;script.src=`rail-network-tiles/tile-${key}.js?v=${p.generated_at}`;
    script.onerror=()=>{pendingTiles.delete(key);script.remove();};pendingTiles.set(key,script);document.body.appendChild(script);
  };
  const updateTiles=()=>{
    if(representedMeters()>=p.detail_load_threshold_m){desiredTileKeys=new Set();[...loadedTiles.keys(),...pendingTiles.keys()].forEach(unloadTile);return;}
    const topLeft=worldPoint(0,0),bottomRight=worldPoint(1200,720),margin=p.tile_size_m*.15;
    const view={minX:Math.min(topLeft.x,bottomRight.x)-margin,maxX:Math.max(topLeft.x,bottomRight.x)+margin,minY:Math.min(topLeft.y,bottomRight.y)-margin,maxY:Math.max(topLeft.y,bottomRight.y)+margin};
    desiredTileKeys=new Set(p.tiles.filter(tile=>tile.max.x>=view.minX&&tile.min.x<=view.maxX&&tile.max.y>=view.minY&&tile.min.y<=view.maxY).map(tile=>tile.key));
    [...loadedTiles.keys(),...pendingTiles.keys()].filter(key=>!desiredTileKeys.has(key)).forEach(unloadTile);
    desiredTileKeys.forEach(loadTile);
  };
  const updateStations=()=>{
    stationViews.forEach(view=>{const q=screenPoint(view.station.center);view.screen=q;view.group.setAttribute('transform',`translate(${q.x} ${q.y})`);view.name.setAttribute('x',6);view.name.setAttribute('y',-5);view.name.setAttribute('visibility','hidden');view.hit.setAttribute('pointer-events','fill');const selected=selectedStation?.entity_id===view.station.entity_id;view.dot.setAttribute('fill',selected?'#56dcff':'#08141e');view.dot.setAttribute('r',selected?'4.5':'3.2');});
    const occupied=[];
    const showEveryStationName=representedMeters()<50;
    [...stationViews].sort((a,b)=>Number(b.served)-Number(a.served)||a.station.name.length-b.station.name.length).forEach(view=>{
      const q=view.screen;
      if(q.x<3||q.x>1197||q.y<3||q.y>717||(!view.served&&zoom<2))return;
      const labelWidth=Math.max(18,Array.from(view.station.name).length*4.8);
      const box={left:q.x+4,right:q.x+8+labelWidth,top:q.y-15,bottom:q.y+1};
      const collides=occupied.some(other=>!(box.right<other.left||box.left>other.right||box.bottom<other.top||box.top>other.bottom));
      if(showEveryStationName||!collides||selectedStation?.entity_id===view.station.entity_id){view.name.setAttribute('visibility','visible');occupied.push(box);}
    });
    depotViews.forEach(view=>{
      const q=screenPoint(view.depot.center),connection=view.depot.track_connection_position?screenPoint(view.depot.track_connection_position):q;
      view.group.setAttribute('transform',`translate(${q.x} ${q.y})`);
      view.group.style.display=q.x>=-10&&q.x<=1210&&q.y>=-10&&q.y<=730?'block':'none';
      Object.entries({x1:q.x,y1:q.y,x2:connection.x,y2:connection.y}).forEach(([key,value])=>view.connector.setAttribute(key,value));
      view.connector.style.display=representedMeters()<300&&view.depot.track_connection_position?'block':'none';
    });
  };
  const updateTrainPositions=()=>{
    trainViews.forEach(view=>{
      const q=screenPoint(view.position||view.vehicle.snapped_position||view.vehicle.position);
      view.group.setAttribute('transform',`translate(${q.x} ${q.y})`);
      view.group.style.display=representedMeters()<1500?'block':'none';
      view.label.style.display=representedMeters()<500?'block':'none';
    });
  };
  const updateLivePositions=()=>{
    updateTrainPositions();
    signalViews.forEach(view=>{
      const q=screenPoint(view.signal.position);
      view.group.setAttribute('transform',`translate(${q.x} ${q.y})`);
      view.group.style.display=representedMeters()<250?'block':'none';
    });
  };
  const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const stationTitle=station=>{const name=String(station.name||`车站 ${station.entity_id}`),base=name.endsWith('站')?name:`${name}站`,yard=stationYardLabel(station);return yard?`${base}－${yard}`:base;};
  const stopForVehicle=vehicle=>lineById.get(vehicle.line_id)?.stops?.[vehicle.stop_index]||null;
  const vehicleStatus=vehicle=>{
    const stop=stopForVehicle(vehicle),station=stop?stationById.get(stop.station_group_id):null;
    if(vehicle.raw_state===2)return `到站${station?.name||''}`;
    if((vehicle.speed_kmh??0)<1)return '等待区间';
    return '预计正点';
  };
  const stationForVehicle=vehicle=>{
    const target=stopForVehicle(vehicle);
    if(vehicle.raw_state===2&&target)return stationById.get(target.station_group_id)||null;
    return (stationsByPlatformEdge.get(vehicle.edge_id)||[])[0]||null;
  };
  const formatSystemTime=value=>new Date(value).toLocaleString('zh-CN',{hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const stationRoutes=station=>{const ids=new Set(relatedStations(station).map(item=>item.entity_id));return p.lines.filter(line=>line.stops.some(stop=>ids.has(stop.station_group_id)));};
  const dwellDescription=(line,station)=>{
    const ids=new Set(relatedStations(station).map(item=>item.entity_id));
    const op=operationLineById.get(line.entity_id),stops=(op?.stops||[]).filter(stop=>ids.has(stop.station_id));
    if(!stops.length)return '停留时间待采';
    return stops.map(stop=>{
      const policy=stop.policy||{},scheduled=Number.isFinite(stop.scheduled_dwell_seconds)?`图定 ${Math.round(stop.scheduled_dwell_seconds)} 秒`:'图定待生成';
      const min=Number.isFinite(policy.min_waiting_time)?policy.min_waiting_time:'—',max=Number.isFinite(policy.max_waiting_time)?policy.max_waiting_time:'—';
      return `第 ${Number(stop.sequence_index)+1} 站 · ${scheduled} · 游戏策略 ${min}–${max} 秒`;
    }).join('<br>');
  };
  const renderOverviewSidebar=()=>{
    const lineRows=p.lines.map((line,index)=>`<div class="event line-row" data-line-row="${line.entity_id}"><i style="background:${palette[index%palette.length]}"></i><em>${escapeHtml(line.name)}</em><span>${line.stops.length} 站</span></div>`).join('');
    const orderedSuggestions=[...(aiAdvice.suggestions||[])].sort((a,b)=>(Number(b.created_at)||0)-(Number(a.created_at)||0));
    const visibleSuggestions=orderedSuggestions.slice(0,aiAdviceVisibleCount);
    const suggestionRows=visibleSuggestions.map(item=>`<div class="suggestion ${item.severity==='ACTION'?'action':''}"><time>${item.created_at?formatSystemTime(item.created_at*1000):'时间 UNKNOWN'}</time><b><em>${escapeHtml(item.template_label||item.template)}</em>${escapeHtml(item.title)}</b><span>${escapeHtml(item.reason)}<br>${escapeHtml(item.required_action)}</span></div>`).join('');
    const moreCount=Math.max(0,orderedSuggestions.length-visibleSuggestions.length),more=moreCount?`<button class="advice-more" data-advice-more>查看更多（剩余 ${moreCount} 条）</button>`:'';
    const suggestions=suggestionRows+more||'<div class="event"><em>CLEAR</em> 当前没有需要人工处理的运行图建议</div>';
    const work=(mcpWorkLog.entries||[]).slice(0,12).map(item=>`<div class="work-entry"><time>${formatSystemTime(item.occurred_at*1000)}</time><span class="${item.applied?'applied':'planned'}">${item.applied?'已执行并验证':'系统测试'}</span> · ${escapeHtml(item.summary)}</div>`).join('')||'<div class="event"><em>WAIT</em> 暂无MCP调整记录</div>';
    document.querySelector('#sidebar').innerHTML=`<div class="panel-title">AI运行图建议</div><div class="section ai-suggestions">${suggestions}</div><div class="panel-title">MCP工作日志</div><div class="section mcp-log">${work}</div><div class="panel-title">铁路线路（点击突出）</div><div class="section line-list">${lineRows}</div>`;
    document.querySelectorAll('[data-line-row]').forEach(row=>row.addEventListener('click',()=>selectLine(Number(row.dataset.lineRow))));
    const moreButton=document.querySelector('[data-advice-more]');if(moreButton)moreButton.addEventListener('click',()=>{aiAdviceVisibleCount+=10;renderOverviewSidebar();});
  };
  const returnToOverview=()=>{selectedStation=null;selectedVehicleId=null;vehicleDetail=null;stationLogRows=[];document.querySelector('#station-name').textContent='全路网';renderOverviewSidebar();updateStations();};
  const detailToolbar=()=>'<div class="detail-toolbar"><button class="detail-back" data-sidebar-back>← 返回全路网</button></div>';
  const bindDetailBack=()=>{const button=document.querySelector('[data-sidebar-back]');if(button)button.addEventListener('click',returnToOverview);};
  const renderStationSidebar=()=>{
    if(!selectedStation){renderOverviewSidebar();return;}
    const station=selectedStation,groups=relatedStations(station),groupIds=new Set(groups.map(item=>item.entity_id)),routes=stationRoutes(station);
    const vehicles=(liveState?.vehicles||[]).filter(vehicle=>groupIds.has(stationForVehicle(vehicle)?.entity_id)||(vehicle.raw_state===2&&groupIds.has(stopForVehicle(vehicle)?.station_group_id)));
    const routeRows=routes.map(line=>`<div class="station-route" data-line-row="${line.entity_id}"><div><i style="background:${lineColor.get(line.entity_id)}"></i><b>${escapeHtml(line.name)}</b></div><span>${dwellDescription(line,station)}</span></div>`).join('')||'<div class="event warn"><em>NONE</em> 当前没有线路办理停靠</div>';
    const liveRows=vehicles.map(vehicle=>`<div class="event line-row" data-vehicle-row="${vehicle.entity_id}"><em>${escapeHtml(vehicle.name||`列车${vehicle.entity_id}`)}</em> ${Math.round(vehicle.speed_kmh??0)} km/h · ${escapeHtml(vehicleStatus(vehicle))}</div>`).join('')||'<div class="event"><em>CLEAR</em> 当前站界内无列车</div>';
    const logs=stationLogRows.map(item=>`<div class="event ${item.event_type==='PASS'?'warn':''}"><em>${formatSystemTime(item.observed_at*1000)}</em> ${escapeHtml(item.line_name)} ${item.event_type==='STOP'?'停靠':'跨站'} · ${escapeHtml(item.vehicle_name)}</div>`).join('')||'<div class="event"><em>WAIT</em> 暂无已记录的到发事件</div>';
    const terminals=groups.flatMap(item=>item.terminals||[]),kinds=terminals.reduce((result,item)=>{result[item.cargo?'货运':'客运']=(result[item.cargo?'货运':'客运']||0)+1;return result;},{});
    document.querySelector('#sidebar').innerHTML=`${detailToolbar()}<div class="panel-title">${escapeHtml(stationTitle(station))} · 运行信息</div><div class="section"><div class="kv"><span>站台</span><b>${terminals.length}</b></div><div class="kv"><span>属性</span><b>${Object.entries(kinds).map(([key,count])=>`${key} ${count}`).join(' / ')||'UNKNOWN'}</b></div><div class="kv"><span>接入线路</span><b>${routes.length}</b></div></div><div class="panel-title">当前站界</div><div class="section">${liveRows}</div><div class="panel-title">接入线路与本站停留</div><div class="section">${routeRows}</div><div class="panel-title">车站日志</div><div class="section station-log">${logs}</div>`;
    bindDetailBack();
    document.querySelectorAll('[data-line-row]').forEach(row=>row.addEventListener('click',()=>selectLine(Number(row.dataset.lineRow))));
    document.querySelectorAll('[data-vehicle-row]').forEach(row=>row.addEventListener('click',()=>{selectedStation=null;selectedVehicleId=Number(row.dataset.vehicleRow);vehicleDetail=null;vehicleDetailLoadedAt=0;renderVehicleSidebar();loadVehicleDetail();updateStations();}));
    document.querySelector('#station-name').textContent=stationTitle(station);
  };
  const renderVehicleSidebar=()=>{
    if(selectedVehicleId==null){renderOverviewSidebar();return;}
    const live=(liveState?.vehicles||[]).find(item=>item.entity_id===selectedVehicleId)||{},detail=vehicleDetail||{},vehicle=detail.vehicle||{},load=detail.load||{},next=detail.next_stop||{};
    const name=live.name||vehicle.name||`列车${selectedVehicleId}`,line=lineById.get(live.line_id??vehicle.line_id),speed=live.speed_kmh??detail.motion?.speed_kmh;
    const loadText=vehicleDetailPending&&!vehicleDetail?'读取中…':load.total==null?'UNKNOWN':`${load.total} / ${load.capacity??'—'}`;
    const cargoRows=(load.cargo_by_type||[]).map(item=>`<div class="kv"><span>${escapeHtml(item.cargo_name||`货物 ${item.cargo_id}`)}</span><b>${item.amount}</b></div>`).join('');
    document.querySelector('#sidebar').innerHTML=`${detailToolbar()}<div class="panel-title">${escapeHtml(name)} · 列车运行信息</div><div class="section"><div class="kv"><span>列车 ID</span><b>${selectedVehicleId}</b></div><div class="kv"><span>所属线路</span><b>${escapeHtml(line?.name||vehicle.line_name||'UNKNOWN')}</b></div><div class="kv"><span>当前速度</span><b>${speed==null?'UNKNOWN':`${Math.round(speed)} km/h`}</b></div><div class="kv"><span>运行状态</span><b>${escapeHtml(vehicleStatus({...live,line_id:live.line_id??vehicle.line_id}))}</b></div><div class="kv"><span>下一站</span><b>${escapeHtml(next.station_name||stopForVehicle(live)?.station_group_name||'UNKNOWN')}</b></div></div><div class="panel-title">当前装载</div><div class="section vehicle-load"><div class="kv"><span>总装载 / 容量</span><b>${loadText}</b></div><div class="kv"><span>旅客</span><b>${load.passengers??'—'}</b></div><div class="kv"><span>货物</span><b>${load.cargo??'—'}</b></div>${cargoRows||''}${detail.availability?.load===false?'<div class="event warn"><em>UNKNOWN</em> 当前装载数据暂不可用</div>':''}</div><div class="panel-title">位置与控制</div><div class="section"><div class="kv"><span>区间</span><b>${escapeHtml(live.block_id||detail.motion?.block_id||'UNKNOWN')}</b></div><div class="kv"><span>位置来源</span><b>${escapeHtml(live.position_source||'UNKNOWN')}</b></div><div class="kv"><span>定位保持</span><b>${live.position_stale?'是':'否'}</b></div></div>`;
    bindDetailBack();document.querySelector('#station-name').textContent=name;
  };
  const loadVehicleDetail=()=>{
    if(selectedVehicleId==null||vehicleDetailPending||Date.now()-vehicleDetailLoadedAt<5000||!(location.protocol==='http:'||location.protocol==='https:'))return;
    const requestedId=selectedVehicleId;vehicleDetailPending=true;renderVehicleSidebar();
    fetch(`/api/vehicle-detail/${requestedId}`,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`vehicle-detail: ${response.status}`);return response.json();}).then(value=>{if(selectedVehicleId!==requestedId)return;vehicleDetail=value;vehicleDetailLoadedAt=Date.now();renderVehicleSidebar();}).catch(error=>{console.error(error);if(selectedVehicleId===requestedId){vehicleDetail={availability:{load:false}};renderVehicleSidebar();}}).finally(()=>{vehicleDetailPending=false;});
  };
  const loadStationLogs=()=>{
    if(!selectedStation||stationLogRequestPending||!(location.protocol==='http:'||location.protocol==='https:'))return;
    const requestedId=selectedStation.entity_id,ids=relatedStations(selectedStation).map(item=>item.entity_id);stationLogRequestPending=true;
    Promise.all(ids.map(id=>fetch(`/api/station-logs/${id}?limit=100`,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`station-logs: ${response.status}`);return response.json();}))).then(values=>{if(selectedStation?.entity_id!==requestedId)return;stationLogRows=values.flatMap(value=>value.events||[]).sort((a,b)=>b.observed_at-a.observed_at).slice(0,100);renderStationSidebar();}).catch(error=>console.error(error)).finally(()=>{stationLogRequestPending=false;});
  };
  const reconcileLive=value=>{
    liveState=value;
    if(value.simulation){
      const simulation=value.simulation,multiplier=Number(simulation.speed_multiplier),clock=document.querySelector('.clock');
      if(clock){
        if(simulation.status==='PAUSED'||simulation.status==='PAUSED_OR_STALLED')clock.textContent='已暂停';
        else if((simulation.status==='RUNNING'||simulation.status==='RUNNING_INFERRED')&&Number.isFinite(multiplier))clock.textContent=`运行 ${multiplier}×`;
        else clock.textContent='运行状态 UNKNOWN';
      }
    }
    if(Object.prototype.hasOwnProperty.call(value,'vehicles')){
     const sampleAt=Number(value.sampled_at)||performance.now()/1000;
     const isNewFrame=lastVehicleSampleAt==null||sampleAt>lastVehicleSampleAt;
     const activeTrains=new Set((value.vehicles||[]).map(vehicle=>vehicle.entity_id));
     trainViews.forEach((view,id)=>{
       if(activeTrains.has(id))return;
       const missingSeconds=Math.max(0,sampleAt-(view.lastSeenAt??sampleAt));
       if(missingSeconds>30){view.group.remove();trainViews.delete(id);return;}
       view.frontendStale=true;view.marker.setAttribute('fill','#ffd34f');view.marker.setAttribute('stroke','#66e2ff');view.marker.setAttribute('stroke-width','2');
     });
     (value.vehicles||[]).forEach(vehicle=>{
      let view=trainViews.get(vehicle.entity_id);
      if(!view){
        const group=S('g',{'data-vehicle-id':vehicle.entity_id,cursor:'pointer'},'',liveLayer);
        const marker=S('path',{d:'M0,-5 L4,0 L0,5 L-4,0 Z',fill:'#ffd34f',stroke:'#2a1a00','stroke-width':1.2},'',group);
        const label=S('text',{x:7,y:3,fill:'#ffe89a','font-size':8,'font-family':'Consolas, Microsoft YaHei','paint-order':'stroke',stroke:'#071019','stroke-width':2},'',group);
        const show=event=>{const current=group.__vehicle,speed=current.speed_kmh==null?'—':Math.round(current.speed_kmh),stale=current.position_stale||group.__view?.frontendStale?` · 隧道/路径边界定位保持 ${current.position_age_seconds??'—'}s`:'';tooltip.textContent=`${current.name||'列车 '+current.entity_id}-${speed}-${vehicleStatus(current)}${stale}`;tooltip.style.display='block';moveTooltip(event);};
        group.addEventListener('pointerenter',show);group.addEventListener('pointermove',show);group.addEventListener('pointerleave',()=>{tooltip.style.display='none';});group.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();selectedStation=null;selectedVehicleId=group.__vehicle.entity_id;vehicleDetail=null;vehicleDetailLoadedAt=0;renderVehicleSidebar();loadVehicleDetail();updateStations();});
        const target=vehicle.snapped_position||vehicle.position;
        view={group,marker,label,vehicle,position:target,sampledAt:sampleAt,lastSeenAt:sampleAt,frontendStale:false};group.__view=view;trainViews.set(vehicle.entity_id,view);
      }else if(isNewFrame&&view.sampledAt!==sampleAt){
        view.position=vehicle.snapped_position||vehicle.position;
        view.sampledAt=sampleAt;
      }
      view.vehicle=vehicle;view.group.__vehicle=vehicle;view.lastSeenAt=sampleAt;view.frontendStale=false;view.label.textContent=`${vehicle.name||`列车${vehicle.entity_id}`}-${vehicle.speed_kmh==null?'—':Math.round(vehicle.speed_kmh)}-${vehicleStatus(vehicle)}`;
      const stale=Boolean(vehicle.position_stale);view.marker.setAttribute('fill','#ffd34f');view.marker.setAttribute('stroke',stale?'#66e2ff':'#2a1a00');view.marker.setAttribute('stroke-width',stale?'2':'1.2');
     });
     if(isNewFrame)lastVehicleSampleAt=sampleAt;
    }
    if(Object.prototype.hasOwnProperty.call(value,'signals')){
     const activeSignals=new Set((value.signals||[]).map((signal,index)=>`${signal.entity_id??'x'}:${signal.edge_id}:${index}`));
     signalViews.forEach((view,id)=>{if(!activeSignals.has(id)){view.group.remove();signalViews.delete(id);}});
     (value.signals||[]).forEach((signal,index)=>{
      const id=`${signal.entity_id??'x'}:${signal.edge_id}:${index}`;
      if(signalViews.has(id)){signalViews.get(id).signal=signal;return;}
      const group=S('g',{'data-signal-id':id,cursor:'help'},'',liveLayer);
      const candidate=signal.source_status==='TRACK_OBJECT_CANDIDATE';
      S('path',{d:'M-3,4 L0,-4 L3,4 Z',fill:candidate?'#ffbd52':'#ff5968',stroke:candidate?'#fff0bd':'#ffd3d7','stroke-width':.8},'',group);
      group.addEventListener('pointerenter',event=>{tooltip.textContent=`${candidate?'轨道控制设备候选':'信号机'} · Edge ${signal.edge_id} · 灯色 UNKNOWN`;tooltip.style.display='block';moveTooltip(event);});
      group.addEventListener('pointermove',moveTooltip);group.addEventListener('pointerleave',()=>{tooltip.style.display='none';});
      signalViews.set(id,{group,signal});
     });
    }
    updateLivePositions();
    if(selectedStation)renderStationSidebar();else if(selectedVehicleId!=null){renderVehicleSidebar();loadVehicleDetail();}
    const summary=document.querySelector('#live-summary');
    if(summary&&Object.prototype.hasOwnProperty.call(value,'line_diagnostics')){
      const warnings=(value.line_diagnostics||[]).filter(item=>item.diagnosis==='POSSIBLE_BUNCHING'||item.diagnosis==='UNEVEN_SPACING').sort((a,b)=>(a.minimum_spacing_m??1e12)-(b.minimum_spacing_m??1e12)).slice(0,8);
      summary.innerHTML=`<div class="kv"><span>在线铁路车辆</span><b>${value.counts?.rail_vehicles??0}</b></div><div class="kv"><span>隧道/边界位置保持</span><b>${value.counts?.position_fallback_vehicles??0}</b></div><div class="kv"><span>控制设备候选 / 已确认</span><b>${value.counts?.signal_candidates??0} / ${value.counts?.confirmed_signals??0}</b></div><div class="kv"><span>控制区间 / 占用</span><b>${value.counts?.blocks??0} / ${value.counts?.occupied_blocks??0}</b></div>${warnings.map(item=>`<div class="event warn"><em>${item.diagnosis}</em> ${item.name} · 最小间隔 ${item.minimum_spacing_m??'—'} m</div>`).join('')||'<div class="event"><em>NORMAL</em> 暂无可证实的间隔告警</div>'}`;
    }
    const liveLamp=document.querySelector('#live-lamp');if(liveLamp){liveLamp.classList.remove('amber','red');liveLamp.classList.add('green');}
  };
  const updateViewport=()=>{
    mapLayer.setAttribute('transform',`translate(${panX} ${panY}) translate(600 360) scale(${zoom}) translate(-600 -360)`);
    document.querySelector('#zoom-value').textContent=`${Math.round(zoom*100)}%`;
    document.querySelector('#zoom-out').disabled=zoom<=1+1e-9;
    scaleText.textContent=formatDistance(representedMeters());
    applyLineStyles();
    updateStations();
    updateLivePositions();
    updateTiles();
    syncPixiViewport();
  };
  let panFrame=0;
  const schedulePanRender=()=>{if(!panFrame)panFrame=requestAnimationFrame(()=>{panFrame=0;updateViewport();});};
  const setZoom=(value,focusX=600,focusY=360)=>{const next=Math.max(1,Math.min(256,value)),ratio=next/zoom,offsetX=focusX-600,offsetY=focusY-360;panX=offsetX-(offsetX-panX)*ratio;panY=offsetY-(offsetY-panY)*ratio;zoom=next;updateViewport();};
  document.querySelector('#zoom-in').onclick=()=>setZoom(zoom*1.6,600,360);
  document.querySelector('#zoom-out').onclick=()=>setZoom(zoom/1.6,600,360);
  document.querySelector('#zoom-reset').onclick=()=>{zoom=1;panX=0;panY=0;updateViewport();};
  svg.addEventListener('wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect(),focusX=(event.clientX-rect.left)*1200/rect.width,focusY=(event.clientY-rect.top)*720/rect.height;setZoom(zoom*(event.deltaY<0?1.35:1/1.35),focusX,focusY);},{passive:false});
  svg.addEventListener('dragstart',event=>event.preventDefault());
  svg.addEventListener('selectstart',event=>event.preventDefault());
  svg.addEventListener('pointerdown',event=>{if(!event.isPrimary||event.button!==0)return;event.preventDefault();dragging=true;dragPointerId=event.pointerId;lastX=dragStartX=event.clientX;lastY=dragStartY=event.clientY;suppressClick=false;svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');});
  svg.addEventListener('pointermove',event=>{if(!dragging||event.pointerId!==dragPointerId)return;event.preventDefault();if(Math.hypot(event.clientX-dragStartX,event.clientY-dragStartY)>4)suppressClick=true;const rect=svg.getBoundingClientRect();panX+=(event.clientX-lastX)*1200/rect.width;panY+=(event.clientY-lastY)*720/rect.height;lastX=event.clientX;lastY=event.clientY;schedulePanRender();});
  const stopDrag=event=>{if(event&&dragPointerId!==null&&event.pointerId!==dragPointerId)return;const pointerId=dragPointerId;dragging=false;dragPointerId=null;svg.classList.remove('dragging');if(pointerId!==null&&svg.hasPointerCapture(pointerId))svg.releasePointerCapture(pointerId);};
  svg.addEventListener('pointerup',stopDrag);svg.addEventListener('pointercancel',stopDrag);svg.addEventListener('lostpointercapture',()=>stopDrag());window.addEventListener('blur',()=>stopDrag());
  svg.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopImmediatePropagation();suppressClick=false;}},true);

  const selectLine=lineId=>{selectedLine=selectedLine===lineId?null:lineId;applyLineStyles();document.querySelectorAll('[data-line-row]').forEach(row=>row.classList.toggle('active-line',Number(row.dataset.lineRow)===selectedLine));};
  linePaths.forEach((path,id)=>{const line=p.lines.find(item=>item.entity_id===id);path.addEventListener('pointerenter',event=>{tooltip.textContent=line.name;tooltip.style.display='block';moveTooltip(event);});path.addEventListener('pointermove',moveTooltip);path.addEventListener('pointerleave',()=>{tooltip.style.display='none';});path.addEventListener('click',()=>selectLine(id));});
  renderOverviewSidebar();
  document.querySelector('#station-name').textContent='全路网';
  document.querySelector('#snapshot').textContent=`${p.counts.stations} STATIONS / ${p.counts.lines} LINES`;
  document.querySelector('.mode').textContent='NETWORK CONTROL · DYNAMIC';
  document.querySelector('.watermark').textContent='GLOBAL PHYSICAL RAIL GRAPH · 游戏引擎原始坐标';
  document.querySelector('.clock').textContent='STATIC';
  document.querySelector('#footer-info').textContent='列车采用 MOVE_PATH.dyn 原始位置，每 0.5 秒点动刷新；信号由 SIGNAL_LIST 确认，灯色与需求为 UNKNOWN';
  if((location.protocol==='http:'||location.protocol==='https:')&&window.EventSource){
    const generation=p.generated_at;
    const events=new EventSource('/api/events');
    events.addEventListener('status',event=>{
      const status=JSON.parse(event.data),mode=document.querySelector('.mode'),lamp=document.querySelector('footer .lamp');
      mode.textContent=status.bridge_connected?'NETWORK CONTROL · LIVE':'NETWORK CONTROL · OFFLINE';
      if(lamp){lamp.classList.toggle('green',status.bridge_connected);lamp.classList.toggle('red',!status.bridge_connected);}
      document.querySelector('#snapshot').textContent=`${p.counts.stations} STATIONS / ${p.counts.lines} LINES · SEQ ${status.snapshot_sequence??'—'}`;
      if(status.rail_generation&&status.rail_generation!==generation)location.reload();
    });
  }
  if(location.protocol==='http:'||location.protocol==='https:'){
    let liveRequestPending=false;
    const pollLive=()=>{if(liveRequestPending)return;liveRequestPending=true;fetch('/api/live',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`live: ${response.status}`);return response.json();}).then(reconcileLive).catch(()=>{}).finally(()=>{liveRequestPending=false;});};
    const pollControl=()=>fetch('/api/control',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`control: ${response.status}`);return response.json();}).then(reconcileLive).catch(()=>{});
    fetch('/api/operations-context',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`operations-context: ${response.status}`);return response.json();}).then(value=>{operationsContext=value;operationLineById.clear();(value.lines||[]).forEach(line=>operationLineById.set(line.line_id,line));if(selectedStation)renderStationSidebar();}).catch(error=>console.error(error));
    const pollAdvice=()=>Promise.all([
      fetch('/api/ai-suggestions',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`ai-suggestions: ${response.status}`);return response.json();}),
      fetch('/api/mcp-work-log?limit=30',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`mcp-work-log: ${response.status}`);return response.json();})
    ]).then(([advice,work])=>{if(aiAdviceGeneration!==advice.generated_at){aiAdviceVisibleCount=10;aiAdviceGeneration=advice.generated_at;}aiAdvice=advice;mcpWorkLog=work;if(!selectedStation&&selectedVehicleId==null)renderOverviewSidebar();}).catch(error=>console.error(error));
    pollAdvice();setInterval(pollAdvice,10000);
    pollLive();pollControl();setInterval(pollLive,500);setInterval(pollControl,30000);setInterval(loadStationLogs,2000);
  }
  const requestedStationId=Number(new URLSearchParams(window.location.search).get('station'));
  const requestedStation=p.stations.find(station=>station.entity_id===requestedStationId);
  if(requestedStation){selectedStation=requestedStation;const q=P(requestedStation.center);zoom=Math.min(256,Math.max(zoom,scaleBarPixels/baseScale/25));panX=-(q.x-600)*zoom;panY=-(q.y-360)*zoom;renderStationSidebar();loadStationLogs();}
  updateViewport();
};
