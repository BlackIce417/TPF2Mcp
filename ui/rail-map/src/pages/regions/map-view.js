import {createPixiViewport} from '../../shared/pixi-viewport.js';
import '../network/bridge-crossings.js';

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

function svgElement(tagName, attributes = {}, text = '') {
  const element = document.createElementNS(SVG_NAMESPACE, tagName);
  Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
  if (text) element.textContent = text;
  return element;
}

export class RegionMapView {
  constructor(host, svg, legend, showBoundaries) {
    this.host = host;
    this.svg = svg;
    this.legend = legend;
    this.showBoundaries = showBoundaries;
    this.pixiViewport = createPixiViewport(window.PIXI, host, svg, 'region-webgl');
    if (!this.pixiViewport) throw new Error('调度区精细路网渲染器初始化失败');
    this.pixiViewport.app.stop();
    this.pixiWorld = this.pixiViewport.world;
    this.resizeObserver = new ResizeObserver(() => this.viewport(false));
    this.resizeObserver.observe(host);
    this.hitContext = document.createElement('canvas').getContext('2d');
    this.data = null;
    this.world = null;
    this.selected = null;
    this.focused = null;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.tracks = new Map();
    this.trackIntervals = new Map();
    this.detailTiles = new Map();
    this.pendingTiles = new Map();
    this.desiredTileKeys = new Set();
    this.bridgeLayer = null;
    this.bridgeFrame = null;
    this.stations = new Map();
    this.anchors = new Map();
    this.callbacks = {};
    this.viewportFrame = null;
    this.markerUpdatePending = false;
    this.zoomValue = document.getElementById('zoom-value');
    this.zoomOut = document.getElementById('zoom-out');
    this.#bindPointerControls();
    showBoundaries.addEventListener('change', () => this.refreshHighlights());
  }

  render(data, network, callbacks) {
    this.clear();
    this.data = data;
    this.network = network;
    this.callbacks = callbacks;
    this.world = svgElement('g', {id: 'region-world'});
    this.svg.append(this.world);

    const bounds = network.bounds;
    const width = Math.max(1, bounds.max.x - bounds.min.x);
    const height = Math.max(1, bounds.max.y - bounds.min.y);
    this.baseScale = Math.min(1080 / width, 620 / height);
    this.originX = 600 - (bounds.min.x + bounds.max.x) * this.baseScale / 2;
    this.originY = 360 + (bounds.min.y + bounds.max.y) * this.baseScale / 2;
    const project = point => ({
      x: this.originX + point[0] * this.baseScale,
      y: this.originY - point[1] * this.baseScale,
    });
    for (const [edgeId, start, end, regionId] of data.track_intervals || []) {
      const intervals = this.trackIntervals.get(Number(edgeId)) || [];
      intervals.push({start: Number(start), end: Number(end), regionId});
      this.trackIntervals.set(Number(edgeId), intervals);
    }

    let segmentCount = 0;
    for (const region of data.regions) {
      const color = /^#[0-9a-f]{6}$/i.test(region.color) ? region.color : '#80bfff';
      const pathData = (region.overview_segments || []).map(segment => segment.map((point, index) => {
        const projected = project(point);
        return `${index ? 'L' : 'M'}${projected.x.toFixed(2)},${projected.y.toFixed(2)}`;
      }).join('')).join('');
      segmentCount += (region.overview_segments || []).reduce((total, segment) => total + Math.max(0, segment.length - 1), 0);
      const display = svgElement('path', {
        class: 'region-network-territory',
        d: pathData,
        stroke: color,
        'data-region-track': region.id,
      });
      this.world.append(display);
      this.tracks.set(region.id, {display, hitPath: new Path2D(pathData)});

      const legendItem = document.createElement('span');
      legendItem.style.setProperty('--region-color', color);
      legendItem.append(document.createElement('i'), document.createTextNode(region.name));
      this.legend.append(legendItem);
    }
    this.bridgeLayer = svgElement('g', {id: 'region-bridge-layer'});
    this.world.append(this.bridgeLayer);
    this.svg.dataset.renderer = 'region-overview-and-network-tiles';
    this.svg.dataset.regionCount = String(this.tracks.size);
    this.svg.dataset.segmentCount = String(segmentCount);

    const seen = [];
    for (const station of data.stations) {
      const duplicate = seen.some(item => item.name === station.name
        && Math.hypot(item.point.x - station.point.x, item.point.y - station.point.y) < 15);
      seen.push(station);
      station.hub = data.regions.some(region => region.name.replace('调度区', '') === station.name.replace(/站$/, ''));
      const region = data.regions.find(item => item.id === station.region);
      const group = svgElement('g', {class: 'region-station', 'data-station': station.entity_id});
      group.append(
        svgElement('circle', {r: station.hub ? 5 : 3, fill: region.color, stroke: '#061421', 'stroke-width': 1}),
        svgElement('title', {}, `${station.name} · ${region.name} · #${station.entity_id}`),
      );
      const label = svgElement('text', {x: 7, y: -6}, station.name);
      group.append(label);
      group.addEventListener('pointerdown', event => {
        if (event.button === 0) event.stopPropagation();
      });
      group.addEventListener('click', event => {
        event.stopPropagation();
        callbacks.focusStation(station);
      });
      this.world.append(group);
      this.stations.set(station.entity_id, {group, value: station, label, duplicate});
    }

    for (const anchor of data.anchors) {
      const group = svgElement('g', {id: `region-anchor-${anchor.anchor_id}`, class: 'region-anchor', 'data-anchor': anchor.anchor_id});
      group.append(
        svgElement('rect', {x: -4, y: -4, width: 8, height: 8}),
        svgElement('title', {}, `${anchor.label} · ${anchor.reference_stations.join(' ↔ ')} · 固定坐标 / 信号待校准`),
      );
      const label = svgElement('text', {x: 6, y: 12}, anchor.label);
      group.append(label);
      group.addEventListener('pointerdown', event => {
        if (event.button === 0) event.stopPropagation();
      });
      group.addEventListener('click', event => {
        event.stopPropagation();
        callbacks.focusAnchor(anchor);
      });
      this.world.append(group);
      this.anchors.set(anchor.anchor_id, {group, value: anchor, label});
    }
    this.viewport(true);
  }

