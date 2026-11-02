'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modes = {recording:'专项串行回放',normal:'正常执行',failure:'失败重试',timeout:'超时恢复',kill:'成员失联',deviation:'进度偏差'};
const statuses = {pending:'待分配',running:'执行中',cancelling:'取消中',succeeded:'已完成',failed:'已失败'};
const types = {patrol:'巡逻警戒',blockade:'区域封控',recon:'协同侦察',assault:'机动突击',hold:'要点坚守'};
function taskLabel(j){const source=state.run?.scenario?.jobs?.find(x=>x.job_id===j.job_id);const wire=source?._task_type;return types[j.jtype||j.type]||({'T-PTL':'巡逻警戒','T-RCN':'协同侦察','T-SEC':'区域封控','T-HLD':'要点坚守'}[wire])||wire||j.jtype||j.type||'未标注任务';}
const icons = {patrol:'↻',blockade:'◇',recon:'⌕',assault:'↗',hold:'⌂'};
const kindNames = {UGV:'轮式车',TANK:'履带车',PLANE:'固定翼',WING:'飞翼'};
function buildingName(id){const k=String(id||'').replace(/^env[ _]city[ _]/,'').replace(/#\d+$/,'').replace(/_/g,' ').trim();const h=k.match(/^house\s*(\d+)/i);if(h)return '民居 '+Number(h[1]);const o=k.match(/^office\s*(\d+)/i);if(o)return '办公楼 '+Number(o[1]);return k;}
const taskPalette=['#288d79','#bd8534','#7264cb','#c27158','#478cac','#9a6b99'];
const events = {recording_start:'专项片段开始',recording_end:'专项片段结束',plan_emitted:'生成规划方案',job_dispatched:'下发作业',job_succeeded:'作业完成',job_requeued:'作业重新排队',job_failed:'作业失败',member_lost:'平台失联',timeout:'作业超时',deviation:'进度偏差',cancel_sent:'发出取消请求',command_abandoned:'终止失联成员指令',feedback_ignored:'反馈未采纳',behavior_event:'到位行为'};
const behaviorEvents = {phase:'行为阶段切换',checkpoint_visited:'到达检查点',cycle_completed:'完成一圈巡逻',posts_occupied:'封控占位就绪',intrusion_detected:'发现入侵',interceptor_assigned:'指派拦截',intercepted:'拦截成功',breach:'越界',map_initialised:'地图初始化',frontier_mapped:'前沿测绘',coverage_reached:'覆盖达标',report_sent:'成果回传',map_shared:'共享地图更新',all_staged:'全员到位',assault_started:'突击开始',effect_started:'效果施加开始',effect_applied:'动作结束',confirmed:'结果确认',salvo_fired:'齐射',ammo_depleted:'平台弹药耗尽',ammo_exhausted:'弹药耗尽终止',restrike_needed:'需要二次打击',control_established:'控制建立',control_lost:'控制丢失',suppression_gap:'压制中断',handover:'移交',assessment_requested:'评估发起',assessment_received:'评估回传',effect_achieved:'效果达成',deadline_exceeded:'执行超时',terminate:'任务终止',behavior_result:'效果判定结果',result_failed:'结果未达成',result_pending:'结果待评估',on_post:'上岗',handover_start:'接替开始',handover_complete:'接替完成',relief:'换班',behavior_complete:'行为完成',arrived_area:'进入作业区',route_failed:'路径失败',command_received:'受领任务',target_designated:'目标指示',all_in_position:'全员到位执行位',withdraw_started:'撤离开始',withdrawn:'撤离完成',withdraw_timeout:'撤离超时',confirmation_timeout:'确认超时',attack_window_missed:'错过攻击窗口',task_timeout:'任务超时',arrived:'到达点位',energy_depleted:'电量耗尽',start_snapped:'出发点吸附',target_appeared:'目标出现',target_detected:'发现目标',target_authorized:'识别为已授权',target_unauthorized:'识别为未授权',warning_issued:'发出警告',warning_effective:'警告有效·目标撤离',intercept_assigned:'指派拦阻',intercept_denied:'授权不足未拦阻',intercepted:'拦阻到位',breach:'未授权进入',authorized_pass:'授权放行',control_established:'控制建立',control_interrupted:'控制中断',control_restored:'控制恢复',containment_result:'封控结果'};
const triggerNames = {init:'首次规划',periodic:'周期更新',member_change:'成员变化',exec_fail:'执行失败',timeout:'超时',deviation:'进度偏差'};
const titles = {overview:'演示总览',tasks:'任务与分配',platforms:'平台状态',runs:'实验与报告',files:'项目文件'};
const sourceFiles = [['readme','README_v2.md','项目说明与运行方式'],['planner','planner_v2.py','六步规则规划器'],['coordinator','coordinator_v2.py','反馈、调度与重规划'],['fleet','mock_fleet.py','本地执行与反馈替身'],['contracts','contracts_v2.py','场景与消息数据契约']];
const state = {catalog:null,run:null,t:0,playing:false,speed:2,focus:null,page:'overview',zoom:1,frames:[],eventRows:[],hits:[],loadToken:0,busy:false,ckView:false};
let toastTimer, pollTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function api(url, options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error||'读取失败');return data;}
function num(value,d=1){return value==null?'未知':Number(value).toFixed(d);}
function no(pid){return '#'+String(pid||'').replace('rover_','');}
function stamp(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
function shortRun(id){if(id==='behavior_20261028_verify')return '专项验证记录 · 2026-10-28';if(id==='workbench_behavior_20261028')return '城市到位动作 · 2026-10-28';if(id==='avoid_run')return '旧版城市绕障 · 无到位动作';return id.replace('workbench_','').replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_.*$/,'$1-$2-$3 $4:$5:$6');}
function setPage(page){state.page=page;$$('.page').forEach(x=>x.classList.toggle('active',x.id==='page-'+page));$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page));$('#crumb').textContent=titles[page];$('#page-title').innerHTML=(page==='overview'?'把规划过程，看清楚。':esc(titles[page]))+'<span class="version">V2</span>';renderTime();draw();if(page==='overview')applyOverviewMode();window.scrollTo(0,0);}
// 演示总览有两个视图：全局分配（多任务）与区域封控（单个封控区）。它们共用
// 同一个页面与顶部运行选择，不再各自是一个独立路由，避免"换数据源才看到
// 其它任务"这种两套口径。
function hasContainment(){return !!(state.run&&state.run.replay&&state.run.replay.containment);}
function applyOverviewMode(){
  const ck=state.page==='overview'&&state.ckView&&hasContainment();
  const mapView=$('#overview-map-view'),ckView=$('#overview-ck-view'),tabs=$('#overview-tabs');
  if(mapView)mapView.hidden=ck;
  if(ckView)ckView.hidden=!ck;
  if(tabs)tabs.hidden=!hasContainment();
  $$('.ov-tab').forEach(b=>b.classList.toggle('active',(b.dataset.ov==='containment')===ck));
  $('#overview-view')?.classList.toggle('active',!ck);
  const badge=$('#view-badge');if(badge&&state.page==='overview')badge.textContent=ck?'区域封控':'全局分配';
  if(window.ContainmentPage){
    if(ck){
      // 切进封控视图时沿用主时间轴的时刻；切回全局分配时把时刻带回去。
      if(!state.ckViewApplied)window.ContainmentPage.syncTime(state.t);
      window.ContainmentPage.show();
    }else{
      if(state.ckViewApplied){const t=window.ContainmentPage.time();if(Number.isFinite(t))setTime(t);}
      window.ContainmentPage.hide();
    }
  }
  state.ckViewApplied=ck;
  if(!ck){state.zoom=1;setBounds();draw();}
}
function showOverviewMode(mode){
  state.ckView=mode==='containment';
  if(state.page!=='overview')setPage('overview');
  else applyOverviewMode();
}
// 没有封控动作记录时，明确说明"为什么看不到"，并给一键入口；
// 否则用户会以为 T1 这个封控作业也应该画出边界和探测圈。
function updateCkHint(){
  const box=$('#ck-hint');if(!box)return;
  if(hasContainment()){box.hidden=true;box.innerHTML='';return;}
  const runs=(state.catalog&&state.catalog.runs)||[];
  const candidate=runs.find(r=>r.scenario==='interop_containment'&&r.id!==state.run?.id);
  if(!candidate){box.hidden=true;box.innerHTML='';return;}
  box.hidden=false;
  box.innerHTML='<span>当前运行没有区域封控的动作记录：这里的 T1 只是历史样例的封控作业（按到点作业执行），'+
    '边界、探测圈、警告与拦阻只在“区域封控”演示运行里生成。</span>'+
    '<button class="button small primary" data-ck-run="'+esc(candidate.id)+'">打开最近一次区域封控演示 →</button>';
}
function eventCategory(e){if(e.kind==='plan_emitted')return 'planning';if(e.kind==='behavior_event')return 'behavior';if(['member_lost','timeout','deviation','job_requeued','job_failed','cancel_sent','command_abandoned','feedback_ignored'].includes(e.kind))return 'exception';return 'task';}
function eventDetail(e){if(e.kind==='plan_emitted')return (e.triggers||[]).map(x=>x.split(':')[0]).join(' / ')+' · '+e.n_assignments+' 项指派';if(e.kind==='behavior_event'){const ev=e.event||{},sub=ev.kind;let d=behaviorEvents[sub]||sub||'';if(ev.phase)d+=' · '+ev.phase;if(ev.pid)d+=' · '+ev.pid;if(ev.cycle!=null)d+=' · 第'+ev.cycle+'圈';if(ev.coverage!=null)d+=' · 覆盖'+Math.round(ev.coverage*100)+'%';
  // T-ASL 效果判定事件的摘要字段
  if(ev.rounds!=null&&ev.pids)d+=' · '+(ev.pids||[]).map(no).join('/')+' 各'+ev.rounds+'发';
  if(ev.damage_level!=null)d+=' · 毁伤等级'+num(ev.damage_level);
  if(ev.level!=null&&ev.required!=null)d+=' · '+num(ev.level,1)+'/'+num(ev.required,1);
  if(ev.gap_s!=null)d+=' · 中断'+num(ev.gap_s,1)+' s';
  if(ev.held_s!=null)d+=' · 保持'+num(ev.held_s,1)+' s';
  if(ev.occupants!=null)d+=' · 在位'+ev.occupants;
  if(ev.at!=null&&sub==='effect_achieved')d+=' · T+'+num(ev.at,1)+' s';
  if(ev.by)d+=' · '+ev.by;
  if(ev.source)d+=' · '+ev.source;
  if(ev.overall)d+=' · '+(resultStatusNames[ev.overall]||ev.overall);
  if(ev.reason)d+=' · '+(terminationNames[ev.reason]||ev.reason);
  if(ev.verified===false)d+=' · 桩·未验证';
  if(ev.latency_s!=null)d+=' · 时延'+num(ev.latency_s,1)+' s';
  return d;}if(e.pids)return e.pids.map(no).join(' · ')+' · 第 '+e.attempt+' 次尝试';return e.reason||e.cause||e.pid||e.command_id||e.job_id||'';}
