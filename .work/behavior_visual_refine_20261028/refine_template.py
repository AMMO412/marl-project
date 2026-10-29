from pathlib import Path

root = Path('D:/Desktop/MARL项目')
template = root / 'planning_middle_demo/behavior_demo.html'
s = template.read_text(encoding='utf-8')

def replace_function(name, next_name, body):
    global s
    start = s.index('function ' + name + '(')
    end = s.index('function ' + next_name + '(', start)
    s = s[:start] + body.strip() + '\n\n' + s[end:]

s = s.replace('<div class="card"><h3>行为指标（本作业全程）</h3>', '<div class="card" id="hold-card" hidden><h3>换班过程 · 当前记录</h3><div id="hold-status"></div></div><div class="card"><h3>当前路径 · 避障证据</h3><div id="route-status"></div></div><div class="card"><h3>行为指标（本作业全程最终值）</h3>')
s = s.replace('<div class="sub">规划器下发指派', '<div class="sub">独立串行行为验证记录（区别于工作台并行运行）；规划器下发指派')
start = s.index('<footer>')
end = s.index('</footer>', start) + len('</footer>')
controls = '''<section class="playback-panel">
  <div id="tabs"></div>
  <div class="controls"><button id="play">播放</button><button id="restart">重播本段</button><select id="chapter"><option value="action">作业区动作</option><option value="approach">机动避障</option></select><select id="speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select><input id="seek" type="range" min="0" max="1" step="any" value="0"><label><input type="checkbox" id="showBuildings" checked>碰撞盒</label><label><input type="checkbox" id="showPaths" checked>当前路径</label><label><input type="checkbox" id="showStraight">被挡直线对照</label></div>
  <div id="hold-track" hidden></div><div id="timeline"></div>
</section>'''
s = s[:start] + s[end:]
s = s.replace('<main>', controls + '\n<main>', 1)
s = s.replace('let T = 0, playing = true, last = 0, view = {scale:1, ox:0, oy:0, pad:26};', "let T=0,playing=false,last=0,selectedJob=DATA.jobs[0].job_id,chapter='action',view={scale:1,ox:0,oy:0,pad:40,bounds:DATA.bounds};")
s = s.replace('(p[0]-DATA.bounds[0])', '(p[0]-view.bounds[0])').replace('(DATA.bounds[3]-p[1])', '(view.bounds[3]-p[1])')
s = s.replace('  const b = DATA.bounds;', '  const b = view.bounds;', 1)

replace_function('resize', 'currentJob', r'''
function actionStart(job){return (job.events.find(e=>e.kind==='arrived_area')||{}).t??job.t0;}
function rangeOf(job){return {start:chapter==='approach'?job.t0:actionStart(job),end:chapter==='approach'?Math.max(job.t0+.1,actionStart(job)):job.t1};}
function routeTime(job,route){return job.t0+(route.t||0);}
function latestRoutes(job){const latest={};for(const route of job.routes)if(routeTime(job,route)<=T+1e-6)latest[route.pid]=route;return latest;}
function standbyFor(job){const route=job.routes.find(r=>r.pid===job.pids[1]);return route?.to;}
function fitBounds(job){
 let points=[job.site];const m=job.metrics;
 if(chapter==='approach'){for(const r of job.approach||[])points.push(...r.path,r.from_pose,r.to);}
 else if(job.type==='hold'){
  points.push(m.posts[0]);if(standbyFor(job))points.push(standbyFor(job));
  for(const sample of job.samples)if(sample.t>=actionStart(job))points.push(...Object.values(sample.agents));
 }else{
  for(const sample of job.samples)if(sample.t>=actionStart(job))points.push(...Object.values(sample.agents));
  points.push(...(m.loop||[]),...(m.posts||[]),...(m.staging||[]),...(m.objective||[]));
  const radius=m.area_radius||m.outer_radius||m.ring_radius||0;
  if(radius)points.push([job.site[0]-radius,job.site[1]-radius],[job.site[0]+radius,job.site[1]+radius]);
 }
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
 const w=Math.max(5,Math.max(...xs)-Math.min(...xs)),h=Math.max(5,Math.max(...ys)-Math.min(...ys)),pad=Math.max(.7,Math.max(w,h)*.08);
 return [cx-w/2-pad,cy-h/2-pad,cx+w/2+pad,cy+h/2+pad];
}
function resize(){
 const dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
 canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
 const bounds=fitBounds(currentJob()),pad=42,s=Math.min((w-2*pad)/(bounds[2]-bounds[0]),(h-2*pad)/(bounds[3]-bounds[1]));
 view={scale:s,pad,bounds,ox:(w-(bounds[2]-bounds[0])*s)/2,oy:(h-(bounds[3]-bounds[1])*s)/2};draw();
}
''')
replace_function('currentJob', 'frameOf', 'function currentJob(){return DATA.jobs.find(j=>j.job_id===selectedJob)||DATA.jobs[0];}')

