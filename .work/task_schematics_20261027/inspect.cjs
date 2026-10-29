const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const {pathToFileURL}=require('url');const fs=require('fs');const assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1190},deviceScaleFactor:1});const errors=[],network=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
 const url=pathToFileURL(process.cwd()+'/planning_middle_demo/outputs/task_motion_schematics_20261027/index.html').href;
 await page.goto(url);await page.waitForTimeout(200);await page.locator('#play').click();
 const seek=async t=>page.locator('#timeline').evaluate((el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}));},String(t));
 const modes=['patrol','boundary','stages','exploration','handover'];
 for(const mode of modes){
   await page.locator('#tab-'+mode).click();
   await seek(0);const first=await page.locator('[data-actor]').evaluateAll(els=>els.map(el=>el.getAttribute('transform')));
   await seek(18);const middle=await page.locator('[data-actor]').evaluateAll(els=>els.map(el=>el.getAttribute('transform')));
   assert.notDeepEqual(first,middle,mode+' actors should move');
   assert.equal(await page.locator('#tab-'+mode).getAttribute('aria-selected'),'true');
   assert.equal(await page.locator('#reference-thumb').evaluate(el=>el.complete&&el.naturalWidth>0),true,mode+' reference should decode');
   await page.screenshot({path:'.work/task_schematics_20261027/'+mode+'.png',fullPage:true});
   await seek(36);assert.equal(await page.locator('#clock').innerText(),'36.0');
   console.log(mode+': '+await page.locator('#phase-title').innerText());
 }
 assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
 console.log('PASS first render, five modes, reference images, no external network or JS errors');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
