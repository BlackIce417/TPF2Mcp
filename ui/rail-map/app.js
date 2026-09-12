(() => {
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'network') {
    window.renderRailNetwork();
    return;
  }
  document.querySelector('#local-view').onclick = () => {};
  document.querySelector('#network-view').onclick = () => { window.location.search = '?view=network'; };
  const p = window.PHYSICAL_TRACK_DATA;
  const g = window.STATION_GROUND_TRUTH;
  const svg = document.querySelector('#board');
  const NS = 'http://www.w3.org/2000/svg';
  if (!p || p.source_status !== 'ENGINE_OBSERVED') {
    svg.textContent = '缺少游戏引擎轨道坐标';
    return;
  }
  let drawParent = svg;
  const S = (tag, attrs = {}, text = '', parent = drawParent) => {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    parent.appendChild(node);
    return node;
  };
  const label = (x, y, text, size = 10, color = '#8ca0b4', anchor = 'start') =>
    S('text', {x, y, fill: color, 'font-size': size, 'font-family': 'Consolas, Microsoft YaHei', 'text-anchor': anchor}, text);

  const nodeById = new Map(p.nodes.map(node => [node.entity_id, node]));
  const terminalNodeIds = new Set(p.terminals.map(item => item.node_id));
  const firstTerminal = p.terminals[0];
  const guideEdge = p.edges.find(edge => edge.node0 === firstTerminal.node_id || edge.node1 === firstTerminal.node_id);
  const ga = nodeById.get(guideEdge.node0).position;
  const gb = nodeById.get(guideEdge.node1).position;
  const gl = Math.hypot(gb.x - ga.x, gb.y - ga.y);
  let ux = (gb.x - ga.x) / gl, uy = (gb.y - ga.y) / gl;
  if (ux < 0) { ux *= -1; uy *= -1; }
  const projectRaw = point => ({
    u: (point.x - p.center.x) * ux + (point.y - p.center.y) * uy,
    v: -(point.x - p.center.x) * uy + (point.y - p.center.y) * ux
  });
  const projected = p.nodes.map(node => projectRaw(node.position));
  const minU = Math.min(...projected.map(q => q.u)), maxU = Math.max(...projected.map(q => q.u));
  const minV = Math.min(...projected.map(q => q.v)), maxV = Math.max(...projected.map(q => q.v));
  const scale = Math.min(1050 / Math.max(1, maxU - minU), 520 / Math.max(1, maxV - minV));
  const offsetX = 600 - (minU + maxU) * scale / 2;
  const offsetY = 390 - (minV + maxV) * scale / 2;
  const P = point => { const q = projectRaw(point); return {x: offsetX + q.u * scale, y: offsetY + q.v * scale}; };
  const tangent = value => ({
    x: (value.x * ux + value.y * uy) * scale,
    y: (-value.x * uy + value.y * ux) * scale
  });

  label(600, 35, `${g.station_name.toUpperCase()} 物理轨道拓扑`, 18, '#d9f4ff', 'middle');
  label(600, 55, `ENGINE-OBSERVED · ${p.counts.nodes} 节点 / ${p.counts.edges} 边 / ${p.counts.switch_nodes} 道岔节点`, 10, '#67a2bb', 'middle');
  const mapLayer = S('g', {id:'map-layer'});
  drawParent = mapLayer;
  let stationHitArea = null;
  if (p.station_bounds) {
    const b = p.station_bounds;
    const corners = [{x:b.min.x,y:b.min.y},{x:b.max.x,y:b.min.y},{x:b.max.x,y:b.max.y},{x:b.min.x,y:b.max.y}].map(P);
    stationHitArea = S('polygon', {points: corners.map(q => `${q.x},${q.y}`).join(' '), fill:'transparent', stroke:'none', 'pointer-events':'fill', cursor:'pointer'});
  }

  const stationPoint = P(p.center);
  const stationMarker = S('g', {'pointer-events':'none', opacity:'0.82'});
  S('rect', {x:stationPoint.x-38,y:stationPoint.y-42,width:76,height:20,rx:3,fill:'#071722dd',stroke:'#39758d','stroke-width':1}, '', stationMarker);
  S('text', {x:stationPoint.x,y:stationPoint.y-28,fill:'#b9edff','font-size':10,'font-family':'Consolas, Microsoft YaHei','text-anchor':'middle'}, g.station_name, stationMarker);
  S('line', {x1:stationPoint.x,y1:stationPoint.y-22,x2:stationPoint.x,y2:stationPoint.y-8,stroke:'#39758d','stroke-width':1}, '', stationMarker);

  const typeColor = type => type === 54 ? '#43d5ff' : type === 148 ? '#dce6ed' : type === 117 ? '#a98cff' : '#72808c';
  const typeWidth = type => type === 1 ? 1.5 : 2.6;
  const edgePathData = new Map();
  for (const edge of p.edges) {
    const a = nodeById.get(edge.node0).position, b = nodeById.get(edge.node1).position;
    const pa = P(a), pb = P(b), ta = tangent(edge.tangent0 || {x:b.x-a.x,y:b.y-a.y});
    const tb = tangent(edge.tangent1 || {x:b.x-a.x,y:b.y-a.y});
    const d = `M${pa.x.toFixed(2)},${pa.y.toFixed(2)} C${(pa.x+ta.x/3).toFixed(2)},${(pa.y+ta.y/3).toFixed(2)} ${(pb.x-tb.x/3).toFixed(2)},${(pb.y-tb.y/3).toFixed(2)} ${pb.x.toFixed(2)},${pb.y.toFixed(2)}`;
    edgePathData.set(edge.entity_id, d);
    S('path', {d, fill:'none', stroke:typeColor(edge.track_type), 'stroke-width':typeWidth(edge.track_type), 'stroke-linecap':'round', opacity:edge.terminal_connected?'1':'0.72', 'pointer-events':'none', 'data-edge-id':edge.entity_id, 'data-track-type':edge.track_type});
  }
  for (const node of p.nodes) {
    if (node.degree < 3 || terminalNodeIds.has(node.entity_id)) continue;
    const q = P(node.position);
    S('circle', {cx:q.x, cy:q.y, r:3.2, fill:'#ffd35a', stroke:'#5b4814', 'stroke-width':1, 'pointer-events':'none', 'data-node-id':node.entity_id});
  }
  const edgeAdjacency = new Map();
  const addAdjacent = (nodeId, edge) => { if (!edgeAdjacency.has(nodeId)) edgeAdjacency.set(nodeId, []); edgeAdjacency.get(nodeId).push(edge); };
  p.edges.forEach(edge => { addAdjacent(edge.node0, edge); addAdjacent(edge.node1, edge); });
  const platformEdgeIds = terminal => {
    const adjacent = edgeAdjacency.get(terminal.node_id) || [];
    const trackType = adjacent[0]?.track_type, visited = new Set(), result = [];
    for (const first of adjacent) {
      let currentNode = terminal.node_id, edge = first;
      while (edge && !visited.has(edge.entity_id) && edge.track_type === trackType) {
        const other = edge.node0 === currentNode ? edge.node1 : edge.node0;
        if ((edgeAdjacency.get(other) || []).length !== 2) break;
        visited.add(edge.entity_id); result.push(edge.entity_id);
        const onward = (edgeAdjacency.get(other) || []).filter(item => !visited.has(item.entity_id) && item.track_type === trackType);
        if (onward.length !== 1) break;
        currentNode = other; edge = onward[0];
      }
    }
    return result;
  };
  const tooltip = document.querySelector('#track-tooltip');
  const boardWrap = document.querySelector('#board-wrap');
  const baseBarMeters = 50;
  let zoom = 1, panX = 0, panY = 0, dragging = false, dragPointerId = null, lastX = 0, lastY = 0, dragStartX = 0, dragStartY = 0, suppressClick = false;
  const stationOnlyAtCurrentScale = () => baseBarMeters / zoom >= 50 - 1e-9;
  const moveTooltip = event => { const rect=boardWrap.getBoundingClientRect(); tooltip.style.left=`${event.clientX-rect.left+12}px`; tooltip.style.top=`${event.clientY-rect.top+12}px`; };
  if (stationHitArea) {
    stationHitArea.addEventListener('pointerenter', () => { tooltip.textContent=g.station_name; tooltip.style.display='block'; stationMarker.setAttribute('opacity','1'); });
    stationHitArea.addEventListener('pointermove', moveTooltip);
    stationHitArea.addEventListener('pointerleave', () => { tooltip.style.display='none'; stationMarker.setAttribute('opacity','0.82'); });
  }
  for (const terminal of p.terminals) {
    for (const edgeId of platformEdgeIds(terminal)) {
      const hit = S('path', {d:edgePathData.get(edgeId), fill:'none', stroke:'transparent', 'stroke-width':16, 'pointer-events':'stroke', cursor:'pointer'});
      const showPlatformTooltip = () => {
        tooltip.textContent = stationOnlyAtCurrentScale() ? g.station_name : `T${terminal.terminal_index+1}`;
        tooltip.style.display = 'block';
      };
      hit.addEventListener('pointerenter', showPlatformTooltip);
      hit.addEventListener('pointermove', event => { showPlatformTooltip(); moveTooltip(event); });
      hit.addEventListener('pointerleave', () => { tooltip.style.display='none'; });
    }
  }

  drawParent = svg;
  const barY = 682, barX = 60, fixedBarWidth = baseBarMeters * scale;
  const scaleLine = S('line', {x1:barX,y1:barY,x2:barX+fixedBarWidth,y2:barY,stroke:'#dce7ef','stroke-width':3});
  S('line', {x1:barX,y1:barY-5,x2:barX,y2:barY+5,stroke:'#dce7ef','stroke-width':2});
  const scaleEnd = S('line', {x1:barX+fixedBarWidth,x2:barX+fixedBarWidth,y1:barY-5,y2:barY+5,stroke:'#dce7ef','stroke-width':2});
  const scaleText = label(barX+fixedBarWidth/2, barY-9, '50 m', 10, '#dce7ef', 'middle');

  const updateViewport = () => {
    mapLayer.setAttribute('transform', `translate(${panX} ${panY}) translate(600 390) scale(${zoom}) translate(-600 -390)`);
    document.querySelector('#zoom-value').textContent = `${Math.round(zoom*100)}%`;
    const representedMeters = baseBarMeters / zoom;
    const digits = representedMeters < 10 ? 1 : 0;
    scaleText.textContent = `${representedMeters.toFixed(digits)} m`;
  };
  let panFrame = 0;
  const schedulePanRender = () => { if (!panFrame) panFrame=requestAnimationFrame(()=>{panFrame=0;updateViewport();}); };
  const setZoom = (value, focusX = 600, focusY = 360) => {
    const next = Math.max(0.5, Math.min(8, value)), ratio = next / zoom;
    const offsetX = focusX - 600, offsetY = focusY - 390;
    panX = offsetX - (offsetX - panX) * ratio;
    panY = offsetY - (offsetY - panY) * ratio;
    zoom = next;
    updateViewport();
  };
  document.querySelector('#zoom-in').addEventListener('click', () => setZoom(zoom * 1.4, 600, 360));
  document.querySelector('#zoom-out').addEventListener('click', () => setZoom(zoom / 1.4, 600, 360));
  document.querySelector('#zoom-reset').addEventListener('click', () => { zoom=1; panX=0; panY=0; updateViewport(); });
  svg.addEventListener('wheel', event => {
    event.preventDefault();
    const rect=svg.getBoundingClientRect(), focusX=(event.clientX-rect.left)*1200/rect.width, focusY=(event.clientY-rect.top)*720/rect.height;
    setZoom(zoom * (event.deltaY < 0 ? 1.15 : 1/1.15), focusX, focusY);
  }, {passive:false});
  svg.addEventListener('dragstart', event => event.preventDefault());
  svg.addEventListener('selectstart', event => event.preventDefault());
  svg.addEventListener('pointerdown', event => { if (!event.isPrimary || event.button!==0) return; event.preventDefault(); dragging=true; dragPointerId=event.pointerId; lastX=dragStartX=event.clientX; lastY=dragStartY=event.clientY; suppressClick=false; svg.setPointerCapture(event.pointerId); svg.classList.add('dragging'); });
  svg.addEventListener('pointermove', event => {
    if (!dragging || event.pointerId!==dragPointerId) return;
    event.preventDefault();
    if (Math.hypot(event.clientX-dragStartX,event.clientY-dragStartY)>4) suppressClick=true;
    const rect=svg.getBoundingClientRect(); panX+=(event.clientX-lastX)*1200/rect.width; panY+=(event.clientY-lastY)*720/rect.height;
    lastX=event.clientX; lastY=event.clientY; schedulePanRender();
  });
  const stopDrag = event => { if (event && dragPointerId!==null && event.pointerId!==dragPointerId) return; const pointerId=dragPointerId; dragging=false; dragPointerId=null; svg.classList.remove('dragging'); if (pointerId!==null && svg.hasPointerCapture(pointerId)) svg.releasePointerCapture(pointerId); };
  svg.addEventListener('pointerup', stopDrag); svg.addEventListener('pointercancel', stopDrag); svg.addEventListener('lostpointercapture',()=>stopDrag()); window.addEventListener('blur',()=>stopDrag());
  svg.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopImmediatePropagation();suppressClick=false;}},true);
  updateViewport();

  document.querySelector('#station-name').textContent = g.station_name;
  document.querySelector('#snapshot').textContent = `GROUP ${p.station_group_id} / STATION ${p.station_entity_id}`;
  document.querySelector('.clock').textContent = 'STATIC';
  document.querySelector('.watermark').textContent = 'PHYSICAL GRAPH · 游戏引擎原始坐标';
  document.querySelector('#footer-info').textContent = '列车与占用状态已隐藏';
  const rows = p.terminals.map(t => `<tr><td>T${t.terminal_index+1}</td><td>${t.service_class==='HIGH_SPEED'?'高速':'普速'}</td><td>${t.platform_length_m == null?'未知':t.platform_length_m.toFixed(1)+' m'+(t.length_source==='SYSTEM_DIRECT'?'':'*')}</td><td>${t.node_id}</td></tr>`).join('');
  document.querySelector('#sidebar').innerHTML = `
    <div class="section"><div class="kv"><span>站名 OCR</span><b>${g.station_name}</b></div><div class="kv"><span>中心 X / Y</span><b>${p.center.x.toFixed(2)} / ${p.center.y.toFixed(2)}</b></div><div class="kv"><span>物理节点 / 边</span><b>${p.counts.nodes} / ${p.counts.edges}</b></div><div class="kv"><span>道岔节点</span><b>${p.counts.switch_nodes}</b></div></div>
    <div class="panel-title">站台长度与原生节点</div><div class="section"><table><thead><tr><th>站台</th><th>类型</th><th>长度</th><th>Node ID</th></tr></thead><tbody>${rows}</tbody></table><div class="event warn"><em>* CURVE</em> 无直接字段时累计 Terminal 至两端咽喉前的轨道曲线</div></div>
    <div class="panel-title">图例</div><div class="section"><div class="event"><em style="color:#43d5ff">━ TRACK 54</em> 高速站台 T1/T2 所在轨型</div><div class="event"><em style="color:#e8eff4">━ TRACK 148</em> 普速站台 T3/T4 所在轨型</div><div class="event"><em style="color:#a98cff">━ TRACK 117</em> 窗口内其他原生轨型</div><div class="event"><em style="color:#ffd35a">● SWITCH</em> 原生节点度数 ≥ 3</div><div class="event"><em>HOVER</em> 标尺 ≥ 50 m 显示站名；放大后显示站台号</div></div>
    <div class="panel-title">证据与限制</div><div class="section"><div class="event"><em>ENGINE</em> 节点、边、切线、轨型和拓扑均由游戏读取</div><div class="event"><em>USER</em> 2 高速、2 普速、全部客运</div><div class="event warn"><em>WINDOW</em> 显示终端连通分量约 ${p.display_radius_m} m</div><div class="event warn"><em>HIDDEN</em> 列车、占用和信号状态</div></div>`;
})();
