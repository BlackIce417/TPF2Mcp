(async () => {
  await window.RAIL_MAP_TEMPLATES_READY;
  const templates = window.RailMapTemplates;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.querySelector('#diagram');
  const list = document.querySelector('#lines');
  const info = document.querySelector('#info');
  const S = (tag, attrs, text, parent = svg) => {
    const element = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => element.setAttribute(key, value));
    if (text != null) element.textContent = text;
    parent.appendChild(element);
    return element;
  };
  const fmt = value => {
    const seconds = Math.round(value);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const plan = await fetch('/api/timetable-plan', {cache: 'no-store'}).then(response => {
    if (!response.ok) throw new Error(response.status);
    return response.json();
  });

  const summary = templates.instantiate('timetable-summary-template');
  templates.setText(summary, 'planned-lines', plan.counts.planned_lines);
  templates.setText(summary, 'conflicts-removed', plan.global_conflict_plan.conflicts_removed);
  document.querySelector('#summary').replaceChildren(summary);

  const render = line => {
    svg.replaceChildren();
    document.querySelectorAll('.line').forEach(element => {
      element.classList.toggle('active', Number(element.dataset.id) === line.line_id);
    });
    const left = 150;
    const right = 1160;
    const top = 70;
    const bottom = 660;
    const cycle = line.cycle_seconds;
    const stops = line.stops;
    const stopIntervals = Math.max(1, stops.length - 1);
    const x = time => left + (time / cycle) * (right - left);
    const y = index => top + index * (bottom - top) / stopIntervals;

    S('rect', {x: left, y: top, width: right - left, height: bottom - top, fill: '#071019', stroke: '#365269'});
    for (let time = 0; time <= cycle; time += Math.max(30, Math.ceil(cycle / 12 / 30) * 30)) {
      S('line', {x1: x(time), y1: top, x2: x(time), y2: bottom, stroke: '#17293a'});
      S('text', {x: x(time), y: top - 12, fill: '#7890a4', 'font-size': 10, 'text-anchor': 'middle', 'font-family': 'Consolas'}, fmt(time));
    }
    stops.forEach((stop, index) => {
      const fit = stop.platform_fit?.status;
      S('line', {x1: left, y1: y(index), x2: right, y2: y(index), stroke: fit === 'TOO_SHORT' ? '#8f3f45' : '#294154'});
      S('text', {x: left - 10, y: y(index) + 4, fill: fit === 'TOO_SHORT' ? '#ff8d95' : '#c8f3ff', 'font-size': 11, 'text-anchor': 'end'}, `${stop.station_name || `站 ${stop.station_group_id}`}${fit === 'TOO_SHORT' ? ' ⚠' : ''}`);
    });
    const colors = ['#42dcff', '#ffe06c', '#6dffa7', '#ff7f9d', '#b89bff', '#ffad66'];
    line.phase_offsets_seconds.forEach((phase, phaseIndex) => {
      for (const base of [phase - cycle, phase, phase + cycle]) {
        let path = '';
        stops.forEach((stop, index) => {
          const arrival = base + stop.arrival_offset_seconds;
          const departure = base + stop.departure_offset_seconds;
          path += `${index ? 'L' : 'M'}${x(arrival)},${y(index)} L${x(departure)},${y(index)} `;
          if (index < stops.length - 1) path += `L${x(departure + stop.next_leg_running_seconds)},${y(index + 1)} `;
        });
        S('path', {d: path, fill: 'none', stroke: colors[phaseIndex % colors.length], 'stroke-width': 2.2, 'clip-path': 'url(#plotclip)', opacity: .9});
      }
    });
    const defs = S('defs', {});
    const clip = S('clipPath', {id: 'plotclip'}, null, defs);
    S('rect', {x: left, y: top, width: right - left, height: bottom - top}, null, clip);
    svg.insertBefore(defs, svg.firstChild);

    const basis = line.speed_basis || {};
    const platform = line.platform_feasibility || {};
    const detail = templates.instantiate('timetable-line-detail-template');
    templates.setText(detail, 'line-name', line.line_name);
    templates.setText(detail, 'service-class', line.service_class);
    templates.setText(detail, 'schedule-speed', line.speed_class_kmh ?? 'UNKNOWN');
    templates.setText(detail, 'consist-speed', basis.consist_top_speed_kmh ?? '待采');
    templates.setText(detail, 'infrastructure-speed', basis.infrastructure_min_speed_limit_kmh ?? '待采');
    templates.setText(detail, 'longest-train', platform.longest_assigned_train_m ?? '待采');
    const platformStatus = templates.setText(detail, 'platform-status', platform.status ?? 'UNKNOWN');
    platformStatus.classList.add(platform.status === 'VERIFIED_FIT' ? 'ok' : 'warn');
    templates.setText(detail, 'vehicle-count', line.vehicle_count);
    templates.setText(detail, 'headway', fmt(line.headway_seconds));
    templates.setText(detail, 'cycle', fmt(cycle));
    templates.setText(detail, 'phase-shift', line.global_phase_shift_seconds);
    templates.setText(detail, 'conflicts-before', line.station_conflicts_before_shift);
    templates.setText(detail, 'conflicts-after', line.station_conflicts_after_shift);
    info.replaceChildren(detail);
  };

  plan.lines.forEach((line, index) => {
    const row = templates.instantiate('timetable-line-row-template');
    row.dataset.id = line.line_id;
    templates.setText(row, 'line-name', line.line_name);
    templates.setText(row, 'summary', `${line.service_class} · ${line.speed_class_kmh ?? '—'} km/h · ${line.vehicle_count}车 · ${fmt(line.headway_seconds)}`);
    row.addEventListener('click', () => render(line));
    list.appendChild(row);
    if (index === 0) render(line);
  });
})().catch(error => {
  console.error(error);
  const info = document.querySelector('#info');
  const templates = window.RailMapTemplates;
  try {
    const message = templates.instantiate('timetable-error-template');
    templates.setText(message, 'message', error.message || error);
    info.replaceChildren(message);
  } catch {
    info.textContent = `运行图载入失败：${error.message || error}`;
    info.classList.add('warn');
  }
});
