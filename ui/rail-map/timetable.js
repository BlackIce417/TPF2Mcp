(async()=>{
 const NS='http://www.w3.org/2000/svg',svg=document.querySelector('#diagram'),list=document.querySelector('#lines'),info=document.querySelector('#info');
 const S=(tag,attrs,text,parent=svg)=>{const e=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>e.setAttribute(k,v));if(text!=null)e.textContent=text;parent.appendChild(e);return e;};
 const fmt=value=>{const s=Math.round(value);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
 const plan=await fetch('/api/timetable-plan',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error(r.status);return r.json();});
 document.querySelector('#summary').innerHTML=`${plan.counts.planned_lines} 条线路<br><span class="ok">消除站场冲突 ${plan.global_conflict_plan.conflicts_removed}</span><br><span class="warn">区间精排待实测</span>`;
 const render=line=>{
  svg.replaceChildren();document.querySelectorAll('.line').forEach(e=>e.classList.toggle('active',Number(e.dataset.id)===line.line_id));
  const left=150,right=1160,top=70,bottom=660,cycle=line.cycle_seconds,stops=line.stops,n=Math.max(1,stops.length-1),x=t=>left+(t/cycle)*(right-left),y=i=>top+i*(bottom-top)/n;
  S('rect',{x:left,y:top,width:right-left,height:bottom-top,fill:'#071019',stroke:'#365269'});
  for(let t=0;t<=cycle;t+=Math.max(30,Math.ceil(cycle/12/30)*30)){S('line',{x1:x(t),y1:top,x2:x(t),y2:bottom,stroke:'#17293a'});S('text',{x:x(t),y:top-12,fill:'#7890a4','font-size':10,'text-anchor':'middle','font-family':'Consolas'},fmt(t));}
  stops.forEach((stop,i)=>{const fit=stop.platform_fit?.status;S('line',{x1:left,y1:y(i),x2:right,y2:y(i),stroke:fit==='TOO_SHORT'?'#8f3f45':'#294154'});S('text',{x:left-10,y:y(i)+4,fill:fit==='TOO_SHORT'?'#ff8d95':'#c8f3ff','font-size':11,'text-anchor':'end'},`${stop.station_name||`站 ${stop.station_group_id}`}${fit==='TOO_SHORT'?' ⚠':''}`);});
  const colors=['#42dcff','#ffe06c','#6dffa7','#ff7f9d','#b89bff','#ffad66'];
  line.phase_offsets_seconds.forEach((phase,phaseIndex)=>{
   for(const base of [phase-cycle,phase,phase+cycle]){
    let d='';
    stops.forEach((stop,i)=>{const arrival=base+stop.arrival_offset_seconds,departure=base+stop.departure_offset_seconds;d+=`${i?'L':'M'}${x(arrival)},${y(i)} L${x(departure)},${y(i)} `;if(i<stops.length-1)d+=`L${x(departure+stop.next_leg_running_seconds)},${y(i+1)} `;});
    S('path',{d,fill:'none',stroke:colors[phaseIndex%colors.length],'stroke-width':2.2,'clip-path':'url(#plotclip)',opacity:.9});
   }
  });
  const defs=S('defs',{}),clip=S('clipPath',{id:'plotclip'},null,defs);S('rect',{x:left,y:top,width:right-left,height:bottom-top},null,clip);svg.insertBefore(defs,svg.firstChild);
  const basis=line.speed_basis||{},platform=line.platform_feasibility||{},platformOk=platform.status==='VERIFIED_FIT';info.innerHTML=`<b>${line.line_name}</b><br>${line.service_class} · 图定运行速度 ${line.speed_class_kmh??'UNKNOWN'} km/h<br>车底上限 ${basis.consist_top_speed_kmh??'待采'} · 线路最低限速 ${basis.infrastructure_min_speed_limit_kmh??'待采'} km/h<br>最长编组 ${platform.longest_assigned_train_m??'待采'} m · 站台适配 <span class="${platformOk?'ok':'warn'}">${platform.status??'UNKNOWN'}</span><br>${line.vehicle_count} 组车 · 间隔 ${fmt(line.headway_seconds)} · 周期 ${fmt(cycle)}<br>全局移位 ${line.global_phase_shift_seconds}s<br>站场冲突 ${line.station_conflicts_before_shift} → <span class="ok">${line.station_conflicts_after_shift}</span><br><span class="warn">当前未启用；区间占用时分仍待实测收敛</span>`;
 };
 plan.lines.forEach((line,index)=>{const e=document.createElement('div');e.className='line';e.dataset.id=line.line_id;e.innerHTML=`${line.line_name}<small>${line.service_class} · ${line.speed_class_kmh??'—'} km/h · ${line.vehicle_count}车 · ${fmt(line.headway_seconds)}</small>`;e.onclick=()=>render(line);list.appendChild(e);if(index===0)render(line);});
})().catch(error=>{document.querySelector('#info').innerHTML=`<span class="warn">运行图载入失败：${error}</span>`;});