const resultStatusNames={achieved:'达成',failed:'未达成',pending:'待确认',info:'信息',succeeded:'成功'};
const terminationNames={ammo_exhausted:'弹药耗尽',deadline_exceeded:'执行超时',confirmation_timeout:'确认超时',timeout:'任务超时',attack_window_missed:'错过攻击窗口',result_failed:'评估未达成',withdrawn:'撤离完成',result_confirmed:'结果已确认'};
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
      if(['job_dispatched','recording_start'].includes(e.kind)&&j){j.status='running';j.assignedAt=e.sim_s;j.attempts=e.attempt;j.pids=e.pids;j.start=e.planned_start;j.end=e.planned_end;if(e.attempt>1)retries++;}
      if(e.kind==='feedback_applied'){const ev=e.event,k=jobs[ev.job_id];if(k){k.progress=Math.max(k.progress,ev.progress||0);k.phase=ev.phase;if(!['succeeded','failed','cancelling'].includes(k.status))k.status='running';}}
      if(e.kind==='behavior_event'){
        const ev=e.event||{},k=jobs[ev.job_id];
        if(k){const b=k.behavior;if(!['behavior_detail','approach_route'].includes(ev.kind))b.last=ev.kind;b.at=e.sim_s;
          if(ev.kind==='behavior_detail'){b.detail={debug:ev.debug,params:ev.params,phase:ev.phase,at:e.sim_s};b.routes=b.routes||{};for(const r of ev.routes||[])b.routes[r.pid]={...r,recordedAt:e.sim_s};}
          if(ev.kind==='approach_route'){b.routes=b.routes||{};b.routes[ev.route.pid]={...ev.route,recordedAt:e.sim_s};}
          if(ev.kind==='behavior_structure')b.startedAt=e.sim_s;
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
      if(e.kind==='recording_end'&&j){j.status=e.succeeded?'succeeded':'failed';j.progress=e.succeeded?data.report.jobs.find(x=>x.job_id===e.job_id).work:0;}
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
function setTime(t){if(!state.run)return;const range=state.taskWindow;state.t=Math.min(range?.end??state.run.replay.end,Math.max(range?.start??0,t));renderTime();draw();}
function setPlaying(yes){state.playing=!!yes;if(yes&&state.t>=(state.taskWindow?.end??state.run.replay.end))state.t=state.taskWindow?.start??0;$('#play').textContent=yes?'Ⅱ 暂停':'▶ 播放';$('#play-state').textContent=yes?'播放中':'已暂停';}
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
  $('#behavior-list').innerHTML=enabled?state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id];return `<button class="behavior-tile ${selectedJobId()===j.job_id?'selected':''}" style="--task-color:${taskColor(j.job_id)}" data-job="${esc(j.job_id)}"><span class="behavior-tile-head"><b>${esc(j.job_id)} · ${esc(taskLabel(j))}</b><span>${esc(s.status==='succeeded'?'已完成':phaseName(s.phase))}</span></span><small>${esc(behaviorSummary(j,s))}</small></button>`;}).join(''):'<div class="empty">本轮轨迹只记录到点作业。<button class="button small" data-behavior-run>载入动作演示 →</button></div>';
  const keyKinds=new Set(['cycle_completed','posts_occupied','intrusion_detected','intercepted','handover_start','handover_complete','map_initialised','coverage_reached','report_sent','all_staged','effect_applied','confirmed']);
  const jid=selectedJobId();
  $('#behavior-milestones').innerHTML=enabled?state.eventRows.filter(e=>e.kind==='behavior_event'&&keyKinds.has(e.event?.kind)&&(!jid||e.job_id===jid)).map(e=>`<button class="milestone ${e.sim_s>state.t?'future':'occurred'}" data-event-time="${e.sim_s}" data-event-job="${esc(e.job_id)}"><span>${e.sim_s} s${e.sim_s>state.t?' · 未发生':''}</span>${esc(e.job_id)} · ${esc(eventTitle(e))}</button>`).join(''):'';
}
function renderTime(){
  if(!state.run)return;const f=frame(),jobs=Object.values(f.jobs),done=jobs.filter(j=>j.status==='succeeded').length;
  $('#stat-done').textContent=done;$('#stat-total').textContent='/ '+jobs.length;$('#done-bar').style.width=100*done/jobs.length+'%';$('#done-note').textContent=done===jobs.length?'本轮全部完成':'按当前反馈统计';
  $('#stat-alive').textContent=state.run.replay.workers.length-f.lost.length;$('#stat-plans').textContent=state.run.report.recording?'未记录':f.plans;$('#plan-note').textContent=state.run.report.recording?'保存的专项串行记录':'已重试 '+f.retries+' 次 · 已超时 '+f.timeouts+' 次';$('#stat-clock').textContent=state.t.toFixed(1);$('#clock').textContent=(state.taskWindow?state.t-state.taskWindow.start:state.t).toFixed(1);$('#scrubber').value=state.t;
  $('#task-list').innerHTML=state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<button class="task-row ${selectedJobId()===j.job_id?'selected':''}" style="--task-color:${taskColor(j.job_id)}" data-job="${esc(j.job_id)}"><div class="task-line"><span class="job-icon">${icons[j.jtype]||'◇'}</span><b>${esc(taskLabel(j)||j.jtype)}<span class="task-id">${esc(j.job_id)}</span></b><span class="task-status ${s.status}">${statuses[s.status]}</span></div><div class="task-progress"><div class="progress-track"><i style="width:${pct}%"></i></div><span>${Math.round(pct)}%</span></div><div class="task-assigned">${s.pids.length?s.pids.map(no).join(' · '):'等待可行分配'}${state.run.report.behavior?' · '+esc(phaseName(s.phase)):''}</div></button>`;}).join('');
  renderInspector();renderEvents();renderBehaviors();renderStage();renderTheater();
  if(state.page==='tasks')renderTasks();if(state.page==='platforms')renderPlatforms();
}
function focus(type,id,go=false){const w=type==='worker'?state.run.replay.workers.find(w=>w.pid===id):null;state.focus={type,id,jobId:state.taskWindow?.jobId||(w?activeWorkerJob(w):null)};state.zoom=1;setBounds();if(go)setPage('overview');renderTime();draw();}
function renderInspector(){
  const f=state.focus;if(!f){$('#inspector').innerHTML='<p class="muted">点击地图平台或任务，查看当前位置、分配关系与反馈。也可从右上角新建演示，比较异常处理。</p>';return;}
  if(f.type==='worker'){
    const w=state.run.replay.workers.find(w=>w.pid===f.id);if(!w)return;const p=workerAt(w);
    const active=p.job&&frame().jobs[p.job]?.status==='running';
    $('#inspector').innerHTML=`<div class="focus-title"><span style="color:${taskColor(activeWorkerJob(w))}">●</span> ${esc(w.pid)} · ${esc(w.kind_name)}</div><dl><div><dt>当前坐标</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度 / 场景单位</dt><dd>${num(p.z)}</dd></div><div><dt>当前作业</dt><dd>${p.lost?'成员失联':active?esc(p.job):'空闲 / 最近反馈'}</dd></div><div><dt>当前动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>累计反馈路程</dt><dd>${num(p.distance)}</dd></div><div><dt>最近位置反馈</dt><dd>${p.t==null?'仅场景初始位':num(p.t,0)+' s'}</dd></div></dl>`;
  }else{
    const j=state.run.report.jobs.find(j=>j.job_id===f.id);if(!j)return;const s=frame().jobs[j.job_id];
    $('#inspector').innerHTML=`<div class="focus-title">${esc(j.job_id)} · ${esc(taskLabel(j))}</div><dl><div><dt>当前状态</dt><dd>${statuses[s.status]}</dd></div><div><dt>工作量</dt><dd>${num(s.progress)} / ${j.work}</dd></div><div><dt>当前动作阶段</dt><dd>${esc(phaseName(s.phase))}</dd></div><div><dt>动作记录</dt><dd>${esc(behaviorSummary(j,s))}</dd></div><div><dt>当前指派</dt><dd>${s.pids.map(no).join(' · ')||'尚未分配'}</dd></div><div><dt>需求人数</dt><dd>${j.crew} 台</dd></div><div><dt>计划开工 / 完工</dt><dd>${s.start==null?'未排程':s.start+' / '+s.end+' s'}</dd></div><div><dt>目标坐标</dt><dd>${j.pos.map(x=>num(x)).join(', ')}</dd></div></dl>`;
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
  $('#task-table').innerHTML=state.run.report.jobs.map(j=>{const s=frame().jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<tr class="${state.focus?.id===j.job_id?'selected':''}"><td><button class="text-button" data-job="${esc(j.job_id)}" data-locate>${esc(j.job_id)} · ${esc(taskLabel(j))}</button><small>协同需求 ${j.crew} 台 · ${esc(j.need_sensor||'无专属传感器')}</small></td><td>${j.pos.map(x=>num(x)).join(', ')}</td><td><span class="pill ${s.status==='failed'?'warning':''}">${statuses[s.status]}</span><small>${esc(phaseName(s.phase))}</small></td><td>${state.run.report.recording?'按记录阶段':num(s.progress)+' / '+j.work}<div class="progress-track table-progress"><i style="width:${pct}%"></i></div></td><td>${s.pids.map(no).join(' · ')||'—'}</td><td>${s.attempts}</td><td>${j.window.join(' – ')} s</td></tr>`;}).join('');
}
function renderPlatforms(){
  const filter=$('#platform-filter').value;
  $('#platform-grid').innerHTML=state.run.replay.workers.filter(w=>filter==='all'||w.kind===filter).map(w=>{const p=workerAt(w);return `<button class="platform-tile" data-worker="${esc(w.pid)}" data-locate><h3><i style="background:${taskColor(activeWorkerJob(w))}"></i>${esc(w.pid)}<span>${p.lost?'失联':'可用'}</span></h3><p>${esc(w.kind_name)} · ${esc(w.kind)}</p><dl><div><dt>位置</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度</dt><dd>${num(p.z)}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>最近作业</dt><dd>${esc(p.job||'—')}</dd></div><div><dt>动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div></dl></button>`;}).join('');
}
function renderRuns(){
  $('#runs-table').innerHTML=state.catalog.runs.map(r=>`<tr class="${r.id===state.run?.id?'selected':''}"><td><button class="text-button" data-load-run="${esc(r.id)}">${esc(shortRun(r.id))}</button><small>${esc(r.objective)} · ${r.recording?'记录已保存':r.settled?'已结算':'达到步数上限，未结算'}</small></td><td>${modes[r.mode]||esc(r.mode)}<small>${r.motion==='real'?'逐步运动':'瞬移'}${r.avoid?' · 建筑绕障':''}${r.behavior?' · 到位行为':''}${r.planner==='interop'?' · 融合规划':''}</small></td><td>${r.done} / ${r.total}</td><td>${r.end} s</td><td>${num(r.energy)}</td><td>${r.recording?'未记录':r.retries+' / '+r.timeouts}</td><td><button class="text-button" data-load-run="${esc(r.id)}">载入回放 ↗</button></td></tr>`).join('');
  if(!state.run)return;const r=state.run.report;
  $('#report-status').textContent=r.all_succeeded?'全部完成':r.settled?'本轮已结算':'未结算';$('#report-status').classList.toggle('warning',!r.all_succeeded);
  $('#report-summary').innerHTML=[[r.done+'/'+r.jobs.length,r.recording?'记录完成的片段':'工作量达标作业'],[r.simulated_until_s+' s','仿真运行终点'],[num(r.used_energy),'累计模型耗电'],[r.plans??'未记录','规划方案数'],[r.retries??'未记录','重试次数'],[r.timeouts??'未记录','超时次数']].map(([v,l])=>`<div><b>${esc(v)}</b><span>${l}</span></div>`).join('');
  const total=Math.max(1,...Object.values(r.triggers||{}));$('#triggers').innerHTML=Object.entries(r.triggers||{}).map(([k,v])=>`<div class="trigger-row"><span>${triggerNames[k]||esc(k)}</span><div><i style="width:${100*v/total}%"></i></div><b>${v}</b></div>`).join('');
  for(const id of ['download-report','show-report'])$('#'+id).hidden=!!r.recording;
  $('#download-report').href=artifact('report.json');$('#download-trace').href=artifact(r.recording?'behavior_trace.json':'trace.jsonl');$('#result-scope').textContent=r.recording?'本页为原始专项串行记录；未记录的规划、工作量与能耗指标不补造。':r.behavior?'本轮启用到位行为；作业终态来自已保存的模拟日志。':'本轮未启用到位行为；完成只表示原模型工作量达标。';
}
function artifact(name){return '/artifacts/'+encodeURIComponent(state.run.id)+'/'+name;}
const fileDescriptions={'manifest.json':'运行配置、来源与环境','scenario.json':'本轮实际场景快照','report.json':'最终指标与状态','trace.jsonl':'逐条原始反馈与审计','summary.txt':'文本结果摘要','report.html':'原始可视化报告','trajectory.html':'原始轨迹播放器','request.json':'工作台请求参数','worker.log':'本轮运行日志','plan.json':'4.2 计划层与执行层完整结构','assignments.csv':'槽位分配字段子集','commands.csv':'速度指令字段子集','report.md':'4.2 计划报告（路径/指令/未分配）','ros2_commands.txt':'可直接粘贴的 ros2 topic pub 命令'};
function renderFiles(){
  $('#source-files').innerHTML=sourceFiles.map(([key,name,desc])=>`<button class="file-item" data-source="${key}"><span>↗</span><b>${name}</b><small>${desc}</small></button>`).join('');
  if(!state.run)return;$('#output-path').textContent='planning_middle_demo/outputs/'+state.run.id+'/';
  $('#artifact-files').innerHTML=state.run.files.map(n=>`<a class="file-item" href="${artifact(n)}" target="_blank" rel="noopener"><span>↗</span><b>${n}</b><small>${fileDescriptions[n]||'运行产物'}</small></a>`).join('');
}
async function loadRun(id,autoplay=false){
  const token=++state.loadToken;closeTheater();setPlaying(false);
  try{
    const data=await api('/api/runs/'+encodeURIComponent(id));if(token!==state.loadToken)return;
    state.run=data;
    let mapNote=$('#scene-map-note');if(!mapNote){mapNote=document.createElement('div');mapNote.id='scene-map-note';mapNote.className='scene-map-note';document.querySelector('.map-legend').after(mapNote);}
    mapNote.textContent=data.scene_map?.note||data.geometry_note||'';
document.body.classList.toggle('recording-data',!!data.report.recording);state.t=0;state.focus=null;state.zoom=1;state.frames=makeFrames(data);state.eventRows=data.trace.map((e,index)=>{if(e.kind==='behavior_event'&&e.event&&e.event.job_id&&!e.job_id)e={...e,job_id:e.event.job_id};return {...e,index};}).filter(e=>events[e.kind]&&!(e.kind==='behavior_event'&&['behavior_structure','behavior_detail','approach_route'].includes(e.event?.kind)));lastEventKey='';
    $('#run-select').value=id;$('#run-mode').textContent=modes[data.report.mode]||data.report.mode;$('#run-semantic').textContent=data.report.recording?data.report.recording_source.note:(data.report.motion==='real'?'逐步运动':'瞬移')+(data.report.avoid?' · 静态建筑绕障':'')+(data.report.behavior?' · 到位行为':'')+' · '+(data.report.objective||'makespan');
    $('#stat-end').textContent=data.replay.end;$('#duration').textContent=data.replay.end;$('#scrubber').max=data.replay.end;$('#timeline-mid').textContent=stamp(data.replay.end/2);$('#timeline-end').textContent=stamp(data.replay.end);$('#task-count').textContent=data.report.jobs.length;$('#side-jobs').textContent=String(data.report.jobs.length).padStart(2,'0');
    $('#fleet-note').textContent=[...new Set(data.replay.workers.map(w=>w.kind_name))].join(' · ');
    const options=data.report.jobs.map(j=>`<option value="${esc(j.job_id)}">${esc(j.job_id)} · ${esc(taskLabel(j))}</option>`).join('');$('#task-select').innerHTML='<option value="">选择一项任务，观看执行过程</option>'+options;$('#theater-task').innerHTML=options;$('#model-note').textContent='选任务后打开大画幅执行回放';setBounds();renderTime();renderRuns();renderFiles();draw();if(window.ContainmentPage)window.ContainmentPage.load(data);
    const ckBtn=$('#open-containment');if(ckBtn)ckBtn.hidden=!data.replay.containment;
    // 只含区域封控一个作业的运行，默认就站在封控视图：这个运行本身就是
    // 一次封控演示，"全局分配"只用来对照机动与任务位置。
    state.ckView=!!(data.replay.containment&&data.report.jobs.length===1);
    applyOverviewMode();
    updateCkHint();
    if(autoplay)setPlaying(true);  }catch(e){toast('载入失败：'+e.message);}
}
async function refreshCatalog(selectId){
  const data=await api('/api/catalog');state.catalog=data;
  $('#connection-text').textContent='本机已连接'+(data.version?' · '+data.version:'');
  const caps=data.features||{};
  if(!caps.planner)toast('工作台服务是旧版本：请关闭旧窗口后重新双击 启动工作台.cmd');
  // 旧服务不认 interop_containment，也不返回封控回放数据：直接禁用该场景并说明，
  // 否则用户只会看到"无效参数"，以为是新场景坏了。
  if(!caps.containment){
    const opt=[...document.querySelectorAll('#config-scenario option')].find(o=>o.value==='interop_containment');
    if(opt){opt.disabled=true;opt.textContent='区域封控 · 需要重启工作台服务（当前服务版本 '+esc(data.version||'未知')+'）';}
    toast('当前工作台服务（'+ (data.version||'未知版本') +'）不含区域封控：请关闭运行中的工作台窗口后重新双击 启动工作台.cmd。');
  }
  $('#run-select').innerHTML=data.runs.map(r=>{const sc=r.scenario?((data.scenarios&&data.scenarios[r.scenario])||r.scenario):null;return `<option value="${esc(r.id)}">${sc?esc(sc)+' · ':''}${r.total} 个任务 · ${r.behavior_details?'动作与避障细节':r.behavior?'到位动作':'到点作业'} · ${modes[r.mode]||r.mode} · ${esc(shortRun(r.id))}</option>`;}).join('');
  if(selectId||!state.run){const requested=new URLSearchParams(location.search).get('source');const id=selectId||(data.runs.some(r=>r.id===requested)?requested:null)||(data.runs.find(r=>r.id===data.default_run)||data.runs.find(r=>r.behavior)||data.runs[0])?.id;if(id){await loadRun(id);const task=new URLSearchParams(location.search).get('task');if(task&&state.run.report.jobs.some(j=>j.job_id===task)){openTask(task,false);const params=new URLSearchParams(location.search);if(params.get('view')==='spatial')state.taskView='spatial';else if(params.get('view')==='process')state.taskView='process';if(params.has('t'))setTime(Number(params.get('t')));renderTheater();draw();}}else toast('还没有运行记录，点击新建演示开始。');}
  else{$('#run-select').value=state.run.id;renderRuns();}
  if(data.process?.state==='running')watchProcess(data.process.id);
  updateCkHint();
  const pageParam=new URLSearchParams(location.search).get('page');
  if(pageParam==='containment')showOverviewMode('containment');
  else if(pageParam&&titles[pageParam]&&pageParam!==state.page)setPage(pageParam);
}
function setBusy(b){state.busy=b;$('#busy-banner').hidden=!b;$('#submit-run').disabled=b;$('#submit-run').textContent=b?'仿真运行中…':'运行演示 →';}
function watchProcess(id){
  setBusy(true);clearTimeout(pollTimer);
  async function poll(){try{const data=await api('/api/catalog');if(data.process?.id!==id){setBusy(false);return;}if(data.process.state==='running'){pollTimer=setTimeout(poll,800);return;}setBusy(false);await refreshCatalog();if(data.process.state==='complete'){await loadRun(id,true);setPage('overview');const hasCk=!!(state.run&&state.run.replay&&state.run.replay.containment);toast(hasCk?'本轮结果已保存，已打开“区域封控”视图；可切到“全局分配”对照机动与任务位置。':'本轮结果已保存，正在回放实际反馈。');}else{const log=await fetch('/artifacts/'+encodeURIComponent(id)+'/worker.log').then(r=>r.text());toast('运行失败：'+log.slice(-200));}}catch(e){setBusy(false);toast('状态读取失败：'+e.message);}}
  pollTimer=setTimeout(poll,800);
}
function updateConfig(){const scenario=$('#config-scenario').value,interop=scenario.startsWith('interop'),aslInterop=scenario==='interop_asl',containment=scenario==='interop_containment',base=scenario==='asl_city',allow=base||aslInterop||containment;$('#config-avoid').disabled=!allow||aslInterop||containment;if(!allow)$('#config-avoid').checked=false;else if(aslInterop||containment)$('#config-avoid').checked=true;$('#config-behavior').disabled=!allow||aslInterop||containment||!$('#config-avoid').checked;if(!allow||!$('#config-avoid').checked)$('#config-behavior').checked=false;else if(aslInterop||containment)$('#config-behavior').checked=true;$('#config-effect').disabled=!base;$('#config-effect-field').hidden=!base;for(const id of ['config-avoid','config-behavior'])$('#'+id).closest('label').hidden=!allow;$('#config-scope-note').textContent=containment?'区域封控：融合层规划 + 基座逐步运动与到位行为；占位/警告/拦阻由行为层执行，结果只作本地仿真结论。':aslInterop?'融合版机动突击（T-ASL）：规划器固定 interop，侦察/突击/评估席位由统一层分配；打击与效果判定由基座行为层执行，效果类型以 4.1 消息为准。':interop?'融合层中性任务：规划器固定为 interop，逐步运动；突击效果类型不适用。':'历史城市场景沿用基座规划器与原有行为链；可在运行记录中查看已保存的地图与回放。';
  // 仿真步数跟随场景默认（asl_city 机动距离远，需要 620 步）；
  // 用户改过自定义值时只保证 asl_city 不低于 620。
  const ticks=$('#config-form [name=max_ticks]');ticks.max=700;
  const defaults={asl_city:620,interop_neutral:260,interop_containment:320,interop_asl:700};
  const untouched=Object.values(defaults).includes(Number(ticks.value));
  if(untouched)ticks.value=defaults[$('#config-scenario').value]||200;
  else if($('#config-scenario').value==='asl_city')ticks.value=Math.max(Number(ticks.value),620);}
