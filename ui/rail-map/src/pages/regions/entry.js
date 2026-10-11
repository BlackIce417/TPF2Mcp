import '../../shared/navigation.js';
import '../../shared/control-ui.js';
import {getJson, HttpError} from '../../shared/http.js';
import {byId} from '../../shared/dom.js';
import {RegionMapView} from './map-view.js';
import {RegionalRuntimePanel} from './runtime-panel.js';
import {RegionSidebarView} from './sidebar-view.js';

const ERROR_MESSAGES = {
  REGIONS_NOT_CONFIGURED: '当前存档尚未配置调度区。',
  REGIONS_SAVE_MISMATCH: '存档已变化，请为当前存档重新生成调度区。',
  REGIONS_TOPOLOGY_STALE: '路网已更新，原划区需要重新核对。',
  REGIONS_SCHEMA_UNSUPPORTED: '调度区数据版本不兼容。',
};

class RegionPage {
  constructor() {
    this.data = null;
    this.network = null;
    this.selected = null;
    this.focused = null;
    this.requestVersion = 0;
    this.healthPending = false;
    this.statusFailureCount = 0;
    this.statusWarningVisible = false;
    this.map = new RegionMapView(
      byId('board-wrap'), byId('board'), byId('region-legend'), byId('show-boundaries'),
    );
    this.sidebar = new RegionSidebarView();
    this.#bindControls();
  }

  start() {
    this.load();
    window.setInterval(() => this.checkScope(), 10000);
  }

  message(text, isError = false) {
    const element = byId('region-message');
    element.textContent = text;
    element.hidden = !text;
    element.classList.toggle('is-error', isError);
  }

  clear(reason) {
    this.data = null;
    this.network = null;
    this.selected = null;
    this.focused = null;
    this.map.clear();
    this.sidebar.clear();
    byId('region-title').textContent = '调度区不可用';
    byId('region-summary').textContent = '';
    byId('region-footer').textContent = '区域显示已停止，原划区不会套用到新路网。';
    this.message(reason, true);
  }

  async load() {
    const version = ++this.requestVersion;
    byId('reload-regions').disabled = true;
    this.message('正在读取调度区…');
    try {
      const [regions, scope, network] = await Promise.all([
        getJson('/api/dispatch-regions', {attempts: 3}),
        getJson('/api/status', {attempts: 3}),
        getJson('/api/rail/manifest', {attempts: 3}),
      ]);
      this.#validate(regions, scope, network);
      if (version !== this.requestVersion) return;
      this.data = regions;
      this.network = network;
      this.statusFailureCount = 0;
      this.statusWarningVisible = false;
      this.render();
      this.message('');
    } catch (error) {
      if (version !== this.requestVersion) return;
      const code = error instanceof HttpError ? error.payload?.error : error.message;
      this.clear(ERROR_MESSAGES[code] || error.message || '服务暂时不可用，请重试。');
    } finally {
      if (version === this.requestVersion) byId('reload-regions').disabled = false;
    }
  }

  render() {
    this.map.render(this.data, this.network, {
      selectRegion: id => this.selectRegion(id),
      focusStation: station => this.focusStation(station),
      focusAnchor: anchor => this.focusAnchor(anchor),
    });
    this.sidebar.renderCards(this.data, id => {
      this.message('');
      this.selectRegion(id);
    });
    byId('region-summary').textContent = `${this.data.regions.length} 区 · ${this.data.stations.length} 个车站实体 · ${this.data.anchors.length} 个边界`;
    byId('region-footer').textContent = `划区草案 · 已导出路网归属遗漏 ${this.data.coverage.unassigned_edges} · 拓扑 ${new Date(this.data.topology_generation * 1000).toLocaleString('zh-CN', {hour12: false})}`;
    this.selectRegion(new URL(window.location.href).searchParams.get('region'), {updateUrl: false});
  }

