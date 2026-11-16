'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modes = {recording:'专项串行回放',normal:'正常执行',failure:'失败重试',timeout:'超时恢复',kill:'成员失联',deviation:'进度偏差'};
const DESKTOP_MODE=new URLSearchParams(location.search).get('desktop')==='1';
const objectives={makespan:'时效优先',energy:'能耗优先',exposure:'暴露度优先',balanced:'均衡目标',dispersion:'空间分散度'};
const statuses = {excluded:'未纳入本轮',pending:'待确认 / 待分配',running:'执行中',cancelling:'取消中',succeeded:'已完成',failed:'已失败'};
const types = {patrol:'巡逻警戒',blockade:'区域封控',recon:'协同侦察',assault:'机动突击',hold:'要点坚守'};
function taskLabel(j){const source=state.run?.scenario?.jobs?.find(x=>x.job_id===j.job_id);const wire=source?._task_type;return types[j.jtype||j.type]||({'T-PTL':'巡逻警戒','T-RCN':'协同侦察','T-SEC':'区域封控','T-HLD':'要点坚守'}[wire])||wire||j.jtype||j.type||'未标注任务';}
const icons = {patrol:'↻',blockade:'◇',recon:'⌕',assault:'↗',hold:'⌂'};
const kindNames = {UGV:'轮式车',TANK:'履带车',PLANE:'固定翼',WING:'飞翼'};
function buildingName(id){const k=String(id||'').replace(/^env[ _]city[ _]/,'').replace(/#\d+$/,'').replace(/_/g,' ').trim();const h=k.match(/^house\s*(\d+)/i);if(h)return '民居 '+Number(h[1]);const o=k.match(/^office\s*(\d+)/i);if(o)return '办公楼 '+Number(o[1]);return k;}
const taskPalette=['#288d79','#bd8534','#7264cb','#c27158','#478cac','#9a6b99'];
const events = {run_stopped:'手动结束并保存',config_updated:'配置已更新',recording_start:'专项片段开始',recording_end:'专项片段结束',plan_emitted:'生成规划方案',job_dispatched:'下发作业',job_succeeded:'作业完成',job_requeued:'作业重新排队',job_failed:'作业失败',member_lost:'平台失联',timeout:'作业超时',deviation:'进度偏差',cancel_sent:'发出取消请求',command_abandoned:'终止失联成员指令',feedback_ignored:'反馈未采纳',subtask_deviation:'子任务偏差',subtask_timeout:'子任务超时',subtask_failed:'子任务失败',subtask_reassigned:'子任务改派',subtask_abandoned:'子任务放弃',behavior_event:'到位行为'};
const behaviorEvents = {target_stopped:'目标已停止 · 坐标交接',phase:'行为阶段切换',checkpoint_visited:'到达检查点',cycle_completed:'完成一圈巡逻',posts_occupied:'封控占位就绪',intrusion_detected:'发现入侵',interceptor_assigned:'指派拦截',intercepted:'拦截成功',breach:'越界',map_initialised:'地图初始化',frontier_mapped:'可侦察网格更新',coverage_reached:'可侦察网格覆盖达标',recon_tracking_phase_started:'覆盖达标·进入目标跟踪',recon_track_handoff:'目标跟踪转交',report_sent:'成果回传',recon_target_report:'侦察目标位置上报',recon_track_started:'开始跟踪目标',recon_track_report:'跟踪位置上报',recon_track_completed:'完成区外跟踪',relay_handoff:'任务接力',return_started:'开始返航',return_completed:'已返回出发点',return_failed:'返航失败',return_interrupted:'返航中接到新任务',patrol_position_report:'模拟上报目标位置',patrol_target_started:'移动目标进入场景',patrol_target_lost:'目标离开感知范围',map_shared:'共享地图更新',all_staged:'全员到位',assault_started:'突击开始',effect_started:'效果施加开始',effect_applied:'动作结束',confirmed:'结果确认',salvo_fired:'齐射',ammo_depleted:'平台弹药耗尽',ammo_exhausted:'弹药耗尽终止',restrike_needed:'需要二次打击',control_established:'控制建立',control_lost:'控制丢失',suppression_gap:'压制中断',handover:'移交',assessment_requested:'评估发起',assessment_received:'评估回传',effect_achieved:'效果达成',deadline_exceeded:'执行超时',terminate:'任务终止',behavior_result:'效果判定结果',result_failed:'结果未达成',result_pending:'结果待评估',on_post:'上岗',handover_start:'接替开始',handover_complete:'接替完成',relief:'换班',behavior_complete:'行为完成',arrived_area:'进入作业区',route_failed:'路径失败',command_received:'受领任务',target_designated:'目标指示',all_in_position:'全员到位执行位',withdraw_started:'撤离开始',withdrawn:'撤离完成',withdraw_timeout:'撤离超时',confirmation_timeout:'确认超时',attack_window_missed:'错过攻击窗口',task_timeout:'任务超时',arrived:'到达点位',energy_depleted:'电量耗尽',start_snapped:'出发点吸附',target_appeared:'目标出现',target_detected:'发现目标',target_authorized:'识别为已授权',target_unauthorized:'识别为未授权',warning_issued:'发出警告',warning_effective:'警告有效·目标撤离',intercept_assigned:'指派拦阻',intercept_denied:'授权不足未拦阻',intercepted:'拦阻到位',breach:'未授权进入',authorized_pass:'授权放行',control_established:'控制建立',control_interrupted:'控制中断',control_restored:'控制恢复',containment_result:'封控结果'};
const triggerNames = {init:'首次规划',periodic:'周期更新',member_change:'成员变化',exec_fail:'执行失败',timeout:'超时',deviation:'进度偏差',subtask_fail:'子任务改派',timing:'时序冲突修复'};
const titles = {overview:'演示总览',tasks:'任务与分配',platforms:'平台状态',runs:'实验与报告',files:'项目文件'};
const sourceFiles = [['entry','README.md','融合版工程入口'],['interop_readme','interop/README.md','融合层接口与使用说明'],['readme','README_v2.md','项目说明与运行方式'],['planner','planner_v2.py','六步规则规划器'],['coordinator','coordinator_v2.py','反馈、调度与重规划'],['fleet','mock_fleet.py','本地执行与反馈替身'],['contracts','contracts_v2.py','场景与消息数据契约']];
const state = {catalog:null,run:null,t:0,playing:false,speed:2,focus:null,page:'overview',zoom:1,frames:[],eventRows:[],hits:[],loadToken:0,selectedTaskId:null,busy:false,ckView:false};
let toastTimer, pollTimer;
let processPollGeneration = 0;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function api(url, options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error||'读取失败');return data;}
function num(value,d=1){return value==null?'未知':Number(value).toFixed(d);}
Object.assign(behaviorEvents,{post_occupancy:'阵位占用变化',hold_result:'坚守结果'});
behaviorEvents.target_withdraw_started='目标开始撤离';
function no(pid){return '#'+String(pid||'').replace('rover_','');}
function reconTargetAt(jobId,t){
  const samples=state.run.replay.recon_target_tracks?.[jobId];
  if(!samples?.length||t<samples[0].t)return null;
  let lo=0,hi=samples.length;
  while(lo+1<hi){
    const mid=(lo+hi)>>1;
    if(samples[mid].t<=t)lo=mid;else hi=mid;
  }
  const a=samples[lo],b=samples[lo+1];
  if(!b||b.t-a.t>1)return a;
  const f=(t-a.t)/(b.t-a.t);
  return {...a,pos:a.pos.map((v,i)=>v+(b.pos[i]-v)*f)};
}
function stamp(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
function shortRun(id){if(id==='behavior_20261028_verify')return '专项验证记录 · 2026-10-28';if(id==='workbench_behavior_20261028')return '城市到位动作 · 2026-10-28';if(id==='avoid_run')return '旧版城市绕障 · 无到位动作';return id.replace('workbench_','').replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_.*$/,'$1-$2-$3 $4:$5:$6');}
function setPage(page){if(!Object.prototype.hasOwnProperty.call(titles,page))return;state.page=page;$$('.page').forEach(x=>x.classList.toggle('active',x.id==='page-'+page));$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page));$('#crumb').textContent=titles[page];$('#page-title').innerHTML=(page==='overview'?'把规划过程，看清楚。':esc(titles[page]))+'<span class="version">V2</span>';if(page==='overview'){renderTime();applyOverviewMode();window.WorkbenchUI?.render();requestAnimationFrame(draw);}else if(page==='runs'){applyOverviewMode();renderRuns();}else if(page==='files'){applyOverviewMode();renderFiles();}else if(page==='tasks'){applyOverviewMode();renderTasks();}else if(page==='platforms'){applyOverviewMode();renderPlatforms();}window.scrollTo(0,0);}
// 演示总览有两个视图：全局分配（多任务）与区域封控（单个封控区）。它们共用
// 同一个页面与顶部运行选择，不再各自是一个独立路由，避免"换数据源才看到
// 其它任务"这种两套口径。
function hasContainment(){return !!(state.run&&state.run.replay&&state.run.replay.containment);}
function hasHold(){return !!(state.run&&state.run.replay&&state.run.replay.hold);}
// 任务专属视图（区域封控 / 要点坚守）与"全局分配"并列，共用一个运行和时钟。
// 一个运行里有什么数据就只开放哪些页签，避免点进去看到空画布。
function overviewView(){return 'map';}