function openConfig(){updateConfig();$('#config-error').hidden=true;$('#config-dialog').showModal();}
$('#config-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target),scenario=f.get('scenario'),interop=scenario.startsWith('interop'),config={scenario,mode:f.get('mode'),motion:'real',objective:f.get('objective'),planner:interop?'interop':'base',max_ticks:Number(f.get('max_ticks')),avoid:$('#config-avoid').checked&&!$('#config-avoid').disabled,behavior:$('#config-behavior').checked&&!$('#config-behavior').disabled,...(!$('#config-effect').disabled?{effect_kind:f.get('effect_kind')}:{})};try{const result=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});$('#config-dialog').close();watchProcess(result.id);}catch(err){$('#config-error').textContent=err.message;$('#config-error').hidden=false;}});
const theater=$('#task-theater'),mapCard=$('.map-card'),sceneHome=$('.overview-grid');
function taskRange(jid){
  const rows=state.run.trace,dispatch=rows.find(e=>['job_dispatched','recording_start'].includes(e.kind)&&e.job_id===jid);
  const structure=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid);
  const samples=state.run.replay.workers.flatMap(w=>w.samples.filter(p=>p.job===jid)).sort((a,b)=>a.t-b.t);
  const start=dispatch?.sim_s??samples[0]?.t??0,execution=structure?.sim_s??samples.find(p=>p.phase&&p.phase!=='travel')?.t??start;
  const end=rows.find(e=>['job_succeeded','job_failed','recording_end'].includes(e.kind)&&e.job_id===jid)?.sim_s??Math.max(start+1,...samples.map(p=>p.t));
  return {jobId:jid,dispatch:start,start,execution,end:Math.max(execution,end)};
}
function updateTaskTimeline(){
  const range=state.taskWindow;if(!range)return;
  $('#scrubber').min=range.start;$('#scrubber').max=range.end;$('#duration').textContent=range.end-range.start;
  $('.player-clock').title='本任务观看区间经过时间；绝对仿真时刻见右侧';
  $('#timeline-mid').textContent=stamp((range.end-range.start)/2);$('#timeline-end').textContent=stamp(range.end-range.start);$('.timeline-labels>span').textContent='00:00';
}
function openTask(jid,autoplay=true){
  if(!state.run||!state.run.report.jobs.some(j=>j.job_id===jid))return;
  setPlaying(false);setPage('overview');state.speed=1;$('#speed').value='1';state.taskWindow=taskRange(jid);state.taskView='spatial';state.focus={type:'job',id:jid};state.t=state.taskWindow.start;state.zoom=1;
  $('#task-select').value=jid;$('#theater-task').value=jid;$('#theater-title').textContent=jid+' · '+taskLabel(state.run.report.jobs.find(j=>j.job_id===jid))+' · 执行回放';
  $('#theater-main').append(mapCard);if(!theater.open)theater.showModal();updateTaskTimeline();setBounds();renderTime();draw();
  if(autoplay)setPlaying(true);
}
function closeTheater(){
  if(!state.taskWindow)return;setPlaying(false);state.taskWindow=null;state.focus=null;$('#hold-chapters').hidden=true;$('#action-chapters').hidden=true;mapCard.classList.remove('process-view','special-task');$('#task-data-warning').hidden=true;
  sceneHome.insertBefore(mapCard,sceneHome.firstChild);if(theater.open)theater.close();$('#task-select').value='';
  $('#scrubber').min=0;$('#scrubber').max=state.run.replay.end;$('#duration').textContent=state.run.replay.end;$('.timeline-labels>span').textContent='00:00';$('#timeline-mid').textContent=stamp(state.run.replay.end/2);$('#timeline-end').textContent=stamp(state.run.replay.end);
  state.zoom=1;setBounds();renderTime();draw();
}
function metricValue(v){
  // 指标值可能是标量、区间数组或{平台: 余弹}字典，统一压成一行可读文本
  if(v==null)return '—';
  if(Array.isArray(v))return v.map(x=>metricValue(x)).join('–');
  if(typeof v==='object')return Object.entries(v).map(([k,x])=>no(k)+':'+metricValue(x)).join('/');
  return String(v);
}
function assaultResultHtml(jid){
  // T-ASL 逐项结算区（规范 §7）：结果只认评估接口回传（behavior_result），
  // 过程数据只作展示，不以预测冒充确认。
  const structure=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid);
  if(!structure||structure.type!=='assault')return '';
  const events=state.run.trace.filter(e=>e.kind==='behavior_event'&&e.event?.kind==='behavior_result'&&e.event.job_id===jid&&e.sim_s<=state.t);
  // 评估回传可能早于"行为终态"落盘（确认发生在阶段结束前）。此时先用
  // assessment_received 的逐项结果展示，不把已确认的结论压到结果事件之后。
  const assess=state.run.trace.filter(e=>e.kind==='behavior_event'&&e.event?.kind==='assessment_received'&&e.event.job_id===jid&&e.sim_s<=state.t);
  let result=events.length?events[events.length-1].event:null;
  if(!result&&assess.length){
    const ev=assess[assess.length-1].event,metricItem=(ev.items||[]).find(x=>x.id==='effect_metric');
    result={items:ev.items||[],auxiliary:(metricItem&&metricItem.metric&&metricItem.metric.auxiliary)||[],
            overall:ev.overall,adjudicator:ev.source,verified:ev.verified,
            termination:null,role_check:null,awaiting_finish:true};
  }
  const roleSet=[...new Set(Object.values(structure.roles||{}))].join(' / ');
  let html=`<div class="assault-result"><h4>效果判定 · ${esc(structure.effect||structure.effect_kind||'突击')}<span>${esc(structure.target_id||jid)} · 第 ${structure.attempt??1} 次执行${roleSet?' · '+esc(roleSet):''}</span></h4>`;
  if(result){
    // 辅助指标：先亮"能不能打、代价多大"，再列逐项结算。判定只认本任务/本版本。
    const aux=result.auxiliary||[];
    html+='<div class="aux-grid">'+aux.map(r=>{const verdict=String(r.verdict||'');const cls=verdict==='达标'?'ok':verdict==='未达标'?'bad':verdict==='需要'||verdict==='有损失'?'warn':'info';return `<div class="aux ${cls}"><small>${esc(r.label)}</small><b>${esc(metricValue(r.value))}<i>${esc(r.unit||'')}</i></b><span>${esc(verdict)}</span><em>${esc(r.note||'')}</em></div>`;}).join('')+'</div>';
    const items=(result.items||[]).filter(it=>it.required);
    html+='<ul class="result-items">'+items.map(it=>{
      const metric=it.metric&&!['null'].includes(String(it.metric))?Object.entries(it.metric).map(([k,v])=>k+' '+metricValue(v)).join(' · '):'';
      return `<li class="${esc(it.status)}"><b>${esc(resultStatusNames[it.status]||it.status)}</b><span>${esc(it.label||it.id)}${it.required?'':'（信息项）'}</span><small>${esc(metric)}${metric&&it.evidence?' · ':''}${esc(it.evidence||'')}</small></li>`;
    }).join('')+'</ul>';
    html+=`<p class="result-overall ${esc(result.overall||'')}">总体结论：<b>${esc(resultStatusNames[result.overall]||result.overall||'')}</b>${result.termination?' · 终止：'+esc(terminationNames[result.termination]||result.termination):''}${result.awaiting_finish?' · 任务终态尚未结算':''}</p>`;
    if(result.role_check&&result.role_check.required>0)html+=`<p class="result-source">角色校核：突击组载荷≥${num(result.role_check.required)} ${result.role_check.ok?'· 通过':'· 未通过'}</p>`;
    html+=`<p class="result-source">评估来源：${esc(result.adjudicator||'')}${result.verified?'':' · 桩判定 · 未验证'}</p>`;
  }else{
    const dbg=frame().jobs[jid]?.behavior?.detail?.debug||{};
    const live=[dbg.damage_level?'毁伤等级 '+num(dbg.damage_level):null,dbg.suppression_s?'连续压制 '+num(dbg.suppression_s)+' s':null,dbg.control_s?'控制时长 '+num(dbg.control_s)+' s':null,dbg.hold_s?'坚守 '+num(dbg.hold_s)+' s':null,dbg.counterattacks?'反击 '+dbg.counterattacks+' 次':null,dbg.losses?'我方损失 '+dbg.losses+' 台':null,dbg.ammo?'剩余弹药 '+Object.values(dbg.ammo).filter(v=>v!=null).join('/')+' 发':null].filter(Boolean).join(' · ');
    html+=`<p class="result-pending-note">评估结果尚未回传${live?' · 当前过程量：'+esc(live):''}；最终逐项结论以评估接口回传为准。</p>`;
  }
  return html+'</div>';
}
function renderTheater(){
  if(!state.taskWindow)return;const jid=state.taskWindow.jobId,j=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],b=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid&&b.sim_s<=state.t);
  const bh=j.behavior||{},order=state.run.report.behavior?`<div class="task-order"><div class="eyebrow">TASK ORDER · 任务指令</div><div class="order-head"><b>${esc(jid)} · ${esc(taskLabel(j))}</b><span>${esc(b?.effect||'')}${b?.target_id?' · 目标 '+esc(b.target_id):''}</span></div><div class="order-meta"><span>时间窗 ${j.window[0]}–${j.window[1]} s</span><span>执行截止 ${bh.execute_deadline??'—'} s</span><span>撤离截止 ${bh.withdraw_deadline??'—'} s</span><span>兵力 ${s.pids.length} 台</span></div>${bh.roe?`<p>规则：${esc(bh.roe)}</p>`:''}</div>`:'';
  const elapsed=Math.max(0,state.t-state.taskWindow.execution);$('#theater-details').innerHTML=order+`<div class="detail-phase" style="color:${taskColor(jid)}">${s.status==='succeeded'?'已完成':esc(phaseName(s.phase))}</div><div class="detail-metric">${esc(behaviorSummary(j,s))}</div><dl><div><dt>${state.run.report.recording?'进度依据':'任务工作量'}</dt><dd>${state.run.report.recording?'已记录阶段':num(s.progress)+' / '+j.work}</dd></div><div><dt>执行经过</dt><dd>${num(elapsed)} s</dd></div><div><dt>当前仿真时刻</dt><dd>${num(state.t)} s</dd></div><div><dt>${state.run.report.recording?'片段起点':'任务下发'}</dt><dd>${state.taskWindow.dispatch} s</dd></div></dl><p>画面只显示本任务的日志反馈。${b&&Math.hypot(b.site[0]-j.pos[0],b.site[1]-j.pos[1])>.1?'作业位置按现有避障结果吸附，原目标：'+j.pos.map(x=>num(x)).join(', ')+'。':''}</p>`+assaultResultHtml(jid);
  $('#theater-members').innerHTML=s.pids.map(pid=>{const w=state.run.replay.workers.find(w=>w.pid===pid),p=w?workerAt(w):{};return `<button class="theater-member ${state.focus?.id===pid?'selected':''}" data-worker="${esc(pid)}"><b>${esc(pid)}<span>${esc(w?.kind_name||'')}</span></b><strong>${esc(phaseName(p.phase))}</strong><small>坐标 ${num(p.x,2)}, ${num(p.y,2)} · 高度 ${num(p.z)}</small></button>`;}).join('')||'<p class="empty">尚未下发成员</p>';
  const rows=state.eventRows.filter(e=>e.job_id===jid&&e.kind==='behavior_event'&&e.sim_s<=state.t&&e.event?.kind!=='phase');$('#theater-event-count').textContent=rows.length;
  $('#theater-events').innerHTML=rows.slice(-6).reverse().map(e=>`<button data-task-time="${e.sim_s}"><time>${e.sim_s} s</time><b>${esc(eventTitle(e))}</b><small>${esc(eventDetail(e))}</small></button>`).join('')||'<p>等待本任务的执行反馈</p>';
  renderExecutionEvidence(jid);renderTaskDetailChrome(jid);
}
function teamColor(pid,jid=selectedJobId()){
  const ids=frame().jobs[jid]?.pids||[],i=ids.indexOf(pid);
  return ['#367bc0','#bf649c','#309a87','#ba8b42'][Math.max(0,i)%4];
}
function workbenchHold(jid){
  const job=frame().jobs[jid],b=job.behavior,debug=b.detail?.debug||{},structure=(state.run.replay.behaviors||[]).find(x=>x.job_id===jid);
  const pending=b.handover&&!b.handover.done?b.handover:null;
  const primary=debug.primary||(b.handover?.done?b.handover.incoming:job.pids[0]),secondary=debug.secondary||job.pids.find(p=>p!==primary);
  const post=structure?.posts?.[0]||structure?.site,standby=structure?.standbys?.[0],roles={};
  if(state.t<(structure?.sim_s??Infinity)){for(const pid of job.pids){const w=state.run.replay.workers.find(w=>w.pid===pid),p=workerAt(w);roles[pid]=p.phase==='work'?'已到作业区 · 等待成员':'前往作业区';}return {primary,secondary,post,standby,pending:null,roles,message:'仍在接近或等待成员到齐，轮换行为尚未启动。'};}
  const dist=(pos,target)=>target?Math.hypot(pos.x-target[0],pos.y-target[1]):Infinity;
  for(const pid of job.pids){const worker=state.run.replay.workers.find(w=>w.pid===pid),pos=worker?workerAt(worker):{};
    if(pending&&pid===pending.incoming)roles[pid]='接班中 → 交接岗位';
    else if(pending&&pid===pending.outgoing)roles[pid]=dist(pos,post)<=.8?'原班守岗 · 等待接替':'原班仍在接近岗位';
    else if(pid===primary)roles[pid]=dist(pos,post)<=.8?'当前主班 · 在岗':'主班就位中';
    else roles[pid]=dist(pos,standby)<=.8?'待命位置等待':b.handovers?'已交班 · 等待/返回待命':'前往待命位置';
  }
  let message=pending?`${no(pending.outgoing)} 交给 ${no(pending.incoming)}：接班成员先到位，原班等待交接。`:`当前主班 ${no(primary)}，另一成员待命或返程。`;
  if(job.status==='succeeded')message='本任务已完成交接。末帧仍在岗位附近的成员按原位置显示，不补画撤离。';
  return {primary,secondary,pending,post,standby,roles,message};
}
function currentTaskRoutes(jid){
  if(frame().jobs[jid]?.status==='succeeded')return [];
  return Object.values(frame().jobs[jid]?.behavior.routes||{}).filter(r=>{
    if(r.recordedAt>state.t)return false;
    const worker=state.run.replay.workers.find(w=>w.pid===r.pid);if(!worker)return false;const pos=workerAt(worker);
    return pos.job===jid&&Math.hypot(pos.x-r.to[0],pos.y-r.to[1])>.65;
  });
}
function renderExecutionEvidence(jid){
  const job=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],isHold=job.jtype==='hold';
  $('#workbench-team-card').hidden=isHold;$('#workbench-hold-card').hidden=!isHold;$('#hold-chapters').hidden=!isHold;
  if(isHold){const hold=workbenchHold(jid);
    $('#workbench-hold-status').innerHTML=`<p class="hold-narrative">${esc(hold.message)}</p><div class="handover-count">已确认交接 <b>${s.behavior.handovers||0}</b> 次</div>${s.pids.map(pid=>`<div class="hold-role" style="border-left-color:${teamColor(pid,jid)}"><b>${esc(pid)}</b><span>${esc(hold.roles[pid])}</span><small>颜色与地图成员标记一致</small></div>`).join('')}`;
    $('#hold-chapters').innerHTML=state.eventRows.filter(e=>e.job_id===jid&&['on_post','handover_start','handover_complete'].includes(e.event?.kind)).map(e=>`<button class="${e.sim_s>state.t?'future':''}" data-task-time="${e.sim_s}"><small>+${num(e.sim_s-state.taskWindow.execution,0)} s${e.sim_s>state.t?' · 未播放':''}</small>${esc(eventTitle(e))}${e.event.incoming?' · '+no(e.event.outgoing)+' → '+no(e.event.incoming):''}</button>`).join('');
    $('#theater-members').innerHTML=s.pids.map(pid=>{const worker=state.run.replay.workers.find(w=>w.pid===pid),pos=worker?workerAt(worker):{};return `<button class="theater-member" data-worker="${esc(pid)}" style="border-left:3px solid ${teamColor(pid,jid)}"><b>${esc(pid)}<span>${esc(worker?.kind_name)}</span></b><strong>${esc(hold.roles[pid])}</strong><small>当前坐标 ${num(pos.x,2)}, ${num(pos.y,2)}</small></button>`;}).join('');
  }
  const history=state.run.trace.filter(e=>e.kind==='behavior_event'&&e.event.job_id===jid&&e.sim_s<=state.t).flatMap(e=>e.event.kind==='behavior_detail'?(e.event.routes||[]).map(r=>({...r,recordedAt:e.sim_s})):e.event.kind==='approach_route'?[{...e.event.route,recordedAt:e.sim_s}]:[]),blocked=history.filter(r=>!r.straight_line_ok);
  const routes=currentTaskRoutes(jid);
  $('#workbench-route-status').innerHTML=routes.map(r=>`<div class="path-evidence"><b style="color:${teamColor(r.pid,jid)}">${esc(r.pid)} · ${r.straight_line_ok?'当前直线可通行':'原直线被挡，已生成绕行路径'}</b><small>路径 ${num(r.length,2)} / 直线 ${num(r.straight,2)} 单位</small><small>规划路径净空 ${num(r.min_clearance,3)} 单位 · 记录于 ${num(r.recordedAt,0)} s</small></div>`).join('')||(s.behavior.detail||state.run.report.behavior_details?'<p>当前无未完成的地面绕行段。空中接近按现有直飞替身处理；任务内部路径另按记录展示。</p>':'<p>这份旧日志未记录路径细节。新建带行为与绕障的运行会自动生成这些证据。</p>');
  $('#workbench-route-status').insertAdjacentHTML('beforeend',`<div class="route-history"><small>已记录 ${history.length} 段路径 · ${blocked.length} 段直线受阻</small>${blocked.slice(-3).map(r=>`<button data-task-time="${r.recordedAt}">回看 ${r.recordedAt} s · ${no(r.pid)} 绕行</button>`).join('')}<small>实线：已行轨迹；虚线：记录的规划路径；灰块：碰撞体。净空为规划指标。</small></div>`);
}
$('#close-theater').onclick=closeTheater;theater.addEventListener('cancel',e=>{e.preventDefault();closeTheater();});
$('#theater-task').onchange=e=>openTask(e.target.value);
$('#task-source')?.remove();
$('#task-view-switch').onclick=e=>{const b=e.target.closest('[data-task-view]');if(!b)return;state.taskView=b.dataset.taskView;setBounds();renderTheater();draw();};
$('#task-restart').onclick=()=>{if(!state.taskWindow)return;state.taskWindow.start=state.taskWindow.dispatch;updateTaskTimeline();setTime(state.taskWindow.start);setBounds();draw();setPlaying(true);};
$('#action-start').onclick=()=>{if(!state.taskWindow)return;state.taskWindow.start=state.taskWindow.execution;updateTaskTimeline();setTime(state.taskWindow.start);setBounds();draw();setPlaying(true);};
document.addEventListener('click',e=>{const event=e.target.closest('[data-task-time]');if(event){setPlaying(false);const t=Number(event.dataset.taskTime);if(state.taskWindow&&t<state.taskWindow.start){state.taskWindow.start=state.taskWindow.dispatch;updateTaskTimeline();setBounds();}setTime(t);draw();}});
// Scene rendering only changes presentation; raw feedback remains unchanged.
let bounds=[0,0,100,100];const canvas=$('#scene'),ctx=canvas.getContext('2d');
function taskColor(jid){const i=state.run?.report.jobs.findIndex(j=>j.job_id===jid)??-1;return i<0?'#9aaba4':taskPalette[i%taskPalette.length];}
function selectedJobId(){if(!state.run||!state.focus)return null;return state.focus.type==='job'?state.focus.id:state.focus.jobId||null;}
function activeWorkerJob(w){const p=workerAt(w),s=frame().jobs[p.job];return s&&['running','cancelling'].includes(s.status)&&s.pids.includes(w.pid)?p.job:null;}
function visibleStructures(){const jid=selectedJobId();return (state.run.replay.behaviors||[]).filter(b=>$('#show-behaviors').checked&&b.sim_s<=state.t&&b.job_id===jid&&(state.taskWindow||frame().jobs[jid]?.status!=='succeeded'||$('#full-trails').checked));}
function globalView(){if(state.taskWindow){closeTheater();return;}state.focus=null;$('#task-select').value='';state.zoom=1;setBounds();renderTime();draw();}
function setBounds(){
  if(!state.run)return;
  // 只含区域封控一个作业的运行：全局分配也按"封控区 + 集结地"取景，
  // 不套整张场景图——否则 140 m 的封控区被压成一个小方块，看不出谁封哪段、
  // 各平台的探测圈也小到看不见。
  if(!state.focus&&!state.taskWindow&&state.run.replay.containment
     &&state.run.report.jobs.length===1){
    const b=containmentBounds();if(b){bounds=b;return;}
  }
  if(!state.focus&&state.run.scene_map?.surfaces?.length){bounds=fullBounds();return;}
  const r=state.run.replay,jid=selectedJobId(),j=r.jobs.find(j=>j.job_id===jid);let points=[];
  if(j&&state.taskWindow){
    const structure=(r.behaviors||[]).find(b=>b.job_id===jid);points.push(structure?.site||j.pos);if(structure){points.push(...(structure.loop||[]),...(structure.type==='hold'?(structure.posts||[]).slice(0,1):(structure.posts||[])),...(structure.type==='hold'?(structure.standbys||[]).slice(0,1):(structure.standbys||[])),...(structure.staging||[]),...(structure.objective||[]));const radius=structure.area_radius||structure.ring_radius;if(radius)points.push([structure.site[0]-radius,structure.site[1]-radius],[structure.site[0]+radius,structure.site[1]+radius]);}
    for(const w of r.workers)for(const p of w.samples)if(p.job===jid&&p.t>=state.taskWindow.start&&p.t<=state.taskWindow.end)points.push([p.x,p.y]);
  }else if(j){
    points.push(j.pos);const structure=(r.behaviors||[]).find(b=>b.job_id===jid&&b.sim_s<=state.t);
    if(structure){points.push(structure.site,...(structure.loop||[]),...(structure.area||[]),...(structure.posts||[]),...(structure.standbys||[]),...(structure.staging||[]),...(structure.objective||[]));const radius=structure.area_radius||structure.ring_radius;if(radius){points.push([structure.site[0]-radius,structure.site[1]-radius],[structure.site[0]+radius,structure.site[1]+radius]);}}
    if(frame().jobs[jid].status!=='succeeded')for(const w of r.workers){if(activeWorkerJob(w)===jid){const p=workerAt(w);points.push([p.x,p.y]);}}
  }else if(state.focus?.type==='worker'){
    const w=r.workers.find(w=>w.pid===state.focus.id),p=workerAt(w);points.push([p.x-4,p.y-4],[p.x+4,p.y+4]);
  }else{
    // 总览以"任务区"取景：出发阵地在 150 m 外，若把起点也算进来自适应，
    // 中间会拉出一大片空地，建筑群和任务点全被压成小点。起点与全场景
    // 的关系放到右下角缩略图里看，主图专注任务区。
    const jobs=r.jobs.map(j=>j.pos);points=[...jobs];
    const ckArea=state.run.replay.containment?.structure?.area;
    if(ckArea)points.push(...ckArea);
    if(jobs.length){
      const cx=jobs.reduce((s,p)=>s+p[0],0)/jobs.length,cy=jobs.reduce((s,p)=>s+p[1],0)/jobs.length;
      const near=(p)=>Math.hypot(p[0]-cx,p[1]-cy)<=130;
      // 只让"建筑级"占地参与取景：花坛/标识柱这类小构件离得远却会把视野拉空，
      // 图上仍画它们，只是不再决定镜头。
      const area=(poly)=>{let a=0;for(let i=0;i<poly.length;i++){const p=poly[i],q=poly[(i+1)%poly.length];a+=p[0]*q[1]-q[0]*p[1];}return Math.abs(a/2);};
      if($('#show-obstacles').checked)for(const o of mapGeometry('obstacles'))if(area(o.polygon)>25&&o.polygon.some(near))points.push(...o.polygon);
      for(const b of (r.behaviors||[])){for(const p of [...(b.staging||[]),...(b.objective||[]),...(b.posts||[]),...(b.standbys||[]),...(b.loop||[])])if(near(p))points.push(p);}
      for(const w of r.workers)if(near(w.start))points.push(w.start);
    }
  }
  // Fit the current recorded chapter, rather than a whole approach journey.
  // This changes the camera only; actor coordinates are never displaced.
  if(j&&state.taskWindow&&state.taskView==='spatial'&&['assault','hold'].includes(j.type)){
    const structure=r.behaviors.find(b=>b.job_id===jid),phase=frame().jobs[jid].phase;
    if(structure&&j.type==='assault'){
      const chapter=state.t<structure.sim_s?'approach':['完成','结果确认'].includes(phase)?'结果确认':phase;
      points=chapter==='approach'?[]:chapter==='机动'?[...(structure.staging||[])]:chapter==='到位'?[...(structure.staging||[])]:chapter==='执行'?[...(structure.staging||[]),...(structure.objective||[])]:[...(structure.objective||[])];
      // 只取"最近 45 s"的成员位置：整段接近航迹（150 m）都算进取景会把
      // 镜头拉到全图，当前动作反而缩成一个角。
      const recent=(p)=>p.t>=Math.max(state.taskWindow.dispatch,state.t-45);
      for(const worker of r.workers)for(const p of worker.samples)if(p.job===jid&&(chapter==='approach'?p.t>=state.taskWindow.dispatch&&p.t<structure.sim_s:p.phase===chapter&&recent(p)))points.push([p.x,p.y]);
    }else if(structure&&j.type==='hold'&&state.t>=(taskEventTime(jid,'on_post')??Infinity)){
      const on=taskEventTime(jid,'on_post');points=[structure.posts[0],structure.standbys?.[0]].filter(Boolean);
      for(const worker of r.workers)for(const p of worker.samples)if(p.job===jid&&p.t>=on)points.push([p.x,p.y]);
    }
  }
  points=points.filter(p=>p&&p.every(Number.isFinite));if(!points.length)points=[[0,0],[10,10]];
  const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),mx=(Math.min(...xs)+Math.max(...xs))/2,my=(Math.min(...ys)+Math.max(...ys))/2;
  const isHoldAction=state.taskWindow&&j?.type==='hold'&&state.taskWindow.start===state.taskWindow.execution;
  // 突击任务固定给 38 单位的取景下限：镜头跟到集结/执行位时仍能看到周边建筑
  // 和道路，否则一放大就只剩一块灰色楼顶，看不出"十字路口建筑群"。
  const assaultChapter=state.taskWindow&&j?.type==='assault';
  const minSpan=isHoldAction?1.8:state.taskWindow?(assaultChapter?95:4):jid?9:15,width=Math.max(minSpan,Math.max(...xs)-Math.min(...xs)),height=Math.max(minSpan,Math.max(...ys)-Math.min(...ys)),pad=state.taskWindow?Math.max((isHoldAction ? 0.5 : 0.65),Math.max(width,height)*.07):jid?2.4:5;
  bounds=[mx-width/2-pad,my-height/2-pad,mx+width/2+pad,my+height/2+pad];
}
function renderStage(){
  const jid=selectedJobId(),j=state.run.report.jobs.find(j=>j.job_id===jid),f=frame();
  $('#overview-view').classList.toggle('active',!state.focus);$('#view-badge').textContent=state.focus?'聚焦动作':'全局分配';
  $('#scene-heading').textContent=j?j.job_id+' · '+taskLabel(j):state.focus?'平台位置':'全局任务分布';
  $('#focus-view').textContent=j?(j.type==='blockade'&&state.run.replay.containment?'区域封控任务 · 可打开封控视图看边界占位与接近事件':'仅突出当前任务 · 镜头保持固定'):'点击右侧任务，查看成员与动作';
  const panel=$('#stage-panel');panel.classList.toggle('has-focus',!!j);panel.style.setProperty('--task-color',taskColor(jid));
  if(!j){panel.innerHTML='<div class="stage-empty"><span>◈</span><div><b>全局看分配</b><small>颜色对应任务；选中任务后查看具体动作。默认收起历史轨迹。</small></div></div>';return;}
  const s=f.jobs[jid],started=s.behavior.startedAt!=null||(!state.run.report.behavior&&s.phase&&s.phase!=='travel');
  const index=s.status==='succeeded'?3:started?2:s.phase?1:s.attempts?0:-1;
  const phase=s.status==='succeeded'?'已完成':s.status==='failed'?'执行失败':s.status==='cancelling'?'取消中':!s.attempts?'等待分配':started?phaseName(s.phase):s.phase==='work'?'等待成员到齐':'前往作业区';
  const ck=!!(state.run.replay.containment&&state.run.replay.containment.job_id===jid);
  panel.innerHTML=`<div class="stage-top"><div><span class="stage-dot"></span><b>${esc(jid)} · ${esc(taskLabel(j))}</b><span class="stage-phase">${esc(phase)}</span>${ck?'<button class="text-button" data-containment>◎ 区域封控视图</button>':''}</div><button class="text-button" data-global>返回全局 ↗</button></div><div class="stage-steps">${['已分配','前往作业区','执行动作','已完成'].map((v,i)=>`<span class="${i<index?'done':i===index?'current':''}"><i>${i<index?'✓':i+1}</i>${v}</span>`).join('')}</div><div class="stage-detail"><span>${esc(behaviorSummary(j,s))}</span><div class="force-chips">${s.pids.map(pid=>{const w=state.run.replay.workers.find(x=>x.pid===pid),role=(state.run.replay.behaviors||[]).find(x=>x.job_id===jid)?.roles?.[pid]||'';return `<button class="member-chip ${state.focus?.id===pid?'selected':''}" data-worker="${esc(pid)}" title="${esc((w?.kind_name||'')+(role?' · '+role:''))}">${no(pid)}<small>${esc(kindNames[w?.kind]||'')}${role?' · '+esc(role):''}</small></button>`;}).join('')||'<small>尚未分配成员</small>'}</div></div>`;
}
function trailsFor(w){
  const full=$('#full-trails').checked,jid=selectedJobId(),s=jid?frame().jobs[jid]:null;
  if(!full&&(!state.focus||!$('#show-trails').checked||(s?.status==='succeeded'&&!state.taskWindow)))return [];
  if(state.focus?.type==='worker'&&state.focus.id!==w.pid&&!full)return [];
  if(jid&&!full&&(state.taskWindow?workerAt(w).job!==jid:activeWorkerJob(w)!==jid))return [];
  const arrived=w.samples.find(p=>p.job===jid&&p.t<=state.t&&p.phase&&p.phase!=='travel');
  const cutoff=full?-Infinity:Math.max(0,state.t-10,s?.behavior.startedAt??arrived?.t??0);
  const all=w.samples.filter(p=>p.t<=state.t&&(!jid||p.job===jid));let segments=[],segment=[];
  for(let i=0;i<all.length;i++){
    const p=all[i],prev=all[i-1];if(p.t<cutoff)continue;
    if(!segment.length||prev?.command!==p.command){if(segment.length>1)segments.push(segment);segment=[];}
    if(!segment.length&&prev&&prev.t<cutoff&&prev.command===p.command&&p.t>prev.t&&state.run.report.motion==='real'){
      const f=(cutoff-prev.t)/(p.t-prev.t);segment.push({...p,t:cutoff,x:prev.x+(p.x-prev.x)*f,y:prev.y+(p.y-prev.y)*f});
    }
    segment.push(p);
  }
  const current=workerAt(w);if(segment.length&&current.job===segment.at(-1).job&&current.command===segment.at(-1).command&&state.t>segment.at(-1).t)segment.push({...current,t:state.t});
  if(segment.length>1)segments.push(segment);return segments;
}