  selectRegion(id, {updateUrl = true, autoFit = true} = {}) {
    if (!this.data) return;
    this.selected = this.data.regions.some(region => region.id === id) ? id : null;
    this.focused = null;
    if (updateUrl) {
      const url = new URL(window.location.href);
      if (this.selected) url.searchParams.set('region', this.selected);
      else url.searchParams.delete('region');
      window.history.pushState({}, '', url);
    }
    const region = this.data.regions.find(item => item.id === this.selected);
    byId('region-title').textContent = region ? region.name : '调度区总览';
    byId('all-regions').setAttribute('aria-pressed', String(!this.selected));
    this.map.setSelection(this.selected, this.focused);
    this.sidebar.setSelection(this.selected);
    this.sidebar.renderDetails(this.data, this.selected, this.focused, {
      focusStation: station => this.focusStation(station),
      focusAnchor: anchor => this.focusAnchor(anchor),
    });
    if (autoFit) this.map.fit(this.selected);
    document.dispatchEvent(new Event('regional-selection'));
  }

  focusStation(station) {
    if (this.selected !== station.region) this.selectRegion(station.region, {autoFit: false});
    this.focused = station.entity_id;
    this.map.setSelection(this.selected, this.focused);
    this.map.focusPoint(station.point);
    this.sidebar.renderDetails(this.data, this.selected, this.focused, {
      focusStation: item => this.focusStation(item),
      focusAnchor: anchor => this.focusAnchor(anchor),
    });
  }

  focusAnchor(anchor) {
    this.map.focusPoint(anchor.point, 12);
    this.message(`${anchor.label}：坐标边界，上下行控制信号待校准`);
  }

  async checkScope() {
    if (!this.data || this.healthPending || document.hidden) return;
    this.healthPending = true;
    try {
      const status = await getJson('/api/status', {attempts: 3});
      if (!this.data) return;
      if (status.save_transition || status.save_id !== this.data.save_id || status.rail_save_id !== this.data.save_id) {
        this.clear(ERROR_MESSAGES.REGIONS_SAVE_MISMATCH);
      } else if (String(status.rail_generation) !== String(this.data.topology_generation)) {
        this.clear(ERROR_MESSAGES.REGIONS_TOPOLOGY_STALE);
      } else {
        this.statusFailureCount = 0;
      }
      if (this.statusWarningVisible) {
        this.statusWarningVisible = false;
        this.message('');
      }
    } catch (_) {
      this.statusFailureCount += 1;
      if (this.statusFailureCount >= 3) {
        this.statusWarningVisible = true;
        this.message('后端持续不可达，当前仍显示上次读取的划区草案。', true);
      }
    } finally {
      this.healthPending = false;
    }
  }

  #validate(regions, scope, network) {
    if (regions.schema_version !== 1) throw new Error('REGIONS_SCHEMA_UNSUPPORTED');
    if (scope.save_transition || scope.save_id !== regions.save_id || scope.rail_save_id !== regions.save_id) {
      throw new Error('REGIONS_SAVE_MISMATCH');
    }
    if (String(scope.rail_generation) !== String(regions.topology_generation)) {
      throw new Error('REGIONS_TOPOLOGY_STALE');
    }
    if (network.save_id !== regions.save_id
        || String(network.generated_at) !== String(regions.topology_generation)) {
      throw new Error('REGIONS_TOPOLOGY_STALE');
    }
  }

  #bindControls() {
    byId('zoom-in').addEventListener('click', () => this.map.setZoom(this.map.zoom * 1.4));
    byId('zoom-out').addEventListener('click', () => this.map.setZoom(this.map.zoom / 1.4));
    byId('zoom-reset').addEventListener('click', () => this.map.resetZoom());
    byId('fit-region').addEventListener('click', () => this.map.fit(this.selected));
    byId('all-regions').addEventListener('click', () => {
      this.message('');
      this.selectRegion(null);
    });
    byId('reload-regions').addEventListener('click', () => this.load());
    window.addEventListener('popstate', () => this.selectRegion(
      new URL(window.location.href).searchParams.get('region'),
      {updateUrl: false},
    ));
    document.addEventListener('visibilitychange', () => this.checkScope());
  }
}

new RegionPage().start();
new RegionalRuntimePanel().start();
