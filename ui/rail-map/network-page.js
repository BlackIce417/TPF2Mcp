(() => {
  let noticeTimer = null;
  window.showRailMapNotice = message => {
    const $notice = $('#map-notice');
    window.clearTimeout(noticeTimer);
    $notice.text(message).addClass('visible');
    noticeTimer = window.setTimeout(() => $notice.removeClass('visible'), 2400);
  };

  document.querySelector('#timetable-view')?.addEventListener('click', () => {
    location.href = 'timetable.html';
  });

  const bridgeLamp = document.querySelector('#bridge-lamp');
  const liveLamp = document.querySelector('#live-lamp');
  const setLamp = (lamp, state, detail) => {
    if (!lamp) return;
    lamp.classList.remove('green', 'amber', 'red');
    lamp.classList.add(state);
    lamp.title = detail;
  };
  const applyStatus = status => {
    const bridgeConnected = status.bridge_connected === true;
    const heartbeatAge = Number(status.heartbeat_age_seconds);
    setLamp(
      bridgeLamp,
      bridgeConnected ? 'green' : 'red',
      bridgeConnected
        ? `Bridge 在线 · 心跳 ${heartbeatAge.toFixed(1)} 秒前`
        : `Bridge 离线 · ${Number.isFinite(heartbeatAge) ? `心跳已中断 ${heartbeatAge.toFixed(1)} 秒` : '无心跳'}`,
    );

    const liveGeneration = Number(status.live_generation);
    const liveAge = Number.isFinite(liveGeneration) ? Math.max(0, Date.now() / 1000 - liveGeneration) : Infinity;
    const liveError = String(status.live_error || '');
    let liveState = 'red';
    let liveDetail = '动态遥测不可用';
    if (bridgeConnected && Number.isFinite(liveGeneration)) {
      if (liveAge < 15 && !liveError) {
        liveState = 'green';
        liveDetail = `动态遥测正常 · ${liveAge.toFixed(1)} 秒前更新`;
      } else if (liveAge < 30) {
        liveState = 'amber';
        liveDetail = liveError
          ? `动态遥测降级 · ${liveError}`
          : `动态遥测延迟 · ${liveAge.toFixed(1)} 秒前更新`;
      } else {
        liveDetail = `动态遥测中断 · ${liveAge.toFixed(1)} 秒未更新`;
      }
    } else if (!bridgeConnected) {
      liveDetail = '动态遥测不可用 · Bridge 离线';
    }
    setLamp(liveLamp, liveState, liveDetail);
  };
  const publishStatus = status => {
    window.RAIL_MAP_STATUS = status;
    applyStatus(status);
    window.dispatchEvent(new CustomEvent('rail-map-status', { detail: status }));
  };

  const staticLocalPreview = new URLSearchParams(window.location.search).get('view') === 'local';
  if (staticLocalPreview) {
    setLamp(bridgeLamp, 'amber', '局部页使用已生成的静态 Bridge 拓扑缓存');
    setLamp(liveLamp, 'amber', '局部页不订阅动态遥测');
  } else if ((location.protocol === 'http:' || location.protocol === 'https:') && window.EventSource) {
    const events = new EventSource('/api/events');
    events.addEventListener('status', event => {
      try {
        publishStatus(JSON.parse(event.data));
      } catch (error) {
        setLamp(bridgeLamp, 'red', `Bridge 状态解析失败 · ${error.message}`);
        setLamp(liveLamp, 'red', '动态遥测状态未知');
      }
    });
    events.addEventListener('error', () => {
      setLamp(bridgeLamp, 'red', 'Bridge 状态流断开');
      setLamp(liveLamp, 'red', '动态遥测状态流断开');
    });
  } else {
    setLamp(bridgeLamp, 'amber', '需要通过本机 HTTP 服务检查 Bridge');
    setLamp(liveLamp, 'amber', '需要通过本机 HTTP 服务检查动态遥测');
  }
})();
