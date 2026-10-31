'use strict';
// Process diagrams use recorded events and poses. They are not spatial maps.
function taskEventTime(jid,kind){return state.run.trace.find(e=>e.kind==='behavior_event'&&e.event?.job_id===jid&&e.event.kind===kind)?.sim_s;}
function taskDetailModel(jid){
  const j=state.run.report.jobs.find(j=>j.job_id===jid),s=frame().jobs[jid],geometry=state.run.replay.behaviors.find(b=>b.job_id===jid),start=geometry?.sim_s??state.taskWindow.execution;
  const steps=j.jtype==='assault'?[['机动','机动集结',start],['到位','全员到位',taskEventTime(jid,'all_staged')],['执行','执行动作',taskEventTime(jid,'assault_started')],['结果确认','结果确认',taskEventTime(jid,'effect_applied')],['撤离','撤离收拢',taskEventTime(jid,'withdrawn')]]:[];
  const complete=s.status==='succeeded'||s.behavior.complete,phase=complete?'完成':s.phase;
  const index=complete?Math.max(steps.length-1,0):Math.max(0,steps.findIndex(x=>x[0]===phase));
  const collapsed=geometry?.type==='assault'&&new Set([...(geometry.staging||[]),...(geometry.objective||[])].map(p=>p.map(x=>x.toFixed(2)).join(','))).size===1;
  const preExecution=state.t<start;
  return {j,s,geometry,start,steps,index:preExecution?-1:index,complete,phase,collapsed,preExecution};
}
function assaultMemberEvidence(jid,pid){
  const m=taskDetailModel(jid),i=m.s.pids.indexOf(pid),w=state.run.replay.workers.find(w=>w.pid===pid),p=workerAt(w);
  if(m.preExecution){const target=m.s.behavior.routes?.[pid]?.to;return {target,distance:target?Math.hypot(p.x-target[0],p.y-target[1]):null,label:p.phase==='work'?'已到作业区 · 等待成员':'前往作业区'};}
  const objective=m.geometry?.objective?.[i],confirming=m.index===3&&i===0,route=m.s.behavior.routes?.[pid];
  const target=m.index<2?m.geometry?.staging?.[i]:m.index===2?objective:route?.to;
  const distance=target?Math.hypot(p.x-target[0],p.y-target[1]):null,atTarget=distance!=null&&distance<=(m.s.behavior.detail?.params?.arrive_tol??.7);
  const confirmRoute=confirming&&target&&objective&&Math.hypot(target[0]-objective[0],target[1]-objective[1])>.7;
  const label=m.complete?'完成':m.index===0?(atTarget?'到达集结位':'集结中'):m.index===1?'到位等待':m.index===2?(m.s.behavior.detail?.debug?.effect_started?'保持执行':atTarget?'到达执行位':'前往执行点'):m.index===4?(atTarget?'到达撤离点':'撤离中'):confirming?(confirmRoute?(atTarget?'确认点已到位':'前往确认点'):'确认阶段准备'):'等待确认';
  return {target,distance,label:m.collapsed?'点位重合 · 动作未验证':label};
}
function renderTaskDetailChrome(jid){
  const m=taskDetailModel(jid),special=['assault','hold'].includes(m.j.jtype),process=special&&state.taskView!=='spatial';
  mapCard.classList.toggle('process-view',process);mapCard.classList.toggle('special-task',special);$('#task-view-switch').hidden=!special;
  $$('#task-view-switch button').forEach(b=>{b.classList.toggle('active',b.dataset.taskView===(process?'process':'spatial'));b.setAttribute('aria-pressed',b.classList.contains('active'));});
  const recording=state.run.report.recording;$('#task-restart').hidden=!!recording;$('#action-start').textContent=recording?'重新看完整片段':'跳到到位后动作';
  $('#task-source-note').textContent=recording?'专项串行记录 · behavior_20261028_verify · 与本轮并行执行分开展示':'当前运行 · '+shortRun(state.run.id);
  $('#task-source-note').classList.toggle('recording',!!recording);
  if(state.taskWindow.start>state.taskWindow.dispatch)$('#task-source-note').textContent+=` · 已跳过 ${num(state.taskWindow.start-state.taskWindow.dispatch,0)} 秒接近过程`;
  $('#task-data-warning').hidden=!m.collapsed;
  $('#task-data-warning').textContent=m.collapsed?'本运行的集结点与执行点重合，不能据此验证集结到执行的分段移动；原坐标与阶段日志保留。':'';
  const sourceKey=state.run.id+':'+state.catalog.default_run;
  if($('#task-source').dataset.sourceKey!==sourceKey){
    $('#task-source').innerHTML=[state.run.id,state.catalog.default_run,'behavior_20261028_verify'].filter((x,i,a)=>x&&a.indexOf(x)===i).map(id=>`<option value="${esc(id)}">${id==='behavior_20261028_verify'?'专项验证记录（串行）':'本轮并行记录 · '+shortRun(id)}</option>`).join('');
    $('#task-source').value=state.run.id;
    $('#task-source').dataset.sourceKey=sourceKey;
  }
  $('#action-chapters').hidden=m.j.jtype!=='assault'||process||m.preExecution;
  if(m.j.jtype==='assault')$('#action-chapters').innerHTML=m.steps.map((step,i)=>`<button class="${i===m.index?'current':''} ${step[2]>state.t?'future':''}" ${step[2]==null?'disabled':`data-task-time="${step[2]}"`}><small>${step[2]==null?'未记录':num(step[2]-m.start,0)+' s'}${step[2]>state.t?' · 未播放':''}</small>${i+1} · ${esc(step[1])}</button>`).join('')+`<span>${m.collapsed?'本轮集结点与执行点重合；可切换专项记录对照。':'点击阶段跳转 · 成员轨道按日志展开'}</span>`;
  for(const id of ['map-zoom-in','map-zoom-out'])$('#'+id).disabled=process;
}
function drawTaskExplanation(ctx,W,H,jid){
  const m=taskDetailModel(jid),ids=m.s.pids,margin=Math.max(30,(W-1080)/2),left=margin,right=W-margin,width=right-left;
  const text=(value,x,y,size=13,color='#4a655d',weight=400)=>{ctx.font=`${weight} ${size}px "Segoe UI","Microsoft YaHei"`;ctx.fillStyle=color;ctx.textAlign='left';ctx.fillText(String(value),x,y);};
  const box=(x,y,w,h,fill='#fff',stroke='#dae5df',radius=10)=>{ctx.beginPath();ctx.roundRect(x,y,w,h,radius);ctx.fillStyle=fill;ctx.fill();ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke();};
  const dot=(x,y,pid,r=17)=>{ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=teamColor(pid,jid);ctx.fill();ctx.font='600 12px "Segoe UI"';ctx.textAlign='center';ctx.fillStyle='#fff';ctx.fillText(no(pid),x,y+4);ctx.textAlign='left';};
  const arrow=(x1,y1,x2,y2,color='#a8bdb1')=>{const back=x2-7*Math.sign(x2-x1);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.beginPath();ctx.moveTo(back,y2-5);ctx.lineTo(x2,y2);ctx.lineTo(back,y2+5);ctx.stroke();};
  text(m.j.jtype==='assault'?'任务执行过程':'轮换与交接过程',left,32,20,'#294e42',600);
  text('阶段卡片可点击跳转；轨道表示成员阶段，实际运动请切换“空间与避障”。',left,55,12,'#81948a');
  const labels=[],chapterHits=[];
  if(m.preExecution){
    text('当前仍在接近作业区，到位后动作尚未启动。',left,100,18,'#4f7c65',600);
    const rowH=Math.min(74,(H-190)/Math.max(1,ids.length));
    ids.forEach((pid,i)=>{const worker=state.run.replay.workers.find(w=>w.pid===pid),pos=workerAt(worker),y=142+i*rowH;box(left,y,width,rowH-8);dot(left+28,y+rowH/2-3,pid);text(pid,left+57,y+25,14,teamColor(pid,jid),600);const label=pos.phase==='work'?'已到作业区 · 等待成员':'前往作业区';text(label,left+220,y+25,14);text(`当前位置 ${num(pos.x,2)}, ${num(pos.y,2)}`,left+450,y+25,12,'#84978c');labels.push({pid,phase:pos.phase});});
    state.hits=[];state.scene={jobId:jid,view:'process',focused:true,preExecution:true,relevantWorkers:ids.length,memberTracks:labels,labels:[],structureCount:0,traceCount:0,plannedCount:0};$('#map-caption').textContent='完整任务回放 · 接近阶段';return;
  }
  if(m.j.jtype==='assault'){
    // 阶段卡片按实际阶段数均分（突击含"撤离"共 5 段，写死 4 段会把最后一张挤出画布）
    const stepCount=Math.max(1,m.steps.length),cardY=76,cardH=66,gap=12,cardW=(width-(stepCount-1)*gap)/stepCount;
    m.steps.forEach((step,i)=>{const x=left+i*(cardW+gap);if(step[2]!=null)chapterHits.push({type:'chapter',x:x+cardW/2,y:cardY+cardH/2,w:cardW,h:cardH,t:step[2]});const active=i===m.index,done=i<m.index||m.complete;box(x,cardY,cardW,cardH,active?'#edf6f1':done?'#f3f8f4':'#fff',active?'#67a087':'#dde7e1');text(`${done?'✓':String(i+1).padStart(2,'0')}  ${step[1]}`,x+15,cardY+26,15,active?'#20765a':'#70887b',600);text(step[2]==null?'未记录':`日志 +${num(step[2]-m.start,0)} s${step[2]>state.t?' · 未播放':''}`,x+15,cardY+48,11,'#8b9d92');});
    const laneTop=184,laneBottom=H-72,rowH=Math.max(39,Math.min(74,(laneBottom-laneTop)/Math.max(1,ids.length))),trackLeft=left+128,trackRight=right-18,cell=(trackRight-trackLeft)/stepCount;
    text('成员',left,laneTop-16,12,'#8ba094');text('独立轨道 · 每行一位成员',trackLeft,laneTop-16,12,'#8ba094');
    // "到执行位"只统计突击组：侦察/评估平台到的是观察位/评估位，不能混进分母
    const assaultIds=ids.filter(pid=>((m.geometry&&m.geometry.roles)||{})[pid]==='突击组');
    let arrived=0;
    ids.forEach((pid,i)=>{
      const w=state.run.replay.workers.find(w=>w.pid===pid),p=workerAt(w),y=laneTop+rowH*i+rowH/2;
      const evidence=assaultMemberEvidence(jid,pid),actualTarget=evidence.target,distance=evidence.distance;
      if(assaultIds.includes(pid)&&distance!=null&&distance<=.7)arrived++;
      box(left,y-rowH/2+3,width,rowH-6,'#fff','#edf1ee',7);text(pid,left+12,y-2,13,teamColor(pid,jid),600);text(w.kind_name,left+12,y+16,10,'#95a499');
      ctx.setLineDash([3,5]);ctx.strokeStyle='#d6e2da';ctx.beginPath();ctx.moveTo(trackLeft,y);ctx.lineTo(trackRight,y);ctx.stroke();ctx.setLineDash([]);
      for(let k=0;k<stepCount;k++){ctx.beginPath();ctx.arc(trackLeft+cell*k+19,y,4,0,Math.PI*2);ctx.fillStyle=k<m.index?'#9dc5ae':'#dfe9e2';ctx.fill();}
      const x=trackLeft+cell*m.index+19;dot(x,y,pid);const label=evidence.label;
      const labelX=x+26;text(label,labelX,y-5,12,teamColor(pid,jid),600);text(distance==null?'距离未记录':`距当前目标 ${num(distance,2)} 单位`,labelX,y+13,10,'#899a8f');
      labels.push({pid,phase:m.phase,target:actualTarget,distance});
    });
    const desc=m.collapsed?'原记录点位重合，无法验证集结与执行的独立移动过程。':m.complete?'日志已记录结果确认。':m.phase==='机动'?`成员分别前往各自集结点；当前到位 ${arrived}/${assaultIds.length}。`:m.phase==='到位'?'已收到全员到位事件，等待下一阶段。':m.phase==='执行'?(m.s.behavior.detail?.debug?.effect_started?'已开始执行，等待日志中的执行完成事件。':`当前已到执行位 ${arrived}/${assaultIds.length}（突击组）；到位成员等待协同，侦察/评估平台在各自观察位。`):`${no(ids[0])} 执行结果确认，其余成员保持在各自位置。`;
    text(desc,left,H-40,13,'#426a54',600);if(m.collapsed)text('这份记录的集结/执行坐标相同；过程轨道只拆开成员，不改写原始运动。',left,H-18,11,'#9a8a6e');
  }else{
    const hold=workbenchHold(jid),primary=hold.pending?.outgoing||hold.primary,other=hold.pending?.incoming||hold.secondary,cardW=(width-100)/2,cardY=78,cardH=Math.min(112,H*.24);
    box(left,cardY,cardW,cardH,'#f0f7f0','#a6c5ae');box(right-cardW,cardY,cardW,cardH,'#fff9ef','#e1ceaa');
    text('主班 / 岗位侧',left+20,cardY+27,12,'#688c70');dot(left+40,cardY+63,primary,20);text(primary||'尚未记录',left+73,cardY+57,20,teamColor(primary,jid),600);text(hold.roles[primary]||'等待到岗记录',left+73,cardY+81,12,'#617a67');
    const x=right-cardW;text(hold.pending?'接班侧':'待命 / 返程侧',x+20,cardY+27,12,'#a68a59');if(other){dot(x+40,cardY+63,other,20);text(other,x+73,cardY+57,20,teamColor(other,jid),600);text(hold.roles[other]||'等待成员记录',x+73,cardY+81,12,'#8d795a');}
    arrow(right-cardW-14,cardY+cardH/2,left+cardW+14,cardY+cardH/2,hold.pending?'#c89646':'#c4d1c7');
    const bandY=cardY+cardH+55,rowH=Math.min(65,(H-bandY-64)/Math.max(1,ids.length)),timeLeft=left+125,timeRight=right-10,start=m.start,end=state.taskWindow.end;
    const X=t=>timeLeft+(t-start)/(end-start)*(timeRight-timeLeft);
    const palette={primary:['#87b49a','主班'],incoming:['#e6ba6c','接班'],waiting:['#d4dfe9','待命/返回'],approach:['#d7d2e8','就位']};
    text('成员角色时间带',left,bandY-20,13,'#5e7d69',600);text('只填充已经播放的记录',timeLeft,bandY-20,11,'#94a296');
    const role=(pid,t)=>{const b=state.frames[Math.min(state.frames.length-1,Math.floor(t))].jobs[jid].behavior,h=b.handover,pending=h&&!h.done,main=b.detail?.debug?.primary||(h?.done?h.incoming:ids[0]);if(pending&&pid===h.incoming)return 'incoming';if(pid===main){const on=taskEventTime(jid,'on_post');return on!=null&&t>=on?'primary':'approach';}return 'waiting';};
    ids.forEach((pid,i)=>{const y=bandY+i*rowH;text(pid,left+10,y+22,13,teamColor(pid,jid),600);box(timeLeft,y,timeRight-timeLeft,30,'#f4f7f4','#e6ede7',4);let from=start,lastRole=role(pid,start);const until=Math.min(state.t,end);for(let t=start+1;t<=Math.ceil(until);t++){const next=t>=until?null:role(pid,t);if(next!==lastRole){ctx.fillStyle=palette[lastRole][0];ctx.fillRect(X(from),y+1,Math.max(0,X(Math.min(t,until))-X(from)),28);from=t;lastRole=next;}}});
    const playX=X(Math.max(start,Math.min(end,state.t)));ctx.strokeStyle='#437d60';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(playX,bandY-7);ctx.lineTo(playX,bandY+rowH*ids.length-8);ctx.stroke();
    text('+0 s',timeLeft,bandY+rowH*ids.length+10,10,'#8b9c90');text('+'+num(end-start,0)+' s',timeRight-38,bandY+rowH*ids.length+10,10,'#8b9c90');
    let legendX=left;for(const [color,label]of Object.values(palette)){ctx.fillStyle=color;ctx.fillRect(legendX,H-39,13,9);text(label,legendX+19,H-30,11,'#7a9081');legendX+=110;}
    text(`当前已确认交接 ${m.s.behavior.handovers||0} 次${m.complete?' · 记录结束':''}`,right-225,H-30,13,'#406f53',600);
  }
  $('#map-caption').textContent='过程视图 · 阶段、角色与距离来自所选记录';$('#map-scale').textContent='';state.hits=chapterHits;
  state.scene={jobId:jid,focused:true,view:'process',structureCount:1,relevantWorkers:ids.length,traceCount:0,plannedCount:0,labels:[],memberTracks:labels};
}
