import {getJson} from '../../shared/http.js';
import {byId} from '../../shared/dom.js';

const REASONS = {
  SESSION_OR_SIGNAL_COLLECTION_REQUIRED: '等待重载后的同会话信号采集',
  TELEMETRY_STALE: '列车遥测已过期',
  SAVE_MISMATCH: '存档不匹配',
  SIMULATION_NOT_RUNNING: '游戏暂停或时钟状态待确认',
  TERRITORY_REVIEW_REQUIRED: '改建后的管辖范围需要核对',
};

const CALIBRATION_NAMES = {
  CALIBRATED: '方向已校准',
  PARTIAL: '部分方向已校准',
  DIRECTION_UNKNOWN: '信号方向待采集',
  NO_SUITABLE_SIGNAL: '未找到合格信号',
  AMBIGUOUS_ROUTE: '分岔进路待核验',
  AMBIGUOUS: '平行线路匹配有歧义',
  NO_TRACK: '坐标附近无匹配轨道',
  DIRECTION_PROHIBITED: '单向信号禁止该方向',
  ILLEGAL_TURN: '轨道连接不可直接通行',
};

export class RegionalRuntimePanel {
  constructor() {
    this.panel = byId('regional-runtime');
    this.title = byId('dispatch-runtime-title');
    this.mode = byId('dispatch-runtime-mode');
    this.trainCount = byId('dispatch-runtime-train-count');
    this.quality = byId('dispatch-runtime-quality');
    this.coverage = byId('dispatch-runtime-coverage');
    this.control = byId('dispatch-runtime-control');
    this.calibration = byId('dispatch-runtime-calibration');
    this.calibrationList = byId('dispatch-runtime-calibration-list');
    this.busy = false;
    this.interacting = false;
    this.interactionTimer = null;
  }

  start() {
    const board = byId('board');
    const beginInteraction = () => { this.interacting = true; };
    const endInteraction = () => { this.interacting = false; };
    board.addEventListener('pointerdown', beginInteraction);
    window.addEventListener('pointerup', endInteraction);
    window.addEventListener('pointercancel', endInteraction);
    board.addEventListener('wheel', () => {
      beginInteraction();
      window.clearTimeout(this.interactionTimer);
      this.interactionTimer = window.setTimeout(endInteraction, 180);
    }, {passive: true});
    document.addEventListener('regional-selection', () => this.update());
    document.addEventListener('visibilitychange', () => this.update());
    this.update();
    window.setInterval(() => this.update(), 1000);
  }

  async update() {
    if (this.busy || document.hidden) return;
    this.busy = true;
    try {
      const [value, current] = await Promise.all([
        getJson('/api/regional-status'),
        getJson('/api/status'),
      ]);
      const now = Date.now() / 1000;
      if (now - value.updated_at > 5 || value.updated_at > now + 2) throw new Error('区域后台状态已过期');
      if (value.error) throw new Error(value.error);
      if (value.save_id !== current.save_id || String(value.topology_generation) !== String(current.rail_generation)) {
        throw new Error('区域后台数据与当前路网不匹配');
      }
      if (!this.interacting) this.render(value);
    } catch (error) {
      this.renderError(error.message || '区域后台尚未启动');
    } finally {
      this.busy = false;
    }
  }

  renderError(message) {
    this.title.textContent = '区域调度后台';
    this.mode.textContent = '';
    this.trainCount.textContent = '';
    this.quality.hidden = false;
    this.quality.textContent = message;
    this.coverage.textContent = '';
    this.control.textContent = '';
    this.calibration.hidden = true;
    this.calibrationList.replaceChildren();
  }

  render(value) {
    const expanded = this.calibration.open;
    this.title.textContent = '区域调度后台 · 影子运行';
    this.mode.textContent = '持续观测与模拟交接，尚未向游戏下发区域控制。';
    const region = new URL(window.location.href).searchParams.get('region');
    const labels = {HK: '汉口', WC: '武昌', WH: '武汉', UNKNOWN: '位置待定'};
    this.trainCount.textContent = Object.entries(value.train_counts || {})
      .filter(([id]) => !region || id === region || id === 'UNKNOWN')
      .map(([id, count]) => `${labels[id] || id} ${count} 列`)
      .join(' · ') || '暂无列车';

    const issues = (value.quality?.issues || []).map(issue => REASONS[issue] || issue);
    this.quality.hidden = issues.length === 0;
    this.quality.textContent = issues.join('；');
    const coverage = value.coverage;
    this.coverage.textContent = `轨道归属 ${coverage.assigned_edge_count}/${coverage.edge_count} · 未锚定跨界通道 ${coverage.unanchored_crossings.length}`;
    const controls = value.control || {};
    this.control.textContent = `预约资源 ${controls.reservations?.length || 0} · 交接记录 ${controls.handovers?.length || 0}`;

    this.calibration.hidden = false;
    this.calibration.open = expanded;
    this.calibrationList.replaceChildren();
    for (const anchor of value.calibration?.anchors || []) {
      const directions = Object.values(anchor.directions || {});
      if (region && directions.length && !directions.some(item => item.from_region === region || item.to_region === region)) continue;
      const status = CALIBRATION_NAMES[anchor.status] || anchor.status;
      const row = document.createElement('p');
      row.textContent = `${anchor.label}：${status}`;
      this.calibrationList.append(row);
      const marker = document.getElementById(`region-anchor-${anchor.anchor_id}`);
      if (!marker) continue;
      marker.classList.toggle('direction-calibrated', anchor.status === 'CALIBRATED');
      marker.querySelector('title').textContent = `${anchor.label} · ${status} · 坐标边界不移动`;
    }
  }
}
