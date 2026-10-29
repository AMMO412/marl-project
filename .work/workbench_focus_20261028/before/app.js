'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modes = {normal:'正常执行',failure:'失败重试',timeout:'超时恢复',kill:'成员失联',deviation:'进度偏差'};
const statuses = {pending:'待分配',running:'执行中',cancelling:'取消中',succeeded:'已完成',failed:'已失败'};
const types = {patrol:'巡逻警戒',blockade:'区域封控',recon:'协同侦察',assault:'机动突击',hold:'要点坚守'};
const icons = {patrol:'↻',blockade:'◇',recon:'⌕',assault:'↗',hold:'⌂'};
const kindNames = {UGV:'轮式车',TANK:'履带车',PLANE:'固定翼',WING:'飞翼'};
const events = {plan_emitted:'生成规划方案',job_dispatched:'下发作业',job_succeeded:'作业完成',job_requeued:'作业重新排队',job_failed:'作业失败',member_lost:'平台失联',timeout:'作业超时',deviation:'进度偏差',cancel_sent:'发出取消请求',command_abandoned:'终止失联成员指令',feedback_ignored:'反馈未采纳',behavior_event:'到位行为'};
const behaviorEvents = {phase:'行为阶段切换',checkpoint_visited:'到达检查点',cycle_completed:'完成一圈巡逻',posts_occupied:'封控占位就绪',intrusion_detected:'发现入侵',interceptor_assigned:'指派拦截',intercepted:'拦截成功',breach:'越界',map_initialised:'地图初始化',frontier_mapped:'前沿测绘',coverage_reached:'覆盖达标',report_sent:'成果回传',map_shared:'共享地图更新',all_staged:'全员到位',assault_started:'突击开始',effect_started:'效能施加',effect_applied:'效能达成',confirmed:'结果确认',on_post:'上岗',handover_start:'接替开始',handover_complete:'接替完成',relief:'换班',behavior_complete:'行为完成',arrived_area:'进入作业区',route_failed:'路径失败'};
const triggerNames = {init:'首次规划',periodic:'周期更新',member_change:'成员变化',exec_fail:'执行失败',timeout:'超时',deviation:'进度偏差'};
const titles = {overview:'演示总览',tasks:'任务与分配',platforms:'平台状态',runs:'实验与报告',files:'项目文件'};
const sourceFiles = [['readme','README_v2.md','项目说明与运行方式'],['planner','planner_v2.py','六步规则规划器'],['coordinator','coordinator_v2.py','反馈、调度与重规划'],['fleet','mock_fleet.py','本地执行与反馈替身'],['contracts','contracts_v2.py','场景与消息数据契约']];
const state = {catalog:null,run:null,t:0,playing:false,speed:2,focus:null,page:'overview',zoom:1,frames:[],eventRows:[],hits:[],loadToken:0,busy:false};
let toastTimer, pollTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function api(url, options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error||'读取失败');return data;}
function num(value,d=1){return value==null?'未知':Number(value).toFixed(d);}
function no(pid){return '#'+String(pid||'').replace('rover_','');}
function stamp(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
function shortRun(id){if(id==='workbench_behavior_20261028')return '城市到位动作 · 2026-10-28';if(id==='avoid_run')return '旧版城市绕障 · 无到位动作';return id.replace('workbench_','').replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_.*$/,'$1-$2-$3 $4:$5:$6');}
function setPage(page){state.page=page;$$('.page').forEach(x=>x.classList.toggle('active',x.id==='page-'+page));$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page));$('#crumb').textContent=titles[page];$('#page-title').innerHTML=(page==='overview'?'把规划过程，看清楚。':esc(titles[page]))+'<span class="version">V2</span>';renderTime();draw();window.scrollTo(0,0);}
function eventCategory(e){if(e.kind==='plan_emitted')return 'planning';if(e.kind==='behavior_event')return 'behavior';if(['member_lost','timeout','deviation','job_requeued','job_failed','cancel_sent','command_abandoned','feedback_ignored'].includes(e.kind))return 'exception';return 'task';}
function eventDetail(e){if(e.kind==='plan_emitted')return (e.triggers||[]).map(x=>x.split(':')[0]).join(' / ')+' · '+e.n_assignments+' 项指派';if(e.kind==='behavior_event'){const ev=e.event||{},sub=ev.kind;let d=behaviorEvents[sub]||sub||'';if(ev.phase)d+=' · '+ev.phase;if(ev.pid)d+=' · '+ev.pid;if(ev.cycle!=null)d+=' · 第'+ev.cycle+'圈';if(ev.coverage!=null)d+=' · 覆盖'+Math.round(ev.coverage*100)+'%';return d;}if(e.pids)return e.pids.map(no).join(' · ')+' · 第 '+e.attempt+' 次尝试';return e.reason||e.cause||e.pid||e.command_id||e.job_id||'';}
function eventTitle(e){if(e.kind==='behavior_event'){const ev=e.event||{};return behaviorEvents[ev.kind]||ev.kind||'到位行为';}return events[e.kind]||e.kind;}
function makeFrames(data){
  const jobs={};data.report.jobs.forEach(j=>jobs[j.job_id]={status:'pending',progress:0,attempts:0,pids:[],start:null,end:null,phase:null,behavior:{}});
  const lost=new Set(),sorted=data.trace.map((e,i)=>({...e,seq:i})).sort((a,b)=>a.sim_s-b.sim_s||a.seq-b.seq);
  const frames=[];let cursor=0,plans=0,retries=0,timeouts=0;
  for(let t=0;t<=Math.ceil(data.replay.end);t++){
    while(cursor<sorted.length&&sorted[cursor].sim_s<=t){
      const e=sorted[cursor++],j=jobs[e.job_id];
      if(e.kind==='plan_emitted')plans++;
      if(e.kind==='member_lost')lost.add(e.pid);
      if(e.kind==='job_dispatched'&&j){j.status='running';j.attempts=e.attempt;j.pids=e.pids;j.start=e.planned_start;j.end=e.planned_end;if(e.attempt>1)retries++;}
      if(e.kind==='feedback_applied'){const ev=e.event,k=jobs[ev.job_id];if(k){k.progress=Math.max(k.progress,ev.progress||0);k.phase=ev.phase;if(!['succeeded','failed','cancelling'].includes(k.status))k.status='running';}}
      if(e.kind==='behavior_event'){
        const ev=e.event||{},k=jobs[ev.job_id];
        if(k){const b=k.behavior;b.last=ev.kind;b.at=e.sim_s;
          if(ev.phase)k.phase=ev.phase;
          if(ev.kind==='checkpoint_visited')b.checkpoints=(b.checkpoints||0)+1;
          if(ev.kind==='cycle_completed')b.cycles=Math.max(b.cycles||0,ev.cycle||0);
          if(ev.coverage!=null)b.coverage=ev.coverage;
          if(ev.kind==='map_shared')b.shares=(b.shares||0)+1;
          if(ev.kind==='handover_start')b.handover={incoming:ev.incoming,outgoing:ev.outgoing,done:false};
          if(ev.kind==='handover_complete'){b.handovers=(b.handovers||0)+1;b.handover={incoming:ev.incoming,outgoing:ev.outgoing,done:true};}
          if(ev.kind==='intrusion_detected'||ev.kind==='intercepted')b.observed={kind:ev.kind,pos:ev.pos};
          if(ev.kind==='intercepted')b.intercepted=true;
          if(ev.kind==='confirmed')b.confirmed=true;
          if(ev.kind==='report_sent')b.reported=true;
          if(ev.kind==='behavior_complete')b.complete=true;
        }
      }
      if(e.kind==='job_succeeded'&&j)j.status='succeeded';
      if(e.kind==='job_failed'&&j)j.status='failed';
      if(e.kind==='job_requeued'&&j){j.status='pending';j.pids=[];}
      if(e.kind==='timeout'&&j){j.status='cancelling';timeouts++;}
    }
    frames.push({jobs:JSON.parse(JSON.stringify(jobs)),lost:[...lost],plans,retries,timeouts});
  }
  return frames;
}
function frame(){return state.frames[Math.min(state.frames.length-1,Math.floor(state.t))];}
function workerAt(w){
  const samples=w.samples;let lo=0,hi=samples.length;
  while(lo<hi){let mid=(lo+hi)>>1;if(samples[mid].t<=state.t)lo=mid+1;else hi=mid;}
  const prev=samples[lo-1];
  let result=prev?{...prev}:{x:w.start[0],y:w.start[1],z:w.start_z||0,battery:w.initial_battery,job:null,status:null,distance:0,t:null};
  const next=samples[lo];
  if(prev&&next&&state.run.report.motion==='real'&&next.t>prev.t&&prev.command===next.command&&['accepted','progress'].includes(prev.status)&&!frame().lost.includes(w.pid)){
    const f=(state.t-prev.t)/(next.t-prev.t);result.x=prev.x+(next.x-prev.x)*f;result.y=prev.y+(next.y-prev.y)*f;result.z=prev.z+(next.z-prev.z)*f;
  }
  result.lost=frame().lost.includes(w.pid);return result;
}
function setTime(t){if(!state.run)return;state.t=Math.min(state.run.replay.end,Math.max(0,t));renderTime();draw();}
function setPlaying(yes){state.playing=!!yes;if(yes&&state.t>=state.run.replay.end)state.t=0;$('#play').textContent=yes?'Ⅱ 暂停':'▶ 播放';$('#play-state').textContent=yes?'播放中':'已暂停';}
function phaseName(phase){return ({travel:'前往作业区',work:'到达作业区'})[phase]||phase||'尚未开始';}
function behaviorSummary(j,s){
  const b=s.behavior;
  if(!state.run.report.behavior)return '本轮为到点工作量模型';
  if(j.jtype==='patrol')return `已记录 ${b.cycles||0} 圈 · ${b.checkpoints||0} 次检查点访问`;
  if(j.jtype==='recon')return b.coverage==null?'等待探索反馈':`覆盖 ${Math.round(b.coverage*100)}% · 共享 ${b.shares||0} 次${b.reported?' · 已回传':''}`;
  if(j.jtype==='hold')return `已接替 ${b.handovers||0} 次`+(b.handover?` · ${no(b.handover.outgoing)} → ${no(b.handover.incoming)}${b.handover.done?' 已完成':' 接替中'}`:'');
  if(j.jtype==='blockade')return b.observed?(b.intercepted?'已记录处置完成':'已记录区域事件'):'等待占位与区域事件反馈';
  return b.confirmed?'已收到结果确认':b.last?(behaviorEvents[b.last]||b.last):'等待阶段反馈';
}
function renderBehaviors(){
  const enabled=!!state.run.report.behavior,f=frame();
  $('#behavior-model').textContent=enabled?'本轮动作已接入':'到点工作量模型';
  $('#behavior-model').classList.toggle('warning',!enabled);
  $('#behavior-count').textContent=enabled?state.run.report.jobs.filter(j=>f.jobs[j.job_id].behavior.at!=null).length+' / '+state.run.report.jobs.length:'0';
  $('#behavior-note').textContent=enabled?'来自当前运行的动作阶段与事件；点击卡片定位任务，点击关键节点跳转。':'此历史运行未启用到位动作。点击“载入动作演示”查看已有动作记录。';
  $('#behavior-list').innerHTML=enabled?state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id];return `<button class="behavior-tile ${state.focus?.id===j.job_id?'selected':''}" data-job="${esc(j.job_id)}"><span class="behavior-tile-head"><b>${esc(j.job_id)} · ${esc(types[j.jtype])}</b><span>${esc(s.status==='succeeded'?'已完成':phaseName(s.phase))}</span></span><small>${esc(behaviorSummary(j,s))}</small></button>`;}).join(''):'<div class="empty">本轮轨迹只记录到点作业。<button class="button small" data-behavior-run>载入动作演示 →</button></div>';
  const keyKinds=new Set(['cycle_completed','posts_occupied','intrusion_detected','intercepted','handover_start','handover_complete','map_initialised','coverage_reached','report_sent','all_staged','effect_applied','confirmed']);
  const jid=state.focus?.type==='job'?state.focus.id:null;
  $('#behavior-milestones').innerHTML=enabled?state.eventRows.filter(e=>e.kind==='behavior_event'&&keyKinds.has(e.event?.kind)&&(!jid||e.job_id===jid)).map(e=>`<button class="milestone ${e.sim_s>state.t?'future':'occurred'}" data-event-time="${e.sim_s}" data-event-job="${esc(e.job_id)}"><span>${e.sim_s} s${e.sim_s>state.t?' · 未发生':''}</span>${esc(e.job_id)} · ${esc(eventTitle(e))}</button>`).join(''):'';
}
function renderTime(){
  if(!state.run)return;const f=frame(),jobs=Object.values(f.jobs),done=jobs.filter(j=>j.status==='succeeded').length;
  $('#stat-done').textContent=done;$('#stat-total').textContent='/ '+jobs.length;$('#done-bar').style.width=100*done/jobs.length+'%';$('#done-note').textContent=done===jobs.length?'本轮全部完成':'按当前反馈统计';
  $('#stat-alive').textContent=state.run.replay.workers.length-f.lost.length;$('#stat-plans').textContent=f.plans;$('#plan-note').textContent='已重试 '+f.retries+' 次 · 已超时 '+f.timeouts+' 次';$('#stat-clock').textContent=state.t.toFixed(1);$('#clock').textContent=state.t.toFixed(1);$('#scrubber').value=state.t;
  $('#task-list').innerHTML=state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<button class="task-row ${state.focus?.id===j.job_id?'selected':''}" data-job="${esc(j.job_id)}"><div class="task-line"><span class="job-icon">${icons[j.jtype]||'◇'}</span><b>${esc(types[j.jtype]||j.jtype)}<span class="task-id">${esc(j.job_id)}</span></b><span class="task-status ${s.status}">${statuses[s.status]}</span></div><div class="task-progress"><div class="progress-track"><i style="width:${pct}%"></i></div><span>${Math.round(pct)}%</span></div><div class="task-assigned">${s.pids.length?s.pids.map(no).join(' · '):'等待可行分配'}${state.run.report.behavior?' · '+esc(phaseName(s.phase)):''}</div></button>`;}).join('');
  renderInspector();renderEvents();renderBehaviors();
  if(state.page==='tasks')renderTasks();if(state.page==='platforms')renderPlatforms();
}
function focus(type,id,go=false){state.focus={type,id};$('#track-worker').value=type==='worker'?id:'all';if(go)setPage('overview');renderTime();draw();}
function renderInspector(){
  const f=state.focus;if(!f){$('#inspector').innerHTML='<p class="muted">点击地图平台或任务，查看当前位置、分配关系与反馈。也可从右上角新建演示，比较异常处理。</p>';return;}
  if(f.type==='worker'){
    const w=state.run.replay.workers.find(w=>w.pid===f.id);if(!w)return;const p=workerAt(w);
    const active=p.job&&frame().jobs[p.job]?.status==='running';
    $('#inspector').innerHTML=`<div class="focus-title"><span style="color:${w.color}">●</span> ${esc(w.pid)} · ${esc(w.kind_name)}</div><dl><div><dt>当前坐标</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度 / 场景单位</dt><dd>${num(p.z)}</dd></div><div><dt>当前作业</dt><dd>${p.lost?'成员失联':active?esc(p.job):'空闲 / 最近反馈'}</dd></div><div><dt>当前动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>累计反馈路程</dt><dd>${num(p.distance)}</dd></div><div><dt>最近位置反馈</dt><dd>${p.t==null?'仅场景初始位':num(p.t,0)+' s'}</dd></div></dl>`;
  }else{
    const j=state.run.report.jobs.find(j=>j.job_id===f.id);if(!j)return;const s=frame().jobs[j.job_id];
    $('#inspector').innerHTML=`<div class="focus-title">${esc(j.job_id)} · ${esc(types[j.jtype])}</div><dl><div><dt>当前状态</dt><dd>${statuses[s.status]}</dd></div><div><dt>工作量</dt><dd>${num(s.progress)} / ${j.work}</dd></div><div><dt>当前动作阶段</dt><dd>${esc(phaseName(s.phase))}</dd></div><div><dt>动作记录</dt><dd>${esc(behaviorSummary(j,s))}</dd></div><div><dt>当前指派</dt><dd>${s.pids.map(no).join(' · ')||'尚未分配'}</dd></div><div><dt>需求人数</dt><dd>${j.crew} 台</dd></div><div><dt>计划开工 / 完工</dt><dd>${s.start==null?'未排程':s.start+' / '+s.end+' s'}</dd></div><div><dt>目标坐标</dt><dd>${j.pos.map(x=>num(x)).join(', ')}</dd></div></dl>`;
  }
}
let lastEventKey='';
function renderEvents(){
  const filter=$('#event-filter').value;
  const visible=state.eventRows.filter(e=>filter==='all'||eventCategory(e)===filter);
  const count=visible.filter(e=>e.sim_s<=state.t).length;$('#event-count').textContent=count+' / '+visible.length;
  const past=visible.filter(e=>e.sim_s<=state.t).slice(-6),future=visible.filter(e=>e.sim_s>state.t).slice(0,2);
  const list=[...past,...future],key=state.run.id+filter+list.map(e=>e.index+(e.sim_s>state.t?'f':'p')).join(',');
  if(key===lastEventKey)return;lastEventKey=key;
  $('#events').innerHTML=list.map(e=>`<button class="event-item ${eventCategory(e)} ${e.sim_s>state.t?'future':''}" data-event-time="${e.sim_s}"><span class="event-time"><i></i>T + ${num(e.sim_s,0)} s${e.sim_s>state.t?' · 尚未发生':''}</span><strong>${e.job_id?esc(e.job_id)+' · ':''}${esc(eventTitle(e))}</strong><small title="${esc(eventDetail(e))}">${esc(eventDetail(e))}</small></button>`).join('')||'<div class="empty">当前筛选没有事件</div>';
}
function renderTasks(){
  $('#task-table').innerHTML=state.run.report.jobs.map(j=>{const s=frame().jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<tr class="${state.focus?.id===j.job_id?'selected':''}"><td><button class="text-button" data-job="${esc(j.job_id)}" data-locate>${esc(j.job_id)} · ${esc(types[j.jtype])}</button><small>协同需求 ${j.crew} 台 · ${esc(j.need_sensor||'无专属传感器')}</small></td><td>${j.pos.map(x=>num(x)).join(', ')}</td><td><span class="pill ${s.status==='failed'?'warning':''}">${statuses[s.status]}</span><small>${esc(phaseName(s.phase))}</small></td><td>${num(s.progress)} / ${j.work}<div class="progress-track table-progress"><i style="width:${pct}%"></i></div></td><td>${s.pids.map(no).join(' · ')||'—'}</td><td>${s.attempts}</td><td>${j.window.join(' – ')} s</td></tr>`;}).join('');
}
function renderPlatforms(){
  const filter=$('#platform-filter').value;
  $('#platform-grid').innerHTML=state.run.replay.workers.filter(w=>filter==='all'||w.kind===filter).map(w=>{const p=workerAt(w);return `<button class="platform-tile" data-worker="${esc(w.pid)}" data-locate><h3><i style="background:${w.color}"></i>${esc(w.pid)}<span>${p.lost?'失联':'可用'}</span></h3><p>${esc(w.kind_name)} · ${esc(w.kind)}</p><dl><div><dt>位置</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度</dt><dd>${num(p.z)}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>最近作业</dt><dd>${esc(p.job||'—')}</dd></div><div><dt>动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div></dl></button>`;}).join('');
}
function renderRuns(){
  $('#runs-table').innerHTML=state.catalog.runs.map(r=>`<tr class="${r.id===state.run?.id?'selected':''}"><td><button class="text-button" data-load-run="${esc(r.id)}">${esc(shortRun(r.id))}</button><small>${esc(r.objective)} · ${r.settled?'已结算':'达到步数上限，未结算'}</small></td><td>${modes[r.mode]||esc(r.mode)}<small>${r.motion==='real'?'逐步运动':'瞬移'}${r.avoid?' · 建筑绕障':''}${r.behavior?' · 到位行为':''}</small></td><td>${r.done} / ${r.total}</td><td>${r.end} s</td><td>${num(r.energy)}</td><td>${r.retries} / ${r.timeouts}</td><td><button class="text-button" data-load-run="${esc(r.id)}">载入回放 ↗</button></td></tr>`).join('');
  if(!state.run)return;const r=state.run.report;
  $('#report-status').textContent=r.all_succeeded?'全部完成':r.settled?'本轮已结算':'未结算';$('#report-status').classList.toggle('warning',!r.all_succeeded);
  $('#report-summary').innerHTML=[[r.done+'/'+r.jobs.length,'工作量达标作业'],[r.simulated_until_s+' s','仿真运行终点'],[num(r.used_energy),'累计模型耗电'],[r.plans,'规划方案数'],[r.retries,'重试次数'],[r.timeouts,'超时次数']].map(([v,l])=>`<div><b>${esc(v)}</b><span>${l}</span></div>`).join('');
  const total=Math.max(1,...Object.values(r.triggers||{}));$('#triggers').innerHTML=Object.entries(r.triggers||{}).map(([k,v])=>`<div class="trigger-row"><span>${triggerNames[k]||esc(k)}</span><div><i style="width:${100*v/total}%"></i></div><b>${v}</b></div>`).join('');
  $('#download-report').href=artifact('report.json');$('#download-trace').href=artifact('trace.jsonl');$('#result-scope').textContent=r.behavior?'本轮启用到位行为；作业终态来自已保存的模拟日志。':'本轮未启用到位行为；完成只表示原模型工作量达标。';
}
function artifact(name){return '/artifacts/'+encodeURIComponent(state.run.id)+'/'+name;}
const fileDescriptions={'manifest.json':'运行配置、来源与环境','scenario.json':'本轮实际场景快照','report.json':'最终指标与状态','trace.jsonl':'逐条原始反馈与审计','summary.txt':'文本结果摘要','report.html':'原始可视化报告','trajectory.html':'原始轨迹播放器','request.json':'工作台请求参数','worker.log':'本轮运行日志'};
function renderFiles(){
  $('#source-files').innerHTML=sourceFiles.map(([key,name,desc])=>`<button class="file-item" data-source="${key}"><span>↗</span><b>${name}</b><small>${desc}</small></button>`).join('');
  if(!state.run)return;$('#output-path').textContent='planning_middle_demo/outputs/'+state.run.id+'/';
  $('#artifact-files').innerHTML=state.run.files.map(n=>`<a class="file-item" href="${artifact(n)}" target="_blank" rel="noopener"><span>↗</span><b>${n}</b><small>${fileDescriptions[n]||'运行产物'}</small></a>`).join('');
}
async function loadRun(id,autoplay=false){
  const token=++state.loadToken;setPlaying(false);
  try{
    const data=await api('/api/runs/'+encodeURIComponent(id));if(token!==state.loadToken)return;
    state.run=data;state.t=0;state.focus=null;state.zoom=1;state.frames=makeFrames(data);state.eventRows=data.trace.map((e,index)=>{if(e.kind==='behavior_event'&&e.event&&e.event.job_id&&!e.job_id)e={...e,job_id:e.event.job_id};return {...e,index};}).filter(e=>events[e.kind]&&!(e.kind==='behavior_event'&&e.event?.kind==='behavior_structure'));lastEventKey='';
    $('#run-select').value=id;$('#run-mode').textContent=modes[data.report.mode]||data.report.mode;$('#run-semantic').textContent=(data.report.motion==='real'?'逐步运动':'瞬移')+(data.report.avoid?' · 静态建筑绕障':'')+(data.report.behavior?' · 到位行为':'')+' · '+(data.report.objective||'makespan');
    $('#scene-title').textContent=data.replay.background.roads.length?'OSRF citysim / 城市道路':'基础编成 / 坐标场景';$('#stat-end').textContent=data.replay.end;$('#duration').textContent=data.replay.end;$('#scrubber').max=data.replay.end;$('#timeline-mid').textContent=stamp(data.replay.end/2);$('#timeline-end').textContent=stamp(data.replay.end);$('#task-count').textContent=data.report.jobs.length;$('#side-jobs').textContent=String(data.report.jobs.length).padStart(2,'0');
    $('#fleet-note').textContent=[...new Set(data.replay.workers.map(w=>w.kind_name))].join(' · ');
    $('#track-worker').innerHTML='<option value="all">全部平台</option>'+data.replay.workers.map(w=>`<option value="${esc(w.pid)}">${esc(w.pid)} · ${esc(w.kind_name)}</option>`).join('');$('#model-note').textContent=data.report.behavior?'已启用到位动作 · 地图、动作与事件共用时间轴':'旧版到点工作量模型 · 未启用到位动作';setBounds();renderTime();renderRuns();renderFiles();draw();if(autoplay)setPlaying(true);
  }catch(e){toast('载入失败：'+e.message);}
}
async function refreshCatalog(selectId){
  const data=await api('/api/catalog');state.catalog=data;
  $('#connection-text').textContent='本机已连接';$('#run-select').innerHTML=data.runs.map(r=>`<option value="${esc(r.id)}">${esc(shortRun(r.id))} · ${r.behavior?'到位动作':'到点作业'} · ${modes[r.mode]||r.mode}</option>`).join('');
  if(selectId||!state.run){const id=selectId||(data.runs.find(r=>r.id===data.default_run)||data.runs.find(r=>r.behavior)||data.runs[0])?.id;if(id)await loadRun(id);else toast('还没有运行记录，点击新建演示开始。');}
  else{$('#run-select').value=state.run.id;renderRuns();}
  if(data.process?.state==='running')watchProcess(data.process.id);
}
function setBusy(b){state.busy=b;$('#busy-banner').hidden=!b;$('#submit-run').disabled=b;$('#submit-run').textContent=b?'仿真运行中…':'运行演示 →';}
function watchProcess(id){
  setBusy(true);clearTimeout(pollTimer);
  async function poll(){try{const data=await api('/api/catalog');if(data.process?.id!==id){setBusy(false);return;}if(data.process.state==='running'){pollTimer=setTimeout(poll,800);return;}setBusy(false);await refreshCatalog();if(data.process.state==='complete'){await loadRun(id,true);setPage('overview');toast('本轮结果已保存，正在回放实际反馈。');}else{const log=await fetch('/artifacts/'+encodeURIComponent(id)+'/worker.log').then(r=>r.text());toast('运行失败：'+log.slice(-200));}}catch(e){setBusy(false);toast('状态读取失败：'+e.message);}}
  pollTimer=setTimeout(poll,800);
}
function updateConfig(){const allow=$('#config-scenario').value==='simple_city'&&$('#config-motion').value==='real';$('#config-avoid').disabled=!allow;if(!allow)$('#config-avoid').checked=false;$('#config-behavior').disabled=!allow||!$('#config-avoid').checked;if(!allow||!$('#config-avoid').checked)$('#config-behavior').checked=false;}
function openConfig(){$('#config-error').hidden=true;$('#config-dialog').showModal();}
$('#config-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target),config={scenario:f.get('scenario'),mode:f.get('mode'),motion:f.get('motion'),objective:f.get('objective'),max_ticks:Number(f.get('max_ticks')),avoid:$('#config-avoid').checked&&!$('#config-avoid').disabled,behavior:$('#config-behavior').checked&&!$('#config-behavior').disabled};try{const result=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});$('#config-dialog').close();watchProcess(result.id);}catch(err){$('#config-error').textContent=err.message;$('#config-error').hidden=false;}});
// Map geometry is drawn from the same replay data used by trajectory_v2.py.
let bounds=[0,0,100,100];const canvas=$('#scene'),ctx=canvas.getContext('2d');
function setBounds(){const r=state.run.replay,points=[...r.workers.map(w=>w.start),...r.jobs.map(j=>j.pos),...r.workers.flatMap(w=>w.samples.map(s=>[s.x,s.y])),...(r.behaviors||[]).flatMap(b=>[...(b.loop||[]),...(b.posts||[]),...(b.standbys||[]),...(b.staging||[]),...(b.objective||[])])];const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);bounds=[Math.min(...xs)-5,Math.min(...ys)-5,Math.max(...xs)+5,Math.max(...ys)+5];}
function draw(){
  if(!state.run||state.page!=='overview')return;
  const rect=canvas.getBoundingClientRect();if(rect.width<1)return;const dpr=window.devicePixelRatio||1;
  if(canvas.width!==Math.round(rect.width*dpr)||canvas.height!==Math.round(rect.height*dpr)){canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);const W=rect.width,H=rect.height;ctx.clearRect(0,0,W,H);ctx.fillStyle='#f4f7f5';ctx.fillRect(0,0,W,H);
  const [x0,y0,x1,y1]=bounds,scale=Math.min((W-65)/(x1-x0),(H-65)/(y1-y0))*state.zoom,cx=(x0+x1)/2,cy=(y0+y1)/2;
  const P=p=>[W/2+(p[0]-cx)*scale,H/2-(p[1]-cy)*scale];const line=(points,color,width=1,dash=[])=>{if(points.length<2)return;ctx.beginPath();points.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  const step=(x1-x0)>70?10:5;ctx.font='8px "Segoe UI",sans-serif';
  for(let x=Math.floor(x0/step)*step;x<=x1+step;x+=step){const a=P([x,y0]),b=P([x,y1]);ctx.strokeStyle='#e5ede6';ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(a[0],0);ctx.lineTo(a[0],H);ctx.stroke();ctx.fillStyle='#a9b9ad';ctx.fillText(x,a[0]+3,H-20);}
  for(let y=Math.floor(y0/step)*step;y<=y1+step;y+=step){const a=P([x0,y]);ctx.strokeStyle='#e5ede6';ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(0,a[1]);ctx.lineTo(W,a[1]);ctx.stroke();ctx.fillStyle='#a9b9ad';ctx.fillText(y,10,a[1]-4);}
  if($('#show-roads').checked){
    ctx.lineCap='butt';for(const road of state.run.replay.background.roads){line(road.points,'#e1e5db',Math.max(2,road.width*scale));line(road.points,'#f5f5eb',.7,[4,5]);}
    for(const o of state.run.obstacles){ctx.beginPath();o.polygon.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.closePath();ctx.fillStyle='#dce5db';ctx.fill();ctx.strokeStyle='#c5d5c7';ctx.lineWidth=1;ctx.stroke();}
  }
  state.hits=[];const f=frame(),showLabels=$('#show-labels').checked;
  for(const j of state.run.replay.jobs){const [x,y]=P(j.pos),s=f.jobs[j.job_id],selected=state.focus?.id===j.job_id;ctx.beginPath();ctx.arc(x,y,selected?17:13,0,Math.PI*2);ctx.fillStyle=s.status==='succeeded'?'#dceee270':'#ffffff80';ctx.fill();ctx.setLineDash(s.status==='succeeded'?[]:[3,3]);ctx.strokeStyle=selected?'#427e58':s.status==='succeeded'?'#79a786':'#a4b59e';ctx.lineWidth=selected?2:1;ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#66886b';ctx.font='10px "Segoe UI","Microsoft YaHei"';ctx.textAlign='center';ctx.fillText(s.status==='succeeded'?'✓':'·',x,y+4);if(showLabels){ctx.font='bold 10px "Segoe UI"';ctx.fillText(j.job_id+(s.status==='succeeded'?' ✓':''),x,y-19);ctx.font='8px "Microsoft YaHei"';const label=$('#show-landmarks').checked?(j.landmark||types[j.type]||'').split('（')[0]:'';ctx.fillStyle='#93a48f';ctx.fillText(label.length>14?label.slice(0,13)+'…':label,x,y+27);}state.hits.push({x,y,type:'job',id:j.job_id,r:19});}
  // 到位后行为结构：巡逻环 / 封控圈 / 侦察区 / 突击阶段点 / 坚守岗位
  const behColors={patrol:'#2563eb',blockade:'#dc2626',recon:'#7c3aed',assault:'#ea580c',hold:'#15803d'};
  for(const b of (state.run.replay.behaviors||[]).filter(b=>$('#show-behaviors').checked&&b.sim_s<=state.t)){const c=behColors[b.type]||'#64748b';ctx.save();ctx.globalAlpha=.8;
    if(b.type==='patrol'&&b.loop){ctx.beginPath();b.loop.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.closePath();ctx.fillStyle=c+'18';ctx.fill();ctx.strokeStyle=c;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.stroke();ctx.setLineDash([]);for(const p of b.loop){const a=P(p);ctx.beginPath();ctx.arc(...a,3.5,0,Math.PI*2);ctx.fillStyle=c+'70';ctx.fill();}}
    else if(b.type==='blockade'){if(b.ring_radius){const a=P(b.site);ctx.beginPath();ctx.arc(...a,b.ring_radius*scale,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=1.3;ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([]);}for(const p of (b.posts||[])){const a=P(p);ctx.beginPath();ctx.arc(...a,5,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=1.7;ctx.stroke();}if(b.intruder_start){const a=P(b.intruder_start);ctx.beginPath();ctx.arc(...a,4,0,Math.PI*2);ctx.fillStyle=c+'60';ctx.fill();}}
    else if(b.type==='recon'){if(b.area_radius){const a=P(b.site);ctx.beginPath();ctx.arc(...a,b.area_radius*scale,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=1.3;ctx.setLineDash([6,4]);ctx.stroke();ctx.setLineDash([]);}}
    else if(b.type==='assault'){for(const p of (b.staging||[])){const a=P(p);ctx.beginPath();ctx.arc(...a,5,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=1.5;ctx.setLineDash([2,2]);ctx.stroke();ctx.setLineDash([]);}for(const p of (b.objective||[])){const a=P(p);ctx.beginPath();ctx.arc(...a,4,0,Math.PI*2);ctx.fillStyle=c+'70';ctx.fill();}}
    else if(b.type==='hold'){for(const p of (b.posts||[])){const a=P(p);ctx.beginPath();ctx.arc(...a,5,0,Math.PI*2);ctx.fillStyle=c+'55';ctx.fill();ctx.strokeStyle=c;ctx.lineWidth=1.3;ctx.stroke();}for(const p of (b.standbys||[])){const a=P(p);ctx.beginPath();ctx.arc(...a,5,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=1.3;ctx.setLineDash([2,2]);ctx.stroke();ctx.setLineDash([]);}}
    ctx.restore();}
  const labels=[];
  for(const w of state.run.replay.workers){const p=workerAt(w),[x,y]=P([p.x,p.y]),selected=state.focus?.id===w.pid;ctx.globalAlpha=state.focus&&state.focus.type==='worker'&&!selected ? 0.4 : 1;
    if($('#show-starts').checked){const [sx,sy]=P(w.start);ctx.beginPath();ctx.arc(sx,sy,4,0,Math.PI*2);ctx.setLineDash([2,2]);ctx.strokeStyle=w.color;ctx.stroke();ctx.setLineDash([]);}
    if($('#show-trails').checked){const points=[w.start,...w.samples.filter(s=>s.t<=state.t).map(s=>[s.x,s.y]),[p.x,p.y]];line(points,w.color,selected?2.5:1.5);}
    if(selected&&p.job&&f.jobs[p.job]?.status==='running'){const j=state.run.replay.jobs.find(j=>j.job_id===p.job);if(j)line([[p.x,p.y],j.pos],w.color,1,[4,5]);}
    ctx.beginPath();ctx.arc(x,y,selected?13:9,0,Math.PI*2);ctx.fillStyle='#ffffffed';ctx.fill();ctx.strokeStyle=p.lost?'#9eaaa0':w.color;ctx.lineWidth=selected?2:1;ctx.stroke();ctx.fillStyle=p.lost?'#a6afa8':w.color;ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=1.6;
    if(w.shape==='square'){ctx.fillRect(x-3,y-3,6,6);}else if(w.shape==='diamond'){ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x+4,y);ctx.lineTo(x,y+4);ctx.lineTo(x-4,y);ctx.closePath();ctx.fill();}else if(w.shape==='triangle'){ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x+4,y+3);ctx.lineTo(x-4,y+3);ctx.closePath();ctx.fill();}else{ctx.beginPath();ctx.moveTo(x-3,y-3);ctx.lineTo(x+3,y+3);ctx.moveTo(x+3,y-3);ctx.lineTo(x-3,y+3);ctx.stroke();}
    if(p.yaw!=null){ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+15*Math.cos(p.yaw),y-15*Math.sin(p.yaw));ctx.strokeStyle=w.color;ctx.lineWidth=1.3;ctx.stroke();}
    if(p.lost){ctx.beginPath();ctx.moveTo(x-7,y-7);ctx.lineTo(x+7,y+7);ctx.stroke();}
    if(showLabels){ctx.font='9px "Segoe UI",sans-serif';const text=no(w.pid)+(p.lost?' 失联':''),tw=ctx.measureText(text).width;let ly=y-10;while(labels.some(b=>Math.abs(b.y-ly)<12&&Math.abs(b.x-(x+16))<tw+7))ly+=13;labels.push({x:x+16,y:ly});ctx.fillStyle='#fffffff0';ctx.fillRect(x+10,ly-8,tw+7,13);ctx.fillStyle=p.lost?'#9daba0':w.color;ctx.textAlign='left';ctx.fillText(text,x+13,ly+1);}
    ctx.globalAlpha=1;state.hits.push({x,y,type:'worker',id:w.pid,r:13});
  }
  ctx.textAlign='left';$('#map-scale').textContent=num(40/scale,0)+' 场景单位';$('#map-caption').textContent=state.focus?state.focus.id+' · 点击空白清除选择':state.run.report.motion==='real'?'逐步位置反馈 · 相邻采样显示插值':'瞬移语义 · 按日志时刻跳变';
}
canvas.addEventListener('click',e=>{const b=canvas.getBoundingClientRect(),x=e.clientX-b.left,y=e.clientY-b.top;const hits=state.hits.filter(h=>Math.hypot(x-h.x,y-h.y)<=h.r).sort((a,b)=>Math.hypot(x-a.x,y-a.y)-Math.hypot(x-b.x,y-b.y));if(hits.length){const current=hits.findIndex(h=>h.id===state.focus?.id),h=hits[(current+1)%hits.length];focus(h.type,h.id);}else{state.focus=null;renderTime();draw();}});
document.addEventListener('click',e=>{
  const nav=e.target.closest('[data-page]');if(nav)setPage(nav.dataset.page);
  const go=e.target.closest('[data-goto]');if(go)setPage(go.dataset.goto);
  const job=e.target.closest('[data-job]');if(job)focus('job',job.dataset.job,job.hasAttribute('data-locate'));
  const worker=e.target.closest('[data-worker]');if(worker)focus('worker',worker.dataset.worker,worker.hasAttribute('data-locate'));
  const event=e.target.closest('[data-event-time]');if(event){setPlaying(false);if(event.dataset.eventJob)state.focus={type:'job',id:event.dataset.eventJob};setTime(Number(event.dataset.eventTime));}
  const run=e.target.closest('[data-load-run]');if(run)loadRun(run.dataset.loadRun).then(()=>setPage('overview'));
  if(e.target.closest('[data-behavior-run]')){const r=state.catalog.runs.find(r=>r.id===state.catalog.default_run&&r.behavior)||state.catalog.runs.find(r=>r.behavior);if(r)loadRun(r.id);else toast('还没有启用到位动作的记录，请新建演示。');}
  const source=e.target.closest('[data-source]');if(source)api('/api/source/'+source.dataset.source).then(d=>{$('#source-title').textContent=d.name;$('#source-text').textContent=d.text;$('#source-dialog').showModal();}).catch(e=>toast(e.message));
});
$('#play').onclick=()=>{if(state.run)setPlaying(!state.playing);};$('#restart').onclick=()=>{setPlaying(false);setTime(0);};$('#step-back').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)-1);};$('#step-next').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)+1);};$('#jump-end').onclick=()=>{setPlaying(false);setTime(state.run.replay.end);};$('#scrubber').oninput=e=>{setPlaying(false);setTime(Number(e.target.value));};$('#speed').onchange=e=>state.speed=Number(e.target.value);
for(const id of ['show-roads','show-trails','show-labels','show-landmarks','show-behaviors','show-starts'])$('#'+id).onchange=draw;
$('#fit-map').onclick=()=>{state.zoom=1;draw();};$('#map-zoom-in').onclick=()=>{state.zoom=Math.min(3,state.zoom*1.2);draw();};$('#map-zoom-out').onclick=()=>{state.zoom=Math.max(.5,state.zoom/1.2);draw();};$('#clear-focus').onclick=()=>{state.focus=null;$('#track-worker').value='all';renderTime();draw();};$('#event-filter').onchange=()=>{lastEventKey='';renderEvents();};$('#platform-filter').onchange=renderPlatforms;
$('#run-select').onchange=e=>loadRun(e.target.value);$('#refresh').onclick=()=>refreshCatalog().catch(e=>toast(e.message));for(const id of ['open-config','guide-run','runs-new'])$('#'+id).onclick=openConfig;$('#close-config').onclick=()=>$('#config-dialog').close();$('#close-source').onclick=()=>$('#source-dialog').close();$('#config-scenario').onchange=updateConfig;$('#config-motion').onchange=updateConfig;$('#config-avoid').onchange=updateConfig;
$('#open-actions').onclick=()=>{setPage('overview');$('#behavior-panel').scrollIntoView({block:'start'});};$('#show-report').onclick=()=>{if(state.run)window.open(artifact('report.html'),'_blank','noopener');};$('#track-worker').onchange=e=>{if(e.target.value==='all'){state.focus=null;renderTime();draw();}else focus('worker',e.target.value);};
document.addEventListener('keydown',e=>{if(!state.run||document.querySelector('dialog[open]')||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName))return;if(e.code==='Space'){e.preventDefault();setPlaying(!state.playing);}if(e.code==='ArrowRight'){e.preventDefault();setPlaying(false);setTime(state.t+1);}if(e.code==='ArrowLeft'){e.preventDefault();setPlaying(false);setTime(state.t-1);}});
new ResizeObserver(draw).observe(canvas);
let last=performance.now(),lastRender=0;
function animate(now){const dt=Math.min((now-last)/1000,.1);last=now;if(state.playing&&state.run){state.t=Math.min(state.run.replay.end,state.t+dt*state.speed);draw();if(now-lastRender>110){renderTime();lastRender=now;}if(state.t>=state.run.replay.end){setPlaying(false);renderTime();}}requestAnimationFrame(animate);}
requestAnimationFrame(animate);renderFiles();refreshCatalog().catch(e=>{$('#connection-text').textContent='连接失败';toast('无法连接本地服务：'+e.message);});
