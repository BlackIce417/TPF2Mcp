import {byId, cloneTemplate} from '../../shared/dom.js';

export class RegionSidebarView {
  constructor() {
    this.cardsContainer = byId('dispatch-region-list');
    this.overviewDetails = byId('dispatch-overview-details');
    this.overviewStationCount = byId('dispatch-overview-station-count');
    this.overviewDepotCount = byId('dispatch-overview-depot-count');
    this.selectedRegion = byId('dispatch-selected-region');
    this.regionName = byId('dispatch-region-name');
    this.regionSummary = byId('dispatch-region-summary');
    this.focusedStation = byId('dispatch-focused-station');
    this.focusedStationName = byId('dispatch-focused-station-name');
    this.focusedStationLink = byId('dispatch-focused-station-link');
    this.regionDepots = byId('dispatch-region-depots');
    this.isolatedTracks = byId('dispatch-region-isolated-tracks');
    this.boundaryCount = byId('dispatch-boundary-count');
    this.boundaryList = byId('dispatch-boundary-list');
    this.stationList = byId('dispatch-station-list');
    this.cards = new Map();
  }

  renderCards(data, onSelect) {
    this.cards.clear();
    this.cardsContainer.replaceChildren();
    for (const region of data.regions) {
      const card = cloneTemplate('region-card-template');
      const color = /^#[0-9a-f]{6}$/i.test(region.color) ? region.color : '#80bfff';
      card.style.setProperty('--region-color', color);
      card.dataset.region = region.id;
      card.querySelector('strong').textContent = region.name;
      card.querySelector('small').textContent = `${region.station_count} 站场 · ${region.track_km.toFixed(1)} 轨道公里`;
      card.addEventListener('click', () => onSelect(region.id));
      this.cardsContainer.append(card);
      this.cards.set(region.id, card);
    }
  }

  setSelection(regionId) {
    this.cards.forEach((card, id) => card.setAttribute('aria-pressed', String(id === regionId)));
  }

  renderDetails(data, regionId, stationId, {focusStation, focusAnchor}) {
    this.overviewStationCount.textContent = String(data.stations.length);
    this.overviewDepotCount.textContent = String(data.depots.length);
    const region = data.regions.find(item => item.id === regionId);
    this.overviewDetails.hidden = Boolean(region);
    this.selectedRegion.hidden = !region;
    this.boundaryList.replaceChildren();
    this.stationList.replaceChildren();
    if (!region) return;

    this.regionName.textContent = region.name;
    this.regionSummary.textContent = `${region.station_count} 个车站实体 · ${region.track_km.toFixed(1)} 轨道公里（上下行及侧线分别计入）`;
    const station = stationId === null ? null : data.stations.find(item => item.entity_id === stationId);
    this.focusedStation.hidden = !station;
    if (station) {
      this.focusedStationName.textContent = `已定位：${station.name}`;
      this.focusedStationLink.href = `local.html?view=local&station=${station.entity_id}`;
    } else {
      this.focusedStationName.textContent = '';
      this.focusedStationLink.removeAttribute('href');
    }

    this.regionDepots.textContent = data.depots
      .filter(item => item.region === regionId).map(item => item.name).join('、') || '暂无';
    const isolated = data.isolated_tracks.filter(item => item.region === regionId);
    this.isolatedTracks.hidden = isolated.length === 0;
    this.isolatedTracks.textContent = isolated.length
      ? `另有 ${isolated.length} 组孤立轨道已登记管辖，连接用途待核对。` : '';

    const regionAnchors = data.anchors.filter(anchor => anchor.regions.includes(regionId));
    this.boundaryCount.textContent = String(regionAnchors.length);
    for (const anchor of regionAnchors) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${anchor.label} · ${anchor.reference_stations.join(' ↔ ')} · 待校准`;
      button.title = `固定坐标 ${anchor.position.x.toFixed(1)}, ${anchor.position.y.toFixed(1)}, ${anchor.position.z.toFixed(1)}`;
      button.addEventListener('click', () => focusAnchor(anchor));
      this.boundaryList.append(button);
    }

    const stations = data.stations
      .filter(item => item.region === regionId)
      .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN') || left.entity_id - right.entity_id);
    for (const item of stations) {
      const button = document.createElement('button');
      const metadata = document.createElement('small');
      button.type = 'button';
      button.dataset.stationId = item.entity_id;
      button.textContent = item.name;
      metadata.textContent = `${item.cargo.map(cargo => cargo ? '货运' : '客运').join(' / ') || '站场'} · #${item.entity_id}`;
      button.append(metadata);
      button.addEventListener('click', () => focusStation(item));
      this.stationList.append(button);
    }
  }

  clear() {
    this.cards.clear();
    this.cardsContainer.replaceChildren();
    this.boundaryList.replaceChildren();
    this.stationList.replaceChildren();
    this.overviewDetails.hidden = false;
    this.selectedRegion.hidden = true;
    this.overviewStationCount.textContent = '0';
    this.overviewDepotCount.textContent = '0';
  }
}
