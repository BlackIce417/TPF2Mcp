import {getJson} from './http.js';

export function bindRailRefresh(button, {onComplete, onStatus}) {
  if (!button) return;
  const label=button.textContent;
  button.addEventListener('click',async()=>{
    if(button.disabled)return;
    button.disabled=true;button.setAttribute('aria-busy','true');window.RAIL_REFRESH_PENDING=true;
    const show=text=>{button.textContent=text;onStatus?.(text);};
    show('正在连接游戏…');
    try{
      const response=await fetch('/api/rail/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw Error('无法开始刷新，请确认本地服务已启动。');
      let job=await response.json();const deadline=Date.now()+300000;
      while(!['SUCCEEDED','FAILED'].includes(job.status)){
        show(({QUEUED:'等待刷新…',COLLECTING:'正在采集路网…',BUILDING:'正在更新地图…'})[job.status]||'正在刷新…');
        if(Date.now()>deadline)throw Error('刷新耗时较长，请稍后重试。');
        await new Promise(resolve=>setTimeout(resolve,500));
        job=await getJson('/api/rail/refresh',{timeoutMs:10000});
      }
      if(job.status==='FAILED')throw Error(job.error||'刷新失败，请重试。');
      show('路网已更新');await onComplete?.(job);
    }catch(error){onStatus?.(`刷新失败：${error.message}`);}
    finally{window.RAIL_REFRESH_PENDING=false;button.disabled=false;button.removeAttribute('aria-busy');button.textContent=label;}
  });
}