replace_function('drawHold', 'drawRoutes', r'''
function holdState(job,frame){
 const evs=job.events.filter(e=>e.t<=T),starts=evs.filter(e=>e.kind==='handover_start'),completes=evs.filter(e=>e.kind==='handover_complete');
 const lastStart=starts.at(-1),lastComplete=completes.at(-1),pending=lastStart&&(!lastComplete||lastStart.t>lastComplete.t)?lastStart:null;
 const primary=frame?.debug?.primary||lastComplete?.incoming||job.pids[0],secondary=frame?.debug?.secondary||job.pids.find(p=>p!==primary),post=job.metrics.posts[0],standby=standbyFor(job);
 const distance=(a,b)=>a&&b?Math.hypot(a[0]-b[0],a[1]-b[1]):Infinity;
 const onPost=job.events.find(e=>e.kind==='on_post'),roles={};
 for(const pid of job.pids){const pos=frame?.agents[pid];
  if(pending&&pid===pending.incoming)roles[pid]='接班中 → 岗位';
  else if(pending&&pid===pending.outgoing)roles[pid]=distance(pos,post)<=.8?'原班守岗 · 等待交接':'原班仍在接近岗位';
  else if(pid===primary)roles[pid]=distance(pos,post)<=.8?'当前主班 · 在岗':'当前主班 · 就位中';
  else roles[pid]=distance(pos,standby)<=.8?'待命位置等待':lastComplete?'已交班 · 等待/返回待命':'前往待命位置';
 }
 let message=pending?`${pending.outgoing.replace('rover_','#')} → ${pending.incoming.replace('rover_','#')}：接班成员正在前往岗位。`:`当前主班 ${primary.replace('rover_','#')}；另一成员在待命或返程。`;
 if(pending&&(!onPost||T<onPost.t))message+='原班尚未建立正式到岗记录，不标为持续守岗。';
 if(T>=job.t1-.11)message+='记录已结束；两成员仍在岗位附近，不补画撤离动作。';
 return {primary,secondary,pending,completed:completes.length,roles,message,onPost,post,standby};
}
function drawHold(job,frame){
 const state=holdState(job,frame),post=project(state.post),standby=state.standby?project(state.standby):null;
 ctx.save();ctx.fillStyle='#edf7ee';ctx.strokeStyle='#8fbc96';ctx.lineWidth=1.5;
 ctx.beginPath();ctx.arc(post[0],post[1],25,0,Math.PI*2);ctx.fill();ctx.stroke();
 ctx.fillStyle='#527c59';ctx.font='600 13px system-ui';ctx.fillText('交接岗位',post[0]-28,post[1]-39);
 if(standby){ctx.setLineDash([4,4]);ctx.strokeStyle='#aab5c1';ctx.beginPath();ctx.arc(standby[0],standby[1],20,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#8593a3';ctx.fillText('待命位置',standby[0]-28,standby[1]-34);}
 ctx.restore();
}
''')

