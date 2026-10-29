const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766');await page.waitForFunction(()=>typeof state!=='undefined'&&state.run?.report.behavior_details);
 const rows=[];
 for(const [jid,t]of [['J5',60],['J5',64],['J5',80],['J3',130],['J3',160],['J2',1]]){
  await page.evaluate(([j,t])=>{openTask(j,false);setTime(t);draw();},[jid,t]);await page.waitForTimeout(180);
  rows.push(await page.evaluate(()=>({t:state.t,job:state.taskWindow.jobId,roles:document.querySelector('#workbench-hold-status').textContent,route:document.querySelector('#workbench-route-status').textContent,scene:state.scene,canvas:document.querySelector('#scene').getBoundingClientRect().toJSON()})));
  await page.screenshot({path:`.work/behavior_visual_refine_20261028/workbench-${jid}-${t}.png`});
 }
 fs.writeFileSync('.work/behavior_visual_refine_20261028/workbench-qa-first.json',JSON.stringify({errors,rows},null,2));
 console.log(JSON.stringify({errors,rows:rows.map(r=>({t:r.t,job:r.job,roles:r.job==='J5'?r.roles:undefined,route:r.route,canvas:[r.canvas.width,r.canvas.height],scene:r.scene}))}));
 await browser.close();if(errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