  clear() {
    if (this.bridgeFrame !== null) cancelAnimationFrame(this.bridgeFrame);
    this.bridgeFrame = null;
    this.bridgeLayer = null;
    this.pendingTiles.forEach(controller => controller.abort());
    this.pendingTiles.clear();
    for (const {container} of this.detailTiles.values()) container.destroy({children: true});
    this.detailTiles.clear();
    this.pixiWorld.removeChildren();
    this.trackIntervals.clear();
    this.desiredTileKeys.clear();
    this.data = null;
    this.network = null;
    this.world = null;
    this.selected = null;
    this.focused = null;
    this.tracks.clear();
    this.stations.clear();
    this.anchors.clear();
    this.svg.dataset.regionCount = '0';
    this.svg.dataset.segmentCount = '0';
    this.svg.dataset.selectedRegion = '';
    this.svg.dataset.dimmedRegionCount = '0';
    this.svg.dataset.detailTileCount = '0';
    this.svg.replaceChildren();
    this.legend.replaceChildren();
  }

  setSelection(regionId, stationId = null) {
    this.selected = regionId;
    this.focused = stationId;
    this.refreshHighlights();
    this.viewport(true);
  }

  refreshHighlights() {
    this.svg.dataset.selectedRegion = this.selected || '';
    this.svg.dataset.dimmedRegionCount = String(this.selected ? Math.max(0, this.tracks.size - 1) : 0);
    this.tracks.forEach(({display}, id) => {
      display.classList.toggle('is-dim', Boolean(this.selected) && id !== this.selected);
      display.classList.toggle('is-selected', id === this.selected);
    });
    this.detailTiles.forEach(({graphicsByRegion}) => graphicsByRegion.forEach((graphics, id) => {
      graphics.alpha = this.selected && id !== this.selected ? .12 : 1;
    }));
    this.#scheduleBridgeRender();
    this.stations.forEach(({group, value}) => {
      group.classList.toggle('is-dim', Boolean(this.selected) && value.region !== this.selected);
      group.classList.toggle('is-focused', value.entity_id === this.focused);
    });
    this.anchors.forEach(({group, value}) => {
      group.classList.toggle('is-dim', Boolean(this.selected) && !value.regions.includes(this.selected));
      group.style.display = this.showBoundaries.checked ? '' : 'none';
    });
  }

