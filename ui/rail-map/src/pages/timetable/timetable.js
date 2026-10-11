/* Pure time geometry is also exercised by Node regression tests. */
const TimetableGeometry = {
  points(line, phase = 0) {
    const points = [];
    line.stops.forEach((stop, index) => {
      points.push([phase + stop.arrival_offset_seconds, index]);
      points.push([phase + stop.departure_offset_seconds, index]);
    });
    if (line.stops.length) points.push([phase + line.cycle_seconds + line.stops[0].arrival_offset_seconds, line.stops.length]);
    return points;
  },
  cycles(line, start, end) {
    const first = line.stops[0]?.arrival_offset_seconds || 0;
    return [Math.floor((start - first) / line.cycle_seconds) - 1, Math.ceil((end - first) / line.cycle_seconds)];
  },
  stationPoints(value, previous, stopCount) {
    const now = value?.simulation?.clock?.game_time;
    const priorTime = previous?.simulation?.clock?.game_time;
    if (!value?.fresh || typeof now !== 'number' || now === priorTime) return [];
    const priorVehicles = new Map((previous?.vehicles || []).map(vehicle => [vehicle.entity_id, vehicle]));
    const consecutive = previous?.fresh && value.sampled_at > previous.sampled_at &&
      value.sampled_at - previous.sampled_at <= 5 && now > priorTime;
    return value.vehicles.filter(vehicle => vehicle.raw_state === 2 && !vehicle.position_stale &&
      Number.isInteger(vehicle.stop_index) && vehicle.stop_index >= 0 && vehicle.stop_index < stopCount).map(vehicle => {
      const prior = priorVehicles.get(vehicle.entity_id);
      return {id: vehicle.entity_id, name: vehicle.name || `列车 ${vehicle.entity_id}`, stop: vehicle.stop_index, time: now / 1000,
        timetable: vehicle.timetable || null,
        wall: value.sampled_at, previousWall: consecutive && prior?.raw_state === 2 && !prior.position_stale && prior.stop_index === vehicle.stop_index ? previous.sampled_at : null,
        previous: consecutive && prior?.raw_state === 2 && !prior.position_stale && prior.stop_index === vehicle.stop_index ? priorTime / 1000 : null};
    });
  },
  clock(seconds) {
    if (!Number.isFinite(seconds)) return '—';
    const sign = seconds < 0 ? '−' : '', value = Math.floor(Math.abs(seconds));
    return `${sign}${Math.floor(value / 3600)}:${String(Math.floor(value / 60) % 60).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  },
};
if (typeof module !== 'undefined') module.exports = TimetableGeometry;

if (typeof window !== 'undefined') (async () => {
  await window.RAIL_MAP_TEMPLATES_READY;
  const templates = window.RailMapTemplates, $svg = $('#diagram');
  const draw = (tag, attrs, text, parent = $svg[0]) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    $(element).attr(attrs || {});
    if (text != null) $(element).text(text);
    $(parent).append(element);
    return element;
  };
  let plan = null, selected = null, live = null, follow = true, center = null, span = 600;
  let planFetchedAt = 0, history = [], lastFrame = null, lastGameTime = null, requestVersion = 0;
  const time = window.RailTime, projection = new time.Clock(), clock = time.localTime;
  const line = () => plan?.lines.find(item => item.line_id === selected);
  const gameTime = () => {
    const value = live?.simulation?.clock?.game_time;
    return typeof value === 'number' ? value / 1000 : null;
  };
  const clearLive = () => { live = null; history = []; lastFrame = null; lastGameTime = null; projection.reset(); };

  function renderCalls(item) {
    const phaseIndex = Number($('#trip-filter').val()) || 0;
    const phase = item.phase_offsets_seconds[phaseIndex] || 0;
    const epoch = item.epoch_game_time_ms / 1000;
    const first = item.stops[0]?.arrival_offset_seconds || 0;
    const cycle = Math.floor(((gameTime() ?? epoch) - epoch - phase - first) / item.cycle_seconds);
    const base = epoch + cycle * item.cycle_seconds + phase;
    $('#planned-calls').empty();
    item.stops.forEach(stop => {
      const row = $('<tr>');
      $('<td>').text(stop.station_name || `站 ${stop.station_group_id}`).appendTo(row);
      [stop.arrival_offset_seconds, stop.departure_offset_seconds].forEach(offset => {
        const wall = projection.prediction(base + offset);
        $('<td>').text(clock(wall)).attr('title', time.localTime(wall, true)).appendTo(row);
      });
      row.appendTo('#planned-calls');
    });
    $('#calls-status').text(`${projection.status()} · 循环计划未绑定具体列车，不作为 ETA 或正晚点依据`);
  }

  function renderDetails(item) {
    const detail = templates.instantiate('timetable-line-detail-template');
    const basis = item.speed_basis || {}, platform = item.platform_feasibility || {};
    const states = {ENABLED: '已启用（本页计划可能尚未应用）', DISABLED: '未启用', UNKNOWN: '未知'};
    const fields = {
      'line-name': item.line_name, 'service-class': {PASSENGER: '客运', FREIGHT: '货运', MIXED: '混合'}[item.service_class] || '未知',
      'schedule-speed': item.speed_class_kmh ?? '未知', 'consist-speed': basis.consist_top_speed_kmh ?? '未知',
      'infrastructure-speed': basis.infrastructure_min_speed_limit_kmh ?? '未知', 'longest-train': platform.longest_assigned_train_m ?? '未知',
      'platform-status': {VERIFIED_FIT: '满足', TOO_SHORT: '过短', UNKNOWN: '待核验'}[platform.status] || '待核验',
      'vehicle-count': item.vehicle_count, 'headway': `${item.headway_seconds} 秒`, 'cycle': `${item.cycle_seconds} 秒`,
      'phase-shift': item.global_phase_shift_seconds, 'conflicts-before': item.station_conflicts_before_shift,
      'conflicts-after': item.station_conflicts_after_shift,
      'time-source': item.source_status?.running_times === 'ENGINE_RAW_SECTION_TIMES_MEDIAN' ? '引擎区间时间中位数（待多趟核验）' : '按周期与距离估算',
      'plan-source': plan.plan_source === 'SAVED_PLAN' ? '已保存计划' : '当前数据只读预览（每分钟更新）',
      'controller-state': states[live?.controller?.state] || '未知',
    };
    Object.entries(fields).forEach(([key, value]) => templates.setText(detail, key, value));
    $('#info').empty().append(detail);
  }

  function render() {
    const item = line();
    $svg.empty();
    if (!item) { $('#planned-calls').empty(); $('#calls-status').text('等待有效线路计划'); return; }
    renderDetails(item);
    renderCalls(item);
    const now = Date.now() / 1000, epoch = item.epoch_game_time_ms / 1000;
    if (center == null || follow) center = now - span * .15;
    const start = center - span / 2, end = start + span;
    const left = 180, right = 1165, top = 50, bottom = 655;
    const x = t => left + (t - start) / span * (right - left);
    const y = index => top + index / item.stops.length * (bottom - top);
    const defs = draw('defs'), clip = draw('clipPath', {id: 'plotclip'}, null, defs);
    draw('rect', {x: left, y: top, width: right - left, height: bottom - top}, null, clip);
    draw('rect', {x: left, y: top, width: right - left, height: bottom - top, fill: '#071019', stroke: '#365269'});
    const tick = Math.max(10, Math.ceil(span / 10 / 10) * 10);
    for (let t = Math.ceil(start / tick) * tick; t <= end; t += tick) {
      draw('line', {x1: x(t), y1: top, x2: x(t), y2: bottom, stroke: '#203243'});
      const label = draw('text', {x: x(t), y: top - 12, class: 'axis-label', 'text-anchor': 'middle'}, clock(t));
      draw('title', {}, time.localTime(t, true), label);
    }
    [...item.stops, item.stops[0]].forEach((stop, index) => {
      draw('line', {x1: left, y1: y(index), x2: right, y2: y(index), stroke: '#294154'});
      const short = stop.platform_fit?.status === 'TOO_SHORT';
      const label = `${stop.station_name || `站 ${stop.station_group_id}`}${index === item.stops.length ? '（下循环）' : ''}${short ? ' ⚠' : ''}`;
      const text = draw('text', {x: left - 10, y: y(index) + 4, class: `station-label${short ? ' short' : ''}`, 'text-anchor': 'end'}, label.length > 17 ? `${label.slice(0, 16)}…` : label);
      draw('title', {}, label, text);
    });
    const canProject = projection.available();
    const [first, last] = canProject ? TimetableGeometry.cycles(item, projection.toGame(start) - epoch, projection.toGame(end) - epoch) : [0, -1];
    const layer = draw('g', {'clip-path': 'url(#plotclip)'});
    for (let cycle = first; cycle <= last; cycle++) {
      item.phase_offsets_seconds.forEach((phase, index) => {
        const points = TimetableGeometry.points(item, epoch + cycle * item.cycle_seconds + phase);
        const path = draw('path', {d: points.map(([t, row], i) => `${i ? 'L' : 'M'}${x(projection.toWall(t))},${y(row)}`).join(' '), class: 'plan-path'}, null, layer);
        draw('title', {}, `计划班次 ${index + 1} · 未绑定具体车辆\n首站计划 ${time.localTime(projection.toWall(points[0][0]), true)}`, path);
      });
    }
    const filter = $('#vehicle-filter').val();
    const filteredVehicle = filter ? (live?.vehicles || []).find(vehicle => String(vehicle.entity_id) === filter) : null;
    if (filteredVehicle) {
      const prediction = filteredVehicle.timetable || {}, status = prediction.punctuality === 'ON_TIME' ? '预计正点'
        : prediction.punctuality === 'LATE' && Number.isFinite(prediction.delay_seconds)
          ? `预计晚点 ${Math.floor(prediction.delay_seconds / 60)} 分 ${Math.round(prediction.delay_seconds % 60)} 秒` : '晚点未定';
      $('#calls-status').text(`${filteredVehicle.name || `列车 ${filteredVehicle.entity_id}`} · 计划到达 ${time.localTime(prediction.scheduled_arrival_at, true)} · 预计到达 ${time.localTime(prediction.estimated_arrival_at, true)} · ${status}`);
    }
    history.filter(point => point.wall >= start && point.wall <= end && (!filter || String(point.id) === filter)).forEach(point => {
      // Join consecutive station observations only, never unobserved travel.
      if (point.previousWall != null && point.previousWall >= start) draw('line', {x1: x(point.previousWall), y1: y(point.stop), x2: x(point.wall), y2: y(point.stop), class: 'observed', 'stroke-width': 3}, null, layer);
      const dot = draw('circle', {cx: x(point.wall), cy: y(point.stop), r: 3, class: 'observed'}, null, layer);
      const prediction = point.timetable || {};
      const punctuality = prediction.punctuality === 'ON_TIME' ? '预计正点' : prediction.punctuality === 'LATE' && Number.isFinite(prediction.delay_seconds)
        ? `预计晚点 ${Math.floor(prediction.delay_seconds / 60)} 分 ${Math.round(prediction.delay_seconds % 60)} 秒` : '晚点未定';
      draw('title', {}, `${point.name} · ID ${point.id}\n${item.stops[point.stop].station_name}\n站内实测 ${time.localTime(point.wall, true)}\n计划到达 ${time.localTime(prediction.scheduled_arrival_at, true)}\n${punctuality}`, dot);
    });
    if (now != null && now >= start && now <= end) {
      draw('line', {x1: x(now), y1: top, x2: x(now), y2: bottom, class: 'now-line'});
      draw('text', {x: x(now), y: bottom + 24, fill: '#ffe06c', 'text-anchor': 'middle', 'font-size': 12}, `现在 ${clock(now)}`);
    }
    $('#follow-time').attr('aria-pressed', String(follow)).text(follow ? '跟随系统时间' : '视窗已固定');
    const sim = {RUNNING: '运行中', RUNNING_INFERRED: '运行中', PAUSED: '已暂停', PAUSED_OR_STALLED: '暂停或停滞'}[live?.simulation?.status] || '状态未知';
    $('#connection-status').text(time.fresh(live) ? `游戏${sim} · 只读预览` : '实时数据不可用');
    $('#chart-status').text(`系统时间（${time.zone()}）· ${Math.round(span / 60)} 分钟视窗 · ${projection.status()} · ${history.length} 个站内观测点`);
  }

  function recordFrame(value) {
    const item = line(), now = gameTime();
    if (!item || !value.fresh || now == null) { lastFrame = null; return; }
    if (lastGameTime != null && now < lastGameTime) { history = []; lastFrame = null; }
    if (lastFrame?.sampled_at === value.sampled_at) return;
    history.push(...TimetableGeometry.stationPoints(value, lastFrame, item.stops.length));
    history = history.filter(point => point.time >= now - 7200).slice(-12000);
    lastFrame = value; lastGameTime = now;
    const filter = $('#vehicle-filter').val();
    $('#vehicle-filter').empty().append($('<option>').val('').text('全部车辆'));
    const names = new Map(history.map(point => [point.id, point.name]));
    value.vehicles.forEach(vehicle => names.set(vehicle.entity_id, vehicle.name || `列车 ${vehicle.entity_id}`));
    names.forEach((name, id) => $('#vehicle-filter').append($('<option>').val(String(id)).text(`${name} · ${id}`)));
    if (names.has(Number(filter))) $('#vehicle-filter').val(filter);
  }

  async function refreshPlan() {
    const value = await $.ajax({url: '/api/timetable-plan', dataType: 'json', cache: false});
    if (value.schema_version < 3) throw new Error('服务仍在使用旧版运行图，请重启 UI 服务');
    const old = line(), sameSave = plan?.save_id === value.save_id;
    plan = value;
    if (!sameSave) { clearLive(); center = null; }
    if (!plan.lines.some(item => item.line_id === selected)) selected = plan.lines[0]?.line_id ?? null;
    const item = line();
    const selectedTrip = $('#trip-filter').val();
    $('#trip-filter').empty();
    (item?.phase_offsets_seconds || []).forEach((phase, index) => $('#trip-filter').append($('<option>').val(String(index)).text(`计划班次 ${index + 1}`)));
    if (sameSave && old?.line_id === item?.line_id && Number(selectedTrip) < (item?.phase_offsets_seconds.length || 0)) $('#trip-filter').val(selectedTrip);
    if (old && item && JSON.stringify(old.stops.map(stop => stop.station_group_id)) !== JSON.stringify(item.stops.map(stop => stop.station_group_id))) clearLive();
    const summary = templates.instantiate('timetable-summary-template');
    templates.setText(summary, 'planned-lines', plan.counts.planned_lines);
    templates.setText(summary, 'conflicts-removed', plan.global_conflict_plan.conflicts_removed);
    $('#summary').empty().append(summary); $('#lines').empty();
    plan.lines.forEach(item => {
      const row = templates.instantiate('timetable-line-row-template');
      templates.setText(row, 'line-name', item.line_name);
      templates.setText(row, 'summary', `${item.vehicle_count} 组车 · 间隔 ${item.headway_seconds} 秒`);
      $(row).toggleClass('active', item.line_id === selected).on('click', () => {
        selected = item.line_id; clearLive(); center = null; span = Math.min(7200, Math.max(120, item.cycle_seconds));
        $('#trip-filter').empty();
        item.phase_offsets_seconds.forEach((phase, index) => $('#trip-filter').append($('<option>').val(String(index)).text(`计划班次 ${index + 1}`)));
        $('#lines .line').removeClass('active'); $(row).addClass('active'); requestVersion++; render();
      });
      $('#lines').append(row);
    });
    if (!item) { $('#info').text('当前没有满足条件的线路：需要两站、已分配车辆和有效班次间隔。'); $('#chart-status').text('等待有效线路数据'); }
    if (item && !old) span = Math.min(7200, Math.max(120, item.cycle_seconds));
    planFetchedAt = Date.now();
  }

  $('#vehicle-filter').on('change', render);
  $('#trip-filter').on('change', render);
  $('#follow-time').on('click', () => { follow = !follow; render(); });
  $('#earlier, #later').on('click', function () { follow = false; center = (center ?? 0) + (this.id === 'earlier' ? -1 : 1) * span / 2; render(); });
  $('#zoom-in, #zoom-out').on('click', function () { span = Math.max(60, Math.min(7200, span * (this.id === 'zoom-in' ? .5 : 2))); render(); });

  async function poll() {
    try {
      if (!plan || Date.now() - planFetchedAt > 30000) await refreshPlan();
      if (selected != null) {
        const version = requestVersion, id = selected;
        const value = await $.ajax({url: '/api/timetable-live', data: {line_id: id}, dataType: 'json', cache: false});
        if (version !== requestVersion || id !== selected) return;
        if (value.save_id !== plan.save_id) { plan = null; clearLive(); $svg.empty(); $('#info').text('存档已切换，正在重新读取计划…'); return; }
        live = value; projection.update(value); recordFrame(value);
      }
      render();
    } catch (error) {
      live = null; lastFrame = null; projection.update(null);
      if (error.status === 409) { plan = null; history = []; $svg.empty(); }
      render();
      $('#connection-status').text('数据暂不可用，将自动重试');
      $('#chart-status').text(error.responseJSON?.error || error.message || '请检查游戏与 Bridge 连接');
    } finally { window.setTimeout(poll, 2000); }
  }
  const systemClock = () => $('#system-clock').text(`${time.localTime(Date.now() / 1000, true)} · ${time.zone()}`);
  systemClock(); window.setInterval(systemClock, 1000);
  await poll();
})().catch(error => { $('#info').text(`运行图载入失败：${error.message || error}`); });
