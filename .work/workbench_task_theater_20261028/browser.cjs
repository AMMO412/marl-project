const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const assert=require('assert/strict'),fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766');await page.waitForFunction(()=>document.querySelector('#stat-done').textContent!=='—');
 assert.equal(await page.locator('#track-worker').count(),0);assert.equal(await page.locator('#show-roads').count(),0);assert.equal(await page.locator('#task-select option').count(),7);
 const data=await page.request.get('http://127.0.0.1:8766/api/runs/workbench_behavior_20261028').then(r=>r.json());let frames=0;const sizes=[];
 async function seek(t){await page.locator('#scrubber').evaluate((e,t)=>{e.value=t;e.dispatchEvent(new Event('input',{bubbles:true}))},t)}
 for(const [i,jid]of ['J1','J2','J3','J4','J5','J6'].entries()){
  if(i===0)await page.locator('#task-select').selectOption(jid);else await page.locator('#theater-task').selectOption(jid);
  await page.waitForFunction(()=>document.querySelector('#task-theater').open);assert.equal(await page.evaluate(()=>state.taskWindow.jobId),jid);
  assert.equal(await page.evaluate(()=>state.playing),true);await page.locator('#play').click();
  const range=await page.evaluate(()=>({...state.taskWindow})),structure=data.replay.behaviors.find(b=>b.job_id===jid);
  assert.equal(range.start,structure.sim_s);assert.equal(range.end,data.trace.find(e=>e.kind==='job_succeeded'&&e.job_id===jid).sim_s);
  const size=await page.locator('#scene').boundingBox();assert(size.width>1000&&size.height>500);sizes.push({jid,width:size.width,height:size.height});
  assert.equal(await page.locator('canvas').count(),1);
  const assigned=data.trace.find(e=>e.kind==='job_dispatched'&&e.job_id===jid).pids;
  for(let t=range.start;t<=range.end;t++){
   await seek(t);assert.equal(await page.evaluate(()=>state.scene.jobId),jid);assert.equal(await page.evaluate(()=>state.scene.structureCount),1);
   assert.equal(Number(await page.locator('#clock').textContent()),t-range.start);
   const visible=await page.evaluate(()=>state.hits.filter(h=>h.type==='worker').map(h=>h.id));assert(visible.every(pid=>assigned.includes(pid)));frames++;
  }
  assert.equal(await page.locator('#theater-details .detail-phase').textContent(),'已完成');await page.locator('#play').click();
  assert((await page.evaluate(()=>state.t))<range.end);await page.locator('#play').click();
  if(jid==='J1'){await seek(26);await page.locator('#task-theater').screenshot({path:'outputs/工作台展示_20261028/task-patrol-large.png'});}
  if(jid==='J3'){await seek(150);assert.match(await page.locator('#theater-details').textContent(),/覆盖/);await page.locator('#task-theater').screenshot({path:'outputs/工作台展示_20261028/task-exploration-large.png'});}
  if(jid==='J5'){await seek(64);assert.match(await page.locator('#theater-details').textContent(),/已接替 1 次/);assert.equal(await page.locator('.theater-member').count(),2);await page.locator('#task-theater').screenshot({path:'outputs/工作台展示_20261028/task-handover-large.png'});}
 }
 await page.locator('#task-restart').click();const all=await page.evaluate(()=>({...state.taskWindow}));assert.equal(all.start,all.dispatch);
 await page.locator('#play').click();await page.locator('#action-start').click();assert.equal(await page.evaluate(()=>state.taskWindow.start),all.execution);await page.locator('#play').click();
 await page.locator('#close-theater').click();assert.equal(await page.locator('#task-theater').isVisible(),false);assert.equal(await page.locator('.overview-grid>.map-card').count(),1);assert.equal(await page.locator('canvas').count(),1);assert.equal(await page.locator('#scrubber').getAttribute('min'),'0');
 await seek(187);await page.locator('#task-list [data-job="J1"]').click();assert((await page.evaluate(()=>state.t))<10);await page.locator('#play').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#task-theater').isVisible(),false);
 await page.setViewportSize({width:390,height:844});await page.locator('#task-select').selectOption('J5');await page.locator('#play').click();await seek(64);
 assert.equal(await page.evaluate(()=>document.querySelector('#task-theater').scrollWidth>document.querySelector('#task-theater').clientWidth),false);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.locator('#task-theater').screenshot({path:'.work/workbench_task_theater_20261028/mobile.png'});await page.locator('#close-theater').click();
 assert.deepEqual(errors,[]);
 const result={passed:true,taskFramesChecked:frames,tasks:6,sizes,checks:['background removed','task chooser','direct autoplay','large task-only stage','task range and relative clock','no unrelated actors','final geometry retained','replay completed tasks','task/action start buttons','single canvas restoration','Escape','mobile layout'],errors};
 fs.writeFileSync('.work/workbench_task_theater_20261028/browser-result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
