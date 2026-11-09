import '../../shared/navigation.js';
import '../../shared/rail-time.js';
import '../../shared/control-ui.js';
import '../../shared/template-runtime.js';
import './bridge-crossings.js';
import {getJson} from '../../shared/http.js';
import {bindRailRefresh} from '../../shared/rail-refresh.js';
bindRailRefresh(document.getElementById('rail-network-refresh'),{
  onComplete:()=>location.reload(),
  onStatus:text=>{const notice=document.getElementById('map-notice');notice.textContent=text;notice.hidden=false;notice.classList.add('visible');},
});

try {
  window.RAIL_NETWORK_DATA = await getJson('/api/rail/manifest', {attempts: 3});
} catch (error) {
  console.error('Unable to load the rail network manifest', error);
  window.RAIL_NETWORK_DATA = null;
}

const localView = new URLSearchParams(window.location.search).get('view') === 'local';
if (!localView) await import('./overview-map.js');
await import('./local-map.js');
await import('./page-controller.js');
