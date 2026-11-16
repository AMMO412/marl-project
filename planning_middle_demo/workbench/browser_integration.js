/* Current maps, planner objectives and immutable run inputs for the new UI. */
(() => {
  const map = document.createElement('select'); map.id = 'config-map';
  const random = document.createElement('input'); random.type='checkbox'; random.checked=true;
  random.id='config-randomize-tasks';
  const seed = document.createElement('input'); seed.type='number'; seed.min=0; seed.max=2147483647;
  seed.value=0; seed.id='config-task-seed';
  const field=(text,input)=>{const label=document.createElement('label');label.className='field';label.append(text,input);return label;};
  const anchor=document.getElementById('config-scenario').closest('label');
  anchor.after(field('规划与显示地图',map),field('随机任务区与威胁区',random),field('场景种子（0=新种子）',seed));
  const objective=document.getElementById('config-objective') || document.querySelector('[name=objective]');
  if(objective){objective.id='config-objective';objective.replaceChildren(...Object.entries({makespan:'时效优先',exposure:'暴露度优先',energy:'能耗优先',balanced:'均衡目标'}).map(([value,label])=>new Option(label,value)));}
  const isCase=id=>['interop_integrated','interop_campus_motion20'].includes(id);
  const request=data=>({...data,map_id:isCase(data.scenario)?'source':data.map_id||(map.value==='source'?cityMap:map.value)||'residential',
    randomize_tasks:isCase(data.scenario)?false:random.checked,
    task_seed:Number(seed.value)||0,reseed_on_run:isCase(data.scenario)?false:!Number(seed.value)});
  let cityMap='residential';
  const syncMap=()=>{
    const fixed=isCase(document.getElementById('config-scenario').value);
    if(fixed){
      if(map.value&&map.value!=='source')cityMap=map.value;
      if(![...map.options].some(option=>option.value==='source'))map.add(new Option('综合案例原始六栋楼地图','source'));
      map.value='source';
    } else {
      const wasSource=map.value==='source';
      [...map.options].filter(option=>option.value==='source').forEach(option=>option.remove());
      if(wasSource||!map.value)map.value=cityMap;
    }
    map.disabled=random.disabled=seed.disabled=fixed;
  };
  document.getElementById('config-scenario').addEventListener('change',syncMap);
  map.addEventListener('change',()=>{if(map.value!=='source')cityMap=map.value;});
  window.BrowserIntegration={request,mapId:()=>map.value==='source'?cityMap:(map.value||cityMap),catalog(data){
    const selected=map.value;
    const entries=Array.isArray(data.maps)?data.maps:(data.maps?.maps||[]);
    map.replaceChildren(...entries.map(item=>new Option(item.label||item.id,item.id)));
    if([...map.options].some(item=>item.value===selected))map.value=selected;
    if(!map.value)map.value='residential';
    syncMap();
  }};
  const apiOriginal=api;
  api=async function(url,options){
    if(url==='/api/runs'&&options?.body){const data=JSON.parse(options.body);if(data.replay_edit)return apiOriginal(url,options);options={...options,body:JSON.stringify({...request(data),live:document.querySelector('[name=live]')?.checked||false,...(data.edit?{randomize_tasks:false,reseed_on_run:false}: {})})};}
    return apiOriginal(url,options);
  };
  const editSource=document.getElementById('editor-source');
  const liveOption=[...editSource.options].find(option=>option.value==='live');if(liveOption)liveOption.hidden=true;
  editSource.add(new Option('当前运行初始配置（另建运行）','initial'));
  const runOption=[...editSource.options].find(option=>option.value==='run');
  if(runOption)runOption.textContent='当前回放暂停时刻（修改并续算）';
})();