function mapGeometry(key){return state.run?.scene_map?.[key]||state.run?.[key]||[];}
function mapStyle(o){const id=o.id||'';return o.source==='mesh_aabb'?['#b9c8d6','#7b90a3']:id.includes('planter')?['#99b78c','#6c8961']:id.includes('walls')?['#aeb4b1','#7e8782']:id.includes('beacon')?['#d2b36b','#a38b4e']:['#ccd5d2','#9fadb4'];}
function landmarkName(o){const n=o.name||'';const names={env_beacon_lawn:'草坪区标识柱',env_beacon_walls:'围墙区标识柱',env_beacon_city:'城市区标识柱',env_beacon_wetlands:'湿地区标识柱',env_beacon_yosemite:'山地区标识柱',env_wetlands_north:'北湿地',env_wetlands_south:'南湿地',env_yosemite:'山地'};return (names[n]||buildingName(n))+(o.missing_geometry?' · 缺少模型，仅示位置':'');}

// 区域封控运行的目标状态：结果里的 state 是最终状态，总览要按当前时刻回推。
const CK_STATE_COLOR={'监视':'#d97706','已警告':'#d97706','拦截中':'#7c3aed',
  '已拦阻':'#0d9488','未授权进入':'#991b1b','已撤离':'#64748b',
  '已放行':'#2563eb','待出现':'#94a3b8'};
