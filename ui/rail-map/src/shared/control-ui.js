(() => {
  const $badge = $('#control-system-state');
  const $stop = $('#control-system-stop');
  const $popover = $('#control-system-popover');
  if (!$badge.length || !$stop.length || !$popover.length) return;

  const text = value => String(value ?? '—');
  const render = value => {
    const config = value.config || {};
    const state = value.state || {};
    const leases = value.leases?.leases || [];
    const runtime = value.runtime || {};
    const lifecycle = text(state.lifecycle || config.mode || 'UNKNOWN');
    $badge.text(`控制：${lifecycle}`).attr('data-lifecycle', lifecycle);
    $stop.prop('disabled', config.mode === 'DISABLED');
    const failed = Object.entries(state.health?.checks || {}).filter(([, ok]) => ok !== true).map(([name]) => name);
    const actions = (state.actions || []).slice(-5);
    const events = (value.events || []).slice(0, 5);
    const $leaseList = $('<ul>');
    (leases.length ? leases : [{kind: '无活动租约'}]).slice(0, 8).forEach(item => {
      $('<li>').text(`${text(item.kind)}${item.vehicle_id != null ? ` · 车辆 ${item.vehicle_id}` : ''}${item.source_line != null ? ` · ${item.source_line}→${item.target_line}` : ''}`).appendTo($leaseList);
    });
    $popover.empty()
      .append($('<strong>').text(`${text(config.mode)} / ${lifecycle}`))
      .append($('<p>').text(`租约 ${leases.length} · 连续失败 ${state.consecutive_failures || 0} · ${state.trip_reason || (failed.length ? `门禁：${failed.join(', ')}` : '健康')}`))
      .append($('<p>').text(`需求扫描待处理 ${runtime.demand_pending_lines || 0} 条 · 原生模块 ${text(runtime.native_supervisor?.supervisor_state)}`))
      .append($('<p>').text(`寻路惩罚 ${state.native_counters?.path_penalties || 0} 次 · 命中边 ${state.native_counters?.path_edge_matches || 0} 次`))
      .append($leaseList)
      .append($('<p>').text(`最近动作：${actions.map(item => item.kind).join('、') || events.map(item => item.kind).join('、') || '无'}`));
  };
  const refresh = async () => {
    try {
      render(await $.ajax({url: '/api/control-system', cache: false, dataType: 'json'}));
    } catch (error) {
      $badge.text('控制：不可用').attr({'data-lifecycle': 'DEGRADED', title: error.statusText || error.message});
    }
  };
  $badge.on('click', () => {
    const hidden = !$popover.prop('hidden');
    $popover.prop('hidden', hidden);
    $badge.attr('aria-expanded', String(!hidden));
  });
  $stop.on('click', async () => {
    $stop.prop('disabled', true);
    try {
      render(await $.ajax({
        url: '/api/control-system/stop', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({reason: 'UI_EMERGENCY_STOP'}), dataType: 'json',
      }));
    } catch (error) {
      $badge.attr('title', `停用失败：${error.responseJSON?.reason || error.statusText || error.message}`);
    } finally {
      await refresh();
    }
  });
  refresh();
  window.setInterval(refresh, 5000);
})();
