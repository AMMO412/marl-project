/* UI state and rendering. Data comes from the existing replay only. */
(() => {
  let ready=false, aircraft=null, lastRun=null;
  const dom={};
  function setHtml(node,html){if(node.innerHTML!==html)node.innerHTML=html;}
  function panel(title,id,open=true){const el=document.createElement('details');el.className='layout-fold';el.open=open;el.id=id;const summary=document.createElement('summary');summary.textContent=title;const content=document.createElement('div');content.className='rail-detail-body';el.append(summary,content);dom[id]=content;return el;}
  function fold(el,title,id){const p=panel(title,id,false);el.before(p);p.lastChild.replaceWith(el);return p;}
  function status(message,error=false){if(!ready)return;dom.status.textContent=message;dom.status.setAttribute('role',error?'alert':'status');}
  function reset(){lastRun=null;aircraft=null;}
  function render(){
    if(!ready||document.hidden||state.page!=='overview')return;
    const run=state.run;
    if(!run){dom.task.replaceChildren();for(const id of ['rail-execution','rail-path','rail-members','rail-events'])dom[id].textContent='尚未载入运行记录';dom.altitudeReading.textContent='尚未载入运行记录';dom.chart.replaceChildren();return;}
    if(lastRun!==run){lastRun=run;aircraft=null;dom.task.replaceChildren(...run.report.jobs.map(j=>new Option(j.job_id+' · '+taskLabel(j),j.job_id)));dom.aircraft.replaceChildren(...run.replay.workers.filter(w=>['PLANE','WING'].includes(w.kind)).map(w=>new Option(w.pid+' · '+w.kind,w.pid)));}
    const jid=state.selectedTaskId;
    dom.task.value=jid||'';
    const j=run.report.jobs.find(j=>j.job_id===jid),s=frame()?.jobs[jid];
    if(j&&s){
      setHtml(dom['rail-execution'],taskExecutionHtml(jid));
      setHtml(dom['rail-path'],taskRoutesHtml(jid));
      setHtml(dom['rail-members'],s.pids.map(pid=>{const w=run.replay.workers.find(w=>w.pid===pid),p=w?workerAt(w):{};return '<button class="theater-member" data-worker="'+esc(pid)+'"><b>'+esc(pid)+'<span>'+esc(w?.kind_name||'')+'</span></b><strong>'+esc(phaseName(p.phase))+'</strong><small>坐标 '+num(p.x)+', '+num(p.y)+' · z '+num(p.z)+'</small></button>';}).join('')||'<p>尚未分配成员</p>');
      const rows=state.eventRows.filter(e=>e.job_id===jid&&e.sim_s<=state.t).slice(-8).reverse();
      setHtml(dom['rail-events'],rows.map(e=>'<button class="text-button" data-event-time="'+e.sim_s+'"><time>'+num(e.sim_s)+' s</time> '+esc(eventTitle(e))+'</button>').join('')||'<p>当前时刻暂无任务事件</p>');
    }else{for(const id of ['rail-execution','rail-path','rail-members','rail-events'])dom[id].textContent='请选择任务查看记录';}
    updateLayerOptions();
    renderAltitude();
    const b=fullBounds(),ratio=(b[2]-b[0])/(b[3]-b[1]);
    if(Number.isFinite(ratio)&&ratio>0)document.querySelector('.map-card').style.setProperty('--map-aspect',String(ratio));
  }
  function updateLayerOptions(){
    const routes=state.selectedTaskId?currentTaskRoutes(state.selectedTaskId):[];
    const visible=(id,on)=>{const input=document.getElementById(id);input.closest('label').hidden=!on;};
    visible('show-planned',!!state.taskWindow&&routes.length>0);
    visible('show-blocked-line',!!state.taskWindow&&document.getElementById('show-planned').checked&&routes.some(r=>!r.straight_line_ok));
    visible('show-sensor-range',!!(state.run.replay.containment?.structure
      ||(state.run.replay.behaviors||[]).some(b=>b.type==='assault')));
    visible('show-landmarks',mapGeometry('landmarks').length>0);
    visible('show-behaviors',!!(state.run.replay.behaviors?.length||state.run.replay.containment||state.run.replay.hold));
    document.getElementById('full-trails').disabled=false;
  }
  function renderAltitude(){
    const w=state.run.replay.workers.find(w=>String(w.pid)===(aircraft||dom.aircraft.value));
    if(!w){dom.altitudeReading.textContent='当前运行没有飞机';dom.chart.replaceChildren();return;}
    const pts=(w.samples||[]).filter(p=>Number.isFinite(p.t)&&p.t<=state.t).sort((a,b)=>a.t-b.t);
    const valid=pts.filter(p=>Number.isFinite(p.z)),latest=pts[pts.length-1];
    if(!valid.length||!Number.isFinite(latest?.z)){dom.altitudeReading.textContent='当前时刻无有效高度反馈';dom.chart.replaceChildren();return;}
    const prev=pts[pts.length-2],dz=Number.isFinite(prev?.z)?latest.z-prev.z:null;
    dom.altitudeReading.textContent='z '+latest.z.toFixed(2)+' · '+(latest.lost?'反馈已失联':dz===null?'单点反馈':Math.abs(dz)<.001?'高度未变':dz>0?'上升':'下降')+' · 最近反馈 '+latest.t.toFixed(1)+' s';
    let lo=valid.reduce((v,p)=>Math.min(v,p.z),Infinity),hi=valid.reduce((v,p)=>Math.max(v,p.z),-Infinity);if(hi===lo){lo-=.5;hi+=.5;}
    const end=Math.max(state.t,1),X=t=>42+266*t/end,Y=z=>76-64*(z-lo)/(hi-lo);
    // Points show observed samples; lines are only drawn between adjacent valid records.
    let paths='',prior=null;
    for(const p of pts){if(!Number.isFinite(p.z)){prior=null;continue;}if(prior)paths+='<path d="M'+X(prior.t)+' '+Y(prior.z)+'H'+X(p.t)+'V'+Y(p.z)+'" fill="none" stroke="#217b66" stroke-width="1.5"/>';paths+='<circle cx="'+X(p.t)+'" cy="'+Y(p.z)+'" r="1.6" fill="#217b66"/>';prior=p;}
    dom.chart.innerHTML='<path d="M42 8V76H310" fill="none" stroke="#dce6df"/>'+paths+'<g font-size="9" fill="#718579"><text x="2" y="15">'+hi.toFixed(1)+'</text><text x="2" y="78">'+lo.toFixed(1)+'</text><text x="42" y="95">0 s</text><text x="260" y="95">'+state.t.toFixed(1)+' s</text></g>';
  }
  function init(){
    const header=document.querySelector('.sidebar');document.querySelector('.brand span').textContent='融合工作台';
    const names={overview:'总览',tasks:'任务',platforms:'平台',runs:'报告',files:'文件'};
    document.querySelectorAll('.nav').forEach(b=>{[...b.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).forEach(n=>{if(n.textContent.trim())n.textContent=names[b.dataset.page];});});
    header.append(document.querySelector('.connection'));
    document.querySelector('.run-right').append(document.getElementById('refresh'),document.getElementById('open-config'));document.getElementById('open-config').textContent='＋ 新建运行';
    dom.status=document.createElement('div');dom.status.className='ui-status';document.querySelector('.run-strip').after(dom.status);
    const history=document.createElement('button');history.className='button';history.textContent='历史运行';history.onclick=()=>setPage('runs');document.querySelector('.run-right').prepend(history);
    fold(document.getElementById('behavior-panel'),'动作与判定详情','layout-actions');fold(document.querySelector('.event-card'),'全部事件记录','layout-events');
    const map=document.querySelector('.map-card'),extra=document.createElement('div');extra.className='layout-map-details';map.append(extra);
    ['.task-context','.map-selection','#task-data-warning','#stage-panel','#action-chapters','#hold-chapters'].forEach(s=>extra.append(document.querySelector(s)));fold(extra,'任务视图选项','layout-map-options');
    document.querySelector('.canvas-wrap').after(document.querySelector('.map-legend'));
    const info=document.createElement('button');info.type='button';info.className='button small';info.id='layout-map-info';
    const switches=['show-labels','show-landmarks'].map(id=>document.getElementById(id));
    const sync=()=>{const on=switches.some(s=>s.checked);info.textContent=on?'收起地图信息':'展开地图信息';info.setAttribute('aria-pressed',String(on));};
    switches.forEach(s=>{s.checked=false;s.addEventListener('change',sync);});info.onclick=()=>{const on=switches.some(s=>s.checked);switches.forEach(s=>{s.checked=!on;s.dispatchEvent(new Event('change'));});sync();};sync();document.querySelector('.map-tools').prepend(info);
    const fitTask=document.createElement('button');fitTask.className='button small';fitTask.textContent='聚焦任务';fitTask.onclick=()=>{if(state.selectedTaskId)focus('job',state.selectedTaskId);};document.querySelector('.map-tools').append(fitTask);
    document.querySelector('.layer-options').append(document.querySelector('.history-toggle'));
    // Recent and full trails are independent display modes, not parent/child switches.
    const recentTrails=document.getElementById('show-trails'),fullTrails=document.getElementById('full-trails');
    fullTrails.disabled=false;
    fullTrails.addEventListener('change',()=>{if(fullTrails.checked)recentTrails.checked=false;draw();});
    recentTrails.addEventListener('change',()=>{if(recentTrails.checked)fullTrails.checked=false;draw();});

    document.querySelectorAll('.layer-options input').forEach(input=>input.addEventListener('change',()=>{if(state.run)updateLayerOptions();}));
    const drawer=document.querySelector('.right-column');
    const label=document.createElement('label');label.className='rail-selector';label.textContent='当前任务';dom.task=document.createElement('select');dom.task.id='rail-task';dom.task.setAttribute('aria-label','当前任务');label.append(dom.task);drawer.prepend(label);dom.task.onchange=()=>selectTask(dom.task.value);
    drawer.append(panel('执行细节','rail-execution'));
    const altitude=panel('飞机高度','rail-altitude');altitude.lastChild.className='altitude-content';altitude.lastChild.innerHTML='<label>飞机 <select id="altitude-aircraft" aria-label="选择飞机"></select></label><div id="altitude-reading"></div><svg id="altitude-chart" viewBox="0 0 320 100" role="img" aria-label="历史高度反馈，阶梯线连接采样点"></svg><small>场景坐标 z · 场景单位，未标定海拔；仅显示已记录采样。</small>';
    drawer.append(altitude,panel('当前路径与避障记录','rail-path'),panel('参与成员','rail-members'),panel('任务事件','rail-events',false));
    dom.aircraft=document.getElementById('altitude-aircraft');dom.chart=document.getElementById('altitude-chart');dom.altitudeReading=document.getElementById('altitude-reading');dom.aircraft.onchange=()=>{aircraft=dom.aircraft.value;render();};
    const grid=document.querySelector('.overview-grid'),splitter=document.createElement('div');splitter.className='layout-splitter';splitter.tabIndex=0;splitter.setAttribute('role','separator');splitter.setAttribute('aria-orientation','vertical');splitter.setAttribute('aria-label','调整地图与任务详情宽度');grid.insertBefore(splitter,drawer);
    let ratio=.6;try{const value=Number(localStorage.getItem('workbench-split'));if(value>=.2&&value<=.8)ratio=value;}catch{}
    const resize=()=>{const width=grid.clientWidth,stacked=width<900;grid.classList.toggle('ui-stacked',stacked);if(!stacked){const low=480/width,high=(width-332)/width;ratio=Math.max(low,Math.min(high,ratio));grid.style.setProperty('--split',(ratio*100).toFixed(2)+'%');splitter.setAttribute('aria-valuemin',String(Math.round(low*100)));splitter.setAttribute('aria-valuemax',String(Math.round(high*100)));splitter.setAttribute('aria-valuenow',String(Math.round(ratio*100)));}draw();};
    const save=()=>{try{localStorage.setItem('workbench-split',String(ratio));}catch{}};
    splitter.onpointerdown=e=>{e.preventDefault();splitter.setPointerCapture(e.pointerId);};splitter.onpointermove=e=>{if(!splitter.hasPointerCapture(e.pointerId))return;ratio=(e.clientX-grid.getBoundingClientRect().left)/grid.clientWidth;resize();};splitter.onpointerup=save;splitter.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;e.preventDefault();ratio=e.key==='Home'?.6:ratio+(e.key==='ArrowLeft'?-.02:.02);resize();save();};
    new ResizeObserver(resize).observe(grid);
    const mapArea=document.querySelector('.canvas-wrap'),heightHandle=document.createElement('div');
    heightHandle.className='layout-height-handle';heightHandle.tabIndex=0;
    heightHandle.setAttribute('role','separator');heightHandle.setAttribute('aria-orientation','horizontal');
    heightHandle.setAttribute('aria-label','上下拖动调整地图高度');heightHandle.title='上下拖动调整地图高度；双击恢复默认';
    mapArea.after(heightHandle);
    let mapHeight=null;
    try{const saved=Number(localStorage.getItem('workbench-map-height'));if(saved>=220&&saved<=1200)mapHeight=saved;}catch{}
    function applyHeight(){
      if(mapHeight===null)mapArea.style.removeProperty('height');
      else{mapHeight=Math.max(220,Math.min(1200,mapHeight));mapArea.style.height=mapHeight+'px';}
      heightHandle.setAttribute('aria-valuemin','220');heightHandle.setAttribute('aria-valuemax','1200');
      heightHandle.setAttribute('aria-valuenow',String(Math.round(mapArea.getBoundingClientRect().height)));
      draw();
    }
    function saveHeight(){try{if(mapHeight===null)localStorage.removeItem('workbench-map-height');else localStorage.setItem('workbench-map-height',String(mapHeight));}catch{}}
    let heightDrag=null;
    heightHandle.onpointerdown=e=>{e.preventDefault();heightDrag={y:e.clientY,height:mapArea.getBoundingClientRect().height};heightHandle.setPointerCapture(e.pointerId);};
    heightHandle.onpointermove=e=>{if(!heightDrag||!heightHandle.hasPointerCapture(e.pointerId))return;mapHeight=heightDrag.height+e.clientY-heightDrag.y;applyHeight();};
    heightHandle.onpointerup=()=>{heightDrag=null;saveHeight();};heightHandle.onpointercancel=()=>{heightDrag=null;saveHeight();};
    heightHandle.ondblclick=()=>{mapHeight=null;applyHeight();saveHeight();};
    heightHandle.onkeydown=e=>{if(!['ArrowUp','ArrowDown','Home'].includes(e.key))return;e.preventDefault();mapHeight=e.key==='Home'?null:mapArea.getBoundingClientRect().height+(e.key==='ArrowUp'?-20:20);applyHeight();saveHeight();};
    applyHeight();

    document.getElementById('fit-map').textContent='显示完整底图';document.getElementById('fit-map').onclick=()=>{if(!state.run)return;state.zoom=1;bounds=fullBounds();draw();};
    document.getElementById('open-actions').onclick=()=>{const p=document.getElementById('layout-actions');p.open=true;p.scrollIntoView();};
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){render();draw();}});
    document.querySelector('.reference-links').title='历史独立记录，不对应当前运行';
    document.body.dataset.layoutVersion='workbench-ui-20261103';ready=true;render();resize();
  }
  window.WorkbenchUI={render,reset,status};
  document.addEventListener('DOMContentLoaded',init);
})();