  viewport(updateMarkers = true, immediate = false) {
    if (!this.world) return;
    this.markerUpdatePending ||= updateMarkers;
    const render = () => {
      this.viewportFrame = null;
      if (!this.world) return;
      this.world.setAttribute('transform', `translate(${this.panX} ${this.panY}) translate(600 360) scale(${this.zoom}) translate(-600 -360)`);
      this.pixiViewport.sync({zoom: this.zoom, panX: this.panX, panY: this.panY});
      this.#updateTiles();
      this.pixiViewport.app.render();
      if (this.markerUpdatePending) {
        this.zoomValue.textContent = `${Math.round(this.zoom * 100)}%`;
        this.zoomOut.disabled = this.zoom <= 1;
        this.#updateMarkers();
      }
      this.markerUpdatePending = false;
    };
    if (immediate) {
      if (this.viewportFrame !== null) cancelAnimationFrame(this.viewportFrame);
      render();
      return;
    }
    if (this.viewportFrame === null) this.viewportFrame = requestAnimationFrame(render);
  }

  #representedMeters() {
    return 92 / this.baseScale / this.zoom;
  }

  #networkPoint(screenX, screenY) {
    const baseX = (screenX - this.panX - 600) / this.zoom + 600;
    const baseY = (screenY - this.panY - 360) / this.zoom + 360;
    return {x: (baseX - this.originX) / this.baseScale, y: (this.originY - baseY) / this.baseScale};
  }

  #setOverviewVisibility(show) {
    this.tracks.forEach(({display}) => { display.style.display = show ? '' : 'none'; });
  }

  #unloadTile(key) {
    const pending = this.pendingTiles.get(key);
    if (pending) {
      pending.abort();
      this.pendingTiles.delete(key);
    }
    const loaded = this.detailTiles.get(key);
    if (loaded) {
      this.pixiWorld.removeChild(loaded.container);
      loaded.container.destroy({children: true});
      this.detailTiles.delete(key);
      this.#scheduleBridgeRender();
    }
  }

  #curve(edge, nodes, t, derivative = false) {
    const a = nodes.get(edge.node0);
    const b = nodes.get(edge.node1);
    const delta = {x: b.x - a.x, y: b.y - a.y};
    const u = edge.tangent0 || delta;
    const v = edge.tangent1 || delta;
    if (derivative) return {
      x: (6*t*t - 6*t) * a.x + (3*t*t - 4*t + 1) * u.x + (-6*t*t + 6*t) * b.x + (3*t*t - 2*t) * v.x,
      y: (6*t*t - 6*t) * a.y + (3*t*t - 4*t + 1) * u.y + (-6*t*t + 6*t) * b.y + (3*t*t - 2*t) * v.y,
    };
    return {
      x: (2*t**3 - 3*t*t + 1) * a.x + (t**3 - 2*t*t + t) * u.x + (-2*t**3 + 3*t*t) * b.x + (t**3 - t*t) * v.x,
      y: (2*t**3 - 3*t*t + 1) * a.y + (t**3 - 2*t*t + t) * u.y + (-2*t**3 + 3*t*t) * b.y + (t**3 - t*t) * v.y,
    };
  }

  #drawInterval(graphics, edge, nodes, start, end) {
    const a = this.#curve(edge, nodes, start);
    const b = this.#curve(edge, nodes, end);
    const u = this.#curve(edge, nodes, start, true);
    const v = this.#curve(edge, nodes, end, true);
    const span = end - start;
    const project = point => ({
      x: this.originX + point.x * this.baseScale,
      y: this.originY - point.y * this.baseScale,
    });
    const p0 = project(a);
    const p1 = project({x: a.x + u.x * span / 3, y: a.y + u.y * span / 3});
    const p2 = project({x: b.x - v.x * span / 3, y: b.y - v.y * span / 3});
    const p3 = project(b);
    graphics.moveTo(p0.x, p0.y).bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
  }

  #edgePath(edge, nodes) {
    const a = this.#curve(edge, nodes, 0);
    const b = this.#curve(edge, nodes, 1);
    const u = this.#curve(edge, nodes, 0, true);
    const v = this.#curve(edge, nodes, 1, true);
    const project = point => ({
      x: this.originX + point.x * this.baseScale,
      y: this.originY - point.y * this.baseScale,
    });
    const points = [project(a), project({x: a.x + u.x / 3, y: a.y + u.y / 3}),
      project({x: b.x - v.x / 3, y: b.y - v.y / 3}), project(b)];
    return `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}C${points[1].x.toFixed(2)},${points[1].y.toFixed(2)} ${points[2].x.toFixed(2)},${points[2].y.toFixed(2)} ${points[3].x.toFixed(2)},${points[3].y.toFixed(2)}`;
  }

  #scheduleBridgeRender() {
    if (!this.bridgeLayer || this.bridgeFrame !== null) return;
    this.bridgeFrame = requestAnimationFrame(() => this.#renderBridges());
  }

  #renderBridges() {
    this.bridgeFrame = null;
    if (!this.bridgeLayer) return;
    this.bridgeLayer.replaceChildren();
    const crossings = [];
    const visibleEdgePaths = new Map();
    const visibleEdges = new Map();
    const visibleNodes = new Map();
    const visibleEdgeIdsByNode = new Map();
    this.detailTiles.forEach(entry => {
      entry.paths.forEach((path, edgeId) => visibleEdgePaths.set(Number(edgeId), path));
      entry.nodes.forEach((position, nodeId) => visibleNodes.set(Number(nodeId), position));
      entry.tile.edges.forEach(edge => {
        const edgeId = Number(edge.entity_id);
        visibleEdges.set(edgeId, edge);
        for (const nodeId of [edge.node0, edge.node1]) {
          const values = visibleEdgeIdsByNode.get(Number(nodeId)) || [];
          if (!values.includes(edgeId)) values.push(edgeId);
          visibleEdgeIdsByNode.set(Number(nodeId), values);
        }
      });
      crossings.push(...(entry.tile.grade_separated_crossings || []));
    });
    if (!crossings.length) return;
    const project = point => ({
      x: this.originX + point.x * this.baseScale,
      y: this.originY - point.y * this.baseScale,
    });
    const create = (tag, attributes = {}, text = '', parent = this.bridgeLayer) => {
      const element = svgElement(tag, attributes, text);
      parent.append(element);
      return element;
    };
    const regionById = new Map(this.data.regions.map(region => [region.id, region]));
    const regionForEdge = edgeId => this.trackIntervals.get(Number(edgeId))?.[0]?.regionId;
    window.RailBridgeCrossings.renderSvg(crossings, project, create, this.bridgeLayer, {
      trackStrokeWidth: 1.2,
      trackColorForEdge: edgeId => regionById.get(regionForEdge(edgeId))?.color,
      trackOpacityForEdge: edgeId => this.selected && regionForEdge(edgeId) !== this.selected ? .12 : 1,
      upperPathForEdge: edgeId => visibleEdgePaths.get(Number(edgeId)),
      upperEdgeIdsForBridge: (crossing, shape) => window.RailBridgeCrossings.expandUpperEdgeIds(
        crossing, shape, visibleEdges, visibleNodes, visibleEdgeIdsByNode,
      ),
      upperPointsForEdge: edgeId => {
        const edge = visibleEdges.get(Number(edgeId));
        return edge ? window.RailBridgeCrossings.sampleEdge(edge, visibleNodes) : null;
      },
    });
  }

  #renderTile(key, tile) {
    if (!this.desiredTileKeys.has(key)) return;
    const nodes = new Map(tile.nodes.map(node => [node.entity_id, node.position]));
    const paths = new Map(tile.edges.map(edge => [Number(edge.entity_id), this.#edgePath(edge, nodes)]));
    const container = new window.PIXI.Container();
    const graphicsByRegion = new Map();
    for (const region of this.data.regions) {
      const graphics = new window.PIXI.Graphics();
      const color = /^#[0-9a-f]{6}$/i.test(region.color) ? Number.parseInt(region.color.slice(1), 16) : 0x80bfff;
      graphics.lineStyle(1.2, color, 1, .5, true);
      graphics.alpha = this.selected && region.id !== this.selected ? .12 : 1;
      graphicsByRegion.set(region.id, graphics);
      container.addChild(graphics);
    }
    for (const edge of tile.edges) {
      for (const interval of this.trackIntervals.get(Number(edge.entity_id)) || []) {
        this.#drawInterval(graphicsByRegion.get(interval.regionId), edge, nodes, interval.start, interval.end);
      }
    }
    this.pixiWorld.addChild(container);
    this.detailTiles.set(key, {container, graphicsByRegion, tile, nodes, paths});
    this.svg.dataset.detailTileCount = String(this.detailTiles.size);
    this.#setOverviewVisibility(![...this.desiredTileKeys].every(candidate => this.detailTiles.has(candidate)));
    this.#scheduleBridgeRender();
    this.pixiViewport.app.render();
  }

  #loadTile(key) {
    if (this.detailTiles.has(key) || this.pendingTiles.has(key)) return;
    const controller = new AbortController();
    this.pendingTiles.set(key, controller);
    fetch(`/api/rail/tile/${key}`, {signal: controller.signal, cache: 'no-store'})
      .then(response => {
        if (!response.ok) throw new Error(`tile ${key}: ${response.status}`);
        return response.json();
      })
      .then(tile => {
        this.pendingTiles.delete(key);
        this.#renderTile(key, tile);
      })
      .catch(error => {
        this.pendingTiles.delete(key);
        if (error.name !== 'AbortError') console.error(error);
      });
  }

  #updateTiles() {
    if (!this.network || this.#representedMeters() >= this.network.detail_load_threshold_m) {
      this.desiredTileKeys = new Set();
      [...this.detailTiles.keys(), ...this.pendingTiles.keys()].forEach(key => this.#unloadTile(key));
      this.#setOverviewVisibility(true);
      this.svg.dataset.detailTileCount = '0';
      return;
    }
    const topLeft = this.#networkPoint(0, 0);
    const bottomRight = this.#networkPoint(1200, 720);
    const margin = this.network.tile_size_m * .15;
    const view = {
      minX: Math.min(topLeft.x, bottomRight.x) - margin,
      maxX: Math.max(topLeft.x, bottomRight.x) + margin,
      minY: Math.min(topLeft.y, bottomRight.y) - margin,
      maxY: Math.max(topLeft.y, bottomRight.y) + margin,
    };
    this.desiredTileKeys = new Set(this.network.tiles.filter(tile => tile.max.x >= view.minX
      && tile.min.x <= view.maxX && tile.max.y >= view.minY && tile.min.y <= view.maxY).map(tile => tile.key));
    [...this.detailTiles.keys(), ...this.pendingTiles.keys()]
      .filter(key => !this.desiredTileKeys.has(key)).forEach(key => this.#unloadTile(key));
    this.desiredTileKeys.forEach(key => this.#loadTile(key));
    this.#setOverviewVisibility(![...this.desiredTileKeys].every(key => this.detailTiles.has(key)));
  }

  #updateMarkers() {
    this.stations.forEach(({group, value, label, duplicate}) => {
      group.setAttribute('transform', `translate(${value.point.x} ${value.point.y}) scale(${1 / this.zoom})`);
      label.setAttribute('visibility', value.entity_id === this.focused
        || (!duplicate && (this.zoom > 2.8 || value.hub || value.region === this.selected)) ? 'visible' : 'hidden');
    });
    this.anchors.forEach(({group, value, label}) => {
      group.setAttribute('transform', `translate(${value.point.x} ${value.point.y}) scale(${1 / this.zoom})`);
      label.setAttribute('visibility', this.zoom > 2 ? 'visible' : 'hidden');
    });
  }

  setZoom(value, x = 600, y = 360) {
    const next = Math.max(1, Math.min(40, value));
    const ratio = next / this.zoom;
    this.panX = x - 600 - ratio * (x - 600 - this.panX);
    this.panY = y - 360 - ratio * (y - 360 - this.panY);
    this.zoom = next;
    this.viewport(true, true);
  }

  fit(regionId) {
    const bounds = this.data?.regions.find(region => region.id === regionId)?.bounds;
    if (!bounds) {
      this.zoom = 1;
      this.panX = 0;
      this.panY = 0;
    } else {
      this.zoom = Math.max(1, Math.min(8,
        1040 / Math.max(1, bounds.max_x - bounds.min_x),
        540 / Math.max(1, bounds.max_y - bounds.min_y)));
      this.panX = (600 - (bounds.min_x + bounds.max_x) / 2) * this.zoom;
      this.panY = (360 - (bounds.min_y + bounds.max_y) / 2) * this.zoom;
    }
    this.viewport(true);
  }

  focusPoint(point, scale = 8) {
    this.zoom = Math.max(this.zoom, scale);
    this.panX = (600 - point.x) * this.zoom;
    this.panY = (360 - point.y) * this.zoom;
    this.viewport(true);
  }

  resetZoom() {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.viewport(true);
  }

  #pointer(event) {
    const point = this.svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(this.svg.getScreenCTM().inverse());
  }

  #worldPoint(point) {
    return {
      x: 600 + (point.x - this.panX - 600) / this.zoom,
      y: 360 + (point.y - this.panY - 360) / this.zoom,
    };
  }

  #trackAt(point) {
    const world = this.#worldPoint(point);
    this.hitContext.lineWidth = 8 / this.zoom;
    for (const [id, track] of [...this.tracks].reverse()) {
      if ((!this.selected || id === this.selected)
          && this.hitContext.isPointInStroke(track.hitPath, world.x, world.y)) return id;
    }
    return null;
  }

  #bindPointerControls() {
    let drag = null;
    let dragged = false;
    this.svg.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !event.isPrimary) return;
      event.preventDefault();
      drag = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
      };
      dragged = false;
      this.svg.setPointerCapture(event.pointerId);
    });
    this.svg.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.id) return;
      event.preventDefault();
      if (!dragged && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 3) return;
      dragged = true;
      this.svg.classList.add('dragging');
      const bounds = this.svg.getBoundingClientRect();
      this.panX += (event.clientX - drag.lastX) * 1200 / bounds.width;
      this.panY += (event.clientY - drag.lastY) * 720 / bounds.height;
      drag.lastX = event.clientX;
      drag.lastY = event.clientY;
      this.viewport(false);
    });
    const stopDrag = event => {
      if (event && drag && event.pointerId !== drag.id) return;
      const pointerId = drag?.id;
      drag = null;
      this.svg.classList.remove('dragging');
      if (pointerId != null && this.svg.hasPointerCapture(pointerId)) this.svg.releasePointerCapture(pointerId);
    };
    this.svg.addEventListener('pointerup', stopDrag);
    this.svg.addEventListener('pointercancel', stopDrag);
    this.svg.addEventListener('lostpointercapture', stopDrag);
    this.svg.addEventListener('click', event => {
      if (dragged) {
        event.stopImmediatePropagation();
        event.preventDefault();
        dragged = false;
        return;
      }
      const regionId = this.#trackAt(this.#pointer(event));
      if (regionId) this.callbacks.selectRegion(regionId);
    });
    this.svg.addEventListener('wheel', event => {
      event.preventDefault();
      const bounds = this.svg.getBoundingClientRect();
      const focusX = (event.clientX - bounds.left) * 1200 / bounds.width;
      const focusY = (event.clientY - bounds.top) * 720 / bounds.height;
      this.setZoom(this.zoom * (event.deltaY < 0 ? 1.35 : 1 / 1.35), focusX, focusY);
    }, {passive: false});
  }
}
