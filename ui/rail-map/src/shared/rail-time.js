/* Shared local-time projection. Simulation seconds stay separate from Unix seconds. */
(function (root) {
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const running = status => status === 'RUNNING' || status === 'RUNNING_INFERRED';
  const paused = status => status === 'PAUSED' || status === 'PAUSED_OR_STALLED';
  const fresh = (frame, now = Date.now() / 1000) => frame?.fresh !== false &&
    finite(frame?.sampled_at) && now - frame.sampled_at >= -5 && now - frame.sampled_at <= 15;
  const localTime = (seconds, date = false) => {
    if (!finite(seconds)) return '—';
    return new Date(seconds * 1000).toLocaleString('zh-CN', {
      ...(date ? {year: 'numeric', month: '2-digit', day: '2-digit'} : {}),
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    });
  };
  const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
  class Clock {
    constructor() { this.reset(); }
    reset() { this.frame = null; this.anchor = null; this.save = null; }
    update(frame) {
      const game = frame?.simulation?.clock?.game_time;
      if (this.save !== frame?.save_id || (finite(game) && this.anchor && game / 1000 < this.anchor.game)) this.reset();
      this.save = frame?.save_id;
      this.frame = frame;
      const rate = frame?.simulation?.speed_multiplier;
      if (!fresh(frame) || !finite(game) || !finite(rate) || rate <= 0 || !running(frame?.simulation?.status)) return;
      this.anchor = {game: game / 1000, wall: frame.sampled_at, rate};
    }
    available(now) { return fresh(this.frame, now) && running(this.frame?.simulation?.status) &&
      finite(this.frame?.simulation?.speed_multiplier) && this.frame.simulation.speed_multiplier > 0 &&
      finite(this.frame?.simulation?.clock?.game_time) && !!this.anchor && this.anchor.wall === this.frame.sampled_at; }
    toWall(game) { return this.anchor && finite(game) ? this.anchor.wall + (game - this.anchor.game) / this.anchor.rate : null; }
    toGame(wall) { return this.anchor && finite(wall) ? this.anchor.game + (wall - this.anchor.wall) * this.anchor.rate : null; }
    prediction(game, now) { return this.available(now) ? this.toWall(game) : null; }
    status(now) {
      if (!fresh(this.frame, now)) return '数据已过期，时刻换算暂停';
      if (paused(this.frame?.simulation?.status)) return '游戏已暂停，恢复后重算未来时刻';
      if (!this.available(now)) return '运行状态未知，无法换算时刻';
      return `按当前 ${this.anchor.rate}× 倍速换算`;
    }
  }
  const motion = (vehicle, frame, now) => {
    if (!fresh(frame, now) || vehicle?.position_stale) return '运行信息未更新';
    if (paused(frame?.simulation?.status)) return '游戏已暂停';
    if (!running(frame?.simulation?.status)) return '运行状态未知';
    if (vehicle?.raw_state === 2) return '站内停靠';
    if (!finite(vehicle?.speed_kmh)) return '速度未知';
    return vehicle.speed_kmh < 1 ? '等待／停车' : '区间运行';
  };
  const api = {Clock, fresh, localTime, zone, motion};
  if (typeof module !== 'undefined') module.exports = api;
  else root.RailTime = api;
})(typeof window === 'undefined' ? globalThis : window);