replace_function('drawRoutes', 'drawTrails', r'''
function drawRoutes(job){
 if(!document.getElementById('showPaths').checked)return;
 const frame=frameOf(job);ctx.save();
 for(const [pid,route]of Object.entries(latestRoutes(job))){
  const pos=frame?.agents[pid];if(pos&&Math.hypot(pos[0]-route.to[0],pos[1]-route.to[1])<.6)continue;
  if(straightToggle.checked&&!route.straight_line_ok){const a=project(route.from_pose),b=project(route.to);ctx.setLineDash([5,5]);ctx.strokeStyle='#dc8b63aa';ctx.lineWidth=1.4;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();ctx.setLineDash([]);}
  ctx.strokeStyle=AGENT_COLORS[job.pids.indexOf(pid)%AGENT_COLORS.length]+'70';ctx.lineWidth=2;ctx.beginPath();route.path.forEach((p,i)=>{const q=project(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.stroke();
 }
 ctx.restore();
}
''')
s = s.replace("    if (s.t > T) break;\n    for (const pid in s.agents){", "    if (s.t > T) break;\n    if(job.type==='hold'&&s.t<Math.max(rangeOf(job).start,T-8))continue;\n    for (const pid in s.agents){", 1)

replace_function('drawAgents', 'draw', r'''
function drawAgents(job,frame){
 if(!frame)return;let index=0;const hold=job.type==='hold'?holdState(job,frame):null;
 for(const [pid,[x,y,yaw]]of Object.entries(frame.agents)){
  const q=project([x,y]),color=AGENT_COLORS[index%AGENT_COLORS.length];ctx.save();ctx.translate(...q);ctx.rotate(-yaw);ctx.beginPath();ctx.moveTo(12,0);ctx.lineTo(-7,7);ctx.lineTo(-7,-7);ctx.closePath();ctx.fillStyle=color;ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.fill();ctx.stroke();ctx.restore();
  ctx.save();ctx.font='600 12px system-ui';const text=pid.replace('rover_','#')+(hold?' · '+hold.roles[pid]:''),w=ctx.measureText(text).width+16;
  const lx=Math.max(6,Math.min(canvas.clientWidth-w-6,q[0]-w/2)),ly=hold?q[1]+(index===0?-73:48):q[1]+20;
  ctx.beginPath();ctx.moveTo(...q);ctx.lineTo(lx+w/2,ly+9);ctx.strokeStyle=color+'99';ctx.lineWidth=1;ctx.stroke();ctx.fillStyle='#fffffff2';ctx.fillRect(lx,ly-9,w,26);ctx.fillStyle=color;ctx.fillText(text,lx+8,ly+8);ctx.restore();index++;
 }
}
''')
s = s.replace('  drawGrid(); drawBuildings();', "  drawGrid();if(document.getElementById('showBuildings').checked)drawBuildings();")
s = s.replace('  drawSite(job);', "  if(job.type!=='hold')drawSite(job);", 1)
s = s.replace('  updatePanel(job);', '  updatePanel(job);updateDetails(job,frameOf(job));', 1)

