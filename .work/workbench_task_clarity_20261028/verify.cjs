const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766/?source=behavior_20261028_verify&task=J4');await page.waitForFunction(()=>typeof state!=='undefined'&&state.taskWindow?.jobId==='J4');
 assert.strictEqual(await page.evaluate(()=>state.run.report.recording),true);assert.strictEqual(await page.evaluate(()=>taskDetailModel('J4').collapsed),false);
 const checks=await page.evaluate(async()=>{
  const rows=[],failures=[];
  for(const id of ['behavior_20261028_verify',state.catalog.default_run]){
   await loadRun(id);
   for(const jid of ['J1','J2','J3','J4','J5','J6']){
    openTask(jid,false);const views=['J4','J5'].includes(jid)?['process','spatial']:['spatial'];
    for(const view of views){state.taskView=view;renderTheater();let count=0;
     for(let t=state.taskWindow.start;t<=state.taskWindow.end;t++){setTime(t);draw();count++;
      if(state.scene.relevantWorkers!==frame().jobs[jid].pids.length)failures.push([id,jid,t,'member count']);
      if(currentTaskRoutes(jid).some(r=>r.recordedAt>state.t))failures.push([id,jid,t,'future route']);
      if(view==='process'&&jid==='J4'&&state.scene.memberTracks.length!==4)failures.push([id,jid,t,'missing track']);
      if(view==='spatial'){const a=state.scene.labels;for(let i=0;i<a.length;i++)for(let j=i+1;j<a.length;j++)if(a[i].x<a[j].x+a[j].w&&a[i].x+a[i].w>a[j].x&&a[i].y<a[j].y+a[j].h&&a[i].y+a[i].h>a[j].y)failures.push([id,jid,t,'overlap']);}
     }rows.push({id,jid,view,count});
    }
   }
  }return {rows,failures};
 });assert.deepStrictEqual(checks.failures,[]);
 await page.evaluate(async()=>{await loadRun('behavior_20261028_verify');openTask('J4',false);});
 const hit=await page.evaluate(()=>state.hits.find(h=>h.type==='chapter'&&h.t===354)),box=await page.locator('#scene').boundingBox();
 await page.mouse.click(box.x+hit.x,box.y+hit.y);assert.strictEqual(await page.evaluate(()=>state.t),354);
 await page.locator('[data-task-view="spatial"]').click();const sameTime=await page.evaluate(()=>state.t);assert.strictEqual(sameTime,354);
 const camera=await page.evaluate(()=>{setTime(365);const a=[...bounds];setTime(366);return {a,b:[...bounds]};});assert.deepStrictEqual(camera.a,camera.b);
 await page.evaluate(()=>setTime(365));await page.screenshot({path:'.work/workbench_task_clarity_20261028/final-assault-spatial.png'});
 await page.locator('[data-task-view="process"]').click();await page.screenshot({path:'.work/workbench_task_clarity_20261028/final-assault-process.png'});
 await page.selectOption('#theater-task','J5');await page.evaluate(()=>{setPlaying(false);setTime(156);});await page.screenshot({path:'.work/workbench_task_clarity_20261028/final-hold-process.png'});
 await page.locator('#hold-chapters [data-task-time="158"]').click();assert.strictEqual(await page.evaluate(()=>workbenchHold('J5').primary),'rover_31');
 await page.selectOption('#task-source',await page.evaluate(()=>state.catalog.default_run));await page.waitForFunction(()=>!state.run.report.recording);await page.evaluate(()=>{setPlaying(false);setTime(60);});assert.strictEqual(await page.evaluate(()=>workbenchHold('J5').primary),'rover_42');
 await page.selectOption('#theater-task','J4');await page.evaluate(()=>{setPlaying(false);setTime(112);});assert.strictEqual(await page.evaluate(()=>taskDetailModel('J4').collapsed),true);
 const snapshots=[];for(const size of [{width:1366,height:900},{width:390,height:844}]){await page.setViewportSize(size);await page.waitForTimeout(100);snapshots.push({size,canvas:await page.locator('#scene').boundingBox()});}
 await page.keyboard.press('Escape');assert.strictEqual(await page.locator('#scene').count(),1);assert(!(await page.locator('#task-theater').evaluate(el=>el.open)));
 assert.deepStrictEqual(errors,[]);const proof={errors,checks,snapshots,chapterClick:true,sourceSwitch:true,sameClock:true};fs.writeFileSync('.work/workbench_task_clarity_20261028/verification.json',JSON.stringify(proof,null,2));console.log(JSON.stringify({errors,frames:checks.rows.reduce((n,r)=>n+r.count,0),checks:checks.rows.length,snapshots}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