function ckTargetState(tgt,events,t){
  const kinds=new Set((events||[]).filter(e=>e.target_id===tgt.target_id&&(e.t||0)<=t).map(e=>e.kind));
  if(kinds.has('breach'))return '未授权进入';
  if(kinds.has('intercepted'))return '已拦阻';
  if(kinds.has('warning_effective'))return '已撤离';
  if(kinds.has('authorized_pass'))return '已放行';
  if(kinds.has('intercept_assigned'))return '拦截中';
  if(kinds.has('warning_issued'))return '已警告';
  if(kinds.has('target_detected'))return '监视';
  return '待出现';
}
// 区域封控运行的取景范围：封控区、通道口、站位、集结待机区与目标起终点。
function containmentBounds(){
  const ck=state.run&&state.run.replay&&state.run.replay.containment;
  if(!ck||!ck.structure)return null;
  const pts=[];
  for(const p of ck.structure.area||[])pts.push(p);
  for(const g of ck.structure.gates||[])if(g.point)pts.push(g.point);
  for(const p of ck.structure.post_plan||[])if(p.point)pts.push(p.point);
  for(const w of state.run.replay.workers)if(w.start)pts.push(w.start);
  for(const t of (ck.result&&ck.result.targets)||[]){
    if(t.start)pts.push(t.start);if(t.goal)pts.push(t.goal);
  }
  if(!pts.length)return null;
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]),pad=22;
  return [Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad];
}
function fullBounds(){  // 全场景（含 150 m 外的出发阵地）的取景范围，缩略图与"看全图"都用它。
  const r=state.run.replay,pts=[...r.workers.map(w=>w.start),...r.jobs.map(j=>j.pos)];
  for(const o of [...mapGeometry('obstacles'),...mapGeometry('roads'),...mapGeometry('surfaces')])pts.push(...o.polygon);
  for(const l of mapGeometry('landmarks'))if(l.pose)pts.push(l.pose.slice(0,2));
  for(const b of r.behaviors||[])for(const p of [...(b.staging||[]),...(b.objective||[]),...(b.loop||[]),...(b.posts||[]),...(b.standbys||[])])pts.push(p);
  if(!pts.length)return [0,0,100,100];
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]),pad=10;
  return [Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad];
}
function drawMinimap(W,H){
  if(!state.run||W<720||H<330)return;
  const w=178,h=124,x0=W-w-14,y0=14;
  const [bx0,by0,bx1,by1]=fullBounds();
  const s=Math.min((w-16)/(bx1-bx0),(h-16)/(by1-by0)),cx=(bx0+bx1)/2,cy=(by0+by1)/2;
  const M=p=>[x0+w/2+(p[0]-cx)*s,y0+h/2-(p[1]-cy)*s];
  ctx.save();
  ctx.beginPath();ctx.roundRect(x0,y0,w,h,8);ctx.fillStyle='#ffffffee';ctx.fill();ctx.strokeStyle='#d6e2da';ctx.lineWidth=1;ctx.stroke();
  for(const rd of mapGeometry('roads')){ctx.beginPath();rd.polygon.forEach((p,i)=>{const q=M(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle='#eef1ec';ctx.fill();}
  for(const o of mapGeometry('obstacles')){ctx.beginPath();o.polygon.forEach((p,i)=>{const q=M(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle=mapStyle(o)[0];ctx.fill();}
  for(const job of state.run.replay.jobs){const [mx,my]=M(job.pos);ctx.strokeStyle=taskColor(job.job_id);ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(mx,my,4,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.arc(mx,my,1.4,0,Math.PI*2);ctx.fillStyle=taskColor(job.job_id);ctx.fill();}
  for(const wk of state.run.replay.workers){const [mx,my]=M(wk.start);ctx.beginPath();ctx.arc(mx,my,1.9,0,Math.PI*2);ctx.fillStyle=state.taskWindow?teamColor(wk.pid):'#5d7f90';ctx.fill();}
  const screen=canvas.getBoundingClientRect(),viewScale=mapScale(),centerX=(bounds[0]+bounds[2])/2,centerY=(bounds[1]+bounds[3])/2;
  const a=M([centerX-screen.width/(2*viewScale),centerY+screen.height/(2*viewScale)]),b=M([centerX+screen.width/(2*viewScale),centerY-screen.height/(2*viewScale)]);
  ctx.save();ctx.beginPath();ctx.rect(x0+1,y0+1,w-2,h-17);ctx.clip();
  ctx.strokeStyle='#2f8f86';ctx.lineWidth=1.2;ctx.setLineDash([3,2]);ctx.strokeRect(a[0],a[1],b[0]-a[0],b[1]-a[1]);ctx.setLineDash([]);ctx.restore();
  ctx.fillStyle='#fffffff2';ctx.fillRect(x0+1,y0+h-16,w-2,15);
  ctx.font='9px "Segoe UI","Microsoft YaHei"';ctx.fillStyle='#6d8778';ctx.fillText('全局态势 · 点击看全图',x0+8,y0+h-5);
  ctx.restore();
  state.hits.push({type:'fit',x:x0+w/2,y:y0+h/2,w:w,h:h});
}
function draw(){
  if(!state.run||state.page!=='overview'||state.ckView)return;
  const rect=canvas.getBoundingClientRect();if(rect.width<1)return;const dpr=window.devicePixelRatio||1;
  if(canvas.width!==Math.round(rect.width*dpr)||canvas.height!==Math.round(rect.height*dpr)){canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);const W=rect.width,H=rect.height;ctx.clearRect(0,0,W,H);ctx.fillStyle='#edf0e9';ctx.fillRect(0,0,W,H);
  if(state.taskWindow&&state.taskView==='spatial'){
    const jid=state.taskWindow.jobId,type=state.run.report.jobs.find(j=>j.job_id===jid)?.jtype;
    if(['assault','hold'].includes(type)){const chapter=type==='hold'?(state.t>=(taskEventTime(jid,'on_post')??Infinity)?'onpost':'approach'):taskDetailModel(jid).preExecution?'approach':frame().jobs[jid].phase;const key=state.run.id+':'+jid+':'+chapter+':'+state.taskWindow.start;
      if(state.cameraChapter!==key){state.cameraChapter=key;state.zoom=1;setBounds();}}
  }
  const [x0,y0,x1,y1]=bounds,scale=Math.min((W-78)/(x1-x0),(H-78)/(y1-y0))*state.zoom,cx=(x0+x1)/2,cy=(y0+y1)/2;
  const P=p=>[W/2+(p[0]-cx)*scale,H/2-(p[1]-cy)*scale],f=frame(),jid=selectedJobId(),focused=!!state.focus,full=$('#full-trails').checked;
  if(state.taskWindow&&['assault','hold'].includes(state.run.report.jobs.find(j=>j.job_id===jid)?.jtype)&&state.taskView==='process'){drawTaskExplanation(ctx,W,H,jid);return;}
  const inView=(x,y)=>x>=8&&x<=W-8&&y>=8&&y<=H-30;
  const line=(points,color,width=1,dash=[])=>{if(points.length<2)return;ctx.beginPath();points.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  const arrowAlong=(points,color)=>{if(!points||points.length<2)return;ctx.fillStyle=color;for(let i=1;i<points.length;i++){const a=P(points[i-1]),b=P(points[i]);if(Math.hypot(b[0]-a[0],b[1]-a[1])<34)continue;const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2,ang=Math.atan2(b[1]-a[1],b[0]-a[0]);ctx.beginPath();ctx.moveTo(mx+Math.cos(ang)*5.5,my+Math.sin(ang)*5.5);ctx.lineTo(mx+Math.cos(ang+2.6)*6,my+Math.sin(ang+2.6)*6);ctx.lineTo(mx+Math.cos(ang-2.6)*6,my+Math.sin(ang-2.6)*6);ctx.closePath();ctx.fill();}};
  const circle=(p,r,color,fill=null,dash=[])=>{const a=P(p);ctx.beginPath();ctx.arc(...a,r,0,Math.PI*2);if(fill){ctx.fillStyle=fill;ctx.fill();}ctx.strokeStyle=color;ctx.lineWidth=1.4;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  if($('#show-grid').checked){const step=(x1-x0)>35?5:2;ctx.font='9px "Segoe UI"';for(let x=Math.floor(x0/step)*step;x<=x1;x+=step){line([[x,y0],[x,y1]],'#e8eee7',.6);const a=P([x,y0]);ctx.fillStyle='#9aada1';ctx.fillText(x,a[0],H-30);}for(let y=Math.floor(y0/step)*step;y<=y1;y+=step)line([[x0,y],[x1,y]],'#e8eee7',.6);}
  if($('#show-obstacles').checked)for(const surface of mapGeometry('surfaces')){ctx.beginPath();surface.polygon.forEach((p,i)=>{const q=P(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle='#e4edda';ctx.fill();ctx.strokeStyle='#a9bf99';ctx.lineWidth=1;ctx.stroke();}
  // 底图：道路/广场来自 SDF（env_road_*/env_city_road_*/env_city_square），
  // 只作底图不参与避障；先画路再画建筑，建筑才压得住路口。
  if($('#show-obstacles').checked&&mapGeometry('roads').length){
    for(const road of mapGeometry('roads')){ctx.beginPath();road.polygon.forEach((p,i)=>{const q=P(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();
      const plaza=String(road.id||'').includes('square');
      ctx.fillStyle=plaza?'#e8ded0':'#d8ddda';ctx.fill();ctx.strokeStyle='#b6c2b8';ctx.lineWidth=.8;ctx.stroke();}
  }
  // Assignment links are not routes; only recorded routes and traveled trails are drawn.
  // 静态占地（建筑/花坛/围墙）在总览与任务视图都画：场景是"左侧十字路口建筑群"，
  // 建筑图层看不见就看不出任务点周围是什么。
  if($('#show-obstacles').checked)for(const obstacle of mapGeometry('obstacles')){
    ctx.beginPath();obstacle.polygon.forEach((p,i)=>{const q=P(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();
    const building=obstacle.source==='mesh_aabb';
    ctx.fillStyle=mapStyle(obstacle)[0];ctx.strokeStyle=mapStyle(obstacle)[1];ctx.lineWidth=1;ctx.fill();ctx.stroke();
    if(building&&$('#show-labels').checked&&(state.taskWindow||scale>3.2)){const pts=obstacle.polygon.map(P);const w=Math.max(...pts.map(p=>p[0]))-Math.min(...pts.map(p=>p[0]));if(w>44){const cx=pts.reduce((s,p)=>s+p[0],0)/pts.length,cy=pts.reduce((s,p)=>s+p[1],0)/pts.length;ctx.fillStyle='#43586ab8';ctx.font='9px "Segoe UI","Microsoft YaHei"';ctx.textAlign='center';ctx.fillText(buildingName(obstacle.label||obstacle.id),cx,cy+3);ctx.textAlign='left';}}
  }
  const annotationLabels=[];
  let plannedCount=0;if(state.taskWindow){
    if($('#show-planned').checked)for(const route of currentTaskRoutes(jid)){const w=state.run.replay.workers.find(w=>w.pid===route.pid),pos=workerAt(w);let nearest=0;for(let i=1;i<route.path.length;i++)if(Math.hypot(route.path[i][0]-pos.x,route.path[i][1]-pos.y)<Math.hypot(route.path[nearest][0]-pos.x,route.path[nearest][1]-pos.y))nearest=i;const seg=route.path.slice(Math.max(0,nearest-1));const air=route.mode==='air_direct';line(seg,teamColor(route.pid,jid)+(air?'99':'cc'),air?1.6:2.4,air?[8,5]:[]);arrowAlong(seg,teamColor(route.pid,jid)+(air?'99':'cc'));if($('#show-blocked-line').checked&&!route.straight_line_ok)line([route.from_pose,route.to],'#c4736a80',1.6,[5,5]);
      // 绕障证据直接写在地图上：倍数 + 规划净空，避免"看起来像直线"的误读
      if(route.straight_line_ok===false&&$('#show-blocked-line').checked){const mid=[(route.from_pose[0]+route.to[0])/2,(route.from_pose[1]+route.to[1])/2],a=P(mid);annotationLabels.push({text:'直线被挡 · 绕行 ×'+num(route.length/Math.max(route.straight,.01),2)+' · 净空 '+num(route.min_clearance,1),x:a[0],y:a[1],color:'#a5762f',priority:false});}
      else if(air&&state.taskWindow){const mid=[(route.from_pose[0]+route.to[0])/2,(route.from_pose[1]+route.to[1])/2],a=P(mid);annotationLabels.push({text:'空中直飞 · 越障 '+num(route.altitude||0,0)+' m',x:a[0],y:a[1],color:'#2f8f86',priority:false});}
      plannedCount++;}
  }
  const holdInfo=state.taskWindow&&state.run.report.jobs.find(j=>j.job_id===jid)?.jtype==='hold'?workbenchHold(jid):null;
  const structures=visibleStructures();for(const b of structures){const c=taskColor(b.job_id);ctx.save();
    if(b.loop){line([...b.loop,b.loop[0]],c+'99',2,[7,5]);const visits=state.eventRows.filter(e=>e.job_id===b.job_id&&e.sim_s<=state.t&&e.event?.kind==='checkpoint_visited');b.loop.forEach((p,i)=>{const seen=visits.some(e=>e.event.index===i);circle(p,state.taskWindow?7:4,c,seen?c+'35':'#ffffff');const a=P(p);ctx.fillStyle=c;ctx.font=state.taskWindow?'12px "Microsoft YaHei"':'10px "Segoe UI"';ctx.fillText((state.taskWindow?'检查点 ':'')+String(i+1)+(seen?' ✓':''),a[0]+10,a[1]-10);});}
    if(b.ring_radius)circle(b.site,b.ring_radius*scale,c+'80',null,[5,5]);
    if(b.type==='recon'&&state.taskWindow){for(const target of Object.values(f.jobs[jid].behavior.detail?.debug?.targets||{}))circle(target,6,c+'bb');}
    if(b.area_radius){circle(b.site,b.area_radius*scale,c+'80',c+'07',[7,6]);if(state.taskWindow)for(const e of state.eventRows.filter(e=>e.job_id===b.job_id&&e.sim_s<=state.t&&e.event?.kind==='frontier_mapped'&&e.event.pos)){const center=P(e.event.pos),radius=(b.sensor_radius||2.6)*scale,gradient=ctx.createRadialGradient(center[0],center[1],1,center[0],center[1],radius);gradient.addColorStop(0,c+'1c');gradient.addColorStop(1,c+'02');ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(center[0],center[1],radius,0,Math.PI*2);ctx.fill();}}
    for(const [i,p]of (b.type==='hold'?(b.posts||[]).slice(0,frame().jobs[jid].pids.length>2?undefined:1):(b.posts||[])).entries()){circle(p,state.taskWindow?9:5,c,c+'25');if(state.taskWindow){const a=P(p);ctx.fillStyle=c;ctx.font='12px "Microsoft YaHei"';ctx.fillText(b.type==='hold'?'交接岗位':'岗位 '+(i+1),a[0]+12,a[1]-12);}}for(const [i,p]of (b.standbys||[]).slice(0,1).entries()){circle(p,state.taskWindow?7:4,c,null,[2,3]);if(state.taskWindow){const a=P(p);ctx.fillStyle=c;ctx.font='11px "Microsoft YaHei"';ctx.fillText('待命位 '+(i+1),a[0]+10,a[1]-10);}}
    if(b.type==='assault'&&state.taskWindow){const m=taskDetailModel(jid),points=m.index<2?b.staging:b.objective,groups=new Map();
      // 执行/集结点位只对应"突击组"，不能拿全员 pids 按下标硬套（会把侦察/评估平台
      // 标到突击位上）。assault_pids 由行为层随 structure 一起记下，旧记录退回角色过滤。
      const assaultPids=b.assault_pids||f.jobs[jid].pids.filter(p=>(b.roles||{})[p]==='突击组');
      (points||[]).forEach((point,i)=>{const key=point.map(v=>v.toFixed(2)).join(',');if(!groups.has(key))groups.set(key,{point,pids:[]});groups.get(key).pids.push(assaultPids[i]||assaultPids[0]);});
      // 集结位只标一次"集结区"：逐个点位标字在 6 台时会把地图糊成一团
      for(const group of groups.values()){const color=teamColor(group.pids[0],jid);circle(group.point,12,color,color+'10',[3,3]);if(m.index>=2)annotationLabels.push({text:'执行位 · '+(group.pids.length>1?group.pids.length+'成员重合':no(group.pids[0])),x:P(group.point)[0],y:P(group.point)[1]+24,color,priority:false});}
      if(m.index<2&&b.staging?.length){const cx=b.staging.reduce((s,q)=>s+q[0],0)/b.staging.length,cy=b.staging.reduce((s,q)=>s+q[1],0)/b.staging.length,a=P([cx,cy]);annotationLabels.push({text:'集结区',x:a[0],y:a[1]+24,color:taskColor(jid),priority:false});}
      // 目标点与集结/执行位分开标：十字路口中心才是效果对象，别让"执行位"
      // 圆圈代替目标。目标标记在所有阶段都画。
      const siteXY=P(b.site);circle(b.site,state.taskWindow?15:8,'#b34a3a','#b34a3a12',[3,3]);
      ctx.strokeStyle='#b34a3a';ctx.lineWidth=1.4;ctx.beginPath();ctx.moveTo(siteXY[0]-5,siteXY[1]);ctx.lineTo(siteXY[0]+5,siteXY[1]);ctx.moveTo(siteXY[0],siteXY[1]-5);ctx.lineTo(siteXY[0],siteXY[1]+5);ctx.stroke();
      annotationLabels.push({text:'目标 · '+(b.target_id||jid),x:siteXY[0],y:siteXY[1],color:'#a8442f',priority:true});const lead=(b.assault_pids||f.jobs[jid].pids)[0],route=f.jobs[jid].behavior.routes?.[lead];if(m.index===3&&route?.to&&Math.hypot(route.to[0]-b.objective[0][0],route.to[1]-b.objective[0][1])>.7){circle(route.to,15,'#5d9c70','#5d9c7015',[3,3]);const a=P(route.to);annotationLabels.push({text:'确认点 · '+no(lead),x:a[0],y:a[1]+24,color:'#5d9c70'});}}else{for(const p of b.staging||[])circle(p,state.taskWindow?9:5,c,null,[2,3]);for(const p of b.objective||[])circle(p,state.taskWindow?6:3,c,c+'44');}ctx.restore();
  }
  // 区域封控场景要素：封控边界、通道口、站位、探测圈与目标处置。
  // 总览要能直接看出"这块区域被谁封住、谁看得见哪段、目标现在什么状态"，
  // 所以这里不用一堆虚线：区域实线、探测圈细实线、目标带状态与拦阻连线。
  const ckData=state.run.replay.containment;
  const ckStructure=ckData&&ckData.structure;
  if(ckStructure&&ckStructure.area&&$('#show-behaviors').checked){
    const c=taskColor(ckStructure.job_id);
    const ckEvents=ckData.events||[];
    const ckEst=ckEvents.find(e=>e.kind==='control_established');
    const established=!!ckEst&&state.t>=(ckEst.t||0);
    ctx.save();
    ctx.beginPath();ckStructure.area.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.closePath();
    ctx.fillStyle=established?c+'1a':c+'0c';ctx.fill();
    ctx.strokeStyle=c+'cc';ctx.lineWidth=2;ctx.stroke();
    for(const gate of ckStructure.gates||[]){const a=P(gate.point);ctx.strokeStyle='#7c3aed';ctx.lineWidth=1.6;ctx.beginPath();ctx.arc(a[0],a[1],4.5,0,Math.PI*2);ctx.stroke();}
    for(const post of ckStructure.post_plan||[]){if(post.air)continue;circle(post.point,3,c,c+'44');}
    // 探测半径：细实线，不再用虚线圈（一屏五六个虚线圈和轨迹线叠在一起太乱）
    const sensorR=(ckStructure.sensor_radius_m||35)*scale;
    if(sensorR>4){
      for(const pid of Object.keys(ckStructure.roles||{})){
        const w=state.run.replay.workers.find(x=>x.pid===pid);
        if(!w)continue;
        const p=workerAt(w);
        if(!p||!Number.isFinite(p.x))continue;
        const air=String(ckStructure.roles[pid]).startsWith('air');
        circle([p.x,p.y],sensorR,air?'#2563eb66':c+'66',air?'#2563eb14':c+'0c');
      }
    }
    // 目标：当前状态、近 30 s 轨迹、拦阻连线——总览里也要看得出"在拦阻"
    for(const tgt of ((ckData.result&&ckData.result.targets)||[])){
      const track=(tgt.track||[]).filter(x=>x[0]<=state.t);
      if(!track.length)continue;
      const last=track[track.length-1],pos=[last[1],last[2]];
      if(track.length>2)line(track.filter(x=>x[0]>=state.t-30).map(x=>[x[1],x[2]]),tgt.authorized?'#2563eb99':'#dc262699',1.6);
      const stateNow=ckTargetState(tgt,ckEvents,state.t);
      if(stateNow==='待出现')continue;
      const color=CK_STATE_COLOR[stateNow]||'#94a3b8';
      const q=P(pos);
      ctx.beginPath();ctx.arc(q[0],q[1],6,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.6;ctx.stroke();
      annotationLabels.push({text:tgt.target_id+' · '+stateNow,x:q[0]+10,y:q[1]-6,color,priority:false});
      const assigned=ckEvents.find(e=>e.kind==='intercept_assigned'&&e.target_id===tgt.target_id);
      const done=ckEvents.find(e=>e.kind==='intercepted'&&e.target_id===tgt.target_id);
      if(assigned&&state.t>=assigned.t&&(!done||state.t<=done.t+3)){
        const w=state.run.replay.workers.find(x=>x.pid===tgt.interceptor);
        const a=w?workerAt(w):null;
        if(a&&Number.isFinite(a.x)){
          line([[a.x,a.y],pos],'#7c3aedcc',2);
          const m=P([(a.x+pos[0])/2,(a.y+pos[1])/2]);
          annotationLabels.push({text:'拦阻',x:m[0]+4,y:m[1]-4,color:'#7c3aed',priority:false});
        }
      }
    }
    const cx=ckStructure.center||ckStructure.site;const a=P(cx);
    annotationLabels.push({text:'封控区 · '+num(ckStructure.perimeter_m,0)+' m 边界',x:a[0],y:a[1]-10,color:c,priority:true});
    ctx.restore();
  }
  let traceCount=0;for(const w of state.run.replay.workers)for(const segment of trailsFor(w)){line(segment.map(p=>[p.x,p.y]),state.taskWindow?teamColor(w.pid,jid):taskColor(segment.at(-1).job),state.focus?.id===w.pid?2.6:1.8);traceCount++;}
  state.hits=[];const labels=[],placed=[];const showLabels=$('#show-labels').checked;
  const placeLabel=(text,x,y,color,priority=false,small=false)=>{
    ctx.font=small?'9px "Segoe UI","Microsoft YaHei"':priority?(state.taskWindow?'600 14px "Segoe UI","Microsoft YaHei"':'600 11px "Segoe UI","Microsoft YaHei"'):'11px "Segoe UI","Microsoft YaHei"';const width=ctx.measureText(text).width+12,height=small?16:20;
    const offsets=[...(holdInfo?[[-width/2,text.startsWith(no(holdInfo.primary))?-90:55]]:[]),[12,-24],[12,7],[-width-12,-24],[-width-12,7],[12,-47],[12,30],[-width/2,-49],[-width/2,35],[15,-70],[-width-15,52]];
    for(const [dx,dy]of offsets){const box={x:x+dx,y:y+dy,w:width,h:height};if(box.x<6||box.y<6||box.x+width>W-6||box.y+height>H-28||placed.some(b=>box.x<b.x+b.w+3&&box.x+width+3>b.x&&box.y<b.y+b.h+2&&box.y+height+2>b.y))continue;
      placed.push(box);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(Math.max(box.x,Math.min(x,box.x+width)),box.y+height/2);ctx.strokeStyle=color+'65';ctx.lineWidth=.7;ctx.stroke();ctx.fillStyle=small?'#ffffffd8':'#fffffff0';ctx.fillRect(box.x,box.y,width,height);ctx.fillStyle=color;ctx.textAlign='left';ctx.fillText(text,box.x+6,box.y+height-5);labels.push({text,...box});return;
    }
  };
  // Draw task markers first; completed tasks collapse to small confirmation marks.
  const jobLabels=[];
  for(const j of state.run.replay.jobs){const s=f.jobs[j.job_id],selected=j.job_id===jid;const structure=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid),beforeStructure=state.taskWindow&&state.t<(structure?.sim_s??Infinity);if(state.taskWindow&&(!selected||(['hold','assault'].includes(j.type)&&!beforeStructure)))continue;const route=Object.values(f.jobs[j.job_id].behavior.routes||{})[0];const site=state.taskWindow?(beforeStructure?route?.to||j.pos:structure?.site||j.pos):j.pos;const [x,y]=P(site);if(!inView(x,y))continue;ctx.save();ctx.globalAlpha=focused&&!selected ? 0.18 : 1;const c=taskColor(j.job_id),done=s.status==='succeeded';
    // 准星环：环内不再写任务号，文字交给 placeLabel，避免和成员标签叠成一团
    const R=done?7:selected?13:10;ctx.strokeStyle=c;ctx.lineWidth=selected?2.2:1.6;ctx.setLineDash(done?[]:[4,3]);ctx.beginPath();ctx.arc(x,y,R,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
    ctx.lineWidth=1.4;for(const ang of [0,Math.PI/2,Math.PI,Math.PI*1.5]){ctx.beginPath();ctx.moveTo(x+Math.cos(ang)*(R+1),y+Math.sin(ang)*(R+1));ctx.lineTo(x+Math.cos(ang)*(R+5),y+Math.sin(ang)*(R+5));ctx.stroke();}
    ctx.beginPath();ctx.arc(x,y,2.6,0,Math.PI*2);ctx.fillStyle=done?'#2e7d4f':c;ctx.fill();
    if(showLabels&&(!focused||selected))jobLabels.push({text:j.job_id+' · '+taskLabel(j)+(done?' · 已完成':''),x,y,color:c,priority:selected});
    state.hits.push({x,y,type:'job',id:j.job_id,r:selected?17:13});ctx.restore();
  }
  const assaultInfo=state.taskWindow&&state.run.report.jobs.find(j=>j.job_id===jid)?.jtype==='assault';
  const kindColor={UGV:'#3f6fa3',TANK:'#8a6b3d',PLANE:'#2f8f86',WING:'#7657a8'};
  const structureFor=(jobId)=>(state.run.replay.behaviors||[]).find(b=>b.job_id===jobId);
  const workerLabels=[];let relevantWorkers=0;
  for(const w of state.run.replay.workers){const p=workerAt(w),[x,y]=P([p.x,p.y]);if(state.taskWindow&&p.job!==jid)continue;if(!inView(x,y))continue;
    const activeJob=state.taskWindow&&p.job===jid?jid:activeWorkerJob(w),relevant=state.taskWindow?f.jobs[jid].pids.includes(w.pid):state.focus?.type==='worker'?w.pid===state.focus.id:!!jid&&activeJob===jid;
    const c=state.taskWindow?teamColor(w.pid,jid):(kindColor[w.kind]||taskColor(activeJob)),alpha=focused&&!relevant ? 0.2 : activeJob ? 1 : 0.6;ctx.save();ctx.globalAlpha=alpha;
    if($('#show-starts').checked&&(!focused||relevant))circle(w.start,3,c,null,[2,2]);
    const air=w.kind==='PLANE'||w.kind==='WING';
    const R=relevant?(state.taskWindow?12:9):7;
    // 空中平台：细虚线吊到地面 + 高度牌，地面平台不画
    if(air&&p.z>0.5){const lift=Math.min(30,8+p.z*0.55);ctx.setLineDash([2,3]);ctx.strokeStyle=c+'88';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x,y-lift);ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.arc(x,y-lift,1.8,0,Math.PI*2);ctx.fillStyle=c;ctx.fill();if(showLabels&&state.focus?.type==='worker'&&state.focus.id===w.pid)workerLabels.push({text:'z '+num(p.z,0)+' m',x:x,y:y-lift-8,color:c,priority:false,small:true});}
    // 底盘：白底圆 + 类型符号（形状即类目，颜色即任务/编组）
    ctx.beginPath();ctx.arc(x,y,R,0,Math.PI*2);ctx.fillStyle=p.lost?'#eef1ee':'#ffffff';ctx.fill();ctx.strokeStyle=p.lost?'#aab3ac':c;ctx.lineWidth=relevant?2:1.5;ctx.stroke();
    drawPlatformIcon(ctx,w.kind,x,y,relevant?10:8,p.yaw||0,p.lost?'#aab3ac':c);
    if(relevant&&!air&&p.yaw!=null){ctx.beginPath();ctx.moveTo(x+Math.cos(p.yaw)*(R+1),y-Math.sin(p.yaw)*(R+1));ctx.lineTo(x+Math.cos(p.yaw)*(R+9),y-Math.sin(p.yaw)*(R+9));ctx.strokeStyle=c;ctx.lineWidth=1.4;ctx.stroke();}
    if(p.lost){ctx.beginPath();ctx.moveTo(x-5,y-5);ctx.lineTo(x+5,y+5);ctx.moveTo(x+5,y-5);ctx.lineTo(x-5,y+5);ctx.strokeStyle='#a04a3f';ctx.lineWidth=1.6;ctx.stroke();}
    if(relevant){relevantWorkers++;if(showLabels){const st=structureFor(jid),role=st?.roles?.[w.pid]||'';const kindTxt=(w.kind_name||'').replace('无人','');workerLabels.push({text:no(w.pid)+(state.focus?.type==='worker'&&state.focus.id===w.pid?' '+kindTxt+(role?' · '+role:''):'')+(p.lost?' · 失联':''),x,y,color:c,priority:true});}}
    else if(showLabels&&!focused&&scale>1.15){workerLabels.push({text:no(w.pid),x,y,color:c,priority:false,small:true});}
    ctx.restore();state.hits.push({x,y,type:'worker',id:w.pid,r:relevant?13:9});
  }
  // 出发阵地：多台挤在 20×45 m 的列队里，逐台标字必然叠；标一次编成，放大后再拆开。
  if(!state.taskWindow&&!focused&&showLabels&&state.run.replay.workers.length>1){
    const starts=state.run.replay.workers.map(w=>P(w.start));
    const pad=16,bx0=Math.min(...starts.map(p=>p[0]))-pad,by0=Math.min(...starts.map(p=>p[1]))-pad,bx1=Math.max(...starts.map(p=>p[0]))+pad,by1=Math.max(...starts.map(p=>p[1]))+pad;
    const ccx=(bx0+bx1)/2,ccy=(by0+by1)/2,clusterInView=ccx>0&&ccx<W&&ccy>0&&ccy<H;
    if(clusterInView&&bx1-bx0>18&&by1-by0>10){
      ctx.save();ctx.setLineDash([4,4]);ctx.strokeStyle='#7f9b8b88';ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(bx0,by0,bx1-bx0,by1-by0,7);ctx.stroke();ctx.setLineDash([]);
      const kinds={};for(const w of state.run.replay.workers)kinds[w.kind_name]=(kinds[w.kind_name]||0)+1;
      const summary='出发阵地 · '+state.run.replay.workers.length+' 台（'+Object.entries(kinds).map(([k,v])=>k+' '+v).join(' · ')+'）';
      ctx.font='10px "Segoe UI","Microsoft YaHei"';const tw=ctx.measureText(summary).width+10,ly=Math.max(6,by0-18);
      ctx.fillStyle='#ffffffec';ctx.fillRect(bx0,ly,tw,16);ctx.fillStyle='#4f6f5f';ctx.fillText(summary,bx0+5,ly+12);
      ctx.restore();
    }else{
      ctx.font='10px "Segoe UI","Microsoft YaHei"';const hint='出发阵地在视图外 · '+state.run.replay.workers.length+' 台 · 见右上缩略图';
      const tw=ctx.measureText(hint).width+12;ctx.fillStyle='#ffffffd8';ctx.fillRect(12,12,tw,18);ctx.fillStyle='#6d8778';ctx.fillText(hint,18,25);
    }
  }
  for(const l of workerLabels)placeLabel(l.text,l.x,l.y,l.color,true,!!l.small);for(const l of [...annotationLabels,...jobLabels])placeLabel(l.text,l.x,l.y,l.color,l.priority,l.small);
  if(jid&&!holdInfo&&$('#show-landmarks').checked){const job=state.run.replay.jobs.find(j=>j.job_id===jid),[x,y]=P(job.pos);if(inView(x,y)){const label=(job.landmark||'').split('（')[0];if(label)placeLabel(label,x,y+20,'#8b9e8a');}}
  if($('#show-landmarks').checked)for(const l of mapGeometry('landmarks')){if(!l.pose)continue;const [x,y]=P(l.pose);if(!inView(x,y))continue;const missing=l.missing_geometry;ctx.strokeStyle=missing?'#a77a52':'#947b42';ctx.lineWidth=1.3;ctx.setLineDash(missing?[3,3]:[]);ctx.beginPath();ctx.arc(x,y,missing?7:3,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);if($('#show-labels').checked)placeLabel(landmarkName(l),x,y,'#796b4d',false,true);}
  ctx.textAlign='left';drawMinimap(W,H);$('#map-scale').textContent=num(40/scale,1)+' 场景单位';
  $('#map-caption').textContent=state.taskWindow?'本任务执行回放 · 仅显示参与成员与已记录动作':full?'完整历史轨迹 · 按所选任务筛选':!focused?'全局态势 · 形状=平台类型，颜色=编组；建筑群即突击目标区，点击任务聚焦':f.jobs[jid]?.status==='succeeded'?'任务已完成 · 已收起动作结构与轨迹':'最近 10 秒尾迹 · 到位后仅保留动作轨迹 · 镜头固定';
  // 封控运行的全局视图要说明多出来的那几圈是什么，不然虚线圆会被当成轨迹。
  if(!state.taskWindow&&!focused&&state.run.replay.containment){
    $('#map-caption').textContent='封控区 + 各平台探测半径（虚线圆）· 控制建立后区域压实显示 · 点任务看执行';
  }
  state.scene={jobId:jid,focused,plannedCount,traceCount,structureCount:structures.length,relevantWorkers,labels,bounds:[...bounds]};
}
canvas.addEventListener('click',e=>{if(mapDragMoved){mapDragMoved=false;return;}const b=canvas.getBoundingClientRect(),x=e.clientX-b.left,y=e.clientY-b.top;
  const fit=state.hits.find(h=>h.type==='fit'&&Math.abs(x-h.x)<=h.w/2&&Math.abs(y-h.y)<=h.h/2);
  if(fit){bounds=fullBounds();state.zoom=1;draw();return;}
  const chapter=state.hits.find(h=>h.type==='chapter'&&Math.abs(x-h.x)<=h.w/2&&Math.abs(y-h.y)<=h.h/2);if(chapter){setPlaying(false);setTime(chapter.t);return;}const hits=state.hits.filter(h=>h.type!=='fit'&&Math.hypot(x-h.x,y-h.y)<=h.r).sort((a,b)=>Math.hypot(x-a.x,y-a.y)-Math.hypot(x-b.x,y-b.y));if(hits.length){const current=hits.findIndex(h=>h.id===state.focus?.id),h=hits[(current+1)%hits.length];if(h.type==='job'){if(!state.taskWindow)openTask(h.id);}else focus(h.type,h.id);}else if(!state.taskWindow)globalView();});
document.addEventListener('click',e=>{
  const nav=e.target.closest('[data-page]');if(nav)setPage(nav.dataset.page);
  const go=e.target.closest('[data-goto]');if(go)setPage(go.dataset.goto);
  const ck=e.target.closest('[data-containment]');if(ck)showOverviewMode('containment');
  if(e.target.closest('[data-ck-back]')){showOverviewMode('map');return;}
  const job=e.target.closest('[data-job]');if(job)openTask(job.dataset.job);
  const worker=e.target.closest('[data-worker]');if(worker)focus('worker',worker.dataset.worker,worker.hasAttribute('data-locate'));
  const event=e.target.closest('[data-event-time]');if(event){setPlaying(false);if(event.dataset.eventJob&&!state.taskWindow)openTask(event.dataset.eventJob,false);setTime(Number(event.dataset.eventTime));}
  const run=e.target.closest('[data-load-run]');if(run)loadRun(run.dataset.loadRun).then(()=>setPage('overview'));
  const ckRun=e.target.closest('[data-ck-run]');if(ckRun){loadRun(ckRun.dataset.ckRun,true).then(()=>{showOverviewMode('containment');toast('已打开区域封控演示；切到“全局分配”页签可对照机动与任务位置。');});}
  if(e.target.closest('[data-behavior-run]')){const r=state.catalog.runs.find(r=>r.id===state.catalog.default_run&&r.behavior)||state.catalog.runs.find(r=>r.behavior);if(r)loadRun(r.id);else toast('还没有启用到位动作的记录，请新建演示。');}
  if(e.target.closest('[data-global]'))globalView();
  const source=e.target.closest('[data-source]');if(source)api('/api/source/'+source.dataset.source).then(d=>{$('#source-title').textContent=d.name;$('#source-text').textContent=d.text;$('#source-dialog').showModal();}).catch(e=>toast(e.message));
});
$('#play').onclick=()=>{if(state.run)setPlaying(!state.playing);};$('#restart').onclick=()=>{setPlaying(false);if(state.taskWindow){state.taskWindow.start=state.taskWindow.dispatch;updateTaskTimeline();}setTime(state.taskWindow?.start??0);setBounds();draw();};$('#step-back').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)-1);};$('#step-next').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)+1);};$('#jump-end').onclick=()=>{setPlaying(false);setTime(state.taskWindow?.end??state.run.replay.end);};$('#scrubber').oninput=e=>{setPlaying(false);setTime(Number(e.target.value));};$('#speed').onchange=e=>state.speed=Number(e.target.value);
for(const id of ['show-trails','show-labels','show-landmarks','show-behaviors','show-starts','show-grid','full-trails','show-obstacles','show-planned','show-blocked-line'])$('#'+id).onchange=draw;
$('#fit-map').onclick=()=>{state.zoom=1;setBounds();draw();};$('#map-zoom-in').onclick=()=>{state.zoom=Math.min(32,state.zoom*1.4);draw();};$('#map-zoom-out').onclick=()=>{state.zoom=Math.max(.25,state.zoom/1.4);draw();};$('#clear-focus').onclick=globalView;$('#overview-view').onclick=()=>{showOverviewMode('map');globalView();};$('#event-filter').onchange=()=>{lastEventKey='';renderEvents();};$('#platform-filter').onchange=renderPlatforms;
$('#run-select').onchange=e=>loadRun(e.target.value);$('#refresh').onclick=()=>refreshCatalog().catch(e=>toast(e.message));for(const id of ['open-config','guide-run','runs-new'])$('#'+id).onclick=openConfig;$('#close-config').onclick=()=>$('#config-dialog').close();$('#close-source').onclick=()=>$('#source-dialog').close();$('#config-scenario').onchange=()=>{if($('#config-scenario').value==='asl_city'){$('#config-avoid').checked=true;$('#config-behavior').checked=true;}updateConfig();};$('#config-avoid').onchange=updateConfig;
$('#open-actions').onclick=()=>{setPage('overview');$('#behavior-panel').scrollIntoView({block:'start'});};$$('.ov-tab').forEach(b=>{b.onclick=()=>showOverviewMode(b.dataset.ov);});$('#show-report').onclick=()=>{if(state.run)window.open(artifact('report.html'),'_blank','noopener');};$('#task-select').onchange=e=>{if(e.target.value)openTask(e.target.value);};
document.addEventListener('keydown',e=>{if(!state.run||document.querySelector('dialog[open]:not(#task-theater)')||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName))return;if(e.code==='Space'){e.preventDefault();setPlaying(!state.playing);}if(e.code==='ArrowRight'){e.preventDefault();setPlaying(false);setTime(state.t+1);}if(e.code==='ArrowLeft'){e.preventDefault();setPlaying(false);setTime(state.t-1);}});
new ResizeObserver(draw).observe(canvas);
let last=performance.now(),lastRender=0;
function animate(now){const dt=Math.min((now-last)/1000,.1);last=now;if(state.playing&&state.run){state.t=Math.min(state.taskWindow?.end??state.run.replay.end,state.t+dt*state.speed);draw();if(now-lastRender>110){renderTime();lastRender=now;}if(state.t>=(state.taskWindow?.end??state.run.replay.end)){setPlaying(false);renderTime();}}requestAnimationFrame(animate);}
requestAnimationFrame(animate);renderFiles();refreshCatalog().then(()=>{if(new URLSearchParams(location.search).get('new')==='interop'){$('#config-scenario').value='interop_containment';openConfig();}}).catch(e=>{$('#connection-text').textContent='连接失败';toast('无法连接本地服务：'+e.message);});

// Map navigation uses world coordinates; icon sizes remain readable in screen pixels.
function drawPlatformIcon(c,kind,x,y,r,yaw,color){
  c.save();c.translate(x,y);c.rotate(-yaw);c.scale(r/10,r/10);c.fillStyle=color;c.strokeStyle=color;c.lineWidth=1.5;c.lineJoin='round';
  if(kind==='UGV'){
    for(const a of [-6,4])for(const b of [-9,5])c.fillRect(a,b,3,4);
    c.beginPath();c.roundRect(-7,-5,14,10,2);c.fill();c.fillStyle='#fff';c.fillRect(2,-3,3,6);
  }else if(kind==='TANK'){
    c.beginPath();c.roundRect(-8,-9,16,5,2);c.roundRect(-8,4,16,5,2);c.fill();c.fillRect(-7,-4,13,8);
    c.beginPath();c.arc(0,0,4,0,Math.PI*2);c.fill();c.lineWidth=3;c.beginPath();c.moveTo(0,0);c.lineTo(12,0);c.stroke();
    c.strokeStyle='#fff';c.lineWidth=.7;c.strokeRect(-3,-3,6,6);
  }else if(kind==='PLANE'){
    c.beginPath();for(const [i,p] of [[11,0],[3,2],[-4,10],[-7,10],[-4,2],[-9,2],[-11,5],[-12,5],[-10,0],[-12,-5],[-11,-5],[-9,-2],[-4,-2],[-7,-10],[-4,-10],[3,-2]].entries())i?c.lineTo(...p):c.moveTo(...p);c.closePath();c.fill();
  }else{
    c.beginPath();c.moveTo(10,0);c.lineTo(-8,11);c.lineTo(-5,2);c.lineTo(-8,0);c.lineTo(-5,-2);c.lineTo(-8,-11);c.closePath();c.fill();c.strokeStyle='#fff';c.lineWidth=.8;c.beginPath();c.moveTo(6,0);c.lineTo(-4,0);c.stroke();
  }c.restore();
}
let mapDrag=null,mapDragMoved=false;
function mapScale(){const b=canvas.getBoundingClientRect();return Math.min((b.width-78)/(bounds[2]-bounds[0]),(b.height-78)/(bounds[3]-bounds[1]))*state.zoom;}
function shiftMap(dx,dy){bounds=[bounds[0]+dx,bounds[1]+dy,bounds[2]+dx,bounds[3]+dy];}
canvas.style.touchAction='none';canvas.style.cursor='grab';
canvas.addEventListener('wheel',e=>{
  if(!state.run||state.taskView==='process'&&state.taskWindow)return;
  e.preventDefault();const b=canvas.getBoundingClientRect(),x=e.clientX-b.left-b.width/2,y=e.clientY-b.top-b.height/2,old=mapScale();
  state.zoom=Math.max(.25,Math.min(32,state.zoom*Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*.008)));
  const next=mapScale();shiftMap(x/old-x/next,-y/old+y/next);draw();
},{passive:false});
canvas.addEventListener('pointerdown',e=>{
  if(e.button!==0||!state.run||state.taskView==='process'&&state.taskWindow)return;
  mapDrag={id:e.pointerId,x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY};mapDragMoved=false;canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove',e=>{
  if(!mapDrag||e.pointerId!==mapDrag.id)return;
  if(!mapDragMoved&&Math.hypot(e.clientX-mapDrag.x,e.clientY-mapDrag.y)<4)return;
  mapDragMoved=true;const scale=mapScale();shiftMap(-(e.clientX-mapDrag.lastX)/scale,(e.clientY-mapDrag.lastY)/scale);mapDrag.lastX=e.clientX;mapDrag.lastY=e.clientY;canvas.style.cursor='grabbing';draw();
});
for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{mapDrag=null;canvas.style.cursor='grab';});
canvas.title='滚轮缩放（以鼠标位置为中心） · 按住拖动平移 · 适应视图恢复';

for(const icon of document.querySelectorAll('.legend-platform')){const c=icon.getContext('2d');drawPlatformIcon(c,icon.dataset.kind,24,24,17,0,({UGV:'#3f6fa3',TANK:'#8a6b3d',PLANE:'#2f8f86',WING:'#7657a8'})[icon.dataset.kind]);}
