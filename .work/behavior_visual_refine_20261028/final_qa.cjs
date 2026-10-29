const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766');await page.waitForFunction(()=>typeof state!=='undefined'&&state.run?.report.behavior_details);
 const run=await page.evaluate(()=>state.run.id);
 await page.selectOption('#task-select','J5');await page.evaluate(()=>setPlaying(false));assert(await page.locator('#task-theater').evaluate(el=>el.open));
 const sweep=await page.evaluate(()=>{
  const rows=[],failures=[];
  for(const job of state.run.report.jobs){openTask(job.job_id,false);let count=0;
   for(let t=state.taskWindow.start;t<=state.taskWindow.end;t++){setTime(t);draw();count++;
    const routes=currentTaskRoutes(job.job_id);if(routes.some(r=>r.recordedAt>state.t))failures.push([job.job_id,t,'future path']);
    if(state.scene.relevantWorkers>frame().jobs[job.job_id].pids.length)failures.push([job.job_id,t,'other members']);
    const labels=state.scene.labels;for(let i=0;i<labels.length;i++)for(let k=i+1;k<labels.length;k++){const a=labels[i],b=labels[k];if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)failures.push([job.job_id,t,'label overlap']);}
    if(job.jtype==='hold'&&frame().jobs[job.job_id].behavior.detail?.debug.primary!==workbenchHold(job.job_id).primary)failures.push([job.job_id,t,'role mismatch']);
   }if(currentTaskRoutes(job.job_id).length)failures.push([job.job_id,'completed path still active']);rows.push({job:job.job_id,frames:count});
  }return {rows,failures};
 });assert.deepStrictEqual(sweep.failures,[]);
 await page.evaluate(()=>{openTask('J5',false);setTime(60);});
 assert((await page.locator('#workbench-hold-status').textContent()).includes('#42 交给 #01'));
 await page.screenshot({path:'.work/behavior_visual_refine_20261028/final-hold.png'});
 await page.locator('#hold-chapters [data-task-time="64"]').click();assert.strictEqual(await page.evaluate(()=>workbenchHold('J5').primary),'rover_01');
 await page.evaluate(()=>{openTask('J3',false);setTime(130);});await page.screenshot({path:'.work/behavior_visual_refine_20261028/final-recon.png'});
 await page.evaluate(()=>{openTask('J4',false);setTime(116);});
 assert((await page.locator('#workbench-route-status').textContent()).includes('原直线被挡'));
 await page.locator('.map-options summary').click();await page.check('#show-blocked-line');await page.locator('.map-options summary').click();await page.screenshot({path:'.work/behavior_visual_refine_20261028/final-avoidance.png'});
 await page.locator('#workbench-route-status [data-task-time="72"]').first().click();assert.strictEqual(await page.evaluate(()=>state.t),72);assert.strictEqual(await page.evaluate(()=>state.taskWindow.start),72);
 await page.setViewportSize({width:1366,height:900});await page.evaluate(()=>{openTask('J5',false);setTime(60);});
 const small=await page.locator('#scene').boundingBox();assert(small.width>900&&small.height>=330);
 await page.keyboard.press('Escape');assert.strictEqual(await page.locator('#scene').count(),1);assert(await page.locator('#scene').isVisible());
 await page.evaluate(async()=>{await loadRun('workbench_behavior_20261028');openTask('J5',false);setTime(60);});
 assert((await page.locator('#workbench-route-status').textContent()).includes('旧日志未记录'));
 assert.strictEqual(await page.locator('#detailed-behavior').count(),0);
 const result={run,errors,sweep,smallCanvas:small,oldRecordCompatible:true,chapterAndRouteSeekVerified:true};
 fs.writeFileSync('.work/behavior_visual_refine_20261028/final-qa.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 await browser.close();assert.deepStrictEqual(errors,[]);
})().catch(e=>{console.error(e);process.exit(1)});