// Workbench controls share the existing runtime API and input contracts.
(() => {
  const selector=document.getElementById('task-select');
  const follow=document.createElement('input');follow.type='checkbox';follow.checked=true;follow.id='follow-current-task';
  const label=document.createElement('label');label.className='checkbox-field';label.append(follow,'跟随执行');selector.closest('label').after(label);
  selector.addEventListener('change',()=>{follow.checked=false;});
  document.addEventListener('click',event=>{if(event.target.closest('[data-job]'))follow.checked=false;},true);
  follow.onchange=()=>{renderTime();draw();};
  let followRun=null;
  window.followExecutionTask=()=>{
    if(!state.run)return;
    if(followRun!==state.run.id){followRun=state.run.id;follow.checked=true;}
    if(!follow.checked)return;
    const current=frame();if(!current)return;
    const jobs=state.run.report.jobs;
    const active=jobs.filter(job=>['running','assigned'].includes(current.jobs[job.job_id]?.status));
    const chosen=active.find(job=>job.job_id===state.selectedTaskId)||active[0]||
      jobs.find(job=>current.jobs[job.job_id]?.status==='pending');
    if(chosen){state.selectedTaskId=chosen.job_id;selector.value=chosen.job_id;}
  };
  let controlling=false;
  document.addEventListener('click',async event=>{
    if(!event.target.closest('#play')||!state.run?.live)return;
    event.preventDefault();event.stopImmediatePropagation();if(controlling)return;
    controlling=true;const button=document.getElementById('play');button.disabled=true;
    try{
      const paused=state.run.live.paused;
      const reply=await api('/api/live/'+encodeURIComponent(state.run.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:paused?'resume':'pause'})});
      state.run.live.paused=reply.paused;state.run.live.sim_s=reply.config.sim_s;state.t=reply.config.sim_s;
      button.textContent=reply.paused?'▶ 继续实时运行':'Ⅱ 暂停实时运行';
      document.getElementById('play-state').textContent=reply.paused?'实时计算已暂停，可查看或编辑':'实时运行';renderTime();draw();
    }catch(error){toast(error.message);}finally{controlling=false;button.disabled=false;}
  },true);

  const section=document.createElement('section');section.id='threat-editor';
  section.innerHTML='<h3>威胁区设置</h3><p id="threat-editor-note" class="form-note"></p><canvas id="threat-preview" width="650" height="260" style="width:100%;max-width:650px;border:1px solid #d5e2de"></canvas><div id="threat-rows"></div><button type="button" class="button" id="add-threat">＋ 新增威胁区</button>';
  const ticks=document.getElementById('editor-ticks');ticks.closest('label').before(section);
  const rows=section.querySelector('#threat-rows');let data=null,editable=false;
  const clone=value=>JSON.parse(JSON.stringify(value));
  function field(title,value,type='number'){
    const box=document.createElement('label');box.className='field';box.append(title);
    const input=document.createElement('input');input.type=type;input.value=value;input.disabled=!editable;
    if(type==='number'){input.step='any';input.required=true;}box.append(input);return {box,input};
  }
  function add(zone){
    const card=document.createElement('div');card.className='editor-row';
    const points=zone.area?.polygon||zone.area;const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
    const entries={id:field('编号',zone.constraint_id,'text'),intensity:field('强度',zone.intensity??1),x:field('中心 X',(x0+x1)/2),y:field('中心 Y',(y0+y1)/2),width:field('横向范围（米）',x1-x0),height:field('纵向范围（米）',y1-y0)};
    entries.intensity.input.min=0;entries.width.input.min=entries.height.input.min=.01;
    const scope=document.createElement('select');scope.disabled=!editable;
    for(const [value,text] of Object.entries({ground:'对地',air:'对空',all:'空地'}))scope.add(new Option(text,value));scope.value=zone.applies_to||'ground';
    const scopeLabel=document.createElement('label');scopeLabel.className='field';scopeLabel.append('作用对象',scope);
    const grid=document.createElement('div');grid.className='param-fields';
    Object.assign(grid.style,{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:'12px',marginBottom:'12px'});
    grid.append(...Object.values(entries).map(e=>e.box),scopeLabel);
    const remove=document.createElement('button');remove.type='button';remove.className='button';remove.textContent='删除威胁区';remove.disabled=!editable;remove.onclick=()=>{card.remove();paint();};
    card.append(grid,remove);card.read=()=>{
      const values={};for(const [key,item] of Object.entries(entries)){values[key]=key==='id'?item.input.value.trim():Number(item.input.value);if(key!=='id'&&(!item.input.value.trim()||!Number.isFinite(values[key])))throw Error('威胁区参数需要完整数字');}
      if(!values.id||values.width<=0||values.height<=0||values.intensity<0)throw Error('请填写威胁区编号、非负强度与正宽高');
      const unchanged=values.x===(x0+x1)/2&&values.y===(y0+y1)/2&&values.width===x1-x0&&values.height===y1-y0;
      const polygon=unchanged?clone(points):points.map(p=>[values.x+(p[0]-(x0+x1)/2)*values.width/(x1-x0),values.y+(p[1]-(y0+y1)/2)*values.height/(y1-y0)]);
      return {...clone(zone),constraint_id:values.id,type:'threat',intensity:values.intensity,applies_to:scope.value,area:zone.area?.polygon?{...clone(zone.area),polygon}:polygon};
    };card.addEventListener('input',paint);card.addEventListener('change',paint);rows.append(card);
  }
  function paint(){
    if(!data)return;const canvas=document.getElementById('threat-preview'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
    const bounds=data.formation.meta?.map_scene_bounds||data.formation.meta?.scene_bounds||[-300,-300,300,300];
    const project=p=>[10+(p[0]-bounds[0])/(bounds[2]-bounds[0])*(canvas.width-20),canvas.height-10-(p[1]-bounds[1])/(bounds[3]-bounds[1])*(canvas.height-20)];
    const polygon=(points,color)=>{if(!points?.length)return;ctx.beginPath();points.forEach((p,i)=>{const q=project(p);if(i)ctx.lineTo(...q);else ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.stroke();};
    ctx.strokeStyle='#aabbb6';for(const zone of data.formation.constraints||[])if(zone.type==='no_go')polygon(zone.area?.polygon||zone.area,'#e4eae7');
    ctx.strokeStyle='#bd7139';for(const row of rows.children)try{const zone=row.read();polygon(zone.area?.polygon||zone.area,'#db8e4955');}catch{}
  }
  document.getElementById('add-threat').onclick=()=>{let n=1;const ids=[...rows.children].map(row=>{try{return row.read().constraint_id;}catch{return '';}});while(ids.includes('THREAT-'+n))n++;add({constraint_id:'THREAT-'+n,type:'threat',applies_to:'ground',intensity:.7,area:{polygon:[[-20,-20],[20,-20],[20,20],[-20,20]]}});paint();};
  window.ThreatEditor={load(config,allowed){data=config;editable=allowed;rows.replaceChildren();for(const zone of config.formation.constraints||[])if(zone.type==='threat')add(zone);document.getElementById('add-threat').disabled=!editable;document.getElementById('threat-editor-note').textContent=editable?'支持新增、删除、移动和缩放；保存后参与本轮规划。此编辑配置按当前位置保存，不再次随机化。':'当前是运行状态，只读查看威胁区。要修改请在起始状态中选择“当前运行初始配置（另建运行）”。';paint();},get(){return [...rows.children].map(row=>row.read());}};
})();
