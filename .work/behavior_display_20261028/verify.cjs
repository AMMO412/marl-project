const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const fs=require('fs'),assert=require('assert/strict'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const root='D:/Desktop/MARL项目',qa=root+'/.work/behavior_display_20261028';
const output=root+'/planning_middle_demo/outputs/behavior_20261028_verify';
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').toUpperCase();
(async()=>{
 const recorded=JSON.parse(fs.readFileSync(output+'/behavior_trace.json','utf8'));
 const baseline=JSON.parse(fs.readFileSync(qa+'/source_hashes.latest.json','utf8').replace(/^\uFEFF/,''));
 for(const item of baseline)assert.equal(sha(item.Path),item.Hash,'Source file changed: '+item.Path);
 const before=fs.readFileSync(qa+'/before_latest/behavior_demo.template.html','utf8');
 const after=fs.readFileSync(root+'/planning_middle_demo/behavior_demo.html','utf8');
 const reconSource=s=>s.slice(s.indexOf('function drawRecon('),s.indexOf('function drawAssault('));
 assert.equal(reconSource(before),reconSource(after),'Recon renderer must stay unchanged');
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1050}}),errors=[],remote=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))remote.push(r.url())});
 const url=pathToFileURL(output+'/behavior_demo.html').href;
 await page.goto(url);assert.equal(await page.evaluate(()=>currentJob().type),'hold');
 assert.equal(await page.evaluate(()=>playing),false);
 assert.deepEqual(await page.evaluate(()=>DATA),recorded,'Embedded data must match original recording');
 const samples=await page.evaluate(()=>{
  const job=currentJob(),cameras={},results=[];
  for(const sample of job.samples){
   seekTo(sample.t);
   const state=holdState(job,frameOf(job));
   const expected=job.events.filter(e=>e.kind==='handover_complete'&&e.t<=T).length;
   if(Number(document.querySelector('#hold-count-now').textContent)!==expected)throw Error('Incorrect count '+sample.t);
   for(const box of view.labels){
    const expectedPoint=project(frameOf(job).agents[box.pid]);
    if(Math.abs(box.point[0]-expectedPoint[0])>1e-7||Math.abs(box.point[1]-expectedPoint[1])>1e-7)throw Error('Moved recorded position');
    if(box.x<0||box.x+box.width>canvas.clientWidth||box.y<0||box.y+box.height>canvas.clientHeight)throw Error('Clipped label '+sample.t);
   }
   const [a,b]=view.labels;
   if(a&&b&&a.x<b.x+b.width&&b.x<a.x+a.width&&a.y<b.y+b.height&&b.y<a.y+a.height)throw Error('Overlapping labels '+sample.t);
   const camera=JSON.stringify(view.bounds);if(cameras[chapter]&&cameras[chapter]!==camera)throw Error('Camera drift');cameras[chapter]=camera;
   const svg=document.querySelector('#role-timeline'),width=svg.viewBox.baseVal.width,marker=47+(T-job.t0)/(job.t1-job.t0)*(width-60);
   for(const bar of svg.querySelectorAll('rect:not([fill="#f1f5f9"])'))if(Number(bar.getAttribute('x'))+Number(bar.getAttribute('width'))>marker+.2)throw Error('Future role exposed');
   results.push({t:T,count:expected,primary:state.primary});
  }
  return results;
 });
 for(const [time,count,primary]of [[154,0,'rover_01'],[158,1,'rover_31'],[170,1,'rover_31'],[174,2,'rover_01']]){
  await page.evaluate(t=>seekTo(t),time);
  assert.equal(await page.locator('#hold-count-now').textContent(),String(count));
  assert.equal(await page.evaluate(()=>holdState(currentJob(),frameOf(currentJob())).primary),primary);
 }
 await page.evaluate(()=>seekTo(156));
 await page.screenshot({path:output+'/preview_hold.png',fullPage:true});
 await page.evaluate(()=>seekTo(162));
 await page.screenshot({path:qa+'/after-first-handover.png',fullPage:true});
 await page.evaluate(()=>seekTo(171));
 await page.screenshot({path:qa+'/second-handover.png',fullPage:true});
 await page.locator('#hold-track [data-jump="158"]').click();assert.equal(await page.evaluate(()=>T),158);
 await page.locator('#chapter').selectOption('approach');await page.locator('#play').click();
 await page.locator('#hold-track [data-jump="170"]').click();assert.equal(await page.locator('#chapter').inputValue(),'action');assert.equal(await page.evaluate(()=>T),170);
 await page.locator('#seek').evaluate(el=>{el.value=0;el.dispatchEvent(new Event('input'))});assert.equal(await page.evaluate(()=>T),154);
 await page.locator('#seek').evaluate(el=>{el.value=1;el.dispatchEvent(new Event('input'))});assert.equal(await page.evaluate(()=>T),175);
 await page.locator('#restart').click();assert.equal(await page.evaluate(()=>playing),true);await page.locator('#play').click();
 await page.evaluate(()=>{T=currentJob().t1-.02;playing=true});await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>playing),false);assert.equal(await page.evaluate(()=>T),175);
 await page.evaluate(()=>seekTo(156));
 const timeline=await page.locator('#role-timeline').boundingBox();await page.mouse.click(timeline.x+timeline.width*.53,timeline.y+28);assert.equal(await page.evaluate(()=>playing),false);
 let tasks=0;
 for(const job of recorded.jobs){
  await page.locator(`.tab[data-job="${job.job_id}"]`).click();await page.evaluate(()=>{playing=false;playBtn.textContent='播放'});
  assert.equal(await page.evaluate(()=>currentJob().job_id),job.job_id);
  assert.equal(await page.locator('#role-board').isVisible(),job.type==='hold');
  const frame=await page.evaluate(()=>({t:T,phase:frameOf(currentJob()).phase}));assert(frame.phase);tasks++;
 }
 await page.goto(url+'?job=J3&t=220');assert.equal(await page.evaluate(()=>currentJob().type),'recon');await page.screenshot({path:qa+'/recon-preserved.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(url+'?job=J5&t=171');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 const mobileLabels=await page.evaluate(()=>view.labels.map(b=>({x:b.x,y:b.y,width:b.width,height:b.height,canvasWidth:canvas.clientWidth,canvasHeight:canvas.clientHeight})));
 for(const b of mobileLabels){assert(b.x>=0&&b.x+b.width<=b.canvasWidth);assert(b.y>=0&&b.y+b.height<=b.canvasHeight)}
 await page.screenshot({path:qa+'/mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);assert.deepEqual(remote,[]);
 for(const item of baseline)assert.equal(sha(item.Path),item.Hash);
 const result={passed:true,holdSamplesChecked:samples.length,tasksChecked:tasks,recordingUnchanged:true,behaviorSourcesUnchanged:true,reconRendererUnchanged:true,checks:['exact recorded positions','labels inside canvas and separated','camera fixed per chapter','event-based current handover count','no future role bars','task isolation','chapter switching on jumps','play/pause/restart/end','seek and timeline clicks','390px viewport','offline/no remote requests'],errors};
 fs.writeFileSync(qa+'/verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
