(async () => {
  await window.RAIL_MAP_TEMPLATES_READY;
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') !== 'local') {
    window.renderRailNetwork();
    return;
  }

  const templates = window.RailMapTemplates;
  const manifest = window.RAIL_NETWORK_DATA;
  const stationIdText = query.get('station');
  const stationId = /^\d+$/.test(stationIdText || '') ? Number(stationIdText) : null;
  const $svg = $('#board');
  const $tooltip = $('#track-tooltip');
  const $boardWrap = $('#board-wrap');
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let dragging = false;
  let pointerId = null;
  let lastX = 0;
  let lastY = 0;
  const NS = 'http://www.w3.org/2000/svg';
  const S = (tag, attrs = {}, text = '', $parent = $svg) => {
    const $node = $(document.createElementNS(NS, tag)).attr(attrs);
    if (text !== '') $node.text(text);
    $parent.append($node);
    return $node;
  };
  const showMessage = (code, message, warning = true) => {
    const sidebar = templates.instantiate('pending-sidebar-template');
    templates.slot(sidebar, 'message').appendChild(templates.message(code, message, warning));
    $('#sidebar').empty().append(sidebar);
    S('text', {
      x: 600, y: 360, fill: warning ? '#ffbd52' : '#c8f3ff',
      'font-size': 16, 'text-anchor': 'middle', 'font-family': 'Microsoft YaHei',
    }, message);
  };

  $('#local-view').addClass('selected').off('.stationPreview').on('click.stationPreview', event => event.preventDefault());
  $('#network-view').removeClass('selected').off('.stationPreview').on('click.stationPreview', event => {
    event.preventDefault();
    const target = new URL(window.location.href);
    target.search = '';
    target.searchParams.set('view', 'network');
    window.location.assign(target.href);
  });

  if (!stationId) {
    $('#station-name').text('未选择车站');
    $('.mode').text('STATION PREVIEW · NO SELECTION');
    showMessage('SELECT', '请选择对应车站');
    return;
  }
  const stationIndex = manifest?.stations?.find(item => item.entity_id === stationId);
  if (!stationIndex) {
    $('#station-name').text('车站不存在');
    $('.mode').text('STATION PREVIEW · INVALID');
    showMessage('UNKNOWN', '当前存档中没有该车站');
    return;
  }

  $('.mode').text('STATION PREVIEW · CACHED PHYSICAL');
  $('#station-name').text(stationIndex.name || `车站 ${stationId}`);
  $('#snapshot').text(`加载车站缓存 ${stationId}`);
  showMessage('LOAD', '正在读取站场拓扑缓存', false);

  const preview = await $.ajax({
    url: `station-previews/station-${stationId}.json`,
    method: 'GET',
    dataType: 'json',
    cache: false,
  });
  if (preview.station?.entity_id !== stationId) throw new Error('车站缓存 ID 不匹配');
  if (manifest?.save_id && preview.save_id !== manifest.save_id) throw new Error('车站缓存不属于当前存档');
  if (preview.source_status !== 'ENGINE_OBSERVED') throw new Error('车站缓存不是游戏引擎实测数据');
  if (preview.diagram_type !== 'ENGINE_OBSERVED_STATION_PHYSICAL_PREVIEW') throw new Error('车站缓存类型无效');

  $svg.empty();
  const bounds = preview.bounds;
  const width = Math.max(1, bounds.max.x - bounds.min.x);
  const height = Math.max(1, bounds.max.y - bounds.min.y);
  const baseScale = Math.min(1080 / width, 620 / height);
  const PLATFORM_DECK_WIDTH_M = 5.2;
  const PLATFORM_BORDER_WIDTH_M = 1.6;
  const PLATFORM_HIT_PADDING_M = 3;
  const PASSENGER_PLATFORM_COLOR = '#69c7e5';
  const CARGO_PLATFORM_COLOR = '#d6a04f';
  const platformStrokeWidths = widthUnits => {
    const deck = PLATFORM_DECK_WIDTH_M * widthUnits * baseScale;
    return {
      deck,
      outline: deck + PLATFORM_BORDER_WIDTH_M * baseScale,
      hit: deck + PLATFORM_HIT_PADDING_M * baseScale,
    };
  };
  const originX = 600 - (bounds.min.x + bounds.max.x) * baseScale / 2;
  const originY = 360 + (bounds.min.y + bounds.max.y) * baseScale / 2;
  const P = point => ({ x: originX + point.x * baseScale, y: originY - point.y * baseScale });
  const T = value => ({ x: value.x * baseScale, y: -value.y * baseScale });
  const nodeById = new Map(preview.nodes.map(node => [node.entity_id, node.position]));
  const pathForEdge = edge => {
    const a = nodeById.get(edge.node0);
    const b = nodeById.get(edge.node1);
    const pa = P(a);
    const pb = P(b);
    const fallback = { x: b.x - a.x, y: b.y - a.y };
    const tangent0 = T(edge.tangent0 || fallback);
    const tangent1 = T(edge.tangent1 || fallback);
    return `M${pa.x.toFixed(2)},${pa.y.toFixed(2)}C${(pa.x + tangent0.x / 3).toFixed(2)},${(pa.y + tangent0.y / 3).toFixed(2)} ${(pb.x - tangent1.x / 3).toFixed(2)},${(pb.y - tangent1.y / 3).toFixed(2)} ${pb.x.toFixed(2)},${pb.y.toFixed(2)}`;
  };
  const pathForPoints = points => points.map((point, index) => {
    const screen = P({ x: point[0], y: point[1] });
    return `${index ? 'L' : 'M'}${screen.x.toFixed(2)},${screen.y.toFixed(2)}`;
  }).join('');
  const $mapLayer = S('g', { id: 'station-preview-layer' });
  const $platformLayer = S('g', { id: 'station-preview-platforms' }, '', $mapLayer);
  const $trackLayer = S('g', { id: 'station-preview-tracks' }, '', $mapLayer);
  const $bridgeLayer = S('g', { id: 'station-preview-bridges' }, '', $mapLayer);
  const $switchLayer = S('g', { id: 'station-preview-switches' }, '', $mapLayer);
  const $labelLayer = S('g', { id: 'station-preview-labels' }, '', $mapLayer);
  if (Array.isArray(preview.scope?.polygon) && preview.scope.polygon.length === 4) {
    const clipId = `station-scope-${stationId}`;
    const $definitions = S('defs');
    const $clip = S('clipPath', { id: clipId }, '', $definitions);
    const scopePoints = preview.scope.polygon.map(point => [point.x, point.y]);
    S('path', { d: `${pathForPoints(scopePoints)}Z` }, '', $clip);
    $mapLayer.attr('clip-path', `url(#${clipId})`);
  }

  preview.edges.forEach(edge => {
    if (!nodeById.has(edge.node0) || !nodeById.has(edge.node1)) return;
    S('path', {
      d: pathForEdge(edge), fill: 'none', stroke: '#83a9bd', 'stroke-width': 1.4,
      'vector-effect': 'non-scaling-stroke', 'pointer-events': 'none',
    }, '', $trackLayer);
  });
  const bridgeCrossings = preview.grade_separated_crossings || window.RailBridgeCrossings.detect(preview.edges, nodeById);
  const edgeById = new Map(preview.edges.map(edge => [Number(edge.entity_id), edge]));
  const edgePathById = new Map(preview.edges.map(edge => [Number(edge.entity_id), pathForEdge(edge)]));
  const edgeIdsByNode = new Map();
  preview.edges.forEach(edge => [edge.node0, edge.node1].forEach(nodeId => {
    const values = edgeIdsByNode.get(Number(nodeId)) || [];
    values.push(Number(edge.entity_id));
    edgeIdsByNode.set(Number(nodeId), values);
  }));
  const bridgeStructureCount = window.RailBridgeCrossings.renderSvg(bridgeCrossings, P, S, $bridgeLayer, {
    trackStrokeWidth: 1.4,
    upperPathForEdge: edgeId => edgePathById.get(Number(edgeId)),
    upperEdgeIdsForBridge: (crossing, shape) => window.RailBridgeCrossings.expandUpperEdgeIds(
      crossing, shape, edgeById, nodeById, edgeIdsByNode,
    ),
    upperPointsForEdge: edgeId => {
      const edge = edgeById.get(Number(edgeId));
      return edge ? window.RailBridgeCrossings.sampleEdge(edge, nodeById) : null;
    },
  });

  const moveTooltip = event => {
    const rect = $boardWrap[0].getBoundingClientRect();
    $tooltip.css({ left: `${event.clientX - rect.left + 12}px`, top: `${event.clientY - rect.top + 12}px` });
  };
  const sideOfPolyline = (points, point) => {
    let bestDistance = Infinity;
    let bestSide = 0;
    for (let index = 0; index + 1 < points.length; index += 1) {
      const a = points[index];
      const b = points[index + 1];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const lengthSquared = dx * dx + dy * dy;
      if (lengthSquared <= 1e-9) continue;
      const ratio = Math.max(0, Math.min(1, ((point.x - a[0]) * dx + (point.y - a[1]) * dy) / lengthSquared));
      const nearest = { x: a[0] + dx * ratio, y: a[1] + dy * ratio };
      const distance = (point.x - nearest.x) ** 2 + (point.y - nearest.y) ** 2;
      if (distance < bestDistance) {
        bestDistance = distance;
        bestSide = dx * (point.y - nearest.y) - dy * (point.x - nearest.x);
      }
    }
    return bestSide;
  };
  const eventWorldPoint = event => {
    const original = event.originalEvent || event;
    const rect = $svg[0].getBoundingClientRect();
    const screenX = (original.clientX - rect.left) * 1200 / rect.width;
    const screenY = (original.clientY - rect.top) * 720 / rect.height;
    const baseX = (screenX - panX - 600) / zoom + 600;
    const baseY = (screenY - panY - 360) / zoom + 360;
    return { x: (baseX - originX) / baseScale, y: (originY - baseY) / baseScale };
  };
  const stationGroups = preview.station_groups || [preview.station];
  const allTerminals = stationGroups.flatMap(station => station.terminals || []);
  const terminalByNode = new Map(allTerminals.map(terminal => [terminal.node_id, terminal]));
  const faceForPointer = (platform, event) => {
    const faces = platform.terminal_faces || [];
    if (faces.length < 2) return faces[0];
    const pointerSide = sideOfPolyline(platform.platform_centerline, eventWorldPoint(event));
    return faces.reduce((best, face) => {
      const terminal = terminalByNode.get(face.node_id);
      const track = terminal?.operating_track_centerline || terminal?.platform_centerline || [];
      if (track.length < 2) return best;
      const middle = track[Math.floor(track.length / 2)];
      const score = sideOfPolyline(platform.platform_centerline, { x: middle[0], y: middle[1] }) * pointerSide;
      return !best || score > best.score ? { face, score } : best;
    }, null)?.face || faces[0];
  };
  const groupPlatforms = stationGroups.flatMap(station => (station.platforms || []).map(platform => ({
    ...platform,
    station_group_id: station.entity_id,
    station_group_name: station.name,
  })));
  const physicalPlatforms = preview.platforms || (groupPlatforms.length ? groupPlatforms : allTerminals.map((terminal, index) => ({
    platform_index: index,
    platform_kind: 'SIDE_OR_SINGLE_FACE',
    cargo: terminal.cargo,
    terminal_faces: [{
      station_index: terminal.station_index,
      terminal_index: terminal.terminal_index,
      node_id: terminal.node_id,
    }],
    platform_centerline: terminal.platform_centerline || terminal.operating_track_centerline || [],
    platform_length_m: terminal.platform_length_m,
  })));
  physicalPlatforms.forEach(platform => {
    const points = platform.platform_centerline || [];
    if (points.length < 2) return;
    const path = pathForPoints(points);
    const widthUnits = platform.platform_width_units || (platform.platform_kind === 'ISLAND' ? 2 : 1);
    const strokeWidths = platformStrokeWidths(widthUnits);
    const platformColor = platform.cargo ? CARGO_PLATFORM_COLOR : PASSENGER_PLATFORM_COLOR;
    S('path', {
      d: path, fill: 'none', stroke: '#26343d', 'stroke-width': strokeWidths.outline,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      'pointer-events': 'none',
    }, '', $platformLayer);
    S('path', {
      d: path, fill: 'none', stroke: platformColor, 'stroke-width': strokeWidths.deck,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      'pointer-events': 'none',
    }, '', $platformLayer);
    const $divider = platform.platform_kind === 'ISLAND' ? S('path', {
      d: path, fill: 'none', stroke: '#58656d', 'stroke-width': 1,
      'stroke-dasharray': '4 3', 'vector-effect': 'non-scaling-stroke',
      'pointer-events': 'none', display: 'none',
    }, '', $platformLayer) : null;
    const $hit = S('path', {
      d: path, fill: 'none', stroke: 'transparent', 'stroke-width': strokeWidths.hit,
      'stroke-linecap': 'round', 'pointer-events': 'stroke', cursor: 'help',
    }, '', $platformLayer);
    const length = Number.isFinite(platform.platform_length_m) ? `${platform.platform_length_m.toFixed(1)} m` : '长度 UNKNOWN';
    $hit.on('pointerenter.stationPreview pointermove.stationPreview', event => {
      const face = faceForPointer(platform, event);
      if ($divider) $divider.attr('display', 'block');
      $tooltip.text(`${Number(face?.terminal_index ?? platform.platform_index) + 1}站台（${platform.cargo ? '货' : '客'}） · ${length}`).show();
      moveTooltip(event);
    }).on('pointerleave.stationPreview', () => {
      if ($divider) $divider.attr('display', 'none');
      $tooltip.hide();
    });
  });

  preview.nodes.filter(node => node.degree >= 3).forEach(node => {
    const point = P(node.position);
    S('circle', {
      cx: point.x, cy: point.y, r: 2.3, fill: '#ffd35a', stroke: '#584613', 'stroke-width': .7,
      'vector-effect': 'non-scaling-stroke', 'pointer-events': 'none',
    }, '', $switchLayer);
  });
  [preview.station].forEach(station => {
    const point = P(station.center);
    const selected = station.entity_id === stationId;
    S('circle', {
      cx: point.x, cy: point.y, r: selected ? 5 : 3, fill: selected ? '#56dcff' : '#08141e',
      stroke: '#83ecff', 'stroke-width': 1.2, 'vector-effect': 'non-scaling-stroke',
    }, '', $labelLayer);
    S('text', {
      x: point.x + 8, y: point.y - 7, fill: selected ? '#d9f9ff' : '#8eaaba',
      'font-size': selected ? 12 : 9, 'font-family': 'Consolas, Microsoft YaHei',
      'paint-order': 'stroke', stroke: '#061019', 'stroke-width': 3,
    }, station.name || `车站 ${station.entity_id}`, $labelLayer);
  });

  const scaleBarPixels = 92;
  const barX = 58;
  const barY = 682;
  S('line', { x1: barX, y1: barY, x2: barX + scaleBarPixels, y2: barY, stroke: '#dce7ef', 'stroke-width': 3 });
  S('line', { x1: barX, y1: barY - 5, x2: barX, y2: barY + 5, stroke: '#dce7ef', 'stroke-width': 2 });
  S('line', { x1: barX + scaleBarPixels, y1: barY - 5, x2: barX + scaleBarPixels, y2: barY + 5, stroke: '#dce7ef', 'stroke-width': 2 });
  const $scaleText = S('text', { x: barX + scaleBarPixels / 2, y: barY - 9, fill: '#dce7ef', 'font-size': 10, 'font-family': 'Consolas', 'text-anchor': 'middle' });
  const platformLegendX = barX + scaleBarPixels + 24;
  [
    { y: barY - 9, color: PASSENGER_PLATFORM_COLOR, label: '客台' },
    { y: barY + 7, color: CARGO_PLATFORM_COLOR, label: '货台' },
  ].forEach(item => {
    S('line', { x1: platformLegendX, y1: item.y, x2: platformLegendX + 20, y2: item.y, stroke: item.color, 'stroke-width': 5, 'stroke-linecap': 'round' });
    S('text', { x: platformLegendX + 27, y: item.y + 3.5, fill: '#dce7ef', 'font-size': 10, 'font-family': 'Microsoft YaHei' }, item.label);
  });
  const formatDistance = value => value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} km` : `${value.toFixed(value < 10 ? 1 : 0)} m`;

  const updateViewport = () => {
    $mapLayer.attr('transform', `translate(${panX} ${panY}) translate(600 360) scale(${zoom}) translate(-600 -360)`);
    $('#zoom-value').text(`${Math.round(zoom * 100)}%`);
    $('#zoom-out').prop('disabled', zoom <= 1 + 1e-9);
    $scaleText.text(formatDistance(scaleBarPixels / baseScale / zoom));
  };
  const setZoom = (value, focusX = 600, focusY = 360) => {
    const next = Math.min(20, Math.max(1, value));
    if (Math.abs(next - zoom) < 1e-9) return;
    const ratio = next / zoom;
    panX = focusX - 600 - ratio * (focusX - 600 - panX);
    panY = focusY - 360 - ratio * (focusY - 360 - panY);
    zoom = next;
    updateViewport();
  };
  $('#zoom-in').off('.stationPreview').on('click.stationPreview', () => setZoom(zoom * 1.4));
  $('#zoom-out').off('.stationPreview').on('click.stationPreview', () => setZoom(zoom / 1.4));
  $('#zoom-reset').off('.stationPreview').on('click.stationPreview', () => { zoom = 1; panX = 0; panY = 0; updateViewport(); });
  $svg.on('wheel.stationPreview', event => {
    event.preventDefault();
    const original = event.originalEvent;
    const rect = $svg[0].getBoundingClientRect();
    const focusX = (original.clientX - rect.left) * 1200 / rect.width;
    const focusY = (original.clientY - rect.top) * 720 / rect.height;
    setZoom(zoom * (original.deltaY < 0 ? 1.15 : 1 / 1.15), focusX, focusY);
  }).on('dragstart.stationPreview selectstart.stationPreview', event => event.preventDefault())
    .on('pointerdown.stationPreview', event => {
      const original = event.originalEvent;
      if (!original.isPrimary || original.button !== 0) return;
      event.preventDefault();
      dragging = true;
      pointerId = original.pointerId;
      lastX = original.clientX;
      lastY = original.clientY;
      $svg[0].setPointerCapture(pointerId);
      $svg.addClass('dragging');
    }).on('pointermove.stationPreview', event => {
      const original = event.originalEvent;
      if (!dragging || original.pointerId !== pointerId) return;
      event.preventDefault();
      const rect = $svg[0].getBoundingClientRect();
      panX += (original.clientX - lastX) * 1200 / rect.width;
      panY += (original.clientY - lastY) * 720 / rect.height;
      lastX = original.clientX;
      lastY = original.clientY;
      updateViewport();
    }).on('pointerup.stationPreview pointercancel.stationPreview lostpointercapture.stationPreview', () => {
      dragging = false;
      pointerId = null;
      $svg.removeClass('dragging');
    });

  const station = preview.station;
  const sidebar = templates.instantiate('local-station-sidebar-template');
  templates.setText(sidebar, 'station-name', station.name || `车站 ${stationId}`);
  const servingLines = [...new Set((preview.lines || []).map(line => line.name || `线路 ${line.entity_id}`))];
  templates.setText(sidebar, 'serving-lines', servingLines.join(' / ') || '无');
  templates.setText(sidebar, 'display-radius', preview.margin_m);
  templates.setText(sidebar, 'generated-at', new Date(preview.generated_at * 1000).toLocaleString('zh-CN', { hour12: false }));
  templates.setText(sidebar, 'save-id', preview.save_id || 'UNKNOWN');
  const rows = templates.slot(sidebar, 'platform-rows');
  physicalPlatforms.forEach(platform => {
    const row = templates.instantiate('local-platform-row-template');
    const faces = platform.terminal_faces || [];
    templates.setText(row, 'platform', `P${Number(platform.platform_index) + 1}`);
    templates.setText(row, 'service-class', `${platform.cargo ? '货运' : '客运'} · ${platform.platform_kind === 'ISLAND' ? '岛式' : '侧式'}`);
    templates.setText(row, 'length', Number.isFinite(platform.platform_length_m) ? `${platform.platform_length_m.toFixed(1)} m` : 'UNKNOWN');
    templates.setText(row, 'terminal-faces', faces.map(face => `T${Number(face.terminal_index) + 1}`).join(' / ') || 'UNKNOWN');
    templates.setText(row, 'node-id', faces.map(face => face.node_id ?? 'UNKNOWN').join(' / '));
    rows.appendChild(row);
  });
  $('#sidebar').empty().append(sidebar);
  $('#station-name').text(station.name || `车站 ${stationId}`);
  $('#snapshot').text(`SAVE ${preview.save_id || 'UNKNOWN'} / STATION ${stationId}`);
  $('.clock').text('STATIC');
  $('.watermark').text('Powered By BlackIce.');
  $('#footer-info').text(`局部站场拓扑为静态缓存 · 立交桥 ${bridgeStructureCount} 座 · 不同步列车信息`);
  updateViewport();
})().catch(error => {
  console.error(error);
  $('#station-name').text('局部图不可用');
  $('.mode').text('STATION PREVIEW · ERROR');
  $('#sidebar').text(`局部站场图加载失败：${error.message || error}`);
  window.showRailMapNotice?.('局部站场图加载失败');
});