const OVERVIEW_BADGE={map:'全局分配',containment:'区域封控',hold:'要点坚守'};
function applyOverviewMode(){
  const view=overviewView(),ck=view==='containment',hl=view==='hold';
  const mapView=$('#overview-map-view'),ckView=$('#overview-ck-view'),hlView=$('#overview-hold-view'),tabs=$('#overview-tabs');
  if(mapView)mapView.hidden=view!=='map';
  if(ckView)ckView.hidden=!ck;
  if(hlView)hlView.hidden=!hl;
  if(tabs)tabs.hidden=true;
  $$('.ov-tab').forEach(b=>{b.classList.toggle('active',b.dataset.ov===view);b.hidden=(b.dataset.ov==='containment'&&!hasContainment())||(b.dataset.ov==='hold'&&!hasHold());});
  $('#overview-view')?.classList.toggle('active',view==='map');
  const badge=$('#view-badge');if(badge&&state.page==='overview')badge.textContent=OVERVIEW_BADGE[view]||'全局分配';
  if(ck||hl)setPlaying(false);
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
  if(window.HoldPage){
    if(hl){
      if(!state.hlViewApplied)window.HoldPage.syncTime(state.t);
      window.HoldPage.show();
    }else{
      if(state.hlViewApplied){const t=window.HoldPage.time();if(Number.isFinite(t))setTime(t);}
      window.HoldPage.hide();
    }
  }
  state.ckViewApplied=ck;state.hlViewApplied=hl;
  state.ckView=ck;state.hlView=hl;
  if(view==='map'){state.zoom=1;setBounds();draw();}
}
function showOverviewMode(mode){
  state.ovView='map';
  if(state.page!=='overview')setPage('overview');
  else applyOverviewMode();
}
// 没有封控动作记录时，明确说明"为什么看不到"，并给一键入口；
// 否则用户会以为 T1 这个封控作业也应该画出边界和探测圈。
function updateCkHint(){
  const box=$('#ck-hint');if(!box)return;
  if(hasContainment()||hasHold()){box.hidden=true;box.innerHTML='';return;}
  const runs=(state.catalog&&state.catalog.runs)||[];
  const candidate=runs.find(r=>r.scenario==='interop_containment'&&r.id!==state.run?.id);
  if(!candidate){box.hidden=true;box.innerHTML='';return;}
  box.hidden=false;
  box.innerHTML='<span>当前运行没有区域封控/要点坚守的动作记录：这里的任务只是历史样例的作业（按到点作业执行），'+
    '边界、探测圈、阵位与轮换只在“区域封控”“要点坚守”演示运行里生成。</span>'+
    '<button class="button small primary" data-ck-run="'+esc(candidate.id)+'">打开最近一次区域封控演示 →</button>';
}
function eventCategory(e){if(e.kind==='plan_emitted')return 'planning';if(e.kind==='behavior_event')return 'behavior';if(['member_lost','timeout','deviation','job_requeued','job_failed','cancel_sent','command_abandoned','feedback_ignored','subtask_deviation','subtask_timeout','subtask_failed','subtask_abandoned','subtask_reassigned'].includes(e.kind))return 'exception';return 'task';}
function eventDetail(e){if(e.kind==='run_stopped')return '已保存当前进度，未完成任务保留原状态';if(String(e.kind||'').startsWith('subtask_'))return (e.subtask_id||'')+(e.old_pid?' · '+e.old_pid+'→'+e.new_pid:'')+(e.reason?' · '+e.reason:'');if(e.kind==='config_updated')return '配置 '+(e.revision??'更新')+' · 修改 '+(e.jobs||e.tasks||[]).length+' 项任务'+(e.deleted?.length?' · 删除 '+e.deleted.join('、'):'');if(e.kind==='plan_emitted')return (e.triggers||[]).map(x=>x.split(':')[0]).join(' / ')+' · '+e.n_assignments+' 项指派';if(e.kind==='behavior_event'){const ev=e.event||{},sub=ev.kind;let d=behaviorEvents[sub]||sub||'';if(ev.phase)d+=' · '+ev.phase;if(ev.pid)d+=' · '+ev.pid;if(ev.cycle!=null)d+=' · 第'+ev.cycle+'圈';if(ev.coverage!=null)d+=' · 覆盖'+Math.round(ev.coverage*100)+'%';
  // T-ASL 效果判定事件的摘要字段
  if(ev.rounds!=null&&ev.pids)d+=' · '+(ev.pids||[]).map(no).join('/')+' 各'+ev.rounds+'发';
  if(ev.damage_level!=null)d+=' · 毁伤等级'+num(ev.damage_level);
  if(ev.level!=null&&ev.required!=null)d+=' · '+num(ev.level,1)+'/'+num(ev.required,1);
  if(ev.gap_s!=null)d+=' · 中断'+num(ev.gap_s,1)+' s';
  if(ev.held_s!=null)d+=' · 保持'+num(ev.held_s,1)+' s';
  if(ev.occupants!=null)d+=' · 在位'+ev.occupants;
  if(ev.at!=null&&sub==='effect_achieved')d+=' · T+'+num(ev.at,1)+' s';
  if(ev.by)d+=' · '+ev.by;
  if(['patrol_position_report','recon_target_report','recon_track_report','recon_track_completed'].includes(sub))d+=' · '+ev.target_id+' ('+ev.pos.map(x=>num(x)).join(', ')+')';
  if(ev.tracked_outside_s!=null)d+=' · 区外连续跟踪 '+num(ev.tracked_outside_s,1)+' s';
  if(sub==='relay_handoff')d+=' · '+ev.from_job_id+' → '+ev.job_id+(ev.pos?' · ('+ev.pos.map(x=>num(x)).join(', ')+')':'');
  if(ev.source)d+=' · '+ev.source;
  if(ev.overall)d+=' · '+(resultStatusNames[ev.overall]||ev.overall);
  if(ev.reason)d+=' · '+(terminationNames[ev.reason]||ev.reason);
  if(ev.verified===false)d+=' · 桩·未验证';
  if(ev.latency_s!=null)d+=' · 时延'+num(ev.latency_s,1)+' s';
  if(sub==='intercept_assigned'&&ev.eta_s!=null){
    d+=' · 预计到位 '+num(ev.eta_s,1)+' s';
    if(ev.entry_eta_s!=null)d+=' · 距目标入界 '+num(ev.entry_eta_s,1)+' s';
  }
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
      if(e.kind==='config_updated'){
        for(const jid of e.jobs||[]){const k=jobs[jid];if(k&&!['succeeded'].includes(k.status))Object.assign(k,{status:(e.excluded||[]).includes(jid)?'excluded':'pending',progress:0,pids:[],phase:null,behavior:{}});}
        for(const jid of e.deleted||[]){if(jobs[jid])jobs[jid].status='deleted';}
      }
      if(e.kind==='plan_emitted')plans++;
      if(e.kind==='member_lost')lost.add(e.pid);
      if(['job_dispatched','recording_start'].includes(e.kind)&&j){j.status='running';j.assignedAt=e.sim_s;j.attempts=e.attempt;j.pids=e.pids;j.start=e.planned_start;j.end=e.planned_end;if(e.attempt>1)retries++;}
      if(e.kind==='feedback_applied'){const ev=e.event,k=jobs[ev.job_id];if(k){k.progress=Math.max(k.progress,ev.progress||0);k.phase=ev.phase;if(!['succeeded','failed','cancelling'].includes(k.status))k.status='running';}}
      if(e.kind==='behavior_event'){
        const ev=e.event||{},k=jobs[ev.job_id];
        if(['relay_target_sample','recon_target_sample'].includes(ev.kind))continue;
        if(k){const b=k.behavior;if(!['behavior_detail','approach_route'].includes(ev.kind))b.last=ev.kind;b.at=e.sim_s;
          if(ev.kind==='behavior_detail'){b.detail={debug:ev.debug,params:ev.params,phase:ev.phase,at:e.sim_s};b.routes=b.routes||{};for(const r of ev.routes||[])b.routes[r.pid]={...r,recordedAt:e.sim_s};}
          if(ev.kind==='approach_route'){b.routes=b.routes||{};b.routes[ev.route.pid]={...ev.route,recordedAt:e.sim_s};}
          if(ev.kind==='behavior_structure')b.startedAt=e.sim_s;
          if(ev.phase)k.phase=ev.phase;
          if(ev.kind==='checkpoint_visited')b.checkpoints=(b.checkpoints||0)+1;
          if(ev.kind==='cycle_completed')b.cycles=Math.max(b.cycles||0,ev.cycle||0);
          if(ev.kind==='map_initialised'&&ev.cells!=null){
            b.mapStartedAt=e.sim_s;b.shares=0;b.reported=false;delete b.reconResult;
            delete b.reconTargetReport;delete b.reconTrack;delete b.reconTrackDone;
          }
          if(ev.kind==='recon_target_report')b.reconTargetReport=ev;
          if(ev.kind==='recon_track_started')b.reconTrack={...ev,at:e.sim_s-1+(ev.t%1)};
          if(ev.kind==='recon_track_completed')b.reconTrackDone=ev;
          if(ev.coverage!=null)b.coverage=ev.coverage;
          if(ev.kind==='map_shared')b.shares=(b.shares||0)+1;
          if(ev.kind==='handover_start')b.handover={incoming:ev.incoming,outgoing:ev.outgoing,done:false};
          if(ev.kind==='handover_complete'){b.handovers=(b.handovers||0)+1;b.handover={incoming:ev.incoming,outgoing:ev.outgoing,done:true};}
          if(ev.kind==='intrusion_detected'||ev.kind==='intercepted')b.observed={kind:ev.kind,pos:ev.pos};
          if(ev.kind==='intercepted')b.intercepted=true;
          if(ev.kind==='confirmed')b.confirmed=true;
          if(ev.kind==='report_sent'){
            b.reported=true;
            if(ev.coverage_target!=null)b.reconResult={
              overall:ev.overall,remaining:ev.remaining_cells.length,
              coverageReached:ev.coverage>=ev.coverage_target,
            };
          }
          if(ev.kind==='patrol_target_started')b.patrolObservers={};
          if(ev.kind==='patrol_position_report'){
            b.patrolReport=ev;b.patrolReportCount=(b.patrolReportCount||0)+1;
            if(!ev.shared_target)(b.patrolObservers||={})[ev.pid]=e.sim_s;
          }
          if(ev.kind==='patrol_target_lost'&&!ev.shared_target&&b.patrolObservers)delete b.patrolObservers[ev.pid];
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
function frame(){if(state.run?.live)return state.liveFrame;return state.frames[Math.min(state.frames.length-1,Math.floor(state.t))];}
function workerAt(w){
  const samples=w.samples;let lo=0,hi=samples.length;
  while(lo<hi){let mid=(lo+hi)>>1;if(samples[mid].t<=state.t)lo=mid+1;else hi=mid;}
  const prev=samples[lo-1];
  let result=prev?{...prev}:{x:w.start[0],y:w.start[1],z:w.start_z||0,yaw:w.start_yaw||0,battery:w.initial_battery,job:null,status:null,distance:0,t:null};
  const next=samples[lo];
  if(prev&&next&&state.run.report.motion==='real'&&next.t>prev.t&&prev.command===next.command&&['accepted','progress'].includes(prev.status)&&!frame().lost.includes(w.pid)){
    result=window.ReplayPose.between(prev,next,state.t);
  }
  const live = state.livePositions?.get(w.pid);
  if (live && (state.t >= state.run.live.sim_s - 1e-6 || !samples.length)) {
    const command = state.run.live.assignments.find(a => a.platform === w.pid);
    const job = command?.id ?? null;
    const phase = job === result.job || result.phase === 'return' ? result.phase : null;
    result = {...result, x:live.pos[0], y:live.pos[1], z:live.z ?? result.z,
      yaw:live.yaw ?? result.yaw, battery:live.battery, job, phase};
  }
  result.lost=frame().lost.includes(w.pid);return result;
}
function setTime(t){if(!state.run||state.run.live)return;const range=state.taskWindow;state.t=Math.min(range?.end??state.run.replay.end,Math.max(range?.start??0,t));renderTime();draw();}
function setPlaying(yes){if(state.run?.live)yes=false;state.playing=!!yes;if(yes&&state.t>=(state.taskWindow?.end??state.run.replay.end))state.t=state.taskWindow?.start??0;$('#play').textContent=yes?'Ⅱ 暂停':'▶ 播放';$('#play-state').textContent=yes?'播放中':'已暂停';}
function phaseName(phase){return ({travel:'前往作业区',work:'到达作业区',return:'返航中',loiter:'盘旋等待',landing:'降落中',returned:'已返回出发点'})[phase]||phase||'尚未开始';}
function taskUsesBehavior(jid){
  return state.run.report.behavior||state.run.replay.behaviors?.some(b=>b.job_id===jid);
}
function behaviorSummary(j,s){
  const b=s.behavior;
  if(!taskUsesBehavior(j.job_id))return '到点工作量模型';
  if(j.jtype==='patrol')return `已记录 ${b.cycles||0} 圈 · ${b.checkpoints||0} 次检查点访问`+(b.patrolReport?` · 已模拟上报 ${b.patrolReportCount} 次`:'');
  if(j.jtype==='recon'&&b.reconResult){
    const outcome=b.reconResult.overall==='succeeded'?'达标已回传':
      b.reconResult.coverageReached?'跟踪未完成，已回传部分成果':'未达标，已回传部分成果';
    return `覆盖 ${num(b.coverage*100,1)}% · ${outcome} · 剩余 ${b.reconResult.remaining} 格`;
  }
  if(j.jtype==='recon')return b.coverage==null?'等待探索反馈':`覆盖 ${Math.round(b.coverage*100)}% · 共享 ${b.shares||0} 次${b.reported?' · 已回传':''}`;
  if(j.jtype==='hold')return `已接替 ${b.handovers||0} 次`+(b.handover?` · ${no(b.handover.outgoing)} → ${no(b.handover.incoming)}${b.handover.done?' 已完成':' 接替中'}`:'');
  if(j.jtype==='blockade')return b.observed?(b.intercepted?'已记录处置完成':'已记录区域事件'):'等待占位与区域事件反馈';
  return b.confirmed?'已收到结果确认':b.last?(behaviorEvents[b.last]||b.last):'等待阶段反馈';
}
function renderBehaviors(){
  const enabled=!!(state.run.report.behavior||state.run.replay.behaviors?.length),f=frame();
  $('#behavior-model').textContent=enabled?'本轮动作已接入':'到点工作量模型';
  $('#behavior-model').classList.toggle('warning',!enabled);
  $('#behavior-count').textContent=enabled?state.run.report.jobs.filter(j=>f.jobs[j.job_id].behavior.at!=null).length+' / '+state.run.report.jobs.length:'0';
  $('#behavior-note').textContent=enabled?'来自当前运行的动作阶段与事件；点击卡片定位任务，点击关键节点跳转。':'此历史运行未启用到位动作。点击“载入动作演示”查看已有动作记录。';
  $('#behavior-list').innerHTML=enabled?state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id];return `<button class="behavior-tile ${selectedJobId()===j.job_id?'selected':''}" style="--task-color:${taskColor(j.job_id)}" data-job="${esc(j.job_id)}"><span class="behavior-tile-head"><b>${esc(j.job_id)} · ${esc(taskLabel(j))}</b><span>${esc(s.status==='succeeded'?'已完成':phaseName(s.phase))}</span></span><small>${esc(behaviorSummary(j,s))}</small></button>`;}).join(''):'<div class="empty">本轮轨迹只记录到点作业。<button class="button small" data-behavior-run>载入动作演示 →</button></div>';
  const keyKinds=new Set(['cycle_completed','posts_occupied','intrusion_detected','intercepted','handover_start','handover_complete','map_initialised','coverage_reached','report_sent','recon_target_report','recon_track_started','recon_track_completed','relay_handoff','patrol_target_started','target_detected','patrol_target_lost','all_staged','effect_applied','confirmed']);
  const jid=selectedJobId();
  $('#behavior-milestones').innerHTML=enabled?state.eventRows.filter(e=>e.kind==='behavior_event'&&keyKinds.has(e.event?.kind)&&(!jid||e.job_id===jid)).map(e=>`<button class="milestone ${e.sim_s>state.t?'future':'occurred'}" data-event-time="${e.sim_s}" data-event-job="${esc(e.job_id)}"><span>${e.sim_s} s${e.sim_s>state.t?' · 未发生':''}</span>${esc(e.job_id)} · ${esc(eventTitle(e))}</button>`).join(''):'';
}
function updatePlaybackStructures(){
  const history=state.run.replay.behavior_history;
  if(!history?.length)return;
  const current=new Map();
  for(const item of history){
    if(!current.has(item.job_id)||item.sim_s<=state.t)current.set(item.job_id,item);
  }
  state.run.replay.behaviors=[...current.values()];
}
function renderTime(){
  window.followExecutionTask?.();
  if(!state.run||document.hidden)return;const f=frame(),jobs=Object.values(f.jobs),done=jobs.filter(j=>j.status==='succeeded').length;
  updatePlaybackStructures();
  renderCampusCase();
  $('#stat-done').textContent=done;$('#stat-total').textContent='/ '+jobs.length;$('#done-bar').style.width=(jobs.length?100*done/jobs.length:0)+'%';const returnTotal=Object.keys(state.run.report.returns||{}).length;
  const returned=state.eventRows.filter(e=>e.sim_s<=state.t&&e.event?.kind==='return_completed').length;
  $('#done-note').textContent=done===jobs.length?(returnTotal?'任务完成 · 已归队 '+returned+'/'+returnTotal:'本轮全部完成'):'按当前反馈统计';
  $('#stat-alive').textContent=state.run.replay.workers.length-f.lost.length;$('#stat-plans').textContent=state.run.report.recording?'未记录':f.plans;$('#plan-note').textContent=state.run.report.recording?'保存的专项串行记录':'已重试 '+f.retries+' 次 · 已超时 '+f.timeouts+' 次';$('#stat-clock').textContent=state.t.toFixed(1);$('#clock').textContent=(state.taskWindow?state.t-state.taskWindow.start:state.t).toFixed(1);$('#scrubber').value=state.t;
  $('#task-list').innerHTML=state.run.report.jobs.map(j=>{const s=f.jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<button class="task-row ${selectedJobId()===j.job_id?'selected':''}" style="--task-color:${taskColor(j.job_id)}" data-job="${esc(j.job_id)}"><div class="task-line"><span class="job-icon">${icons[j.jtype]||'◇'}</span><b>${esc(taskLabel(j)||j.jtype)}<span class="task-id">${esc(j.job_id)}</span></b><span class="task-status ${s.status}">${statuses[s.status]}</span></div><div class="task-progress"><div class="progress-track"><i style="width:${pct}%"></i></div><span>${Math.round(pct)}%</span></div><div class="task-assigned">${s.pids.length?s.pids.map(no).join(' · '):'等待可行分配'}${state.run.report.behavior?' · '+esc(phaseName(s.phase)):''}</div></button>`;}).join('');
  if(state.page==='overview'){renderInspector();renderEvents();renderBehaviors();renderStage();renderTheater();window.WorkbenchUI?.render();}
  if(state.page==='tasks')renderTasks();if(state.page==='platforms')renderPlatforms();
}
function focus(type,id,go=false){const w=type==='worker'?state.run.replay.workers.find(w=>w.pid===id):null;state.focus={type,id,jobId:state.taskWindow?.jobId||(w?activeWorkerJob(w):null)};if(type==='job')state.selectedTaskId=id;else if(state.focus.jobId)state.selectedTaskId=state.focus.jobId;state.zoom=1;setBounds();if(go)setPage('overview');renderTime();draw();}
function observationVersion(t=state.t){
  return state.run?.replay.observation_target_versions?.findLast(version=>version.t<=t);
}
function observationPosition(target,t){
  const elapsed=target.release_s==null?0:Math.max(0,t-target.release_s);
  const fraction=target.duration_s?Math.min(1,elapsed/target.duration_s):0;
  return target.start.map((value,i)=>value+(target.goal[i]-value)*fraction);
}
const observationReportIndex=new WeakMap();
function observationReports(id){
  if(!observationReportIndex.has(state.run)){
    const byTarget=new Map();
    for(const row of state.run.trace){
      const event=row.event;
      if(!event?.shared_target||!['patrol_position_report','patrol_target_lost'].includes(event.kind))continue;
      if(!byTarget.has(event.target_id))byTarget.set(event.target_id,new Map());
      const byTask=byTarget.get(event.target_id);
      if(!byTask.has(event.job_id))byTask.set(event.job_id,{reports:[],byPlatform:new Map()});
      const task=byTask.get(event.job_id);
      const sample={t:row.sim_s,pid:event.pid,pos:event.pos};
      if(!task.byPlatform.has(event.pid))task.byPlatform.set(event.pid,[]);
      task.byPlatform.get(event.pid).push(sample);
      if(sample.pos)task.reports.push(sample);
    }
    observationReportIndex.set(state.run,byTarget);
  }
  return observationReportIndex.get(state.run).get(id)||new Map();
}
function observationAt(events,t){
  let start=0,end=events.length;
  while(start<end){
    const mid=(start+end)>>1;
    if(events[mid].t<=t)start=mid+1;
    else end=mid;
  }
  return events[start-1];
}
function observationReporting(job,history){
  const current=frame();
  if(current.jobs[job]?.status!=='running'||!history)return false;
  return [...history.byPlatform].some(([pid,events])=>{
    if(current.lost.includes(pid))return false;
    const last=observationAt(events,state.t);
    return last?.pos&&last.t===Math.floor(state.t);
  });
}
function renderInspector(){
  const f=state.focus;if(!f){$('#inspector').innerHTML='<p class="muted">点击地图平台或任务，查看当前位置、分配关系与反馈。也可从右上角新建演示，比较异常处理。</p>';return;}
  if(f.type==='worker'){
    const w=state.run.replay.workers.find(w=>w.pid===f.id);if(!w)return;const p=workerAt(w);
    const active=p.job&&frame().jobs[p.job]?.status==='running';
    $('#inspector').innerHTML=`<div class="focus-title"><span style="color:${taskColor(activeWorkerJob(w))}">●</span> ${esc(w.pid)} · ${esc(w.kind_name)}</div><dl><div><dt>当前坐标</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度 / 场景单位</dt><dd>${num(p.z)}</dd></div><div><dt>当前作业</dt><dd>${p.lost?'成员失联':active?esc(p.job):'空闲 / 最近反馈'}</dd></div><div><dt>当前动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>累计反馈路程</dt><dd>${num(p.distance)}</dd></div><div><dt>最近位置反馈</dt><dd>${p.t==null?'仅场景初始位':num(p.t,0)+' s'}</dd></div></dl>`;
  }else if(f.type==='observation-target'){
    const version=observationVersion();
    const target=version?.targets.find(item=>item.target_id===f.id);
    if(!target){$('#inspector').textContent='当前时刻未配置该目标。';return;}
    const reports=observationReports(f.id);
    const tasks=new Set([...Object.entries(version.links).filter(([,ids])=>ids.includes(f.id))
      .map(([id])=>id),...[...reports].filter(([,history])=>history.reports[0]?.t<=state.t).map(([id])=>id)]);
    const pos=observationPosition(target,state.t);
    const rows=[...tasks].map(id=>{
      const history=reports.get(id);
      const last=history&&observationAt(history.reports,state.t);
      return '<div><dt>'+esc(id)+'</dt><dd>'+(last
        ? (observationReporting(id,history)?'正在上报':'当前未上报')
          +' · 首次 '+num(history.reports[0].t,0)+' s · 最近 '+num(last.t,0)+' s · '+esc(last.pid)
          +' ('+last.pos.map(v=>num(v)).join(', ')+')'
        : '尚无上报')+'</dd></div>';
    }).join('');
    $('#inspector').innerHTML='<div class="focus-title">'+esc(f.id)+' · 观察目标</div><dl><div><dt>位置</dt><dd>'
      +pos.map(v=>num(v)).join(', ')+'</dd></div>'+rows+'</dl>';
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
  if(!state.run){$('#task-table').innerHTML='<tr><td colspan="7">尚未载入运行记录</td></tr>';return;}
  $('#task-table').innerHTML=state.run.report.jobs.map(j=>{const s=frame().jobs[j.job_id],pct=Math.min(100,100*s.progress/j.work);return `<tr class="${selectedJobId()===j.job_id?'selected':''}"><td><button class="text-button" data-job="${esc(j.job_id)}" data-locate>${esc(j.job_id)} · ${esc(taskLabel(j))}</button><small>协同需求 ${j.crew} 台 · ${esc(j.need_sensor||'无专属传感器')}</small></td><td>${j.pos.map(x=>num(x)).join(', ')}</td><td><span class="pill ${s.status==='failed'?'warning':''}">${statuses[s.status]}</span><small>${esc(phaseName(s.phase))}</small></td><td>${state.run.report.recording?'按记录阶段':num(s.progress)+' / '+j.work}<div class="progress-track table-progress"><i style="width:${pct}%"></i></div></td><td>${s.pids.map(no).join(' · ')||'—'}</td><td>${s.attempts}</td><td>${j.window.join(' – ')} s</td></tr>`;}).join('');
}
function renderPlatforms(){
  if(!state.run){$('#platform-grid').textContent='尚未载入运行记录';return;}
  const filter=$('#platform-filter').value;
  $('#platform-grid').innerHTML=state.run.replay.workers.filter(w=>filter==='all'||w.kind===filter).map(w=>{const p=workerAt(w);return `<button class="platform-tile" data-worker="${esc(w.pid)}" data-locate><h3><i style="background:${taskColor(activeWorkerJob(w))}"></i>${esc(w.pid)}<span>${p.lost?'失联':'可用'}</span></h3><p>${esc(w.kind_name)} · ${esc(w.kind)}</p><dl><div><dt>位置</dt><dd>${num(p.x)}, ${num(p.y)}</dd></div><div><dt>高度</dt><dd>${num(p.z)}</dd></div><div><dt>模型电量</dt><dd>${num(p.battery)}</dd></div><div><dt>最近作业</dt><dd>${esc(p.job||'—')}</dd></div><div><dt>动作阶段</dt><dd>${esc(phaseName(p.phase))}</dd></div></dl></button>`;}).join('');
}
function renderRuns(){
  $('#runs-table').innerHTML=(state.catalog?.runs||[]).map(r=>`<tr class="${r.id===state.run?.id?'selected':''}"><td><button class="text-button" data-load-run="${esc(r.id)}">${esc(shortRun(r.id))}</button><small>${esc(objectives[r.objective]||r.objective)} · ${r.recording?'记录已保存':r.settled?'已结算':'达到步数上限，未结算'}</small></td><td>${modes[r.mode]||esc(r.mode)}<small>${r.motion==='real'?'逐步运动':'瞬移'}${r.avoid?' · 建筑绕障':''}${r.behavior?' · 到位行为':''}${r.planner==='interop'?' · 融合规划':''}</small></td><td>${r.done} / ${r.total}</td><td>${r.end} s</td><td>${num(r.energy)}</td><td>${r.recording?'未记录':r.retries+' / '+r.timeouts}</td><td><button class="text-button" data-load-run="${esc(r.id)}">载入回放 ↗</button></td></tr>`).join('');
  renderRunCompare();
  if(!state.run){$('#report-status').textContent='尚未载入';$('#report-summary').textContent='选择运行记录后查看整轮最终结果';return;}const r=state.run.report;
  $('#report-status').textContent=r.manual_stopped?'手动结束 · 已保存部分结果':r.all_succeeded?'全部完成':r.settled?'本轮已结算':'未结算';$('#report-status').classList.toggle('warning',!r.all_succeeded);
  $('#report-objective').textContent='目标 · '+(objectives[r.objective]||r.objective||'未记录')+(r.plan_objective_metrics?'':'（旧记录）');
  const pm=r.plan_objective_metrics||{};
  const shown=v=>v==null?'未记录':num(v,v!==0&&Math.abs(v)<10?2:1);
  const pct=v=>v==null?'未记录':(100*v).toFixed(1)+'%';
  $('#report-summary').innerHTML=[[r.done+'/'+r.jobs.length,r.recording?'记录完成的片段':'工作量达标作业'],[r.simulated_until_s+' s','仿真运行终点'],[num(r.used_energy),'累计模型耗电'],[shown(pm.makespan_s??r.makespan),'计划 makespan / s'],[shown(pm.total_exposure),'总暴露量（计划）'],[pct(pm.detection_probability),'被侦察到的概率（计划）'],[r.plans??'未记录','规划方案数'],[r.retries??'未记录','重试次数'],[r.timeouts??'未记录','超时次数']].map(([v,l])=>`<div><b>${esc(v)}</b><span>${l}</span></div>`).join('');
  const execX=r.execution_exposure,execP=r.execution_detection_probability;
  const execNote=$('#exec-exposure-note');
  if(execNote){
    if(!(state.run.threats||[]).length){execNote.textContent='本场景无威胁区，不计算执行暴露。';execNote.classList.remove('warning');}
    else if(execX==null){execNote.textContent='';execNote.classList.remove('warning');}
    else{
      const planX=pm.total_exposure;
      const crossed=planX!=null&&execX>planX+0.01;
      execNote.textContent='模拟执行轨迹暴露量 '+num(execX,2)+' · 被侦察到的概率 '+pct(execP)+(planX!=null?'（计划估计：暴露量 '+num(planX,2)+' / 被侦察到的概率 '+pct(pm.detection_probability)+'）':'');
      execNote.classList.toggle('warning',crossed);
      if(crossed)execNote.textContent+=' · 执行暴露高于计划估计，需核对路径、停留与规划版本';
    }
  }
  const total=Math.max(1,...Object.values(r.triggers||{}));$('#triggers').innerHTML=Object.entries(r.triggers||{}).map(([k,v])=>`<div class="trigger-row"><span>${triggerNames[k]||esc(k)}</span><div><i style="width:${100*v/total}%"></i></div><b>${v}</b></div>`).join('');
  for(const id of ['download-report'])$('#'+id).hidden=!!r.recording;
  $('#download-report').href=artifact('report.json');$('#download-trace').href=artifact(r.recording?'behavior_trace.json':'trace.jsonl');$('#result-scope').textContent=r.recording?'本页为原始专项串行记录；未记录的规划、工作量与能耗指标不补造。':r.behavior?'本轮启用到位行为；作业终态来自已保存的模拟日志。':'本轮未启用到位行为；完成只表示原模型工作量达标。';
  // Gazebo / ROS2 对接：把"控制平台怎么走"的速度指令文件放在报告页最前面，
  // 三轮任务（封控/坚守/突击）走同一条输出链路，所以这里对任一运行都同样显示。
  renderResolution();
  renderGazeboCard(state.run.files||[]);
}
function renderResolution(){
  if(!document.getElementById('resolution-status')){
    const card=document.createElement('article');card.className='card';
    card.innerHTML='<div class="card-heading"><div><div class="eyebrow">DYNAMIC RESCHEDULING</div><h2>配置变更后的子任务消解率</h2><p>同一平台切换到不同子任务，且在20回合内收到已采纳反馈才计为消解。排除空闲变化和同子任务重发。</p></div><span class="pill" id="resolution-status">—</span></div><div id="resolution-summary" class="report-summary"></div><div class="table-scroll"><table><thead><tr><th>配置生效</th><th>平台</th><th>原子任务 → 新子任务</th><th>下发 / 确认</th><th>判定</th><th>反馈编号</th></tr></thead><tbody id="resolution-table"></tbody></table></div>';
    document.getElementById('page-runs').append(card);
  }
  const data=state.run?.report?.timing_resolution;
  const status=$('#resolution-status'),summary=$('#resolution-summary'),table=$('#resolution-table');
  if(!status||!summary||!table)return;
  status.classList.remove('warning');
  if(data?.metric!=='config_subtask_switch_rate_20'){
    status.textContent='—';summary.innerHTML='';
    table.innerHTML='<tr><td colspan="6" class="muted">本轮未记录新口径的子任务切换统计。</td></tr>';
    return;
  }
  const roundText=[1,5,10,20].map(k=>data.by_round[k]==null?'—':(data.by_round[k]*100).toFixed(2)+'%').join(' / ');
  status.textContent=data.meets_threshold==null
    ? (data.insufficient?'观察窗口不足':'无有效切换样本')
    : (data.meets_threshold?'达标':'未达标');
  status.classList.toggle('warning',data.meets_threshold===false);
  summary.innerHTML=[
    [(data.rate_percent==null?'—':data.rate_percent+'%'),'20回合内消解率'],
    [data.resolved+' / '+data.total,'已消解 / 有效切换'],
    [data.expired+' 超限 · '+data.insufficient+' 待观察','超预算 / 观察窗口不足'],
    ['1 / 5 / 10 / 20 回合',roundText]
  ].map(([v,l])=>`<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
  const labels={resolved:'已消解',expired:'超预算',insufficient:'观察窗口不足'};
  table.innerHTML=data.switches.map(c=>`<tr><td>${esc(c.config_version)} · ${c.edit_s} s</td><td>${esc(c.unit_id||c.worker_id)}</td><td>${esc(c.from_subtask_id)} → ${esc(c.to_subtask_id)}</td><td>${c.dispatch_s} s / ${c.confirmed_s==null?'—':c.confirmed_s+' s · '+c.rounds_used+' 回合'}</td><td>${labels[c.status]}</td><td>${esc(c.feedback_id||'—')}</td></tr>`).join('')||'<tr><td colspan="6" class="muted">本轮没有符合统计条件的子任务切换。</td></tr>';
}
function renderGazeboCard(files){
  let card=document.getElementById('gazebo-card');
  const grid=document.querySelector('#page-runs .report-grid');
  if(!card&&grid){card=document.createElement('article');card.id='gazebo-card';card.className='card gazebo-card';grid.prepend(card);}
  if(!card)return;
  const has=id=>files.includes(id);
  const motion=state.run.report.motion_commands;
  const full=has('motion_commands.json');
  card.hidden=!full&&!has('commands.csv');
  if(card.hidden)return;
  const parts=[];
  if(full)parts.push(`<a class="button primary" href="${artifact('motion_commands.json')}" download>↓ 完整运动指令 JSON</a>`);
  if(has('motion_commands.csv'))parts.push(`<a class="button" href="${artifact('motion_commands.csv')}" download>↓ 完整运动指令 CSV</a>`);
  if(has('ros2_plan_node.py'))parts.push(`<a class="button" href="${artifact('ros2_plan_node.py')}" download>↓ ros2_plan_node.py · ROS 2 独立节点</a>`);
  if(has('commands.csv'))parts.push(`<a class="button" href="${artifact('commands.csv')}" download>↓ 路径规划速度表</a>`);
  if(has('plan.json'))parts.push(`<a class="button" href="${artifact('plan.json')}" download>↓ plan.json · 静态计划</a>`);
  if(has('ros2_commands.txt'))parts.push(`<a class="button" href="${artifact('ros2_commands.txt')}" target="_blank" rel="noopener">静态计划发布示例</a>`);
  const info=full
    ? '包含本轮已执行的任务运动、驻留盘旋和返航。ROS 2 节点默认读取完整运动 JSON。'
    : '本轮提供静态计划速度指令。重新运行可生成完整运动文件。';
  const status=motion?(motion.status==='complete'?'本地仿真已归队':'本轮仅导出已执行片段')+
    ' · 默认播放时间倍率 '+motion.recommended_time_scale+'×。':'';
  card.innerHTML=`<div class="card-heading"><div><div class="eyebrow">GAZEBO / ROS2 INTERFACE</div><h2>运动指令导出</h2><p>${info}</p></div></div><div class="report-actions">${parts.join('')}</div><p class="muted">${esc(status)} 当前按时间发布，Gazebo 位姿反馈尚未接入。</p>`;
}
function artifact(name){return '/artifacts/'+encodeURIComponent(state.run.id)+'/'+name;}
const fileDescriptions={'chain_viewer.html':'集编组、任务分解、指令与反馈全链路查看','chain_verification.json':'全链路关联完整性校验','chain_raw.json':'本轮真实采集的指令、反馈和配置事件','initial_config.json':'运行前任务与平台配置','final_config.json':'运行后任务与平台配置','run_meta.json':'全链路运行元数据','manifest.json':'运行配置、来源与环境','scenario.json':'本轮实际场景快照','report.json':'最终指标与状态','trace.jsonl':'逐条原始反馈与审计','summary.txt':'文本结果摘要','report.html':'原始可视化报告','trajectory.html':'原始轨迹播放器','request.json':'工作台请求参数','worker.log':'本轮运行日志','plan.json':'4.2 计划层与执行层完整结构','assignments.csv':'槽位分配字段子集','commands.csv':'速度指令字段子集','report.md':'4.2 计划报告（路径/指令/未分配）','ros2_commands.txt':'可直接粘贴的 ros2 topic pub 命令','motion_commands.json':'完整运动速度序列与参考位姿','motion_commands.csv':'完整运动速度指令表','ros2_plan_node.py':'ROS 2 节点，优先播放完整运动，兼容静态计划'};
function renderFiles(){
  let entry=document.getElementById('files-entry');
  if(!entry){entry=document.createElement('div');entry.id='files-entry';entry.className='files-entry';$('#source-files').before(entry);}
  entry.innerHTML='<h3>融合版工程入口</h3>'+sourceFiles.slice(0,2).map(([key,name,desc])=>'<button class="button" data-source="'+key+'">'+esc(name)+' · '+esc(desc)+'</button>').join(' ');

  $('#source-files').innerHTML=sourceFiles.slice(2).map(([key,name,desc])=>`<button class="file-item" data-source="${key}"><span>↗</span><b>${name}</b><small>${desc}</small></button>`).join('');
  if(!state.run){$('#artifact-files').textContent='尚未载入运行记录';return;}$('#output-path').textContent='planning_middle_demo/outputs/'+state.run.id+'/';
  $('#artifact-files').innerHTML=state.run.files.map(n=>`<a class="file-item" href="${artifact(n)}" target="_blank" rel="noopener"><span>↗</span><b>${n}</b><small>${fileDescriptions[n]||'运行产物'}</small></a>`).join('');
}
async function loadRun(id,autoplay=false){
  const wasLive = state.run?.id===id && state.run?.live;
  const token=++state.loadToken;closeTheater();setPlaying(false);window.WorkbenchUI?.status('正在加载运行…');
  try{
    const data=await api('/api/runs/'+encodeURIComponent(id));if(token!==state.loadToken)return;
    if(wasLive){displayRun(data,{keepView:true});return true;}
    for(const id of ['play','restart','step-back','step-next','jump-end','speed','scrubber'])$('#'+id).disabled=false;state.livePositions=null;state.liveFrame=null;
    state.run=data;state.selectedTaskId=data.report.jobs[0]?.job_id||null;window.WorkbenchUI?.reset();
    let mapNote=$('#scene-map-note');if(!mapNote){mapNote=document.createElement('div');mapNote.id='scene-map-note';mapNote.className='scene-map-note';document.querySelector('.map-legend').after(mapNote);}
    mapNote.textContent=data.scene_map?.note||data.geometry_note||'';
document.body.classList.toggle('recording-data',!!data.report.recording);state.t=0;state.focus=null;state.zoom=1;state.frames=makeFrames(data);state.eventRows=data.trace.map((e,index)=>{if(e.kind==='behavior_event'&&e.event&&e.event.job_id&&!e.job_id)e={...e,job_id:e.event.job_id};return {...e,index};}).filter(e=>events[e.kind]&&!(e.kind==='behavior_event'&&['behavior_structure','behavior_detail','approach_route','relay_target_sample','recon_target_sample','return_sample','air_wait_sample'].includes(e.event?.kind)));lastEventKey='';
    $('#run-select').value=id;$('#run-mode').textContent=modes[data.report.mode]||data.report.mode;$('#run-semantic').textContent=data.report.recording?data.report.recording_source.note:(data.report.motion==='real'?'逐步运动':'瞬移')+(data.report.avoid?' · 静态建筑绕障':'')+(data.report.behavior?' · 到位行为':'')+' · '+(data.report.objective||'makespan');
    $('#stat-end').textContent=data.replay.end;$('#duration').textContent=data.replay.end;$('#scrubber').max=data.replay.end;$('#timeline-mid').textContent=stamp(data.replay.end/2);$('#timeline-end').textContent=stamp(data.replay.end);$('#task-count').textContent=data.report.jobs.length;$('#side-jobs').textContent=String(data.report.jobs.length).padStart(2,'0');
    $('#fleet-note').textContent=[...new Set(data.replay.workers.map(w=>w.kind_name))].join(' · ');
    const options=data.report.jobs.map(j=>`<option value="${esc(j.job_id)}">${esc(j.job_id)} · ${esc(taskLabel(j))}</option>`).join('');$('#task-select').innerHTML='<option value="">选择一项任务，观看执行过程</option>'+options;$('#theater-task').innerHTML=options;$('#model-note').textContent='选任务后打开大画幅执行回放';setBounds();renderTime();renderRuns();renderFiles();draw();if(window.ContainmentPage)window.ContainmentPage.load(data);if(window.HoldPage)window.HoldPage.load(data);
    const ckBtn=$('#open-containment');if(ckBtn)ckBtn.hidden=!data.replay.containment;
    // 只含区域封控/要点坚守一个作业的运行，默认就站在对应的任务视图：这个
    // 运行本身就是一次演示，"全局分配"只用来对照机动与任务位置。
    state.ckView=!!(data.replay.containment&&data.report.jobs.length===1);
    state.hlView=!!(data.replay.hold&&data.report.jobs.length===1);
    state.ckView=false;state.hlView=false;state.ovView='map';
    applyOverviewMode();
    updateCkHint();
    window.WorkbenchUI?.status('');if(data.manifest.playback_start_s!=null)setTime(data.manifest.playback_start_s);if(autoplay)setPlaying(true);return true;}catch(e){if(token!==state.loadToken)return false;$('#run-select').value=state.run?.id||'';window.WorkbenchUI?.status('载入失败：'+e.message,true);toast('载入失败：'+e.message);return false;}
}
async function refreshCatalog(selectId){
  const data=await api('/api/catalog');state.catalog=data;state.templates=data.templates||{};window.BrowserIntegration?.catalog(data);window.dispatchEvent(new CustomEvent('workbench-templates'));
  if(data.templates)setTemplates(data.templates);
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
  if(!caps.hold){
    const opt=[...document.querySelectorAll('#config-scenario option')].find(o=>o.value==='interop_hold');
    if(opt){opt.disabled=true;opt.textContent='要点坚守 · 需要重启工作台服务（当前服务版本 '+esc(data.version||'未知')+'）';}
  }
  $('#run-select').innerHTML=data.runs.map(r=>{const sc=r.scenario?((data.scenarios&&data.scenarios[r.scenario])||r.scenario):null;return `<option value="${esc(r.id)}">${sc?esc(sc)+' · ':''}${r.total} 个任务 · ${r.behavior_details?'动作与避障细节':r.behavior?'到位动作':'到点作业'} · ${modes[r.mode]||r.mode} · ${esc(shortRun(r.id))}</option>`;}).join('');
  if(selectId||!state.run){const requested=new URLSearchParams(location.search).get('source');const id=selectId||(data.runs.some(r=>r.id===requested)?requested:null)||(data.runs.find(r=>r.id===data.default_run)||data.runs.find(r=>r.behavior)||data.runs[0])?.id;if(id){await loadRun(id);const task=new URLSearchParams(location.search).get('task');if(task&&state.run?.report.jobs.some(j=>j.job_id===task)){openTask(task,false);const params=new URLSearchParams(location.search);if(params.get('view')==='spatial')state.taskView='spatial';else if(params.get('view')==='process')state.taskView='process';if(params.has('t'))setTime(Number(params.get('t')));renderTheater();draw();}}else toast('还没有运行记录，点击新建演示开始。');}
  else{$('#run-select').value=state.run.id;renderRuns();}
  if(data.process?.state==='running')watchProcess(data.process.id);
  updateCkHint();
  const pageParam=new URLSearchParams(location.search).get('page');
  if(pageParam==='containment')showOverviewMode('containment');
  if(pageParam==='hold')showOverviewMode('hold');
  else if(pageParam&&titles[pageParam]&&pageParam!==state.page)setPage(pageParam);
}
function updateRunControls(process=state.activeProcess){
  state.activeProcess=process;
  const banner=$('#busy-banner'),footer=$('#config-dialog .dialog-footer');
  for(const [id,parent] of [['stop-live',banner],['stop-live-config',footer]]){
    if(!document.getElementById(id)){
      const button=document.createElement('button');button.id=id;button.type='button';button.className='button';
      button.textContent='结束本轮并保存';button.onclick=stopCurrentLive;parent.append(button);
    }
  }
  let note=document.getElementById('run-active-note');
  if(!note){note=document.createElement('p');note.id='run-active-note';note.className='form-note';footer.before(note);}
  const live=state.busy&&Boolean(process?.live);
  const ending=live&&(state.endingLive||process.stopping);
  const paused=live&&state.run?.id===process.id&&state.run.live?.paused;
  const canStop=live&&Boolean(state.catalog?.features?.live_stop);
  for(const id of ['stop-live','stop-live-config']){
    const button=document.getElementById(id);button.hidden=!canStop;button.disabled=Boolean(ending);
    button.textContent=ending?'正在结束并保存…':'结束本轮并保存';
  }
  note.hidden=!state.busy;
  note.textContent=live?'当前实时运行尚未结束。可先调整新演示配置，结束并保存本轮后再启动。':'当前计算尚未完成，可先调整新演示配置，完成后再启动。';
  $('#submit-run').disabled=state.busy;
  $('#submit-run').textContent=!state.busy?'运行演示 →':ending?'正在保存当前运行…':live?'请先结束当前实时运行':'当前计算中…';
  if(state.busy)$('#busy-banner>span:last-of-type').textContent=ending?'正在结束本轮并保存结果，请稍候…':live?(paused?'实时运行已暂停，可继续或结束并保存':'实时运行中，可暂停查看或结束并保存'):'正在计算规划、模拟执行并生成报告…';
  banner.style.flexWrap='wrap';
}
async function stopCurrentLive(){
  const process=state.activeProcess;
  if(!state.busy||!process?.live||state.endingLive)return;
  state.endingLive=true;updateRunControls(process);
  try{
    await api('/api/live/'+encodeURIComponent(process.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'})});
    toast('已请求结束本轮，保存完成后可运行新演示');
  }catch(error){state.endingLive=false;updateRunControls(process);toast(error.message);}
}
function setBusy(b){state.busy=b;if(!b){state.endingLive=false;state.activeProcess=null;$('#run-select').disabled=false;window.dispatchEvent(new CustomEvent('workbench-process'));}$('#busy-banner').hidden=!b;updateRunControls();}
function watchProcess(id){
  const generation = ++processPollGeneration;
  setBusy(true);
  clearTimeout(pollTimer);
  window.dispatchEvent(new CustomEvent('workbench-process', {detail: id}));
  async function poll() {
    try {
      const {process} = await api(state.catalog?.features?.process_status?'/api/process':'/api/catalog');
      if (generation !== processPollGeneration) return;
      if (process?.id !== id) {
        setBusy(false);
        return;
      }
      if (process.state === 'running') {
        updateRunControls(process);
        pollTimer = setTimeout(poll, 800);
        return;
      }
      await refreshCatalog();
      if (generation !== processPollGeneration) return;
      setBusy(false);
      if (process.state === 'complete') {
        if (!await loadRun(id, true) || generation !== processPollGeneration) return;
        setPage('overview');
        if (process.replacing) {
          toast('当前演示已更新，正在播放重规划后的回放');
        } else {
          const replay = state.run.replay;
          toast(state.run.report.manual_stopped?'本轮已结束并保存，可新建演示':replay.hold ? '本轮结果已保存，已打开“要点坚守”视图。'
            : replay.containment ? '本轮结果已保存，已打开“区域封控”视图。'
            : '本轮结果已保存，正在回放实际反馈。');
        }
      } else if (process.error) {
        toast(process.error);
      } else {
        const log = await fetch('/artifacts/' + encodeURIComponent(id) + '/worker.log').then(r => r.text());
        if (generation === processPollGeneration) toast('运行失败：' + log.slice(-200));
      }
    } catch (e) {
      if (generation !== processPollGeneration) return;
      $('#busy-banner>span:last-of-type').textContent='正在重新连接运行状态，尚未确认本轮结束…';
      toast('状态读取失败：' + e.message);
      pollTimer=setTimeout(poll,1600);
    }
  }
  pollTimer = setTimeout(poll, 800);
}
function updateConfig(){const scenario=$('#config-scenario').value,interop=scenario.startsWith('interop'),aslInterop=scenario==='interop_asl',containment=scenario==='interop_containment',hold=scenario==='interop_hold',patrol=['interop_patrol','interop_patrol_sdf50'].includes(scenario),recon=scenario==='interop_recon',campus=scenario==='interop_campus_motion20',taskView=containment||hold||patrol||recon||campus,base=false,allow=base||aslInterop||taskView;$('#config-avoid').disabled=!allow||aslInterop||taskView;if(!allow)$('#config-avoid').checked=false;else if(aslInterop||taskView)$('#config-avoid').checked=true;$('#config-behavior').disabled=!allow||aslInterop||taskView||!$('#config-avoid').checked;if(!allow||!$('#config-avoid').checked)$('#config-behavior').checked=false;else if(aslInterop||taskView)$('#config-behavior').checked=true;$('#config-effect').disabled=!base;$('#config-effect-field').hidden=!base;for(const id of ['config-avoid','config-behavior'])$('#'+id).closest('label').hidden=!allow;$('#config-scope-note').textContent=containment?'区域封控：融合层规划 + 基座逐步运动与到位行为；占位/警告/拦阻由行为层执行，结果只作本地仿真结论。':hold?'要点坚守：融合层分配阵位与预备队，基座行为层执行占位/观察/轮换/增援/撤离；反击与压制只作桩判定的抽象效果（verified=false），结果只作本地仿真结论。':patrol?'巡逻警戒：2 台轮式无人车绕障进场，2 台飞翼无人机从空中进场。空地各自调速，感知到移动目标时每秒模拟上报位置。':recon?'协同侦察：四台空地平台分头扫描，发现目标后上报。优先派无人机跟踪驶离目标，完成区外跟踪及 99% 覆盖后回传。':aslInterop?'机动突击演示（T-ASL）：规划器固定 interop，侦察/突击/评估席位由统一层分配；打击与效果判定由基座行为层执行，效果类型以 4.1 消息为准。':interop?'融合层中性任务：规划器固定为 interop，逐步运动；突击效果类型不适用。':'历史城市场景沿用基座规划器与原有行为链；可在运行记录中查看已保存的地图与回放。';
  // 仿真步数跟随当前场景默认值；
  // 用户编辑过的值不会因切换场景被覆盖。
  const ticks=$('#config-form [name=max_ticks]');ticks.max=1200;
  const defaults={interop_containment:620,interop_hold:700,interop_patrol:320,interop_recon:220,interop_asl:700,interop_integrated:700,interop_campus_motion20:1100};
  if(scenario==='interop_patrol_sdf50')$('#config-scope-note').textContent='SDF 50台编成：轮式20台、履带10台、固定翼10台、飞翼10台，初始位姿取自场景文件。沿用原巡逻任务的4个执行名额、区域与2圈要求。模板保存在项目场景目录，删除运行记录后仍可重新生成。';
  if(scenario==='interop_campus_motion20')$('#config-scope-note').textContent='六栋楼综合任务：轮式8台、履带4台、固定翼4台、飞翼4台；地面起飞、28米巡航、8米转弯半径。侦察跟踪至目标停止，停止位置交给后续机动任务；全部任务完成后统一归队。';
  const untouched=ticks.dataset.userEdited!=='true';
  if(untouched)ticks.value=defaults[scenario]??state.templates?.[scenario]?.max_ticks??200;
  // User input is validated by existing form/server limits, not silently rewritten.
}
function openConfig(){updateConfig();$('#config-error').hidden=true;$('#config-dialog').showModal();}
let submittingRun=false;
$('#config-form [name=max_ticks]').addEventListener('input',e=>{e.target.dataset.userEdited='true';});
$('#config-form').addEventListener('submit',async e=>{e.preventDefault();if(submittingRun||state.busy)return;submittingRun=true;$('#submit-run').disabled=true;const f=new FormData(e.target),scenario=f.get('scenario'),interop=scenario.startsWith('interop'),config={scenario,mode:f.get('mode'),motion:'real',objective:f.get('objective'),planner:interop?'interop':'base',live:false,max_ticks:Number(f.get('max_ticks')),avoid:$('#config-avoid').checked&&!$('#config-avoid').disabled,behavior:$('#config-behavior').checked&&!$('#config-behavior').disabled,...(!$('#config-effect').disabled?{effect_kind:f.get('effect_kind')}:{})};try{const result=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});$('#config-dialog').close();watchProcess(result.id);}catch(err){$('#config-error').textContent=err.message;$('#config-error').hidden=false;}finally{submittingRun=false;$('#submit-run').disabled=state.busy;}});
const theater=$('#task-theater'),mapCard=$('.map-card'),sceneHome=$('.overview-grid');
function taskRange(jid){
  const rows=state.run.trace,dispatch=rows.find(e=>['job_dispatched','recording_start'].includes(e.kind)&&e.job_id===jid);
  const structure=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid);
  const samples=state.run.replay.workers.flatMap(w=>w.samples.filter(p=>p.job===jid)).sort((a,b)=>a.t-b.t);
  const start=dispatch?.sim_s??samples[0]?.t??0,execution=structure?.sim_s??samples.find(p=>p.phase&&p.phase!=='travel')?.t??start;
  const settled=rows.findLast(e=>['job_succeeded','job_failed','recording_end'].includes(e.kind)&&e.job_id===jid)?.sim_s;
  const returns=holdReplayFor(jid)?state.run.replay.workers.map(w=>window.HoldPage.taskSamples(w,jid).at(-1)?.t||0):[];
  const end=Math.max(settled??samples.at(-1)?.t??start+1,...returns);
  return {jobId:jid,dispatch:start,start,execution,end:Math.max(execution,end)};
}
function updateTaskTimeline(){
  const range=state.taskWindow;if(!range)return;
  $('#scrubber').min=range.start;$('#scrubber').max=range.end;$('#duration').textContent=range.end-range.start;
  $('.player-clock').title='本任务观看区间经过时间；绝对仿真时刻见右侧';
  $('#timeline-mid').textContent=stamp((range.end-range.start)/2);$('#timeline-end').textContent=stamp(range.end-range.start);$('.timeline-labels>span').textContent='00:00';
}
function openTask(jid,autoplay=false){
  if(!state.run||!state.run.report.jobs.some(j=>j.job_id===jid))return;
  const savedPlaying=state.playing;setPage('overview');state.selectedTaskId=jid;state.taskWindow=taskRange(jid);state.taskView='spatial';state.focus={type:'job',id:jid};state.zoom=1;
  state.taskWindow.start=Math.min(state.taskWindow.start,state.t);state.taskWindow.end=Math.max(state.taskWindow.end,state.t);setPlaying(savedPlaying);
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
function taskExecutionHtml(jid){
  const j=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],b=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid&&b.sim_s<=state.t),range=taskRange(jid);
  const bh=j.behavior||{},order=state.run.report.behavior?`<div class="task-order"><div class="eyebrow">TASK ORDER · 任务指令</div><div class="order-head"><b>${esc(jid)} · ${esc(taskLabel(j))}</b><span>${esc(b?.effect||'')}${b?.target_id?' · 目标 '+esc(b.target_id):''}</span></div><div class="order-meta"><span>时间窗 ${j.window[0]}–${j.window[1]} s</span><span>执行截止 ${bh.execute_deadline??'—'} s</span><span>撤离截止 ${bh.withdraw_deadline??'—'} s</span><span>兵力 ${s.pids.length} 台</span></div>${bh.roe?`<p>规则：${esc(bh.roe)}</p>`:''}</div>`:'';
  const elapsed=Math.max(0,state.t-range.execution);return order+`<div class="detail-phase" style="color:${taskColor(jid)}">${s.status==='succeeded'?'已完成':esc(phaseName(s.phase))}</div><div class="detail-metric">${esc(behaviorSummary(j,s))}</div><dl><div><dt>${state.run.report.recording?'进度依据':'任务工作量'}</dt><dd>${state.run.report.recording?'已记录阶段':num(s.progress)+' / '+j.work}</dd></div><div><dt>执行经过</dt><dd>${num(elapsed)} s</dd></div><div><dt>当前仿真时刻</dt><dd>${num(state.t)} s</dd></div><div><dt>${state.run.report.recording?'片段起点':'任务下发'}</dt><dd>${range.dispatch} s</dd></div></dl><p>画面只显示本任务的日志反馈。${b&&Math.hypot(b.site[0]-j.pos[0],b.site[1]-j.pos[1])>.1?'作业位置按现有避障结果吸附，原目标：'+j.pos.map(x=>num(x)).join(', ')+'。':''}</p>`+assaultResultHtml(jid);
}
function renderTheater(){
  if(!state.taskWindow)return;const jid=state.taskWindow.jobId,j=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],b=(state.run.replay.behaviors||[]).find(b=>b.job_id===jid&&b.sim_s<=state.t);
  $('#theater-details').innerHTML=taskExecutionHtml(jid);
  $('#theater-members').innerHTML=s.pids.map(pid=>{const w=state.run.replay.workers.find(w=>w.pid===pid),p=w?workerAt(w):{};return `<button class="theater-member ${state.focus?.id===pid?'selected':''}" data-worker="${esc(pid)}"><b>${esc(pid)}<span>${esc(w?.kind_name||'')}</span></b><strong>${esc(phaseName(p.phase))}</strong><small>坐标 ${num(p.x,2)}, ${num(p.y,2)} · 高度 ${num(p.z)}</small></button>`;}).join('')||'<p class="empty">尚未下发成员</p>';
  const rows=state.eventRows.filter(e=>e.job_id===jid&&e.kind==='behavior_event'&&e.sim_s<=state.t&&e.event?.kind!=='phase');$('#theater-event-count').textContent=rows.length;
  $('#theater-events').innerHTML=rows.slice(-6).reverse().map(e=>`<button data-task-time="${e.sim_s}"><time>${e.sim_s} s</time><b>${esc(eventTitle(e))}</b><small>${esc(eventDetail(e))}</small></button>`).join('')||'<p>等待本任务的执行反馈</p>';
  renderExecutionEvidence(jid);renderTaskDetailChrome(jid);
}
function teamColor(pid,jid=selectedJobId()){
  const ids=frame().jobs[jid]?.pids||[],i=ids.indexOf(pid);
  return ['#367bc0','#bf649c','#309a87','#ba8b42'][Math.max(0,i)%4];
}
function holdReplayFor(jid){
  const r=state.run.replay;
  return r.hold_by_job?.[jid]||(r.hold?.job_id===jid?r.hold:null);
}
function holdReturnAt(w,jid){
  const sample=w.samples.findLast(s=>s.t<=state.t);
  return sample?.command?.startsWith('return:')&&window.HoldPage.taskSamples(w,jid).includes(sample);
}
function workbenchHold(jid){
  const job=frame().jobs[jid],b=job.behavior,debug=b.detail?.debug||{},structure=(state.run.replay.behaviors||[]).find(x=>x.job_id===jid);
  const replay=holdReplayFor(jid);
  if(replay&&state.t>=replay.structure.sim_s){
    const statuses=replay.structure.positions.map(p=>({id:p.id,...window.HoldPage.postStatus(replay,p.id,state.t)}));
    const returning=replay.result&&state.t>=replay.result.sim_s;
    const names={reserve:'预备队',support:'支援位',relay:'中继位',air:'空中观察'};
    const roles={};
    for(const pid of job.pids){
      const w=state.run.replay.workers.find(x=>x.pid===pid);
      const station=statuses.find(p=>p.pid===pid);
      const role=replay.structure.roles?.[pid]||'';
      roles[pid]=returning?(w&&holdReturnAt(w,jid)?phaseName(workerAt(w).phase):'任务已结算'):
        station?station.id+' · '+station.label:
        statuses.some(p=>p.label==='撤离中')?'撤离中':
        role.startsWith('post:')?role.slice(5)+' · 尚未在位':names[role.split(':')[0]]||'机动中';
    }
    const message=returning?replay.result.reason:
      statuses.map(p=>p.id+' '+p.label).join('；');
    return {primary:statuses.find(p=>p.pid)?.pid,roles,message};
  }
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
function taskRoutesHtml(jid){
 const s=frame().jobs[jid];
  const history=state.run.trace.filter(e=>e.kind==='behavior_event'&&e.event.job_id===jid&&e.sim_s<=state.t).flatMap(e=>e.event.kind==='behavior_detail'?(e.event.routes||[]).map(r=>({...r,recordedAt:e.sim_s})):e.event.kind==='approach_route'?[{...e.event.route,recordedAt:e.sim_s}]:[]),blocked=history.filter(r=>!r.straight_line_ok);
  const routes=currentTaskRoutes(jid);
  let html=routes.map(r=>`<div class="path-evidence"><b style="color:${teamColor(r.pid,jid)}">${esc(r.pid)} · ${r.straight_line_ok?'当前直线可通行':'原直线被挡，已生成绕行路径'}</b><small>路径 ${num(r.length,2)} / 直线 ${num(r.straight,2)} 单位</small><small>规划路径净空 ${num(r.min_clearance,3)} 单位 · 记录于 ${num(r.recordedAt,0)} s</small></div>`).join('')||(s.behavior.detail||state.run.report.behavior_details?'<p>当前无未完成的地面绕行段。空中接近按现有直飞替身处理；任务内部路径另按记录展示。</p>':'<p>这份旧日志未记录路径细节。新建带行为与绕障的运行会自动生成这些证据。</p>');
  html+=`<div class="route-history"><small>已记录 ${history.length} 段路径 · ${blocked.length} 段直线受阻</small>${blocked.slice(-3).map(r=>`<button data-task-time="${r.recordedAt}">回看 ${r.recordedAt} s · ${no(r.pid)} 绕行</button>`).join('')}<small>实线：已行轨迹；虚线：记录的规划路径；灰块：碰撞体。净空为规划指标。</small></div>`;
 return html;
}
function renderExecutionEvidence(jid){
  const job=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],isHold=job.jtype==='hold';
  $('#workbench-team-card').hidden=isHold;$('#workbench-hold-card').hidden=!isHold;$('#hold-chapters').hidden=!isHold;
  if(isHold){const hold=workbenchHold(jid);
    $('#workbench-hold-status').innerHTML=`<p class="hold-narrative">${esc(hold.message)}</p><div class="handover-count">已确认交接 <b>${s.behavior.handovers||0}</b> 次</div>${s.pids.map(pid=>`<div class="hold-role" style="border-left-color:${teamColor(pid,jid)}"><b>${esc(pid)}</b><span>${esc(hold.roles[pid])}</span><small>颜色与地图成员标记一致</small></div>`).join('')}`;
    $('#hold-chapters').innerHTML=state.eventRows.filter(e=>e.job_id===jid&&['on_post','handover_start','handover_complete','withdraw_started','withdrawn','withdraw_timeout','hold_result'].includes(e.event?.kind)).map(e=>`<button class="${e.sim_s>state.t?'future':''}" data-task-time="${e.sim_s}"><small>+${num(e.sim_s-state.taskWindow.execution,0)} s${e.sim_s>state.t?' · 未播放':''}</small>${esc(eventTitle(e))}${e.event.incoming?' · '+no(e.event.outgoing)+' → '+no(e.event.incoming):''}</button>`).join('');
    $('#theater-members').innerHTML=s.pids.map(pid=>{const worker=state.run.replay.workers.find(w=>w.pid===pid),pos=worker?workerAt(worker):{};return `<button class="theater-member" data-worker="${esc(pid)}" style="border-left:3px solid ${teamColor(pid,jid)}"><b>${esc(pid)}<span>${esc(worker?.kind_name)}</span></b><strong>${esc(hold.roles[pid])}</strong><small>当前坐标 ${num(pos.x,2)}, ${num(pos.y,2)}</small></button>`;}).join('');
  }
  $('#workbench-route-status').innerHTML=taskRoutesHtml(jid);
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
function selectedJobId(){return state.run ? state.selectedTaskId : null;}
function selectTask(jid){if(!state.run?.report.jobs.some(j=>j.job_id===jid))return;state.selectedTaskId=jid;state.focus={type:'job',id:jid};$('#task-select').value=jid;state.zoom=1;setBounds();renderTime();draw();}

function activeWorkerJob(w){const p=workerAt(w),s=frame().jobs[p.job];return s&&['running','cancelling'].includes(s.status)&&s.pids.includes(w.pid)?p.job:null;}
function visibleStructures(){const jid=selectedJobId();return (state.run.replay.behaviors||[]).filter(b=>$('#show-behaviors').checked&&b.sim_s<=state.t&&b.job_id===jid&&(state.taskWindow||frame().jobs[jid]?.status!=='succeeded'||$('#full-trails').checked));}
function globalView(){if(state.taskWindow){closeTheater();return;}state.selectedTaskId=null;state.focus=null;$('#task-select').value='';state.zoom=1;setBounds();renderTime();draw();}
function taskArea(job){
  const area=job._behavior?.area;
  return ['patrol','recon'].includes(job.type)&&Array.isArray(area)?area:null;
}
function containmentLayers(jid=null){
  const replay=state.run?.replay;
  const byJob=replay?.containment_by_job||{};
  const layers=Object.values(byJob);
  const items=layers.length?layers:(replay?.containment?[replay.containment]:[]);
  return jid?items.filter(layer=>layer.job_id===jid):items;
}
function containmentPoints(layer){
  return [...(layer.structure.area||[]),...(layer.targets||layer.structure.targets||[])
    .flatMap(t=>[t.start,t.goal]).filter(Boolean)];
}
function campusTasks(){
  const bundle=state.run?.scenario?._meta?.interop;
  if(!bundle?.formation?.meta?.movement_case)return [];
  // Rewind the observed target update when the replay clock is before it.
  let tasks=bundle.message.tasks;
  const updates=state.run.trace.filter(e=>e.kind==='config_updated'&&e.source==='target_stopped');
  for(const e of updates){if(state.t<e.sim_s)tasks=tasks.map(t=>t.task_id==='MOV-C'?{...t,target:{point:[-95,-145]}}:t);}
  return tasks;
}
function campusRegion(t){const a=t.target.area||t.target.patrol_area;return a?.polygon||a||null;}
function campusMetric(t){
  const rows=state.run.trace.filter(e=>e.kind==='behavior_event'&&e.event.job_id===t.task_id&&e.sim_s<=state.t),last=rows.filter(e=>e.event.kind==='behavior_detail').at(-1)?.event.debug||{};
  if(t.task_type==='T-RCN'){
    let metric=`可侦察网格覆盖目标 ≥${Math.round(t.params.coverage_target*100)}% · 当前 ${Math.round((last.coverage||0)*100)}%`;
    if(t.params.tracking_target){const e=rows.filter(e=>['recon_track_started','recon_track_report','target_stopped','recon_track_completed'].includes(e.event.kind)).at(-1)?.event;metric+=e?` · ${behaviorEvents[e.kind]} · ${e.pid} · (${e.pos.join(', ')})`:' · 等待发现移动目标';}
    return metric;
  }
  if(t.task_type==='T-PTL')return `边界巡逻 ${t.params.cycles||1} 圈 · 已完成 ${rows.filter(e=>e.event.kind==='cycle_completed').length} 圈`;
  if(t.task_type==='T-SEC')return `占位保持 ${t.params.hold_duration_s}s · ${t.params.roles.boundary}边界 / ${t.params.roles.gate}门哨 / ${t.params.roles.reserve}机动`;
  if(t.task_type==='T-HLD')return `坚守 ${t.params.hold_duration_s}s · ${t.params.roles.post}在岗 / ${t.params.roles.reserve}预备`;
  const stop=state.run.trace.find(e=>e.event?.kind==='target_stopped'&&e.sim_s<=state.t);
  return stop?`停止位置已交接 (${stop.event.pos.join(', ')}) · 到点协同 ${t.params.duration_s}s`:'等待目标发现 → 跟踪 → 停止位置交接';
}
function renderCampusCase(){
  let panel=document.getElementById('campus-case-panel');const tasks=campusTasks();
  if(!tasks.length){if(panel)panel.hidden=true;return;}
  if(!panel){panel=document.createElement('section');panel.id='campus-case-panel';panel.className='campus-case-panel';document.querySelector('.canvas-wrap').after(panel);}
  panel.hidden=false;const f=frame(),selected=selectedJobId(),names={'T-RCN':'协同侦察','T-SEC':'区域封控','T-PTL':'巡逻警戒','T-HLD':'要点坚守','T-ASL':'机动突击 · 仿真到点'};
  panel.innerHTML=`<div class="campus-heading"><b>六栋楼综合任务 · 区域与指标</b><a class="button small" href="${artifact('chain_viewer.html')}" target="_blank">查看全链路数据 ↗</a></div><p>20台 / 4类 · 地面起飞 → 28m巡航 · 最小转弯与盘旋半径8m · 全部任务完成后统一返回起点并降落</p><div class="campus-task-grid">${tasks.filter(t=>!selected||selected===t.task_id).map(t=>{const p=campusRegion(t),pt=t.target.point||t.target.key_point,region=p?`${Math.min(...p.map(x=>x[0]))}～${Math.max(...p.map(x=>x[0]))} × ${Math.min(...p.map(x=>x[1]))}～${Math.max(...p.map(x=>x[1]))} m`:`目标 (${pt?.join(', ')}) m`;return `<button data-job="${esc(t.task_id)}" class="campus-task" style="border-left-color:${taskColor(t.task_id)}"><b>${esc(t.task_id)} · ${names[t.task_type]}</b><span>${esc(t.description)} · ${statuses[f.jobs[t.task_id].status]}</span><span>区域 / 点位：${esc(region)}</span><span>${esc(campusMetric(t))}</span><small>先后：${esc(t.depends_on.join(' + ')||'首先执行')} · ${t.min_units}台 · 窗口 ${t.window.start_s}–${t.window.end_s}s</small></button>`;}).join('')}</div>`;
}
function drawCampusAreas(ctx,P){
  const tasks=campusTasks(),selected=selectedJobId();if(!tasks.length)return;
  ctx.save();for(const t of tasks){if(selected&&selected!==t.task_id)continue;const poly=campusRegion(t),c=taskColor(t.task_id);
    if(poly?.length){ctx.beginPath();poly.forEach((p,i)=>i?ctx.lineTo(...P(p)):ctx.moveTo(...P(p)));ctx.closePath();ctx.fillStyle=c+'15';ctx.fill();ctx.strokeStyle=c;ctx.lineWidth=1.6;ctx.setLineDash([5,3]);ctx.stroke();ctx.setLineDash([]);const [x,y]=P([Math.min(...poly.map(p=>p[0])),Math.max(...poly.map(p=>p[1]))]);ctx.font='bold 10px Microsoft YaHei';ctx.fillStyle='#ffffffeb';ctx.fillRect(x,y-17,110,16);ctx.fillStyle=c;ctx.fillText(t.task_id+' · '+({'T-RCN':'侦察区','T-SEC':'封控区','T-PTL':'巡逻区'}[t.task_type]||''),x+3,y-5);}
  }ctx.restore();
}
function setBounds(){
  if(!state.run)return;
  const versions=state.run.replay.observation_target_versions||[];
  const hasObservationTargets=versions.some(version=>version.targets.length);
  const taskAreas=state.run.replay.jobs.flatMap(j=>taskArea(j)||[]);
  const containment=containmentLayers();
  if(!taskAreas.length&&!containment.length&&!state.focus&&!state.taskWindow&&state.run.scene_map?.surfaces?.length){bounds=fullBounds();return;}
  // 只含区域封控一个作业的运行：全局分配也按"封控区 + 集结地"取景，
  // 不套整张场景图——否则 140 m 的封控区被压成一个小方块，看不出谁封哪段、
  // 各平台的探测圈也小到看不见。
  if(!hasObservationTargets&&!state.focus&&!state.taskWindow&&state.run.replay.containment
     &&state.run.report.jobs.length===1){
    const b=containmentBounds();if(b){bounds=b;return;}
  }
  // 要点坚守的运行同理：按"要点 + 阵位 + 威胁扇区"取景，不套整张场景图。
  if(!hasObservationTargets&&!state.focus&&!state.taskWindow&&state.run.replay.hold
     &&state.run.report.jobs.length===1){
    const b=holdBounds();if(b){bounds=b;return;}
  }
  if(!taskAreas.length&&!containment.length&&!state.focus&&state.run.scene_map?.surfaces?.length){bounds=fullBounds();return;}
  const r=state.run.replay,jid=state.taskWindow?.jobId||(state.focus?.type==='job'?state.focus.id:null),j=r.jobs.find(j=>j.job_id===jid);let points=[];
  if(j&&state.taskWindow){
    const structure=(r.behaviors||[]).find(b=>b.job_id===jid);points.push(structure?.site||j.pos);if(structure){points.push(...(structure.loop||[]),...(structure.type==='hold'?(structure.posts||[]).slice(0,1):(structure.posts||[])),...(structure.type==='hold'?(structure.standbys||[]).slice(0,1):(structure.standbys||[])),...(structure.staging||[]),...(structure.objective||[]));const radius=structure.area_radius||structure.ring_radius;if(radius)points.push([structure.site[0]-radius,structure.site[1]-radius],[structure.site[0]+radius,structure.site[1]+radius]);}
    const hold=holdReplayFor(jid);
    for(const w of r.workers){
      const samples=hold?window.HoldPage.taskSamples(w,jid):w.samples;
      if(hold&&samples.length)points.push(w.start);
      for(const p of samples)if((hold||p.job===jid)&&p.t>=state.taskWindow.start&&p.t<=state.taskWindow.end)points.push([p.x,p.y]);
    }
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
  if(j)points.push(...(taskArea(j)||[]));
  else if(!state.focus)points.push(...taskAreas);
  if(j||!state.focus)points.push(...containmentLayers(jid).flatMap(containmentPoints));
  for(const version of versions){
    for(const target of version.targets){
      if(jid&&!version.links[jid]?.includes?.(target.target_id))continue;
      if(state.focus?.type==='observation-target'&&state.focus.id!==target.target_id)continue;
      if(jid||!state.focus||state.focus.type==='observation-target')points.push(target.start,target.goal);
    }
  }
  if(r.relay_track&&!state.focus&&!state.taskWindow){
    points.push(...taskAreas,...r.jobs.map(job=>job.pos),...r.workers.map(w=>w.start),
      ...r.relay_track.samples.map(([,x,y])=>[x,y]));
  }
  if(j||!state.focus)for(const behavior of r.behaviors||[]){
    if(behavior.tracking_target&&(!j||behavior.job_id===jid))points.push(behavior.tracking_target.goal);
  }
  if(j||!state.focus)for(const row of r.events||[]){
    if(row.event?.kind==='patrol_target_started'&&(!j||row.job_id===jid)){
      points.push(row.event.pos,row.event.goal);
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
    }else if(structure&&j.type==='hold'&&state.t>=(taskEventTime(jid,'on_post')??Infinity)
      &&state.t<(holdReplayFor(jid)?.result?.sim_s??Infinity)){
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
  const s=f.jobs[jid],started=s.behavior.startedAt!=null||(!taskUsesBehavior(jid)&&s.phase&&s.phase!=='travel');
  const index=s.status==='succeeded'?3:started?2:s.phase?1:s.attempts?0:-1;
  const phase=s.status==='succeeded'?'已完成':s.status==='failed'?'执行失败':s.status==='cancelling'?'取消中':!s.attempts?'等待分配':started?phaseName(s.phase):s.phase==='work'?'等待成员到齐':'前往作业区';
  const ck=!!(state.run.replay.containment&&state.run.replay.containment.job_id===jid);
  panel.innerHTML=`<div class="stage-top"><div><span class="stage-dot"></span><b>${esc(jid)} · ${esc(taskLabel(j))}</b><span class="stage-phase">${esc(phase)}</span>${ck?'<button class="text-button" data-containment>◎ 区域封控视图</button>':''}</div><button class="text-button" data-global>返回全局 ↗</button></div><div class="stage-steps">${['已分配','前往作业区','执行动作','已完成'].map((v,i)=>`<span class="${i<index?'done':i===index?'current':''}"><i>${i<index?'✓':i+1}</i>${v}</span>`).join('')}</div><div class="stage-detail"><span>${esc(behaviorSummary(j,s))}</span><div class="force-chips">${s.pids.map(pid=>{const w=state.run.replay.workers.find(x=>x.pid===pid),role=(state.run.replay.behaviors||[]).find(x=>x.job_id===jid)?.roles?.[pid]||'';return `<button class="member-chip ${state.focus?.id===pid?'selected':''}" data-worker="${esc(pid)}" title="${esc((w?.kind_name||'')+(role?' · '+role:''))}">${no(pid)}<small>${esc(kindNames[w?.kind]||'')}${role?' · '+esc(role):''}</small></button>`;}).join('')||'<small>尚未分配成员</small>'}</div></div>`;
}
function trailsFor(w){
  const full = $('#full-trails').checked;
  if (!full && !$('#show-trails').checked) return [];
  // Focus highlights an agent/task; every visible agent keeps its recent tail.
  // Only a dedicated task playback restricts the participating agents.
  const taskId = state.taskWindow?.jobId;
  const hold = taskId && holdReplayFor(taskId);
  const samples=hold?window.HoldPage.taskSamples(w,taskId):w.samples;
  return window.ReplayPose.trails(samples,state.t,{
    full,seconds:10,interpolate:state.run.report.motion==='real',current:workerAt(w)
  }).filter(segment=>!taskId||hold||segment[0].job===taskId);
}

function mapGeometry(key){return state.run?.scene_map?.[key]||state.run?.[key]||[];}
function mapStyle(o){const id=o.id||'';return o.source==='mesh_aabb'?['#b9c8d6','#7b90a3']:id.includes('planter')?['#99b78c','#6c8961']:id.includes('walls')?['#aeb4b1','#7e8782']:id.includes('beacon')?['#d2b36b','#a38b4e']:['#ccd5d2','#9fadb4'];}
function landmarkName(o){const n=o.name||'';const names={env_beacon_lawn:'草坪区标识柱',env_beacon_walls:'围墙区标识柱',env_beacon_city:'城市区标识柱',env_beacon_wetlands:'湿地区标识柱',env_beacon_yosemite:'山地区标识柱',env_wetlands_north:'北湿地',env_wetlands_south:'南湿地',env_yosemite:'山地'};return (names[n]||buildingName(n))+(o.missing_geometry?' · 缺少模型，仅示位置':'');}

// 区域封控运行的目标状态：结果里的 state 是最终状态，总览要按当前时刻回推。
const CK_STATE_COLOR={'监视':'#d97706','已警告':'#d97706','拦截中':'#7c3aed',
  '已拦阻':'#0d9488','未授权进入':'#991b1b','已撤离':'#64748b',
  '已放行':'#2563eb','已出场':'#be6849','待出场':'#94a3b8','撤离中':'#0f766e'};
function ckTargetState(tgt,events,t){
  const kinds=new Set((events||[]).filter(e=>e.target_id===tgt.target_id&&(e.t||0)<=t).map(e=>e.kind));
  if(kinds.has('breach'))return '未授权进入';
  if(kinds.has('intercepted'))return '已拦阻';
  if(kinds.has('warning_effective'))return '已撤离';
  if(kinds.has('target_withdraw_started'))return '撤离中';
  if(kinds.has('authorized_pass'))return '已放行';
  if(kinds.has('intercept_assigned'))return '拦截中';
  if(kinds.has('warning_issued'))return '已警告';
  if(kinds.has('target_detected'))return '监视';
  if(kinds.has('target_appeared')||tgt.track?.[0]?.[0]<=t)return '已出场';
  return '待出场';
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
  for(const t of ck.targets||ck.structure.targets||[]){
    if(t.start)pts.push(t.start);if(t.goal)pts.push(t.goal);
  }
  if(!pts.length)return null;
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]),pad=22;
  return [Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad];
}
// 要点坚守运行的取景范围：要点、阵位、威胁扇区、集结地与撤离点。
function holdBounds(){
  const hl=state.run&&state.run.replay&&state.run.replay.hold;
  if(!hl||!hl.structure)return null;
  const st=hl.structure,pts=[];
  if(st.key_point)pts.push(st.key_point);
  for(const p of st.positions||[])if(p.point)pts.push(p.point);
  for(const s of st.threat_sectors||[])for(const p of s.polygon||[])pts.push(p);
  for(const w of state.run.replay.workers)if(w.start)pts.push(w.start);
  if(st.standby)pts.push(st.standby);
  for(const p of (st.withdraw||{}).route||[])pts.push(p);
  if(!pts.length)return null;
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]),pad=22;
  return [Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad];
}
function fullBounds(){  // 全场景（含 150 m 外的出发阵地）的取景范围，缩略图与"看全图"都用它。
  const r=state.run.replay,pts=[...r.workers.map(w=>w.start),...r.jobs.map(j=>j.pos)];
  for(const o of [...mapGeometry('obstacles'),...mapGeometry('roads'),...mapGeometry('surfaces')])pts.push(...o.polygon);
  for(const l of mapGeometry('landmarks'))if(l.pose)pts.push(l.pose.slice(0,2));
  for(const b of r.behaviors||[])for(const p of [...(b.staging||[]),...(b.objective||[]),...(b.loop||[]),...(b.posts||[]),...(b.standbys||[])])pts.push(p);
  pts.push(...containmentLayers().flatMap(containmentPoints));
  for(const version of r.observation_target_versions||[])
    for(const target of version.targets)pts.push(target.start,target.goal);
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
  if(!state.run)return;
  clearCoordinateView();
  if(state.page!=='overview'||document.hidden||state.ckView||state.hlView)return;
  const rect=canvas.getBoundingClientRect();if(rect.width<1)return;const dpr=window.devicePixelRatio||1;
  if(canvas.width!==Math.round(rect.width*dpr)||canvas.height!==Math.round(rect.height*dpr)){canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);const W=rect.width,H=rect.height;ctx.clearRect(0,0,W,H);ctx.fillStyle='#edf0e9';ctx.fillRect(0,0,W,H);
  if(state.taskWindow&&state.taskView==='spatial'){
    const jid=state.taskWindow.jobId,type=state.run.report.jobs.find(j=>j.job_id===jid)?.jtype;
    if(['assault','hold'].includes(type)){const chapter=type==='hold'?(state.t>=(holdReplayFor(jid)?.result?.sim_s??Infinity)?'return':state.t>=(taskEventTime(jid,'on_post')??Infinity)?'onpost':'approach'):taskDetailModel(jid).preExecution?'approach':frame().jobs[jid].phase;const key=state.run.id+':'+jid+':'+chapter+':'+state.taskWindow.start;
      if(state.cameraChapter!==key){state.cameraChapter=key;state.zoom=1;setBounds();}}
  }
  const [x0,y0,x1,y1]=bounds,scale=Math.min((W-78)/(x1-x0),(H-78)/(y1-y0))*state.zoom,cx=(x0+x1)/2,cy=(y0+y1)/2;
  const P=p=>[W/2+(p[0]-cx)*scale,H/2-(p[1]-cy)*scale],f=frame(),jid=selectedJobId(),focused=!!state.focus,full=$('#full-trails').checked;
  if(state.taskWindow&&['assault','hold'].includes(state.run.report.jobs.find(j=>j.job_id===jid)?.jtype)&&!campusTasks().find(t=>t.task_id===jid)?.params.movement_only&&state.taskView==='process'&&state.t<(holdReplayFor(jid)?.result?.sim_s??Infinity)){drawTaskExplanation(ctx,W,H,jid);return;}
  const inView=(x,y)=>x>=8&&x<=W-8&&y>=8&&y<=H-30;
  const line=(points,color,width=1,dash=[])=>{if(points.length<2)return;ctx.beginPath();points.forEach((p,i)=>{const a=P(p);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  const arrowAlong=(points,color)=>{if(!points||points.length<2)return;ctx.fillStyle=color;for(let i=1;i<points.length;i++){const a=P(points[i-1]),b=P(points[i]);if(Math.hypot(b[0]-a[0],b[1]-a[1])<34)continue;const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2,ang=Math.atan2(b[1]-a[1],b[0]-a[0]);ctx.beginPath();ctx.moveTo(mx+Math.cos(ang)*5.5,my+Math.sin(ang)*5.5);ctx.lineTo(mx+Math.cos(ang+2.6)*6,my+Math.sin(ang+2.6)*6);ctx.lineTo(mx+Math.cos(ang-2.6)*6,my+Math.sin(ang-2.6)*6);ctx.closePath();ctx.fill();}};
  const circle=(p,r,color,fill=null,dash=[])=>{const a=P(p);ctx.beginPath();ctx.arc(...a,r,0,Math.PI*2);if(fill){ctx.fillStyle=fill;ctx.fill();}ctx.strokeStyle=color;ctx.lineWidth=1.4;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  if($('#show-obstacles').checked)for(const surface of mapGeometry('surfaces')){ctx.beginPath();surface.polygon.forEach((p,i)=>{const q=P(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle='#e4edda';ctx.fill();ctx.strokeStyle='#a9bf99';ctx.lineWidth=1;ctx.stroke();}
  // 底图：道路/广场来自 SDF（env_road_*/env_city_road_*/env_city_square），
  // 只作底图不参与避障；先画路再画建筑，建筑才压得住路口。
  if($('#show-obstacles').checked&&mapGeometry('roads').length){
    for(const road of mapGeometry('roads')){ctx.beginPath();road.polygon.forEach((p,i)=>{const q=P(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();
      const plaza=String(road.id||'').includes('square');
      ctx.fillStyle=plaza?'#e8ded0':'#d8ddda';ctx.fill();ctx.strokeStyle='#b6c2b8';ctx.lineWidth=.8;ctx.stroke();}
  }
  if($('#show-threats').checked)for(const threat of mapGeometry('threats')){
    const pts=threat.polygon.map(P);if(pts.length<3)continue;
    const style=threatStyle(threat);
    ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
    ctx.fillStyle=style.fill;ctx.fill();
    ctx.strokeStyle=style.stroke;ctx.lineWidth=1.8;ctx.setLineDash([6,4]);ctx.stroke();ctx.setLineDash([]);
    const text='威胁区 I='+num(threat.intensity,2)+' · '+style.scope;const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);const cx=(Math.min(...xs)+Math.max(...xs))/2,top=Math.min(...ys);ctx.font='9px "Segoe UI","Microsoft YaHei"';const tw=ctx.measureText(text).width,lx=cx,ly=Math.max(12,top-6);ctx.fillStyle=style.labelFill+'ee';ctx.fillRect(lx-tw/2-4,ly-11,tw+8,14);ctx.strokeStyle=style.stroke;ctx.lineWidth=1;ctx.strokeRect(lx-tw/2-4,ly-11,tw+8,14);ctx.fillStyle=style.labelText;ctx.textAlign='center';ctx.fillText(text,lx,ly);ctx.textAlign='left';
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
  drawCoordinateGrid(ctx,W,H,P,scale,cx,cy);
  drawCampusAreas(ctx,P);
  for(const job of state.run.replay.jobs){
    const area=taskArea(job);
    if(!area?.length||(state.taskWindow&&jid!==job.job_id))continue;
    const color=taskColor(job.job_id);
    ctx.beginPath();
    area.forEach((point,i)=>i?ctx.lineTo(...P(point)):ctx.moveTo(...P(point)));
    ctx.closePath();
    ctx.fillStyle=color+'20';ctx.fill();
    if(job.type!=='recon'){ctx.strokeStyle=color;ctx.lineWidth=3.5;ctx.stroke();}
  }
  const annotationLabels=[];
  const observationHits=[];
  const version=observationVersion();
  if(version&&$('#show-behaviors').checked){
    const scope=state.taskWindow?.jobId||(state.focus?.type==='job'?state.focus.id:null);
    for(const target of version.targets){
      const id=target.target_id;
      if(scope&&!version.links[scope]?.includes?.(id))continue;
      const pos=observationPosition(target,state.t);
      const waiting=target.release_s==null||target.release_s>state.t;
      const reports=[...observationReports(id)].filter(([job,history])=>
        (!scope||scope===job)&&version.links[job]?.includes(id)&&observationReporting(job,history));
      const color=waiting?'#94a3b8':reports.length?'#2d7760':'#b45309';
      line([target.start,target.goal],color+'70',1.2,[4,5]);
      circle(pos,7,color,waiting?'#fff':color+'55',waiting?[3,2]:[]);
      const [x,y]=P(pos);
      const status=waiting?'待出场':reports.length?reports.length+' 项任务正在上报':'当前未上报';
      annotationLabels.push({text:id+' · '+status,x:x+8,y:y-8,color,priority:true});
      if(inView(x,y))observationHits.push({type:'observation-target',id,x,y,r:9});
    }
  }
  const relay=state.run.replay.relay_track;
  if(relay){
    const samples=relay.samples;
    const next=samples.findIndex(s=>s[0]>state.t);
    const count=next<0?samples.length:Math.max(1,next);
    const path=samples.slice(0,count).map(([,x,y])=>[x,y]);
    const pos=path.at(-1);
    if(next>0){
      const a=samples[next-1],b=samples[next],fraction=(state.t-a[0])/(b[0]-a[0]);
      pos[0]=a[1]+(b[1]-a[1])*fraction;
      pos[1]=a[2]+(b[2]-a[2])*fraction;
    }
    const ink='#b45309';
    line(path,ink+'bd',2.5,[5,4]);
    circle(pos,7,ink,'#fbbf24');
    const [x,y]=P(pos);
    const n=(state.run.report.relay_handoffs||[]).filter(e=>e.sim_s<=state.t).length;
    const stages=['侦察跟踪','巡逻接力','封控接管','要点坚守'];
    annotationLabels.push({text:relay.target_id+' · '+stages[Math.min(n,3)],x,y:y-12,color:ink,priority:true});
    if(!state.taskWindow&&!state.focus){
      const starts=state.run.replay.workers.map(w=>w.start);
      const center=starts.reduce((sum,p)=>[sum[0]+p[0]/starts.length,sum[1]+p[1]/starts.length],[0,0]);
      const [sx,sy]=P(center);
      annotationLabels.push({text:'共同集结区',x:sx,y:sy-14,color:'#24735f',priority:true});
      const shown=new Set();
      for(const row of state.run.trace){
        const e=row.event;
        if(!e?.routes||row.sim_s>state.t||state.t-row.sim_s>22||f.jobs[e.job_id]?.status!=='running')continue;
        for(const route of e.routes){
          const key=e.job_id+':'+route.pid;
          if(route.t!==0||route.straight_line_ok!==false||shown.has(key))continue;
          shown.add(key);
          line([route.from_pose,route.to],'#ba675c88',1.4,[4,4]);
          line(route.path,'#3367a9',2.4);
          const [rx,ry]=P(route.path[Math.floor(route.path.length/2)]);
          annotationLabels.push({text:no(route.pid)+' · 进场绕障',x:rx,y:ry,color:'#3367a9',priority:false});
        }
      }
    }
  }
  for(const recon of (state.run.replay.behaviors||[])){
    if(recon.type!=='recon'||!recon.sensor_radii||(state.taskWindow&&jid!==recon.job_id))continue;
    const b=f.jobs[recon.job_id].behavior;
    const startedAt=b.mapStartedAt??recon.sim_s;
    const sweep=state.run.trace.filter(row=>row.sim_s>=startedAt
      &&row.event?.job_id===recon.job_id&&row.event.recon_sweep);
    ctx.save();
    ctx.beginPath();
    recon.area.forEach((p,i)=>i?ctx.lineTo(...P(p)):ctx.moveTo(...P(p)));
    ctx.closePath();ctx.clip();
    ctx.lineCap='round';ctx.lineJoin='round';
    // 覆盖率按可通行网格计算。把实际已覆盖格直接铺在地图上，避免只看到
    // 半透明运动扫带时误以为大量区域仍未扫描。
    const cell=Number(recon.cell_size_m)||4;
    const mapped=state.run.trace.filter(row=>row.sim_s>=startedAt
      &&row.sim_s<=state.t&&row.event?.job_id===recon.job_id
      &&row.event?.kind==='frontier_mapped'&&row.event.new_cells);
    ctx.fillStyle='#2f7d5c25';
    const covered=new Set();
    for(const row of mapped)for(const p of row.event.new_cells){
      const key=p.join(',');if(covered.has(key))continue;covered.add(key);
      const [cx,cy]=P(p);ctx.fillRect(cx-cell*scale/2,cy-cell*scale/2,cell*scale+0.3,cell*scale+0.3);
    }
    for(const w of state.run.replay.workers){
      const radius=recon.sensor_radii[w.pid];
      if(!radius)continue;
      // 新录制按实际感知采样回放，旧录制沿已保存的反馈轨迹绘制。
      const points=sweep.length?sweep.flatMap(row=>(row.event.recon_sweep[w.pid]||[])
        .filter(([dt])=>row.sim_s-1+dt<=state.t).map(([,x,y])=>[x,y])):
        w.samples.filter(p=>p.t>=startedAt&&p.t<=state.t&&p.job===recon.job_id)
          .map(p=>[p.x,p.y]);
      const ink=recon.air_pids.includes(w.pid)?'#2563eb38':'#28887540';
      if(points.length===1){
        ctx.beginPath();ctx.arc(...P(points[0]),radius*scale,0,2*Math.PI);
        ctx.fillStyle=ink;ctx.fill();
      }else if(points.length>1){
        line(points,ink,2*radius*scale);
      }
    }
    ctx.restore();
    if($('#show-sensor-range').checked)for(const w of state.run.replay.workers){
      const radius=recon.sensor_radii[w.pid],p=workerAt(w);
      if(!radius||p.lost)continue;
      const air=recon.air_pids.includes(w.pid);
      circle([p.x,p.y],radius*scale,air?'#2563eb66':'#28887566',air?'#2563eb14':'#28887514');
    }
    const [x,y]=P(recon.area[3]);
    const trackingPhase=b.detail?.phase==='目标跟踪';
    const coverageSuffix=b.reconResult?(b.reconResult.overall==='succeeded'?' · 已回传':' · 部分成果已回传'):
      trackingPhase?' · 覆盖达标，目标跟踪中':'';
    annotationLabels.push({text:`侦察区 · 可侦察网格覆盖 ${num((b.coverage||0)*100,1)}% / ${num(recon.coverage_target*100,0)}%${coverageSuffix}`,x,y:y-16,color:'#583c91',priority:true});
    const target=recon.tracking_target;
    if(target&&target.target_id!==relay?.target_id){
      const d=Math.hypot(target.goal[0]-target.start[0],target.goal[1]-target.start[1]);
      const fraction=b.reconTrack?Math.min(1,Math.max(0,state.t-b.reconTrack.at)*target.speed_mps/d):0;
      const sample=reconTargetAt(recon.job_id,state.t);
      const pos=sample?.pos||target.start.map((v,i)=>v+(target.goal[i]-v)*fraction);
      const [tx,ty]=P(pos),ink='#b45309';
      if(Math.hypot(pos[0]-target.start[0],pos[1]-target.start[1])>0)line([target.start,pos],ink+'aa',2,[5,4]);
      const tracker=sample?(sample.follow_point&&sample.pid):(!b.reconTrackDone&&b.reconTrack?.pid);
      if(sample?.status==='orbiting'&&sample.orbit_radius>0)
        circle(pos,sample.orbit_radius*scale,'#2563eb88',null,[4,3]);
      if(tracker){
        const worker=state.run.replay.workers.find(w=>w.pid===tracker);
        if(worker){const p=workerAt(worker);line([[p.x,p.y],pos],ink+'90',1.5,[3,4]);}
      }
      circle(pos,7,ink,'#fbbf24');
      const recorded={waiting:'待发现',reported:'位置已上报',approaching:'正在接近',tracking:'持续跟踪',
        reacquiring:'失去接触 · 重捕中',orbiting:'目标已停止 · 空中盘旋',completed:'跟踪完成',ended:'跟踪未完成'};
      const status=sample?(sample.pid?no(sample.pid)+' · ':'')+recorded[sample.status]+
        (sample.moving?' · 目标移动中':''):
        b.reconTrackDone?'跟踪完成':b.reconTrack?(b.reconResult?'跟踪中止':no(b.reconTrack.pid)+' 跟踪中'):
        b.reconTargetReport?'位置已上报':'待发现';
      annotationLabels.push({text:target.target_id+' · '+status,x:tx,y:ty-10,color:ink,priority:true});
    }
  }
  let plannedCount=0;if(state.taskWindow){
    if($('#show-planned').checked)for(const route of currentTaskRoutes(jid)){const w=state.run.replay.workers.find(w=>w.pid===route.pid),pos=workerAt(w);let nearest=0;for(let i=1;i<route.path.length;i++)if(Math.hypot(route.path[i][0]-pos.x,route.path[i][1]-pos.y)<Math.hypot(route.path[nearest][0]-pos.x,route.path[nearest][1]-pos.y))nearest=i;const seg=route.path.slice(Math.max(0,nearest-1));const air=route.mode==='air_direct';line(seg,teamColor(route.pid,jid)+(air?'99':'cc'),air?1.6:2.4,air?[8,5]:[]);arrowAlong(seg,teamColor(route.pid,jid)+(air?'99':'cc'));if($('#show-blocked-line').checked&&!route.straight_line_ok)line([route.from_pose,route.to],'#c4736a80',1.6,[5,5]);
      // 绕障证据直接写在地图上：倍数 + 规划净空，避免"看起来像直线"的误读
      if(route.straight_line_ok===false&&$('#show-blocked-line').checked){const mid=[(route.from_pose[0]+route.to[0])/2,(route.from_pose[1]+route.to[1])/2],a=P(mid);annotationLabels.push({text:'直线被挡 · 绕行 ×'+num(route.length/Math.max(route.straight,.01),2)+' · 净空 '+num(route.min_clearance,1),x:a[0],y:a[1],color:'#a5762f',priority:false});}
      else if(air&&state.taskWindow){const mid=[(route.from_pose[0]+route.to[0])/2,(route.from_pose[1]+route.to[1])/2],a=P(mid);annotationLabels.push({text:'空中直飞 · 越障 '+num(route.altitude||0,0)+' m',x:a[0],y:a[1],color:'#2f8f86',priority:false});}
      plannedCount++;}
  }
  const holdInfo=state.taskWindow&&state.run.report.jobs.find(j=>j.job_id===jid)?.jtype==='hold'?workbenchHold(jid):null;
  for(const patrol of (state.run.replay.behaviors||[])){
    if(patrol.type!=='patrol'||patrol.sim_s>state.t||(state.taskWindow&&jid!==patrol.job_id))continue;
    if(patrol.sensor_radii&&$('#show-sensor-range').checked){
      for(const w of state.run.replay.workers){
        const radius=patrol.sensor_radii[w.pid];
        if(!radius)continue;
        const p=workerAt(w);
        if(p.lost)continue;
        const air=patrol.air_pids.includes(w.pid);
        circle([p.x,p.y],radius*scale/(patrol.cell_size_m||1),air?'#2563eb66':'#28887566',air?'#2563eb14':'#28887514');
      }
    }
    if(relay)continue;
    const starts=state.eventRows.filter(e=>e.job_id===patrol.job_id&&e.event?.kind==='patrol_target_started');
    const started=starts.findLast(e=>e.sim_s<=state.t)||starts[0];
    const legacy=state.eventRows.find(e=>e.job_id===patrol.job_id&&e.sim_s<=state.t&&e.event?.kind==='target_appeared');
    const target=(started||legacy)?.event;
    if(!target||version?.targets.some(item=>item.target_id===target.target_id))continue;
    const behavior=f.jobs[patrol.job_id]?.behavior||{};
    const observers=f.jobs[patrol.job_id]?.status==='running'
      ? Object.entries(behavior.patrolObservers||{}).filter(([pid,at])=>
        at===Math.floor(state.t)&&!f.lost.includes(pid)).map(([pid])=>pid) : [];
    // 首拍在步末写入日志，目标从该步的起点开始移动。
    const elapsed=started?Math.max(0,state.t-started.sim_s+1):0;
    const fraction=target.duration_s?Math.min(1,elapsed/target.duration_s):0;
    const goal=target.goal||target.pos;
    const pos=target.pos.map((v,i)=>v+(goal[i]-v)*fraction);
    const color=observers.length?'#2d7760':'#b45309';
    if(started&&target.duration_s&&$('#show-behaviors').checked)line([target.pos,goal],'#b4530970',1.3,[4,5]);
    const [x,y]=P(pos);
    circle(pos,7,color,color+'55');
    const status=legacy&&!started&&state.run.report.recording&&behavior.patrolReport?'已上报':
      observers.length?observers.map(no).join('、')+' 正在上报':
      started?.sim_s>state.t?'待出场':'当前未上报';
    annotationLabels.push({text:target.target_id+' · '+status,x,y,color,priority:true});
  }
  const structures=visibleStructures();for(const b of structures){const c=taskColor(b.job_id);ctx.save();
    if(b.loop){line([...b.loop,b.loop[0]],c+'99',2,[7,5]);const visits=state.eventRows.filter(e=>e.job_id===b.job_id&&e.sim_s<=state.t&&e.event?.kind==='checkpoint_visited');b.loop.forEach((p,i)=>{const seen=visits.some(e=>e.event.index===i);circle(p,state.taskWindow?7:4,c,seen?c+'35':'#ffffff');const a=P(p);ctx.fillStyle=c;ctx.font=state.taskWindow?'12px "Microsoft YaHei"':'10px "Segoe UI"';ctx.fillText((state.taskWindow?'检查点 ':'')+String(i+1)+(seen?' ✓':''),a[0]+10,a[1]-10);});}
    if(b.type==='patrol'&&b.air_orbit_centers&&$('#show-behaviors').checked){
      for(const [pid,center] of Object.entries(b.air_orbit_centers)){
        const radius=Number(b.air_orbit_radii?.[pid])||0;
        if(radius>0)circle(center,radius*scale,'#2f8f8688','#2f8f8610',[4,3]);
      }
    }
    if(b.type==='patrol'&&b.air_routes&&$('#show-behaviors').checked){
      for(const route of Object.values(b.air_routes)){
        if(route?.length>1)line([...route,route[0]],'#2f8f86aa',1.5,[7,4]);
      }
    }
    if(b.ring_radius)circle(b.site,b.ring_radius*scale,c+'80',null,[5,5]);
    if(b.type==='recon'&&state.taskWindow){for(const target of Object.values(f.jobs[jid].behavior.detail?.debug?.targets||{}))circle(target,6,c+'bb');}
    if(b.area_radius){circle(b.site,b.area_radius*scale,c+'80',c+'07',[7,6]);if(state.taskWindow)for(const e of state.eventRows.filter(e=>e.job_id===b.job_id&&e.sim_s<=state.t&&e.event?.kind==='frontier_mapped'&&e.event.pos)){const center=P(e.event.pos),radius=(b.sensor_radius||2.6)*scale,gradient=ctx.createRadialGradient(center[0],center[1],1,center[0],center[1],radius);gradient.addColorStop(0,c+'1c');gradient.addColorStop(1,c+'02');ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(center[0],center[1],radius,0,Math.PI*2);ctx.fill();}}
    for(const [i,p]of (b.type==='hold'?(b.posts||[]).slice(0,frame().jobs[jid].pids.length>2?undefined:1):(b.posts||[])).entries()){circle(p,state.taskWindow?9:5,c,c+'25');if(state.taskWindow){const a=P(p);ctx.fillStyle=c;ctx.font='12px "Microsoft YaHei"';ctx.fillText(b.type==='hold'?'交接岗位':'岗位 '+(i+1),a[0]+12,a[1]-12);}}for(const [i,p]of (b.standbys||[]).slice(0,1).entries()){circle(p,state.taskWindow?7:4,c,null,[2,3]);if(state.taskWindow){const a=P(p);ctx.fillStyle=c;ctx.font='11px "Microsoft YaHei"';ctx.fillText('待命位 '+(i+1),a[0]+10,a[1]-10);}}
    if(b.type==='assault'&&state.taskWindow){const m=taskDetailModel(jid),points=m.index<2?b.staging:b.objective,groups=new Map();
      // 智能体探测范围：圆心跟实时位置走，半径取任务参数（缺省 35 m）
      if($('#show-sensor-range').checked){
        const sensorR=(Number(b.sensor_radius_m)||35)*scale;
        if(sensorR>4){
          for(const pid of b.pids||[]){
            const w=state.run.replay.workers.find(x=>x.pid===pid);
            if(!w)continue;
            const p=workerAt(w);
            if(!p||!Number.isFinite(p.x))continue;
            const role=String((b.roles||{})[pid]||'');
            const air=w.kind==='PLANE'||w.kind==='WING';
            const col=role.includes('侦察')?'#2563eb':role.includes('评估')?'#0d9488':(air?'#2563eb':c);
            circle([p.x,p.y],sensorR,col+'55',col+'0a');
          }
        }
      }
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
  const ckFocus=state.taskWindow?.jobId||(state.focus?.type==='job'?state.focus.id:null);
  for(const ckData of containmentLayers(ckFocus)){
  const ckStructure=ckData.structure;
  if(ckStructure.sim_s!=null&&ckStructure.sim_s<=state.t&&$('#show-sensor-range').checked){
    const c=taskColor(ckStructure.job_id);
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
  }
  if(ckStructure.area&&$('#show-behaviors').checked){
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

    // 目标：当前状态、近 30 s 轨迹、拦阻连线——总览里也要看得出"在拦阻"
    for(const tgt of (ckData.targets||ckData.result?.targets||[])){
      if(tgt.target_id===relay?.target_id)continue;
      if(tgt.goal)circle(tgt.goal,3,'#97543b','#ffffffb0');
      const track=(tgt.track||[]).filter(x=>x[0]<=state.t);
      const last=track.at(-1),pos=last?last.slice(1):tgt.start;
      if(!pos)continue;
      if(track.length>2)line(track.filter(x=>x[0]>=state.t-10).map(x=>[x[1],x[2]]),tgt.authorized?'#2563eb99':'#dc262699',1.6);
      const stateNow=ckTargetState(tgt,ckEvents,state.t);
      const color=CK_STATE_COLOR[stateNow]||'#94a3b8';
      const q=P(pos);
      const waiting=stateNow==='待出场';
      circle(pos,waiting?5:6,color,waiting?'#fff':color,waiting?[3,2]:[]);
      annotationLabels.push({text:tgt.target_id+' · '+stateNow,x:q[0]+10,y:q[1]-6,color,priority:false});
      const assigned=ckEvents.findLast(e=>e.kind==='intercept_assigned'&&e.target_id===tgt.target_id&&e.t<=state.t);
      const done=assigned&&ckEvents.find(e=>['intercepted','breach'].includes(e.kind)&&e.target_id===tgt.target_id&&e.t>=assigned.t);
      if(assigned&&(!done||state.t<=done.t+3)){
        const w=state.run.replay.workers.find(x=>x.pid===assigned.pid);
        const a=w?workerAt(w):null;
        if(a&&Number.isFinite(a.x)){
          line([[a.x,a.y],pos],'#7c3aedcc',2);
          const m=P([(a.x+pos[0])/2,(a.y+pos[1])/2]);
          annotationLabels.push({text:'拦阻',x:m[0]+4,y:m[1]-4,color:'#7c3aed',priority:false});
        }
      }
    }
    const cx=ckStructure.center||ckStructure.site;const a=P(cx);
    annotationLabels.push({text:ckData.job_id+' · 封控区',x:a[0],y:a[1]-10,color:c,priority:true});
    ctx.restore();
  }
  }
  // 要点坚守覆盖层（1028 §2.5）：要点、阵位（含朝向）、威胁扇区、在位着色。
  // 与封控一样默认干净：威胁扇区淡填充、阵位用实心/空心区分在位，不画虚线长线。
  const hlData=state.taskWindow||state.focus?.type==='job'
    ? holdReplayFor(jid) : state.run.replay.hold;
  const hlStructure=hlData&&hlData.structure;
  if(hlStructure&&hlStructure.positions&&hlStructure.sim_s<=state.t&&$('#show-behaviors').checked){
    const c=taskColor(hlStructure.job_id);
    const hlEvents=hlData.events||[];
    const est=hlEvents.find(e=>e.kind==='control_established');
    const established=!!est&&state.t>=(est.t||0);
    ctx.save();
    for(const sector of hlStructure.threat_sectors||[]){
      const poly=(sector.polygon||[]).map(P);if(poly.length<3)continue;
      ctx.beginPath();poly.forEach((p,i)=>{i?ctx.lineTo(...p):ctx.moveTo(...p);});ctx.closePath();
      ctx.fillStyle='rgba(185,28,28,0.06)';ctx.fill();
      ctx.strokeStyle='rgba(185,28,28,0.28)';ctx.lineWidth=1;ctx.stroke();
    }
    for(const position of hlStructure.positions){
      const q=P(position.point),{pid,label}=window.HoldPage.postStatus(hlData,position.id,state.t);
      const color=pid?'#0f766e':'#94a3b8';
      ctx.beginPath();ctx.arc(q[0],q[1],5,0,Math.PI*2);
      ctx.fillStyle=pid?color:'#ffffff';ctx.fill();ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
      const facing=(Number(position.facing_deg)||0)*Math.PI/180;
      ctx.beginPath();ctx.moveTo(q[0]+Math.sin(facing)*6,q[1]-Math.cos(facing)*6);
      ctx.lineTo(q[0]+Math.sin(facing)*12,q[1]-Math.cos(facing)*12);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
      annotationLabels.push({text:position.id+' · '+label,x:q[0]+9,y:q[1]-7,color,priority:false});
    }
    const kp=P(hlStructure.key_point);
    ctx.beginPath();ctx.moveTo(kp[0],kp[1]-8);ctx.lineTo(kp[0]+8,kp[1]);ctx.lineTo(kp[0],kp[1]+8);ctx.lineTo(kp[0]-8,kp[1]);ctx.closePath();
    ctx.fillStyle=established?c:c+'99';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.8;ctx.stroke();
    annotationLabels.push({text:'要点 · 在位下限 '+num(hlStructure.min_on_post,0)+' 台',x:kp[0]+14,y:kp[1]+10,color:c,priority:true});
    ctx.restore();
  }
  let traceCount=0;for(const w of state.run.replay.workers)for(const segment of trailsFor(w)){
    const returning=segment.at(-1).command?.startsWith('return:');
    line(segment.map(p=>[p.x,p.y]),returning?'#24735f':state.taskWindow?teamColor(w.pid,jid):taskColor(segment.at(-1).job),
      state.focus?.id===w.pid?2.6:1.8,returning?[5,3]:[]);
    traceCount++;
  }
  if(state.taskWindow&&hlData?.result&&state.t>=hlData.result.sim_s){
    for(const w of state.run.replay.workers){
      if(holdReturnAt(w,jid))circle(w.start,6,'#24735f','#ffffffc0',[2,2]);
    }
  }
  state.hits=observationHits;const labels=[],placed=[];const showLabels=$('#show-labels').checked;
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
  for(const w of state.run.replay.workers){const p=workerAt(w),[x,y]=P([p.x,p.y]);if(state.taskWindow&&p.job!==jid&&!(hlData&&holdReturnAt(w,jid)))continue;if(!inView(x,y))continue;
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
    else if(showLabels&&!focused&&scale>1.15){
      const phase=['return','landing'].includes(p.phase)?' · '+phaseName(p.phase):'';
      workerLabels.push({text:no(w.pid)+phase,x,y,color:c,priority:false,small:true});
    }
    ctx.restore();state.hits.push({x,y,type:'worker',id:w.pid,r:relevant?13:9});
  }
  // 机动突击齐射：发射效果。演示口径是桩判定（占位在目标环内且有弹即命中），
  // 所以这里只画"谁在何时朝目标环开火"，不画弹道、不做落点散布或毁伤推断；
  // 事件与位置都取自已记录数据（salvo_fired + 该时刻的平台位置）。
  let assaultJobId=assaultInfo?jid:null;
  if(!assaultJobId&&!state.taskWindow){const list=state.run.replay.jobs.filter(j=>j.type==='assault');if(list.length===1)assaultJobId=list[0].job_id;}
  const assaultStruct=assaultJobId?structureFor(assaultJobId):null;
  if(assaultJobId&&assaultStruct&&assaultStruct.type==='assault'&&assaultStruct.site&&$('#show-behaviors').checked){
    const color=assaultStruct.effect_kind==='suppress'?'#b45309':assaultStruct.effect_kind==='seize'?'#7c3aed':'#ea580c';
    const site=assaultStruct.site,[tx,ty]=P(site);
    const ring=(assaultStruct.objective&&assaultStruct.objective.length)?Math.max(7,Math.hypot(assaultStruct.objective[0][0]-site[0],assaultStruct.objective[0][1]-site[1])*scale):10;
    ctx.save();ctx.setLineDash([4,3]);ctx.strokeStyle=color;ctx.globalAlpha=.5;ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(tx,ty,ring,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;ctx.setLineDash([]);
    // 观察环：侦察指示组的观察位落在这个半径上（params.observe_radius），
    // 与"目标环"是两个不同参数；这里只按记录值画，不自己推半径。
    const obsR=Number(assaultStruct.observe_radius)||0;
    if(obsR>0&&assaultStruct.observation){
      ctx.globalAlpha=.38;ctx.strokeStyle='#4f7f8f';ctx.setLineDash([2,6]);ctx.lineWidth=1.2;
      ctx.beginPath();ctx.arc(tx,ty,obsR*scale,0,Math.PI*2);ctx.stroke();
      ctx.globalAlpha=1;ctx.setLineDash([]);
      if(assaultStruct.observation){const op=P(assaultStruct.observation);ctx.beginPath();ctx.arc(op[0],op[1],3.2,0,Math.PI*2);ctx.fillStyle='#4f7f8f';ctx.fill();}
      annotationLabels.push({text:'目标环 R='+num(ring/scale,0)+' · 观察环 R='+num(obsR,0)
        +($('#show-sensor-range').checked?' · 探测 R='+num(assaultStruct.sensor_radius_m||35,0):'')
        +'（任务参数）',x:tx,y:ty+ring+16,color:'#7c6a55',priority:false});
    }
    const salvos=state.eventRows.filter(e=>e.job_id===assaultJobId&&e.event?.kind==='salvo_fired'&&e.sim_s<=state.t+1e-6);
    for(const e of salvos){
      const age=state.t-e.sim_s;if(age>1.6)continue;
      const fade=Math.max(0,1-age/1.6),pids=e.event.pids||[],rounds=e.event.rounds||1;
      for(const pid of pids){
        const w=state.run.replay.workers.find(x=>x.pid===pid);if(!w)continue;
        const s=workerAt(w),[x0,y0]=P([s.x,s.y]);
        if(age<=.35){
          const f=Math.max(.12,Math.min(1,age/.35)),xm=x0+(tx-x0)*f,ym=y0+(ty-y0)*f;
          ctx.globalAlpha=fade;ctx.strokeStyle=color;ctx.lineWidth=2.6;ctx.lineCap='round';
          ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(xm,ym);ctx.stroke();
          ctx.beginPath();ctx.arc(x0,y0,3+6*(1-age/.35),0,Math.PI*2);ctx.fillStyle='#fff7ed';ctx.fill();
          ctx.lineWidth=1.5;ctx.stroke();ctx.globalAlpha=1;
        }
      }
      if(age>=.28){
        const k=Math.min(1,(age-.28)/.9);ctx.globalAlpha=.85*(1-k);ctx.strokeStyle=color;ctx.lineWidth=2*(1-k*.6);
        ctx.beginPath();ctx.arc(tx,ty,4+14*k,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;
      }
      if(age<.9){ctx.globalAlpha=fade;ctx.fillStyle=color;ctx.font='600 12px "Microsoft YaHei"';ctx.fillText('齐射 '+pids.length+' 台 · '+rounds+' 发/台',tx+18,ty+30);ctx.globalAlpha=1;}
    }
    ctx.restore();
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
  // 侦察区边界置于覆盖、轨迹与感知圈上方，便于在底图和回放末帧辨认。
  for(const job of state.run.replay.jobs){
    if(job.type!=='recon'||(state.taskWindow&&jid!==job.job_id))continue;
    const area=taskArea(job);
    if(!area?.length)continue;
    const outline=[...area,area[0]];
    line(outline,'#ffffff',7);
    line(outline,'#583c91',4);
  }
  for(const l of workerLabels)placeLabel(l.text,l.x,l.y,l.color,true,!!l.small);for(const l of [...annotationLabels,...jobLabels])placeLabel(l.text,l.x,l.y,l.color,l.priority,l.small);
  if(jid&&!holdInfo&&$('#show-landmarks').checked){const job=state.run.replay.jobs.find(j=>j.job_id===jid),[x,y]=P(job.pos);if(inView(x,y)){const label=(job.landmark||'').split('（')[0];if(label)placeLabel(label,x,y+20,'#8b9e8a');}}
  if($('#show-landmarks').checked)for(const l of mapGeometry('landmarks')){if(!l.pose)continue;const [x,y]=P(l.pose);if(!inView(x,y))continue;const missing=l.missing_geometry;ctx.strokeStyle=missing?'#a77a52':'#947b42';ctx.lineWidth=1.3;ctx.setLineDash(missing?[3,3]:[]);ctx.beginPath();ctx.arc(x,y,missing?7:3,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);if($('#show-labels').checked)placeLabel(landmarkName(l),x,y,'#796b4d',false,true);}
  drawMapKeyPoints(ctx,P,inView,placeLabel);
  ctx.textAlign='left';drawMinimap(W,H);$('#map-scale').textContent=num(40/scale,1)+' 场景单位';
  if(Number.isFinite(scale)&&scale>0){coordinateView={scale,cx,cy};updateCoordinateReadout();}
  $('#map-caption').textContent=state.taskWindow?'本任务执行回放 · 仅显示参与成员与已记录动作':full?'完整轨迹 · 截至当前时刻':$('#show-trails').checked?'近期尾迹 · 最近 10 秒':!focused?(relay?'接力处置 · 同一移动目标与四项任务；可在关键节点跳转交接':'全局态势 · 形状=平台类型，颜色=编组；建筑群即突击目标区，点击任务聚焦'):'当前焦点 · 点击地图空白处返回全局';
  // 封控运行的全局视图要说明多出来的那几圈是什么，不然虚线圆会被当成轨迹。
  if(!state.taskWindow&&!focused&&state.run.replay.containment){
    $('#map-caption').textContent='封控区 + 各平台探测半径（虚线圆）· 控制建立后区域压实显示 · 点任务看执行';
  }
  state.scene={jobId:jid,focused,plannedCount,traceCount,structureCount:structures.length,relevantWorkers,labels,bounds:[...bounds]};
}
canvas.addEventListener('click',e=>{if(mapDragMoved){mapDragMoved=false;return;}const b=canvas.getBoundingClientRect(),x=e.clientX-b.left,y=e.clientY-b.top;
  const fit=state.hits.find(h=>h.type==='fit'&&Math.abs(x-h.x)<=h.w/2&&Math.abs(y-h.y)<=h.h/2);
  if(fit){bounds=fullBounds();state.zoom=1;draw();return;}
  const chapter=state.hits.find(h=>h.type==='chapter'&&Math.abs(x-h.x)<=h.w/2&&Math.abs(y-h.y)<=h.h/2);if(chapter){setPlaying(false);setTime(chapter.t);return;}const hits=state.hits.filter(h=>h.type!=='fit'&&Math.hypot(x-h.x,y-h.y)<=h.r).sort((a,b)=>Math.hypot(x-a.x,y-a.y)-Math.hypot(x-b.x,y-b.y));if(hits.length){const current=hits.findIndex(h=>h.id===state.focus?.id),h=hits[(current+1)%hits.length];if(h.type==='job'){selectTask(h.id);}else focus(h.type,h.id);}else if(!state.taskWindow)globalView();});
document.addEventListener('click',e=>{
  const nav=e.target.closest('[data-page]');if(nav)setPage(nav.dataset.page);
  const go=e.target.closest('[data-goto]');if(go)setPage(go.dataset.goto);
  const ck=e.target.closest('[data-containment]');if(ck)showOverviewMode('containment');
  if(e.target.closest('[data-ck-back]')){showOverviewMode('map');return;}
  const job=e.target.closest('[data-job]');if(job){selectTask(job.dataset.job);if(state.page!=='overview')setPage('overview');}
  const worker=e.target.closest('[data-worker]');if(worker)focus('worker',worker.dataset.worker,worker.hasAttribute('data-locate'));
  const event=e.target.closest('[data-event-time]');if(event){setPlaying(false);if(event.dataset.eventJob)selectTask(event.dataset.eventJob);setTime(Number(event.dataset.eventTime));}
  const run=e.target.closest('[data-load-run]');if(run)loadRun(run.dataset.loadRun).then(ok=>{if(ok)setPage('overview');});
  const ckRun=e.target.closest('[data-ck-run]');if(ckRun){loadRun(ckRun.dataset.ckRun,true).then(()=>{showOverviewMode('containment');toast('已打开区域封控演示；切到“全局分配”页签可对照机动与任务位置。');});}
  if(e.target.closest('[data-behavior-run]')){const r=state.catalog.runs.find(r=>r.id===state.catalog.default_run&&r.behavior)||state.catalog.runs.find(r=>r.behavior);if(r)loadRun(r.id);else toast('还没有启用到位动作的记录，请新建演示。');}
  if(e.target.closest('[data-global]'))globalView();
  const source=e.target.closest('[data-source]');if(source)api('/api/source/'+source.dataset.source).then(d=>{$('#source-title').textContent=d.name;$('#source-text').textContent=d.text;$('#source-dialog').showModal();}).catch(e=>toast(e.message));
});
$('#play').onclick=()=>{if(state.run)setPlaying(!state.playing);};$('#restart').onclick=()=>{setPlaying(false);if(state.taskWindow){state.taskWindow.start=state.taskWindow.dispatch;updateTaskTimeline();}setTime(state.taskWindow?.start??0);setBounds();draw();};$('#step-back').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)-1);};$('#step-next').onclick=()=>{setPlaying(false);setTime(Math.floor(state.t)+1);};$('#jump-end').onclick=()=>{setPlaying(false);setTime(state.taskWindow?.end??state.run.replay.end);};$('#scrubber').oninput=e=>{setPlaying(false);setTime(Number(e.target.value));};$('#speed').onchange=e=>state.speed=Number(e.target.value);
for(const id of ['show-trails','show-labels','show-landmarks','show-behaviors','show-starts','show-sensor-range','full-trails','show-obstacles','show-planned','show-blocked-line'])$('#'+id).onchange=draw;
$('#fit-map').onclick=()=>{state.zoom=1;setBounds();draw();};$('#map-zoom-in').onclick=()=>{state.zoom=Math.min(32,state.zoom*1.4);draw();};$('#map-zoom-out').onclick=()=>{state.zoom=Math.max(.25,state.zoom/1.4);draw();};$('#clear-focus').onclick=globalView;$('#overview-view').onclick=()=>{showOverviewMode('map');globalView();};$('#event-filter').onchange=()=>{lastEventKey='';renderEvents();};$('#platform-filter').onchange=renderPlatforms;
$('#run-select').onchange=e=>loadRun(e.target.value);$('#refresh').onclick=()=>refreshCatalog().catch(e=>toast(e.message));for(const id of ['open-config','guide-run','runs-new'])$('#'+id).onclick=openConfig;$('#close-config').onclick=()=>$('#config-dialog').close();$('#close-source').onclick=()=>$('#source-dialog').close();$('#config-scenario').onchange=()=>{updateConfig();};$('#config-avoid').onchange=updateConfig;
$('#open-actions').onclick=()=>{setPage('overview');$('#behavior-panel').scrollIntoView({block:'start'});};$$('.ov-tab').forEach(b=>{b.onclick=()=>showOverviewMode(b.dataset.ov);});$('#show-report').onclick=()=>{if(state.run)window.open(artifact('report.html'),'_blank','noopener');};$('#task-select').onchange=e=>{if(e.target.value)selectTask(e.target.value);};
document.addEventListener('keydown',e=>{if(!state.run||document.querySelector('dialog[open]:not(#task-theater)')||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName))return;if(e.code==='Space'){e.preventDefault();setPlaying(!state.playing);}if(e.code==='ArrowRight'){e.preventDefault();setPlaying(false);setTime(state.t+1);}if(e.code==='ArrowLeft'){e.preventDefault();setPlaying(false);setTime(state.t-1);}});
new ResizeObserver(draw).observe(canvas);
let last=performance.now(),lastRender=0;
function animate(now){if(state.run?.live&&!state.run.live.paused){const delta=Math.min((now-last)/1000,.1);state.t=Math.min(state.run.live.sim_s,state.t+delta*(state.liveRate||4));if(now-lastRender>33){draw();lastRender=now;}}const dt=Math.min((now-last)/1000,.1);last=now;if(state.playing&&state.run){state.t=Math.min(state.taskWindow?.end??state.run.replay.end,state.t+dt*state.speed);draw();if(now-lastRender>110){renderTime();lastRender=now;}if(state.t>=(state.taskWindow?.end??state.run.replay.end)){setPlaying(false);renderTime();}}requestAnimationFrame(animate);}
requestAnimationFrame(animate);renderFiles();
document.addEventListener('DOMContentLoaded', () => {
  refreshCatalog().then(() => {
    if (new URLSearchParams(location.search).get('new') === 'interop') {
      $('#config-scenario').value = 'interop_containment';
      openConfig();
    }
  }).catch(e => {
    $('#connection-text').textContent = '连接失败';
    toast('无法连接本地服务：' + e.message);
  });
}, {once: true});

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

function renderRunCompare(){
  const sel=$('#run-compare-scenario'),body=$('#run-compare-body'),note=$('#run-compare-note');
  if(!sel||!body)return;
  const runs=(state.catalog?.runs||[]).filter(r=>r.scenario);
  const counts={};for(const r of runs)counts[r.scenario]=(counts[r.scenario]||0)+1;
  const scenarios=[...new Set(runs.map(r=>r.scenario))].sort((a,b)=>(counts[b]-counts[a])||a.localeCompare(b));
  const previous=sel.value;
  sel.innerHTML=scenarios.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  if(!scenarios.length){body.innerHTML='';note.textContent='暂无运行记录。';return;}
  const currentScenario=state.run?.manifest?.workbench_config?.scenario;
  const target=scenarios.includes(previous)?previous:(scenarios.includes(currentScenario)?currentScenario:scenarios[0]);
  sel.value=target;
  const order={makespan:0,energy:1,balanced:2,exposure:3,dispersion:4};
  const rows=runs.filter(r=>r.scenario===target).sort((a,b)=>(order[a.objective]??9)-(order[b.objective]??9)||String(a.id).localeCompare(String(b.id)));
  const val=(v,d=1)=>v==null?'—':num(v,d);
  const pct=v=>v==null?'—':(100*v).toFixed(1)+'%';
  body.innerHTML=rows.map(r=>`<tr><td>${esc(objectives[r.objective]||r.objective||'未记录')}${r.plan_metrics_source==='runtime_dispatch'?' · 已绑定下发':' · 旧静态参考'}</td><td>${r.done} / ${r.total}</td><td>${val(r.makespan)}</td><td>${val(r.plan_energy)}</td><td>${val(r.exposure,2)} / ${val(r.execution_exposure,2)}</td><td>${pct(r.detection_probability)} / ${pct(r.execution_detection_probability)}</td><td>${r.recording?'—':(r.retries??'—')+' / '+(r.timeouts??'—')}</td><td><button class="text-button" data-load-run="${esc(r.id)}">载入 ↗</button></td></tr>`).join('');
  note.textContent='共 '+rows.length+' 次运行；同一目标多行表示重复跑。新记录的计划来自实际下发版本，执行按同次任务尝试的模拟轨迹统计，不含返航，并非另跑一次。旧静态参考未绑定版本；失败、取消和未完成片段不能直接作为完整规划误差。被侦察到的概率由暴露量折算，尚未实测标定。均衡按时效/暴露/能耗 0.5/0.3/0.2 折中，可能与其他目标同解。';
}

function resetCompare(){const p=$('#compare-panel');if(p)p.hidden=true;const b=$('#compare-body');if(b)b.innerHTML='';const t=$('#compare-threat');if(t)t.textContent='';const n=$('#compare-note');if(n)n.textContent='';}

async function compareObjectives(){
  if(comparing||state.busy)return;
  const scenario=$('#config-scenario').value,err=$('#config-error');
  if(!scenario.startsWith('interop')){err.textContent='四目标对比只支持融合版场景（interop_*）；历史场景没有统一的暴露/均衡口径。';err.hidden=false;resetCompare();return;}
  comparing=true;const btn=$('#compare-objectives'),old=btn.textContent;btn.disabled=true;btn.textContent='规划中…';err.hidden=true;
  const panel=$('#compare-panel'),bodyEl=$('#compare-body');
  panel.hidden=false;bodyEl.innerHTML='<tr><td colspan="7" class="muted">正在按四个目标各规划一次…</td></tr>';
  try{
    const r=await api('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario})});
    const rows=r.results||[];
    if(!rows.length)throw Error('没有返回对比结果');
    const minM=Math.min(...rows.map(x=>x.makespan_s)),minE=Math.min(...rows.map(x=>x.total_energy)),minX=Math.min(...rows.map(x=>x.total_exposure));
    const cell=(v,isBest)=>isBest?'<b>'+v+'</b>':v;
    bodyEl.innerHTML=rows.map(x=>'<tr><td>'+esc(x.label)+'</td><td>'+x.assigned+' / '+x.total+'</td><td>'+cell(Number(x.makespan_s).toFixed(1),x.makespan_s===minM)+'</td><td>'+cell(Number(x.total_energy).toFixed(1),x.total_energy===minE)+'</td><td>'+cell(Number(x.total_exposure).toFixed(2),x.total_exposure===minX)+'</td><td>'+(100*x.detection_probability).toFixed(1)+'%</td><td>'+Number(x.runtime_ms).toFixed(0)+'</td></tr>').join('');
    const threats=r.threats||[];
    $('#compare-threat').textContent=threats.length?('威胁区：'+threats.map(t=>{const xs=(t.polygon||[]).map(p=>Number(p[0])),ys=(t.polygon||[]).map(p=>Number(p[1]));return t.id+' 强度 '+t.intensity+'，x '+Math.min(...xs)+'–'+Math.max(...xs)+'，y '+Math.min(...ys)+'–'+Math.max(...ys);}).join('；')+'。仅影响规划暴露量，不阻断通行。'):'本场景没有威胁区，暴露度目标会与完工时间同解。';
    $('#compare-note').textContent=r.note||'';
  }catch(e){panel.hidden=true;err.textContent='对比失败：'+e.message;err.hidden=false;}
  finally{comparing=false;btn.disabled=false;btn.textContent=old;}
}

function threatStyle(threat){const scope=threat?.applies_to||'ground';return scope==='air'
  ?{fill:'rgba(37,99,235,0.10)',stroke:'#2563eb',labelFill:'#eff6ff',labelText:'#1d4ed8',scope:'仅对空（地面可通行）'}
  :scope==='all'
    ?{fill:'rgba(185,28,28,0.11)',stroke:'#b91c1c',labelFill:'#fef2f2',labelText:'#991b1b',scope:'空地均作用'}
    :{fill:'rgba(194,65,12,0.11)',stroke:'#c2410c',labelFill:'#fff7ed',labelText:'#9a3412',scope:'仅对地（空中可通行）'};}

let comparing=false;
$('#compare-objectives')?.addEventListener('click',compareObjectives);
$('#run-compare-scenario').onchange=renderRunCompare;
$('#show-threats').onchange=draw;