start = s.index('function buildTabs(){')
end = s.index('const params = new URLSearchParams', start)
s = s[:start] + r'''
function updateDetails(job,frame){
 const hold=job.type==='hold',card=document.getElementById('hold-card');card.hidden=!hold;
 const evs=job.events.filter(e=>e.t<=T);const latest=latestRoutes(job);
 const routes=Object.values(latest).filter(r=>{const p=frame?.agents[r.pid];return p&&Math.hypot(p[0]-r.to[0],p[1]-r.to[1])>=.6;});
 document.getElementById('route-status').innerHTML=routes.map(r=>`<div class="route-card"><b>${r.pid.replace('rover_','#')} · ${r.straight_line_ok?'当前直线可通行':'原直线被挡 → 已绕行'}</b><small>路径 ${money(r.length)} / 直线 ${money(r.straight)} 单位</small><small>规划路径最小净空 ${money(r.min_clearance,3)} 单位</small></div>`).join('')||'<div class="notes">当前路径已到达或尚未产生。可切换“机动避障”查看接近过程。</div>';
 if(hold){
  const state=holdState(job,frame);document.getElementById('hold-status').innerHTML=`<div class="hold-message">${state.message}</div><div class="hold-count">已完成交接 <b>${state.completed}</b> 次</div>${job.pids.map((pid,i)=>`<div class="role-card" style="border-left-color:${AGENT_COLORS[i]}"><b>${pid.replace('rover_','#')}</b><strong>${state.roles[pid]}</strong><small>当前坐标 ${frame.agents[pid].slice(0,2).map(x=>money(x)).join(', ')}</small></div>`).join('')}<p class="notes">首次正式到岗记录：${state.onPost?money(state.onPost.t-job.t0,1)+' s（本任务时间）':'未记录'}。全程“零人在位”指标从该基线开始统计，不覆盖此前机动。</p>`;
  hudPhase.textContent='· '+(state.pending?'接替进行中':frame.phase);document.getElementById('hold-track').hidden=false;
  document.getElementById('hold-track').innerHTML=job.events.filter(e=>['on_post','handover_start','handover_complete'].includes(e.kind)).map(e=>`<button class="${e.t<=T?'past':'future'}" data-jump="${e.t}"><small>${money(e.t-job.t0,0)} s</small>${EVENT_NAME[e.kind]}${e.incoming?' · '+e.outgoing.replace('rover_','#')+' → '+e.incoming.replace('rover_','#'):''}</button>`).join('');
 }else document.getElementById('hold-track').hidden=true;
 if(job.type==='recon'&&frame.debug?.coverage!=null)hudPhase.textContent='· '+frame.phase+' · 当前覆盖 '+money(frame.debug.coverage*100,1)+'%';
 const range=rangeOf(job);clockEl.textContent=money(T-job.t0,1)+' s · 本任务';seek.value=(T-range.start)/Math.max(.1,range.end-range.start);
 document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('active',el.dataset.job===job.job_id));
 const head=document.getElementById('playhead');if(head)head.style.left=(T/DATA.total*100)+'%';
}
function selectJob(jid,mode=chapter,autoplay=false){
 selectedJob=jid;chapter=mode;document.getElementById('chapter').value=mode;T=rangeOf(currentJob()).start;playing=autoplay;playBtn.textContent=playing?'暂停':'播放';lastJobId=null;resize();
}
function buildTabs(){
 for(const job of DATA.jobs){const b=document.createElement('button');b.className='tab';b.dataset.job=job.job_id;b.textContent=job.job_id+' '+job.label;b.onclick=()=>selectJob(job.job_id,chapter,true);tabsEl.append(b);
 const seg=document.createElement('div');seg.className='seg';seg.style.flex=String(job.t1-job.t0);seg.style.background=job.color;seg.textContent=job.job_id+' '+job.label;seg.title='独立串行验证记录';seg.onclick=()=>selectJob(job.job_id,chapter,true);timelineEl.append(seg);}
 const head=document.createElement('div');head.className='playhead';head.id='playhead';timelineEl.append(head);
}
function tick(ts){if(!last)last=ts;const dt=Math.min(.1,(ts-last)/1000);last=ts;if(playing){const range=rangeOf(currentJob());T=Math.min(range.end,T+dt*Number(speedSel.value));if(T>=range.end){playing=false;playBtn.textContent='播放';}draw();}requestAnimationFrame(tick);}
seek.max=1;seek.oninput=()=>{playing=false;playBtn.textContent='播放';const r=rangeOf(currentJob());T=r.start+Number(seek.value)*(r.end-r.start);draw();};
playBtn.onclick=()=>{const r=rangeOf(currentJob());if(T>=r.end)T=r.start;playing=!playing;playBtn.textContent=playing?'暂停':'播放';last=0;};
document.getElementById('restart').onclick=()=>selectJob(selectedJob,chapter,true);
document.getElementById('chapter').onchange=e=>selectJob(selectedJob,e.target.value,true);
for(const el of [straightToggle,document.getElementById('showBuildings'),document.getElementById('showPaths')])el.onchange=draw;
document.addEventListener('click',e=>{const button=e.target.closest('[data-jump]');if(button){T=Number(button.dataset.jump);playing=false;playBtn.textContent='播放';draw();}});
window.addEventListener('resize',resize);
''' + s[end:]

