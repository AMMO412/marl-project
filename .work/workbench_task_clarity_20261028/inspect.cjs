const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const fs=require('fs');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8766/?source=behavior_20261028_verify&task=J4');await page.waitForFunction(()=>typeof state!=='undefined'&&state.taskWindow?.jobId==='J4');
for(const [jid,t]of [['J4',340],['J4',365],['J4',388],['J5',156],['J5',169]]){await page.evaluate(([j,t])=>{openTask(j,false);setTime(t);},[jid,t]);await page.screenshot({path:`.work/workbench_task_clarity_20261028/${jid}-${t}.png`});}
await page.locator('[data-task-view="spatial"]').click();await page.screenshot({path:'.work/workbench_task_clarity_20261028/hold-spatial.png'});
await page.evaluate(()=>{openTask('J4',false);setTime(365);state.taskView='spatial';renderTheater();draw();});await page.screenshot({path:'.work/workbench_task_clarity_20261028/assault-spatial.png'});
console.log(JSON.stringify({errors,scene:await page.evaluate(()=>state.scene)}));await browser.close();if(errors.length)process.exitCode=1;})().catch(e=>{console.error(e);process.exit(1)});
