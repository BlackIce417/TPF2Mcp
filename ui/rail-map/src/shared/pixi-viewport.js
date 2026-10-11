const VIEW_WIDTH = 1200;
const VIEW_HEIGHT = 720;
const NUMBER = '([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)';
const CUBIC_SEGMENT = new RegExp(`M${NUMBER},${NUMBER}C${NUMBER},${NUMBER} ${NUMBER},${NUMBER} ${NUMBER},${NUMBER}`, 'g');

export function createPixiViewport(pixi, host, before, canvasId) {
  if (!pixi) return null;
  try {
    const app = new pixi.Application({
      resizeTo: host,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      powerPreference: 'high-performance',
    });
    const world = new pixi.Container();
    app.view.id = canvasId;
    app.view.setAttribute('aria-hidden', 'true');
    app.stage.addChild(world);
    host.insertBefore(app.view, before);

    let state = {zoom: 1, panX: 0, panY: 0};
    const sync = ({zoom, panX, panY}) => {
      state = {zoom, panX, panY};
      const bounds = host.getBoundingClientRect();
      const scale = Math.min(bounds.width / VIEW_WIDTH, bounds.height / VIEW_HEIGHT);
      const offsetX = (bounds.width - VIEW_WIDTH * scale) / 2;
      const offsetY = (bounds.height - VIEW_HEIGHT * scale) / 2;
      world.scale.set(scale * zoom);
      world.position.set(
        offsetX + scale * (600 + panX - 600 * zoom),
        offsetY + scale * (360 + panY - 360 * zoom),
      );
    };
    const resizeObserver = new ResizeObserver(() => sync(state));
    resizeObserver.observe(host);
    sync(state);
    return {app, world, sync, resizeObserver};
  } catch (error) {
    console.error('PixiJS WebGL renderer unavailable', error);
    return null;
  }
}

export function drawSvgCubicPath(graphics, source) {
  let count = 0;
  for (const match of source.matchAll(CUBIC_SEGMENT)) {
    const values = match.slice(1).map(Number);
    graphics.moveTo(values[0], values[1]);
    graphics.bezierCurveTo(values[2], values[3], values[4], values[5], values[6], values[7]);
    count += 1;
  }
  if (!count) throw new Error('Region path contains no supported cubic segments');
  return count;
}