start = s.index('const params = new URLSearchParams')
end = s.index('</script>', start)
s = s[:start] + '''const params=new URLSearchParams(location.search);
if(DATA.jobs.some(j=>j.job_id===params.get('job')))selectedJob=params.get('job');
chapter=params.get('chapter')==='approach'?'approach':'action';
buildTabs();selectJob(selectedJob,chapter,false);
if(params.has('t')&&Number.isFinite(Number(params.get('t')))){const r=rangeOf(currentJob());T=Math.max(r.start,Math.min(r.end,Number(params.get('t'))));draw();}
requestAnimationFrame(tick);
''' + s[end:]

css = '''
header{padding:20px 24px 12px}.playback-panel{margin:0 24px 16px}#tabs{margin-bottom:10px}.controls{flex-wrap:wrap}.controls label{font-size:11px;color:#718096;white-space:nowrap}.controls select,.controls button{font-size:12px}#seek{min-width:170px}.stage{min-height:600px}canvas{height:70vh;min-height:580px;max-height:850px}main{padding-bottom:24px}#timeline{height:28px}.card h3{font-size:12px}.hold-message{padding:12px;background:#eff6ef;border:1px solid #d7e7d5;border-radius:7px;font-size:12px;color:#4c7354}.hold-count{font-size:12px;color:#6b7280;margin:12px 0}.hold-count b{font-size:22px;color:#24845b;margin:0 5px}.role-card{padding:11px;border:1px solid #e2e8f0;border-left:3px solid;border-radius:6px;margin-top:9px;background:#fcfdfc}.role-card b{display:block;font-size:12px}.role-card strong{display:block;font-size:12px;font-weight:500;margin-top:4px;color:#506475}.role-card small{display:block;font-size:10px;color:#94a3b8;margin-top:5px}.route-card{padding:9px 0;border-bottom:1px solid #edf0f4}.route-card:last-child{border:0}.route-card b{display:block;font-size:12px;font-weight:500;color:#4f6981}.route-card small{display:block;color:#8c9aae;font-size:10px;margin-top:4px}#hold-track{display:flex;gap:8px;overflow:auto;padding:10px 0 2px}#hold-track[hidden]{display:none}#hold-track button{font-size:11px;white-space:nowrap;text-align:left;color:#4b6e59;background:#f4faf3;border-color:#dbe8d7;padding:8px 12px}#hold-track small{display:block;color:#8c9e8d;font-size:10px}.future{opacity:.45}.clock{right:14px;left:auto}.notes{font-size:10px}aside{max-height:none}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #75a490;outline-offset:3px}@media(max-width:1100px){aside{display:grid;grid-template-columns:1fr 1fr}.stage{min-height:520px}canvas{height:65vh;min-height:500px}}@media(max-width:650px){header{padding:15px 12px 8px}h1{font-size:17px}.sub{font-size:11px}.playback-panel{margin:0 12px 12px}main{padding:0 12px 18px;grid-template-columns:1fr}aside{display:block}.card{margin-bottom:10px}.controls{gap:8px}.controls #seek{order:5;flex:1 1 100%}.stage{min-height:440px}canvas{height:480px;min-height:480px}.hud{font-size:10px;left:8px;top:8px;padding:4px 8px;max-width:70%;flex-wrap:wrap;gap:5px}.clock{font-size:10px;top:8px;right:8px;padding:4px 8px}.tab{font-size:11px;padding:5px 8px}.legend{font-size:10px}}
'''
s = s.replace('</style>', css + '\n</style>')
template.write_text(s, encoding='utf-8')
print('Updated template:', template)
