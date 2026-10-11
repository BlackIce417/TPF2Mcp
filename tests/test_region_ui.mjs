// Browser integration checks using a dedicated local Chromium CDP instance.
// Start with a repository-owned profile; no third-party JS dependencies required.
import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'diagnostics', 'region-ui');
await mkdir(output, {recursive: true});
const base = process.env.REGION_UI_BASE || 'http://127.0.0.1:5173';
const target = await (await fetch('http://127.0.0.1:9234/json/new?about:blank', {method: 'PUT'})).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let next = 0;
const pending = new Map(), errors = [];
let fakeScope = null;
socket.onmessage = ({data}) => {
  const message = JSON.parse(data);
  if (message.id) {
    const request = pending.get(message.id);
    if (request) { pending.delete(message.id); clearTimeout(request.timer); message.error ? request.reject(message.error) : request.resolve(message.result); }
  } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
  else if (message.method === 'Fetch.requestPaused') {
    const requestId = message.params.requestId;
    if (fakeScope) send('Fetch.fulfillRequest', {requestId, responseCode: 200,
      responseHeaders: [{name: 'Content-Type', value: 'application/json'}], body: Buffer.from(JSON.stringify(fakeScope)).toString('base64')});
    else send('Fetch.continueRequest', {requestId});
  }
};
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++next;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const value = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
  return value.result.value;
}
async function until(expression) {
  const deadline = Date.now()+25000;
  while (Date.now()<deadline) { if (await evaluate(expression)) return; await new Promise(r => setTimeout(r, 150)); }
  throw new Error(`UI timeout: ${expression}`);
}
async function screenshot(name) {
  const result = await send('Page.captureScreenshot', {format: 'png'});
  await writeFile(path.join(output, name), Buffer.from(result.data, 'base64'));
}
try {
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false});
  await send('Page.navigate', {url: `${base}/regions.html`});
  await until("document.querySelectorAll('.region-card').length === 3 && document.getElementById('region-message').hidden");
  if (!process.env.REGION_UI_SKIP_RUNTIME) {
    await until("document.getElementById('regional-runtime')?.textContent.includes('影子运行')");
    assert.ok(await evaluate("document.getElementById('regional-runtime').textContent.includes('20401/20401')"));
  }
  assert.deepEqual(await evaluate("[Number(document.getElementById('board').dataset.regionCount),document.querySelectorAll('.region-network-territory').length,document.querySelectorAll('.region-station').length,document.querySelectorAll('.region-anchor').length]"), [3,3,86,16]);
  assert.deepEqual(await evaluate("[document.querySelectorAll('#board path.region-network-base').length,document.getElementById('board').dataset.renderer,document.getElementById('region-webgl')!==null,Number(document.getElementById('board').dataset.segmentCount)>0]"), [0,'region-overview-and-network-tiles',true,true]);
  assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('nav button')).map(b=>b.textContent)"), ['站场图','运行图','调度区']);
  await screenshot('overview.png');
  const board = await evaluate("(()=>{const r=document.getElementById('board').getBoundingClientRect();return {x:r.x+r.width*.48,y:r.y+r.height*.48}})()");
  const transformBeforeDrag = await evaluate("document.getElementById('region-world').getAttribute('transform')");
  const dragStarted = Date.now();
  await send('Input.dispatchMouseEvent', {type: 'mousePressed', x: board.x, y: board.y, button: 'left', clickCount: 1});
  for (let step = 1; step <= 24; step += 1) {
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: board.x + step * 5, y: board.y + step * 2, button: 'left', buttons: 1});
  }
  await send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: board.x + 120, y: board.y + 48, button: 'left', clickCount: 1});
  await until(`document.getElementById('region-world').getAttribute('transform') !== ${JSON.stringify(transformBeforeDrag)}`);
  const dragMs = Date.now() - dragStarted;
  await evaluate("document.getElementById('zoom-reset').click(); for(let i=0;i<6;i+=1) document.getElementById('zoom-in').click()");
  await until("Number(document.getElementById('board').dataset.detailTileCount)>0");
  await until("Array.from(document.querySelectorAll('.region-network-territory')).every(path=>path.style.display==='none')");
  await until("document.querySelectorAll('#region-bridge-layer [data-bridge-role=\"bridge-deck-mask\"]').length>0");
  assert.ok(await evaluate("document.querySelectorAll('#region-bridge-layer [data-bridge-role=\"upper-track\"]').length>0"));
  assert.ok(await evaluate("Array.from(document.querySelectorAll('#region-bridge-layer [data-bridge-role=\"upper-track\"]')).every(path=>/^#[0-9a-f]{6}$/i.test(path.getAttribute('stroke')))"));
  await screenshot('detail-tiles.png');
  await evaluate("document.getElementById('zoom-reset').click()");
  const checks = [];
  for (const [region, count] of [['HK',40],['WC',28],['WH',18]]) {
    await evaluate(`document.querySelector('.region-card[data-region="${region}"]').click()`);
    const state = await evaluate("({selected:document.getElementById('board').dataset.selectedRegion,dim:Number(document.getElementById('board').dataset.dimmedRegionCount),stations:document.querySelectorAll('.region-stations button').length,url:location.search})");
    assert.equal(state.selected, region); assert.equal(state.dim,2); assert.equal(state.stations,count); assert.ok(state.url.includes(region)); checks.push(state);
  }
  await screenshot('wuhan-selected.png');
  await evaluate("document.querySelector('.region-stations button').click()");
  assert.equal(await evaluate("document.querySelectorAll('.region-station.is-focused').length"),1);
  assert.ok(await evaluate("document.querySelector('#region-details a').href.includes('local.html?view=local&station=')"));
  await evaluate("document.querySelector('.region-boundaries button').click()");
  assert.ok(await evaluate("document.getElementById('region-message').textContent.includes('待校准')"));
  await evaluate("document.getElementById('show-boundaries').click()");
  assert.equal(await evaluate("Array.from(document.querySelectorAll('.region-anchor')).filter(n=>n.style.display==='none').length"),16);
  await evaluate("document.getElementById('all-regions').click()");
  assert.equal(await evaluate("Number(document.getElementById('board').dataset.dimmedRegionCount)"),0);
  await send('Page.navigate', {url: `${base}/regions.html?region=WC`});
  await until("document.getElementById('board')?.dataset.selectedRegion === 'WC'");
  await screenshot('wuchang-selected.png');
  const performance = await evaluate("({readyMs:performance.now(),resources:performance.getEntriesByType('resource').map(r=>r.name),renderer:document.getElementById('board').dataset.renderer})");
  performance.dragMs = dragMs;
  assert.ok(!performance.resources.some(url=>url.includes('/api/live')));

  // Simulate current-save mismatch and topology change without touching game files.
  const actual = await (await fetch(`${base}/api/status`)).json();
  await send('Fetch.enable', {patterns: [{urlPattern: '*/api/status'}]});
  fakeScope = {...actual, save_id: 'other-save'};
  await evaluate("document.getElementById('reload-regions').click()");
  await until("document.getElementById('region-message').textContent.includes('存档已变化')");
  assert.equal(await evaluate("Number(document.getElementById('board').dataset.regionCount)"),0);
  fakeScope = {...actual, rail_generation: actual.rail_generation+1};
  await evaluate("document.getElementById('reload-regions').click()");
  await until("document.getElementById('region-message').textContent.includes('路网已更新')");
  assert.equal(await evaluate("document.querySelectorAll('.region-card').length"),0);
  fakeScope = null; await send('Fetch.disable');
  await evaluate("document.getElementById('reload-regions').click()");
  await until("document.querySelectorAll('.region-card').length === 3");
  assert.equal(errors.length,0,JSON.stringify(errors));

  for (const url of ['index.html?view=network','timetable.html','local.html?view=local&station=31005']) {
    await send('Page.navigate', {url:`${base}/${url}`});
    await until(`location.pathname === ${JSON.stringify('/'+url.split('?')[0])} && document.querySelectorAll('nav button[data-nav]').length === 3 && document.readyState === 'complete'`);
    if (url.startsWith('index.html')) await until("document.getElementById('rail-webgl') !== null");
    assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('nav button')).map(b=>b.textContent)"), ['站场图','运行图','调度区']);
    await evaluate("document.querySelector('nav button[data-nav=\"regions.html\"]').click()");
    await until("location.pathname === '/regions.html' && document.querySelectorAll('.region-card').length === 3");
  }
  assert.equal(errors.length,0,JSON.stringify(errors));
  await writeFile(path.join(output, 'checks.json'), JSON.stringify({checks, performance, errors},null,2));
  console.log(JSON.stringify({passed:true,checks,screenshots:['overview.png','detail-tiles.png','wuhan-selected.png','wuchang-selected.png'],regionPageExceptions:errors.length}));
} catch (error) {
  await screenshot('failure.png');
  console.error(await evaluate("({url:location.href,state:document.readyState,message:document.getElementById('region-message')?.textContent})"));
  throw error;
} finally {
  await fetch(`http://127.0.0.1:9234/json/close/${target.id}`);
  socket.close();
}
