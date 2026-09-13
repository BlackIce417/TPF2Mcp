window.renderRailNetwork = function renderRailNetwork() {
  const p = window.RAIL_NETWORK_DATA;
  const templates = window.RailMapTemplates;
  const svg = document.querySelector('#board');
  const tooltip = document.querySelector('#track-tooltip');
  const boardWrap = document.querySelector('#board-wrap');
  $('#local-view').removeClass('selected').off('.stationPreview').on('click.stationPreview', event => {
    event.preventDefault();
    if (!selectedStation) {
      window.showRailMapNotice('请选择对应车站');
      return;
    }
    const target = new URL(window.location.href);
    target.search = '';
    target.searchParams.set('view', 'local');
    target.searchParams.set('station', selectedStation.entity_id);
    window.location.assign(target.href);
  });
  $('#network-view').addClass('selected').off('.stationPreview').on('click.stationPreview', event => event.preventDefault());
  if (!p || p.source_status !== 'ENGINE_OBSERVED') {
    document.querySelector('#station-name').textContent = '全路网';
    document.querySelector('#snapshot').textContent = '等待一次性铁路拓扑导出';
    document.querySelector('.mode').textContent = 'NETWORK CONTROL · PENDING';
    const pending = templates.instantiate('pending-sidebar-template');
    templates.slot(pending, 'message').appendChild(templates.message('PENDING', '尚未生成 rail-network-data.js', true));
    document.querySelector('#sidebar').replaceChildren(pending);
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
  const platformLayer=S('g',{id:'network-platform-layer'},'',mapLayer);
  const detailLayer=S('g',{id:'network-detail-layer'},'',mapLayer);
  const bridgeLayer=S('g',{id:'network-bridge-layer'},'',mapLayer);
  let pixiApp=null;
  try{if(window.PIXI)pixiApp=new PIXI.Application({resizeTo:boardWrap,backgroundAlpha:0,antialias:true,autoDensity:true,resolution:Math.min(window.devicePixelRatio||1,2),powerPreference:'high-performance'});}catch(error){console.error('PixiJS rail renderer unavailable; using SVG fallback',error);}
  const pixiWorld=pixiApp?new PIXI.Container():null;
  if(pixiApp){pixiApp.view.id='rail-webgl';pixiApp.stage.addChild(pixiWorld);boardWrap.insertBefore(pixiApp.view,svg);}

  const physicalOverviewPath=(p.physical_overview_segments||[]).map(segment=>segment.map((point,index)=>{const q=P({x:point[0],y:point[1]});return `${index?'L':'M'}${q.x.toFixed(2)},${q.y.toFixed(2)}`;}).join('')).join('');
  const physicalOverview=physicalOverviewPath?S('path',{d:physicalOverviewPath,fill:'none',stroke:'#83a9bd','stroke-width':1.15,opacity:1,'vector-effect':'non-scaling-stroke','pointer-events':'none','data-layer':'physical-overview'},'',mapLayer):null;

  const stationLayer=S('g',{id:'network-station-layer'});
  const depotLayer=S('g',{id:'network-depot-layer'});
  const liveLayer=S('g',{id:'network-live-layer'});
  const stationViews=[];
  const depotViews=[];
  const platformViews=[];
  const trainViews=new Map(),signalViews=new Map();
  let signalsVisible=true;
  const lineById=new Map(p.lines.map(line=>[line.entity_id,line]));
  const stationById=new Map(p.stations.map(station=>[station.entity_id,station]));
  let liveState=null,operationsContext={lines:[]},aiAdvice={suggestions:[]},aiAdviceVisibleCount=10,aiAdviceGeneration=null,mcpWorkLog={entries:[]},allMcpWorkLog={entries:[]},workLogModal=null,workLogFilter='ALL',workLogSearch='',workLogRequestPending=false,workLogLoadError=null,workLogReturnFocus=null,selectedStation=null,selectedVehicleId=null,vehicleDetail=null,vehicleDetailPending=false,vehicleDetailLoadedAt=0;
  const operationLineById=new Map();
  let stationLogRows=[],stationLogRequestPending=false;
  let lastVehicleSampleAt=null;
  const stationsByPlatformEdge=new Map();
  p.stations.forEach(station=>(station.terminals||[]).forEach(terminal=>(terminal.platform_edge_ids||[]).forEach(edgeId=>{const values=stationsByPlatformEdge.get(edgeId)||[];if(!values.some(item=>item.entity_id===station.entity_id))values.push(station);stationsByPlatformEdge.set(edgeId,values);}))); 
  const normalizedStationName=station=>String(station.name||'').trim().toLocaleLowerCase('zh-CN');
  const sameLogicalYard=(station,other)=>normalizedStationName(other)===normalizedStationName(station)&&Math.hypot(other.center.x-station.center.x,other.center.y-station.center.y)<=500;
  const relatedStations=station=>p.stations.filter(other=>sameLogicalYard(station,other));
  const logicalStations=p.stations.filter((station,index)=>!p.stations.slice(0,index).some(other=>sameLogicalYard(station,other)));
  const terminalSelectorKey=(stationId,stationIndex,terminalId)=>`${stationId}:${stationIndex}:${terminalId}`;
  const lineServesPassengerTerminal=(line,station)=>{
    const selectors=new Set(relatedStations(station).flatMap(item=>(item.terminals||[]).filter(terminal=>!terminal.cargo).map(terminal=>terminalSelectorKey(item.entity_id,terminal.station_index,terminal.terminal_index))));
    return (line.stops||[]).some(stop=>{
      if(selectors.has(terminalSelectorKey(stop.station_id,stop.station_index,stop.terminal_id)))return true;
      return (stop.alternative_terminals||[]).some(terminal=>selectors.has(terminalSelectorKey(stop.station_id,terminal.station_index,terminal.terminal_id)));
    });
  };
  const stationPassengerServiceClass=station=>{
    let high=0,conventional=0,unknown=0;
    (operationsContext.lines||[]).filter(line=>lineServesPassengerTerminal(line,station)).forEach(line=>{
      const vehicles=line.active_passenger_vehicles||{};
      high+=Number(vehicles.high_speed)||0;
      conventional+=Number(vehicles.conventional)||0;
      unknown+=Number(vehicles.unknown_speed)||0;
    });
    if(high&&conventional)return 'MIXED';
    if(unknown)return 'UNKNOWN';
    if(high)return 'HIGH_SPEED';
    if(conventional)return 'CONVENTIONAL';
    return 'UNKNOWN';
  };
  const stationYardLabel=station=>{
    const terminals=relatedStations(station).flatMap(item=>item.terminals||[]),passenger=terminals.some(terminal=>!terminal.cargo),cargo=terminals.some(terminal=>terminal.cargo);
    if(!passenger)return cargo?'普速场(货)':'';
    const serviceClass=stationPassengerServiceClass(station);
    if(serviceClass==='CONVENTIONAL')return cargo?'普速场(客-货)':'普速场(客)';
    const passengerLabel=serviceClass==='HIGH_SPEED'?'高速场(客)':serviceClass==='MIXED'?'高普混合场(客)':'客运场(待确认)';
    return cargo?`${passengerLabel}/普速场(货)`:passengerLabel;
  };
  const stationBaseName=station=>{const name=String(station.name||`车站 ${station.entity_id}`);return name.endsWith('站')?name.slice(0,-1):name;};
  const stationPreview=station=>{const name=stationBaseName(station),yard=stationYardLabel(station);return yard?`${name}-${yard}`:name;};
  const physicalPlatforms=station=>station.platforms||(station.terminals||[]).map((terminal,index)=>({platform_index:index,platform_kind:'SIDE_OR_SINGLE_FACE',cargo:terminal.cargo,terminal_faces:[{station_index:terminal.station_index,terminal_index:terminal.terminal_index,node_id:terminal.node_id}],platform_centerline:terminal.platform_centerline||terminal.operating_track_centerline||[],platform_length_m:terminal.platform_length_m}));
  const depotDisplayName=depot=>{
    const fallback=`车辆段 ${depot.entity_id}`;
    const name=String(depot.name||fallback).trim();
    return ({'汉口所':'汉口动车所','武汉所':'武汉动车所'})[name]||name;
  };
  const sideOfPolyline=(points,point)=>{
    let bestDistance=Infinity,bestSide=0;
    for(let index=0;index+1<points.length;index+=1){
      const a=points[index],b=points[index+1],dx=b[0]-a[0],dy=b[1]-a[1],lengthSquared=dx*dx+dy*dy;
      if(lengthSquared<=1e-9)continue;
      const ratio=Math.max(0,Math.min(1,((point.x-a[0])*dx+(point.y-a[1])*dy)/lengthSquared));
      const nearest={x:a[0]+dx*ratio,y:a[1]+dy*ratio},distance=(point.x-nearest.x)**2+(point.y-nearest.y)**2;
      if(distance<bestDistance){bestDistance=distance;bestSide=dx*(point.y-nearest.y)-dy*(point.x-nearest.x);}
    }
    return bestSide;
  };
  const faceForPointer=(station,platform,event)=>{
    const faces=platform.terminal_faces||[];
    if(faces.length<2)return faces[0];
    const rect=boardWrap.getBoundingClientRect(),screenX=(event.clientX-rect.left)*1200/rect.width,screenY=(event.clientY-rect.top)*720/rect.height;
    const pointerSide=sideOfPolyline(platform.platform_centerline,worldPoint(screenX,screenY));
    const terminalByIndex=new Map((station.terminals||[]).map(terminal=>[terminal.terminal_index,terminal]));
    return faces.reduce((best,face)=>{
      const terminal=terminalByIndex.get(face.terminal_index),track=terminal?.operating_track_centerline||terminal?.platform_centerline||[];
      if(track.length<2)return best;
      const middle=track[Math.floor(track.length/2)],score=sideOfPolyline(platform.platform_centerline,{x:middle[0],y:middle[1]})*pointerSide;
      return !best||score>best.score?{face,score}:best;
    },null)?.face||faces[0];
  };
  const servedStationIds=new Set(p.lines.flatMap(line=>line.stops.map(stop=>stop.station_group_id)));
  p.stations.forEach(station=>{
    physicalPlatforms(station).forEach(platform=>{
      const platformLine=platform.platform_centerline||[],hitLine=platformLine;
      if(hitLine.length>=2){
        const widthUnits=platform.platform_width_units||(platform.platform_kind==='ISLAND'?2:1);
        const makePath=line=>line.map((point,index)=>{const q=P({x:point[0],y:point[1]});return `${index?'L':'M'}${q.x.toFixed(5)},${q.y.toFixed(5)}`;}).join('');
        const platformPath=platformLine.length>=2?makePath(platformLine):'';
        const hitPath=makePath(hitLine);
        const outline=platformPath?S('path',{d:platformPath,fill:'none',stroke:'#26343d','stroke-width':6*widthUnits+2,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},'',platformLayer):null;
        const surface=platformPath?S('path',{d:platformPath,fill:'none',stroke:'#96a2a8','stroke-width':6*widthUnits,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},'',platformLayer):null;
        const divider=platform.platform_kind==='ISLAND'?S('path',{d:platformPath,fill:'none',stroke:'#58656d','stroke-width':1,'stroke-dasharray':'4 3','vector-effect':'non-scaling-stroke','pointer-events':'none',display:'none'},'',platformLayer):null;
        const hit=S('path',{d:hitPath,fill:'none',stroke:'transparent','stroke-width':6*widthUnits+4,'vector-effect':'non-scaling-stroke','stroke-linecap':'round','pointer-events':'stroke',cursor:'pointer'},'',platformLayer);
        const show=event=>{if(divider)divider.style.display='block';const face=faceForPointer(station,platform,event),kind=platform.cargo?'货':'客';tooltip.textContent=`${Number(face?.terminal_index??platform.platform_index)+1}站台（${kind}）`;tooltip.style.display='block';};
        hit.addEventListener('pointerenter',show);hit.addEventListener('pointermove',event=>{show(event);moveTooltip(event);});hit.addEventListener('pointerleave',()=>{if(divider)divider.style.display='none';tooltip.style.display='none';});
        platformViews.push({outline,surface,divider,hit,station,platform,widthUnits});
      }
    });
  });
  const moveTooltip=event=>{const rect=boardWrap.getBoundingClientRect();tooltip.style.left=`${event.clientX-rect.left+12}px`;tooltip.style.top=`${event.clientY-rect.top+12}px`;};
  const scaleBarPixels=92;
  let zoom=1,panX=0,panY=0,dragging=false,dragPointerId=null,lastX=0,lastY=0,dragStartX=0,dragStartY=0,suppressClick=false;
  let desiredTileKeys=new Set();
  const loadedTiles=new Map(),pendingTiles=new Map();
  let bridgeRenderFrame=null;
  const renderVisibleBridges=()=>{
    bridgeRenderFrame=null;
    bridgeLayer.replaceChildren();
    const crossings=[],fallbackEdges=[],fallbackNodes=new Map();
    const visibleEdgePaths=new Map(),visibleEdges=new Map(),visibleNodes=new Map(),visibleEdgeIdsByNode=new Map();
    loadedTiles.forEach(entry=>{
      entry.paths.forEach((path,edgeId)=>visibleEdgePaths.set(Number(edgeId),path));
      entry.tileNodes.forEach((position,nodeId)=>visibleNodes.set(Number(nodeId),position));
      entry.tile.edges.forEach(edge=>{
        visibleEdges.set(Number(edge.entity_id),edge);
        [edge.node0,edge.node1].forEach(nodeId=>{
          const key=Number(nodeId),values=visibleEdgeIdsByNode.get(key)||[];
          if(!values.includes(Number(edge.entity_id)))values.push(Number(edge.entity_id));
          visibleEdgeIdsByNode.set(key,values);
        });
      });
      if(Array.isArray(entry.tile.grade_separated_crossings))crossings.push(...entry.tile.grade_separated_crossings);
      else{
        entry.tile.edges.forEach(edge=>fallbackEdges.push(edge));
        entry.tileNodes.forEach((position,nodeId)=>fallbackNodes.set(nodeId,position));
      }
    });
    if(fallbackEdges.length)crossings.push(...window.RailBridgeCrossings.detect(fallbackEdges,fallbackNodes));
    window.RailBridgeCrossings.renderSvg(crossings,P,S,bridgeLayer,{
      trackStrokeWidth:1,
      upperPathForEdge:edgeId=>visibleEdgePaths.get(Number(edgeId)),
      upperEdgeIdsForBridge:(crossing,shape)=>window.RailBridgeCrossings.expandUpperEdgeIds(
        crossing,shape,visibleEdges,visibleNodes,visibleEdgeIdsByNode,
      ),
      upperPointsForEdge:edgeId=>{
        const edge=visibleEdges.get(Number(edgeId));
        return edge?window.RailBridgeCrossings.sampleEdge(edge,visibleNodes):null;
      },
    });
  };
  const scheduleBridgeRender=()=>{
    if(bridgeRenderFrame!==null)return;
    bridgeRenderFrame=requestAnimationFrame(renderVisibleBridges);
  };
  const pixiDomScale=()=>{const rect=boardWrap.getBoundingClientRect();return Math.min(rect.width/1200,rect.height/720);};
  const syncPixiViewport=()=>{if(!pixiWorld)return;const rect=boardWrap.getBoundingClientRect(),scale=pixiDomScale(),offsetX=(rect.width-1200*scale)/2,offsetY=(rect.height-720*scale)/2;pixiWorld.scale.set(scale*zoom);pixiWorld.position.set(offsetX+scale*(600+panX-600*zoom),offsetY+scale*(360+panY-360*zoom));};
  const makePixiTile=(tile,nodeById)=>{if(!pixiWorld)return null;const container=new PIXI.Container(),track=new PIXI.Graphics();track.lineStyle(1,0x83a9bd,1,.5,true);tile.edges.forEach(edge=>drawPixiEdge(track,edge,nodeById));container.addChild(track);pixiWorld.addChild(container);return{container};};
  window.RAIL_NETWORK_TILES={};
  const updateTileStatus=()=>{const value=document.querySelector('#loaded-tile-count');if(value)value.textContent=`${loadedTiles.size} / ${p.tiles.length}`;};
  const representedMeters=()=>scaleBarPixels/baseScale/zoom;
  const updateMapDetailVisibility=()=>{
    const detail=representedMeters()<p.detail_load_threshold_m;
    if(physicalOverview)physicalOverview.setAttribute('opacity',detail?0:1);
    const showPlatforms=detail,closePlatforms=representedMeters()<120;
    platformViews.forEach(view=>{if(view.outline){view.outline.style.display=showPlatforms?'block':'none';view.outline.setAttribute('stroke-width',(closePlatforms?6:1.5)*view.widthUnits+2);}if(view.surface){view.surface.style.display=showPlatforms?'block':'none';view.surface.setAttribute('stroke-width',(closePlatforms?6:1.5)*view.widthUnits);}if(!showPlatforms&&view.divider)view.divider.style.display='none';view.hit.setAttribute('stroke-width',(closePlatforms?6:1.5)*view.widthUnits+4);view.hit.setAttribute('pointer-events',showPlatforms?'stroke':'none');});
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
    S('text',{x:0,y:-7,fill:'#9ef4fa','font-size':6.5,'font-family':'Consolas, Microsoft YaHei','text-anchor':'middle','paint-order':'stroke',stroke:'#061019','stroke-width':2},depotDisplayName(depot),group);
    const show=event=>{
      const parked=depot.parked_vehicle_count_source==='UNKNOWN'?'场内车辆 UNKNOWN':`场内 ${depot.parked_vehicle_count}`;
      tooltip.textContent=`${depotDisplayName(depot)} · 配属 ${depot.assigned_vehicle_count} · ${parked}`;
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
    const entry={group,resource,tile,tileNodes,paths,pixi:makePixiTile(tile,tileNodes)};loadedTiles.set(key,entry);
    updateTileStatus();
    scheduleBridgeRender();
  };
  window.addEventListener('rail-network-tile',event=>{
    const key=event.detail,tile=window.RAIL_NETWORK_TILES[key],script=pendingTiles.get(key);
    if(tile&&script)renderTile(key,tile,script);
    delete window.RAIL_NETWORK_TILES[key];pendingTiles.delete(key);
  });
  const unloadTile=key=>{const loaded=loadedTiles.get(key);if(loaded){loaded.group.remove();loaded.resource.remove();if(loaded.pixi){loaded.pixi.container.parent?.removeChild(loaded.pixi.container);loaded.pixi.container.destroy({children:true});}loadedTiles.delete(key);updateTileStatus();scheduleBridgeRender();}const pending=pendingTiles.get(key);if(pending){pending.remove();pendingTiles.delete(key);}delete window.RAIL_NETWORK_TILES[key];};
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
      view.group.style.display=signalsVisible&&representedMeters()<250?'block':'none';
    });
  };
  const stationTitle=station=>stationPreview(station);
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
  const formatStationLogTime=value=>{
    const date=new Date(value),two=part=>String(part).padStart(2,'0');
    return `${two(date.getMonth()+1)}-${two(date.getDate())} ${two(date.getHours())}:${two(date.getMinutes())}`;
  };
  const workLogStatus={
    EXECUTED:{label:'已执行',className:'applied'},
    BLOCKED:{label:'被阻挡',className:'blocked'},
    PENDING:{label:'待处理',className:'pending'},
    CANCELLED:{label:'已取消',className:'cancelled'},
    TEST:{label:'系统测试',className:'planned'},
  };
  const workLogActionLabels={
    BUY_VEHICLE:'购买车辆',ASSIGN_VEHICLE_TO_LINE:'车辆分配到线路',SET_LINE_STOP_POLICY:'调整停站策略',SET_LINE_STOPS:'调整线路停靠站台',CREATE_LINE:'创建线路',CREATE_LINE_FROM_SOURCE_ROUTE:'创建线路',SELL_VEHICLE:'出售车辆',RENAME_LINE:'重命名线路',HOLD_VEHICLE:'扣停列车',HOLD_VEHICLE_AT_TERMINAL:'扣停列车',RELEASE_VEHICLE:'放行列车',TIMETABLE_PLAN_GENERATED:'运行图系统测试',
  };
  const workLogCategory=item=>item.category||(item.applied?'EXECUTED':'TEST');
  const workLogTarget=item=>[Number.isInteger(item.line_id)?`线路 ${item.line_id}`:'',Number.isInteger(item.vehicle_id)?`车辆 ${item.vehicle_id}`:'',item.task_id?`任务 ${item.task_id}`:''].filter(Boolean).join(' · ')||'全路网';
  const closeWorkLogModal=()=>{
    if(!workLogModal)return;
    workLogModal.remove();workLogModal=null;
    if(workLogReturnFocus?.focus)workLogReturnFocus.focus();
    workLogReturnFocus=null;
  };
  const renderWorkLogModal=()=>{
    if(!workLogModal)return;
    const entries=allMcpWorkLog.entries||[],counts={ALL:entries.length};
    Object.keys(workLogStatus).forEach(category=>{counts[category]=entries.filter(item=>workLogCategory(item)===category).length;});
    workLogModal.querySelectorAll('[data-work-log-filter]').forEach(button=>{
      const category=button.dataset.workLogFilter,label=category==='ALL'?'全部':workLogStatus[category]?.label||category;
      button.textContent=`${label} ${counts[category]||0}`;
      button.classList.toggle('active',category===workLogFilter);
      button.setAttribute('aria-pressed',String(category===workLogFilter));
    });
    const query=workLogSearch.trim().toLocaleLowerCase('zh-CN');
    const visible=entries.filter(item=>(workLogFilter==='ALL'||workLogCategory(item)===workLogFilter)&&(!query||[item.summary,item.action_type,item.reason,item.line_id,item.vehicle_id,item.task_id,item.task_status].some(value=>String(value??'').toLocaleLowerCase('zh-CN').includes(query))));
    templates.setText(workLogModal,'work-log-summary',`显示 ${visible.length} 条，共 ${entries.length} 条`);
    const slot=templates.slot(workLogModal,'work-log-entries'),rows=[];
    if(workLogRequestPending)rows.push(templates.message('WAIT','正在读取全部工作日志'));
    else if(workLogLoadError)rows.push(templates.message('ERROR',workLogLoadError,true));
    else visible.forEach(item=>{
      const category=workLogCategory(item),meta=workLogStatus[category]||{label:category,className:'pending'};
      const row=templates.instantiate('work-log-detail-row-template'),status=templates.setText(row,'status',meta.label);
      status.classList.add(`status-${category.toLowerCase()}`);
      templates.setText(row,'time',formatSystemTime(item.occurred_at*1000));
      templates.setText(row,'summary',item.summary||workLogActionLabels[item.action_type]||item.action_type);
      templates.setText(row,'action',workLogActionLabels[item.action_type]||item.action_type||'UNKNOWN');
      templates.setText(row,'target',workLogTarget(item));
      templates.setText(row,'reason',`状态依据：${item.reason||item.verification_status||item.task_status||'UNKNOWN'}`);
      rows.push(row);
    });
    if(!rows.length)rows.push(templates.message('NONE','当前筛选条件下没有记录'));
    slot.replaceChildren(...rows);
  };
  const openWorkLogModal=()=>{
    if(workLogModal)return;
    workLogReturnFocus=document.activeElement;
    workLogFilter='ALL';workLogSearch='';workLogLoadError=null;allMcpWorkLog={entries:[]};
    workLogModal=templates.instantiate('work-log-modal-template');
    workLogModal.querySelectorAll('[data-action="work-log-close"]').forEach(button=>button.addEventListener('click',closeWorkLogModal));
    workLogModal.querySelectorAll('[data-work-log-filter]').forEach(button=>button.addEventListener('click',()=>{workLogFilter=button.dataset.workLogFilter;renderWorkLogModal();}));
    const search=workLogModal.querySelector('[data-action="work-log-search"]');
    search.addEventListener('input',()=>{workLogSearch=search.value;renderWorkLogModal();});
    document.body.appendChild(workLogModal);search.focus();
    workLogRequestPending=true;renderWorkLogModal();
    fetch('/api/mcp-work-log?limit=all',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`mcp-work-log: ${response.status}`);return response.json();}).then(value=>{allMcpWorkLog=value;}).catch(error=>{console.error(error);workLogLoadError='读取工作日志失败';}).finally(()=>{workLogRequestPending=false;renderWorkLogModal();});
  };
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&workLogModal)closeWorkLogModal();});
  const stationRoutes=station=>{const ids=new Set(relatedStations(station).map(item=>item.entity_id));return p.lines.filter(line=>line.stops.some(stop=>ids.has(stop.station_group_id)));};
  const stationServingVehicleCount=routes=>{
    const liveCounts=new Map();
    (liveState?.vehicles||[]).forEach(vehicle=>{
      if(Number.isInteger(vehicle.line_id))liveCounts.set(vehicle.line_id,(liveCounts.get(vehicle.line_id)||0)+1);
    });
    return routes.reduce((total,line)=>{
      const configured=operationLineById.get(line.entity_id)?.vehicle_count;
      return total+(Number.isFinite(configured)?configured:(liveCounts.get(line.entity_id)||0));
    },0);
  };
  const currentSimulationSpeedLabel=()=>{
    const multiplier=Number(liveState?.simulation?.speed_multiplier);
    return Number.isFinite(multiplier)?`${multiplier}x`:'?x';
  };
  const dwellDescription=(line,station)=>{
    const ids=new Set(relatedStations(station).map(item=>item.entity_id));
    const op=operationLineById.get(line.entity_id),stops=(op?.stops||[]).filter(stop=>ids.has(stop.station_id));
    if(!stops.length)return '停留时间待采';
    return stops.map(stop=>{
      const scheduled=Number.isFinite(stop.scheduled_dwell_seconds)?`${Math.round(stop.scheduled_dwell_seconds)}秒`:'待生成';
      return `第${Number(stop.sequence_index)+1}站 图定停车${scheduled}(${currentSimulationSpeedLabel()})`;
    }).join('\n');
  };
  const $sidebarBack=$('#sidebar-back');
  const setSidebarBackVisible=visible=>$sidebarBack.toggleClass('is-hidden',!visible);
  const renderOverviewSidebar=()=>{
    setSidebarBackVisible(false);
    const sidebar=templates.instantiate('overview-sidebar-template');
    const lineSlot=templates.slot(sidebar,'lines');
    p.lines.forEach(line=>{
      const row=templates.instantiate('route-row-template');
      templates.setText(row,'name',line.name);
      templates.setText(row,'stop-count',`${line.stops.length} 站`);
      lineSlot.appendChild(row);
    });
    const orderedSuggestions=[...(aiAdvice.suggestions||[])].sort((a,b)=>(Number(b.created_at)||0)-(Number(a.created_at)||0));
    const visibleSuggestions=orderedSuggestions.slice(0,aiAdviceVisibleCount);
    const suggestionSlot=templates.slot(sidebar,'suggestions');
    visibleSuggestions.forEach(item=>{
      const row=templates.instantiate('suggestion-row-template');
      if(item.severity==='ACTION')row.classList.add('action');
      templates.setText(row,'time',item.created_at?formatSystemTime(item.created_at*1000):'时间 UNKNOWN');
      templates.setText(row,'label',item.template_label||item.template);
      templates.setText(row,'title',item.title);
      templates.setText(row,'detail',[item.reason,item.required_action].filter(Boolean).join('\n'));
      suggestionSlot.appendChild(row);
    });
    const moreCount=Math.max(0,orderedSuggestions.length-visibleSuggestions.length);
    if(moreCount){
      const more=templates.instantiate('advice-more-template');
      more.textContent=`查看更多（剩余 ${moreCount} 条）`;
      more.addEventListener('click',()=>{aiAdviceVisibleCount+=10;renderOverviewSidebar();});
      suggestionSlot.appendChild(more);
    }else if(!visibleSuggestions.length){
      suggestionSlot.appendChild(templates.message('CLEAR','当前没有需要人工处理的运行图建议'));
    }
    const workSlot=templates.slot(sidebar,'work-log'),entries=(mcpWorkLog.entries||[]).slice(0,12);
    entries.forEach(item=>{
      const category=workLogCategory(item),meta=workLogStatus[category]||{label:category,className:'planned'};
      const row=templates.instantiate('work-entry-template'),result=templates.setText(row,'result',meta.label);
      result.classList.add(meta.className);
      templates.setText(row,'time',formatSystemTime(item.occurred_at*1000));
      templates.setText(row,'summary',item.summary);
      workSlot.appendChild(row);
    });
    if(!entries.length)workSlot.appendChild(templates.message('WAIT','暂无MCP调整记录'));
    sidebar.querySelector('[data-action="work-log-all"]').addEventListener('click',openWorkLogModal);
    document.querySelector('#sidebar').replaceChildren(sidebar);
  };
  const returnToOverview=()=>{selectedStation=null;selectedVehicleId=null;vehicleDetail=null;stationLogRows=[];document.querySelector('#station-name').textContent='全路网';renderOverviewSidebar();updateStations();};
  $sidebarBack.off('.sidebarBack').on('click.sidebarBack',returnToOverview);
  const stationFacilityKind=groups=>{
    const kinds=groups.map(group=>{const terminals=group.terminals||[];return {passenger:terminals.some(terminal=>!terminal.cargo),cargo:terminals.some(terminal=>terminal.cargo)};});
    const passenger=kinds.some(kind=>kind.passenger),cargo=kinds.some(kind=>kind.cargo);
    if(passenger&&cargo)return kinds.some(kind=>kind.passenger&&kind.cargo)?'客货混用车站':'客货车站';
    return passenger?'客运车站':cargo?'货运车站':'未知车站';
  };
  const stationSidebarData=station=>{
    const groups=relatedStations(station),groupIds=new Set(groups.map(item=>item.entity_id)),routes=stationRoutes(station);
    const vehicles=(liveState?.vehicles||[]).filter(vehicle=>groupIds.has(stationForVehicle(vehicle)?.entity_id)||(vehicle.raw_state===2&&groupIds.has(stopForVehicle(vehicle)?.station_group_id)));
    const platforms=groups.flatMap(physicalPlatforms);
    const platformFaces=platforms.reduce((total,platform)=>total+Math.max(1,(platform.terminal_faces||[]).length),0);
    return {groups,routes,vehicles,platforms,platformFaces,summary:`${stationFacilityKind(groups)} ${platformFaces}站台`,servingVehicles:stationServingVehicleCount(routes)};
  };
  const fillStationRoutes=(slot,station,routes)=>{
    const rows=routes.map(line=>{const row=templates.instantiate('station-route-row-template');templates.setText(row,'name',line.name);templates.setText(row,'dwell',dwellDescription(line,station));return row;});
    if(!rows.length)rows.push(templates.message('NONE','当前没有线路办理停靠',true));
    slot.replaceChildren(...rows);
  };
  const fillStationLiveVehicles=(slot,vehicles)=>{
    const rows=vehicles.map(vehicle=>{
      const row=templates.instantiate('station-live-vehicle-row-template');
      row.dataset.vehicleId=vehicle.entity_id;
      templates.setText(row,'name',vehicle.name||`列车${vehicle.entity_id}`);
      templates.setText(row,'motion',`${Math.round(vehicle.speed_kmh??0)} km/h · ${vehicleStatus(vehicle)}`);
      row.addEventListener('click',()=>{selectedStation=null;selectedVehicleId=Number(row.dataset.vehicleId);vehicleDetail=null;vehicleDetailLoadedAt=0;renderVehicleSidebar();loadVehicleDetail();updateStations();});
      return row;
    });
    if(!rows.length)rows.push(templates.message('CLEAR','当前站界内无列车'));
    slot.replaceChildren(...rows);
  };
  const stationLogKey=item=>[item.observed_at,item.line_id,item.vehicle_id??item.vehicle_name,item.event_type].join(':');
  const fillStationLogs=slot=>{
    const previousTop=slot.scrollTop;
    const anchor=[...slot.children].find(row=>row.offsetTop+row.offsetHeight>previousTop);
    const anchorKey=anchor?.dataset.logKey,anchorOffset=anchor?anchor.offsetTop-previousTop:0;
    const rows=stationLogRows.map(item=>{const row=templates.instantiate('station-log-row-template');row.dataset.logKey=stationLogKey(item);if(item.event_type==='PASS')row.classList.add('warn');templates.setText(row,'time',formatStationLogTime(item.observed_at*1000));templates.setText(row,'event',`${item.line_name} ${item.vehicle_name} ${item.event_type==='STOP'?'停靠':'跨站'}`);return row;});
    if(!rows.length)rows.push(templates.message('WAIT','暂无已记录的到发事件'));
    slot.replaceChildren(...rows);
    if(previousTop<=1){slot.scrollTop=previousTop;return;}
    const nextAnchor=anchorKey?[...slot.children].find(row=>row.dataset.logKey===anchorKey):null;
    slot.scrollTop=nextAnchor?nextAnchor.offsetTop-anchorOffset:Math.min(previousTop,Math.max(0,slot.scrollHeight-slot.clientHeight));
  };
  const currentStationSidebar=()=>document.querySelector('#sidebar > .station-sidebar');
  const refreshStationLiveSidebar=()=>{
    if(!selectedStation)return;
    const sidebar=currentStationSidebar();
    if(!sidebar){renderStationSidebar();return;}
    const data=stationSidebarData(selectedStation);
    templates.setText(sidebar,'serving-vehicles',`图定停靠 ${data.servingVehicles} 趟列车`);
    fillStationLiveVehicles(templates.slot(sidebar,'live-vehicles'),data.vehicles);
    const speedLabel=currentSimulationSpeedLabel();
    if(sidebar.dataset.dwellSpeed!==speedLabel){fillStationRoutes(templates.slot(sidebar,'routes'),selectedStation,data.routes);sidebar.dataset.dwellSpeed=speedLabel;}
  };
  const refreshStationOperationsSidebar=()=>{
    if(!selectedStation)return;
    const sidebar=currentStationSidebar();
    if(!sidebar){renderStationSidebar();return;}
    const data=stationSidebarData(selectedStation),title=stationTitle(selectedStation);
    templates.setText(sidebar,'station-name',title);
    templates.setText(sidebar,'station-summary',data.summary);
    templates.setText(sidebar,'serving-vehicles',`图定停靠 ${data.servingVehicles} 趟列车`);
    fillStationRoutes(templates.slot(sidebar,'routes'),selectedStation,data.routes);
    sidebar.dataset.dwellSpeed=currentSimulationSpeedLabel();
    document.querySelector('#station-name').textContent=title;
  };
  const refreshStationLogSidebar=()=>{
    if(!selectedStation)return;
    const sidebar=currentStationSidebar();
    if(!sidebar){renderStationSidebar();return;}
    fillStationLogs(templates.slot(sidebar,'logs'));
  };
  const renderStationSidebar=()=>{
    if(!selectedStation){renderOverviewSidebar();return;}
    setSidebarBackVisible(true);
    const station=selectedStation,{routes,vehicles,summary,servingVehicles}=stationSidebarData(station);
    const sidebar=templates.instantiate('station-sidebar-template');
    templates.setText(sidebar,'station-name',stationTitle(station));
    templates.setText(sidebar,'station-summary',summary);
    templates.setText(sidebar,'serving-vehicles',`图定停靠 ${servingVehicles} 趟列车`);
    fillStationRoutes(templates.slot(sidebar,'routes'),station,routes);
    sidebar.dataset.dwellSpeed=currentSimulationSpeedLabel();
    fillStationLiveVehicles(templates.slot(sidebar,'live-vehicles'),vehicles);
    fillStationLogs(templates.slot(sidebar,'logs'));
    document.querySelector('#sidebar').replaceChildren(sidebar);
    document.querySelector('#station-name').textContent=stationTitle(station);
  };
  const renderVehicleSidebar=()=>{
    if(selectedVehicleId==null){renderOverviewSidebar();return;}
    setSidebarBackVisible(true);
    const live=(liveState?.vehicles||[]).find(item=>item.entity_id===selectedVehicleId)||{},detail=vehicleDetail||{},vehicle=detail.vehicle||{},load=detail.load||{},next=detail.next_stop||{};
    const name=live.name||vehicle.name||`列车${selectedVehicleId}`,line=lineById.get(live.line_id??vehicle.line_id),speed=live.speed_kmh??detail.motion?.speed_kmh;
    const loadText=vehicleDetailPending&&!vehicleDetail?'读取中…':load.total==null?'UNKNOWN':`${load.total} / ${load.capacity??'—'}`;
    const sidebar=templates.instantiate('vehicle-sidebar-template');
    templates.setText(sidebar,'vehicle-name',name);
    templates.setText(sidebar,'vehicle-id',selectedVehicleId);
    templates.setText(sidebar,'line-name',line?.name||vehicle.line_name||'UNKNOWN');
    templates.setText(sidebar,'speed',speed==null?'UNKNOWN':`${Math.round(speed)} km/h`);
    templates.setText(sidebar,'status',vehicleStatus({...live,line_id:live.line_id??vehicle.line_id}));
    templates.setText(sidebar,'next-station',next.station_name||stopForVehicle(live)?.station_group_name||'UNKNOWN');
    templates.setText(sidebar,'total-load',loadText);
    templates.setText(sidebar,'passengers',load.passengers??'—');
    templates.setText(sidebar,'cargo',load.cargo??'—');
    templates.setText(sidebar,'block',live.block_id||detail.motion?.block_id||'UNKNOWN');
    templates.setText(sidebar,'position-source',live.position_source||'UNKNOWN');
    templates.setText(sidebar,'position-stale',live.position_stale?'是':'否');
    const cargoSlot=templates.slot(sidebar,'cargo-types');
    (load.cargo_by_type||[]).forEach(item=>{const row=templates.instantiate('cargo-row-template');templates.setText(row,'cargo-name',item.cargo_name||`货物 ${item.cargo_id}`);templates.setText(row,'amount',item.amount);cargoSlot.appendChild(row);});
    if(detail.availability?.load===false)templates.slot(sidebar,'load-status').appendChild(templates.message('UNKNOWN','当前装载数据暂不可用',true));
    document.querySelector('#sidebar').replaceChildren(sidebar);
    document.querySelector('#station-name').textContent=name;
  };
  const loadVehicleDetail=()=>{
    if(selectedVehicleId==null||vehicleDetailPending||Date.now()-vehicleDetailLoadedAt<5000||!(location.protocol==='http:'||location.protocol==='https:'))return;
    const requestedId=selectedVehicleId;vehicleDetailPending=true;renderVehicleSidebar();
    fetch(`/api/vehicle-detail/${requestedId}`,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`vehicle-detail: ${response.status}`);return response.json();}).then(value=>{if(selectedVehicleId!==requestedId)return;vehicleDetail=value;vehicleDetailLoadedAt=Date.now();renderVehicleSidebar();}).catch(error=>{console.error(error);if(selectedVehicleId===requestedId){vehicleDetail={availability:{load:false}};renderVehicleSidebar();}}).finally(()=>{vehicleDetailPending=false;});
  };
  const loadStationLogs=()=>{
    if(!selectedStation||stationLogRequestPending||!(location.protocol==='http:'||location.protocol==='https:'))return;
    const requestedId=selectedStation.entity_id,ids=relatedStations(selectedStation).map(item=>item.entity_id);stationLogRequestPending=true;
    Promise.all(ids.map(id=>fetch(`/api/station-logs/${id}?limit=100`,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`station-logs: ${response.status}`);return response.json();}))).then(values=>{if(selectedStation?.entity_id!==requestedId)return;stationLogRows=values.flatMap(value=>value.events||[]).sort((a,b)=>b.observed_at-a.observed_at).slice(0,100);refreshStationLogSidebar();}).catch(error=>console.error(error)).finally(()=>{stationLogRequestPending=false;});
  };
  const reconcileLive=value=>{
    const hasVehicles=Object.prototype.hasOwnProperty.call(value,'vehicles');
    if(hasVehicles)liveState=value;
    if(value.simulation){
      const simulation=value.simulation,multiplier=Number(simulation.speed_multiplier),clock=document.querySelector('.clock');
      if(clock){
        const clockText=simulation.status==='PAUSED'||simulation.status==='PAUSED_OR_STALLED'
          ?'已暂停'
          :(simulation.status==='RUNNING'||simulation.status==='RUNNING_INFERRED')&&Number.isFinite(multiplier)
            ?`运行中 ${multiplier}×`
            :'运行状态 UNKNOWN';
        if(clock.textContent!==clockText)clock.textContent=clockText;
      }
    }
    if(hasVehicles){
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
    if(selectedStation&&hasVehicles)refreshStationLiveSidebar();else if(selectedVehicleId!=null&&hasVehicles){renderVehicleSidebar();loadVehicleDetail();}
  };
  const updateViewport=()=>{
    mapLayer.setAttribute('transform',`translate(${panX} ${panY}) translate(600 360) scale(${zoom}) translate(-600 -360)`);
    document.querySelector('#zoom-value').textContent=`${Math.round(zoom*100)}%`;
    document.querySelector('#zoom-out').disabled=zoom<=1+1e-9;
    scaleText.textContent=formatDistance(representedMeters());
    updateMapDetailVisibility();
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

  renderOverviewSidebar();
  document.querySelector('#station-name').textContent='全路网';
  document.querySelector('#snapshot').textContent=`${p.counts.stations} STATIONS / ${p.counts.lines} LINES`;
  document.querySelector('.mode').textContent='NETWORK CONTROL · DYNAMIC';
  document.querySelector('.watermark').textContent='Powered By BlackIce.';
  document.querySelector('.clock').textContent='STATIC';
  $('#footer-info').text('列车位置刷新时间: 0.5s');
  const $signalToggle=$('#toggle-signals');
  $signalToggle.prop('hidden',false).attr('aria-pressed','true').on('click',()=>{
    signalsVisible=!signalsVisible;
    $signalToggle.attr('aria-pressed',String(signalsVisible)).text(signalsVisible?'隐藏信号机':'显示信号机');
    updateLivePositions();
  });
  const generation=p.generated_at;
  let reloadRequested=false;
  const handleStatus=status=>{
    const mode=document.querySelector('.mode');
    mode.textContent=status.bridge_connected?'NETWORK CONTROL · LIVE':'NETWORK CONTROL · OFFLINE';
    document.querySelector('#snapshot').textContent=`${p.counts.stations} STATIONS / ${p.counts.lines} LINES · SEQ ${status.snapshot_sequence??'—'}`;
    const saveReady=!status.save_transition&&status.save_id&&status.rail_save_id===status.save_id;
    const mapChanged=(status.rail_generation&&String(status.rail_generation)!==String(generation))||(p.save_id&&p.save_id!==status.save_id);
    if(saveReady&&mapChanged&&!reloadRequested){
      reloadRequested=true;
      const target=new URL(location.href),nextGeneration=String(status.rail_generation||'');
      if(target.searchParams.get('_rail')!==nextGeneration){target.searchParams.set('_rail',nextGeneration);location.replace(target.href);}
    }
  };
  window.addEventListener('rail-map-status',event=>handleStatus(event.detail));
  if(window.RAIL_MAP_STATUS)handleStatus(window.RAIL_MAP_STATUS);
  if(location.protocol==='http:'||location.protocol==='https:'){
    let liveRequestPending=false;
    const pollLive=()=>{if(liveRequestPending)return;liveRequestPending=true;fetch('/api/live',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`live: ${response.status}`);return response.json();}).then(reconcileLive).catch(()=>{}).finally(()=>{liveRequestPending=false;});};
    const pollControl=()=>fetch('/api/control',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`control: ${response.status}`);return response.json();}).then(reconcileLive).catch(()=>{});
    let operationsRequestPending=false;
    const pollOperationsContext=()=>{if(operationsRequestPending)return;operationsRequestPending=true;fetch('/api/operations-context',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`operations-context: ${response.status}`);return response.json();}).then(value=>{operationsContext=value;operationLineById.clear();(value.lines||[]).forEach(line=>operationLineById.set(line.line_id,line));if(selectedStation)refreshStationOperationsSidebar();}).catch(error=>console.error(error)).finally(()=>{operationsRequestPending=false;});};
    pollOperationsContext();
    setInterval(pollOperationsContext,10000);
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
