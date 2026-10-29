const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const {pathToFileURL}=require('url');const fs=require('fs');const assert=require('assert/strict');
(async()=>{
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
const root=process.cwd(),base=root+'/planning_middle_demo/outputs/task_motion_schematics_20261027/';
const seek=async t=>page.locator('#timeline').evaluate((el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}));},String(t));
const position=async id=>page.locator('#'+id).evaluate(el=>{const m=el.transform.baseVal.consolidate().matrix;return [m.e,m.f];});
const near=(a,b,tolerance=.12)=>assert.ok(Math.hypot(a[0]-b[0],a[1]-b[1])<tolerance,JSON.stringify({a,b}));
await page.goto(pathToFileURL(base+'index.html').href);await page.locator('#play').click();
assert.equal(await page.locator('[role=tab]').count(),5);
assert.ok((await page.locator('.controls').boundingBox()).y<450,'controls appear above illustration');
const samples=[];
for(const key of ['patrol','boundary','stages','exploration','handover']){
 await page.locator('#tab-'+key).click();
 for(const t of [0,.1,1,3,6,10,11.99,12,13.99,14,16,18,18.99,19,20,24,27,30,35.99,36]){
  await seek(t);assert.equal(await page.locator('#clock').innerText(),t.toFixed(1));
  const current=await page.locator('[data-actor]').evaluateAll(els=>els.map(el=>({name:el.dataset.actor,transform:el.getAttribute('transform')})));
  for(const x of current)assert.ok(!/NaN|Infinity/.test(x.transform));
  samples.push({mode:key,t,actors:current});
 }
}
// 1: loops return to the same position; passed checkpoint marks accumulate.
await page.locator('#tab-patrol').click();await seek(0);const startA=await position('patrol-a');const startB=await position('patrol-b');assert.notDeepEqual(startA,startB);
await seek(12);near(await position('patrol-a'),startA);assert.equal(await page.locator('#visit-1 circle').getAttribute('fill'),'#f39127');
await seek(25);assert.equal(await page.locator('#visit-2 circle').getAttribute('fill'),'#f39127');
// 2: branch starts/ends exactly on the pre-authored boundary curve.
await page.locator('#tab-boundary').click();await seek(10);const departure=await position('boundary-b');
const expectedStart=await page.locator('#boundary-path').evaluate(el=>{const p=el.getPointAtLength(el.getTotalLength()*.28);return [p.x,p.y];});near(departure,expectedStart);
await seek(18);const mid=await position('boundary-b');assert.ok(mid[0]>800,'pre-authored branch is visible beyond the region');
await seek(24);const expectedEnd=await page.locator('#boundary-path').evaluate(el=>{const p=el.getPointAtLength(el.getTotalLength()*.5);return [p.x,p.y];});near(await position('boundary-b'),expectedEnd);
// 3: actor movement ends before staged icons/confirmation.
await page.locator('#tab-stages').click();await seek(12);const arrival=await position('stage-a');await seek(22);near(await position('stage-a'),arrival);assert.equal(await page.locator('#stage-confirm').getAttribute('opacity'),'0.000');
await seek(30);assert.equal(await page.locator('#stage-confirm').getAttribute('opacity'),'1.000');assert.match(await page.locator('#phase-title').innerText(),/确认/);
// 4: reveal grows, paths pass through their own door gaps, map lights at the end.
await page.locator('#tab-exploration').click();await seek(0);assert.equal(await page.locator('#room-reveal-0').getAttribute('height'),'0');
await seek(12);assert.ok(Number(await page.locator('#room-reveal-0').getAttribute('height'))>0);
const doors=await page.evaluate(()=>['a','b','c'].map((key,i)=>{const p=document.getElementById('explore-path-'+key),length=p.getTotalLength();let worst=0;for(let n=0;n<=500;n++){const v=p.getPointAtLength(length*n/500);if(Math.abs(v.y-307)<7)worst=Math.max(worst,Math.abs(v.x-[213,503,793][i]));}return worst;}));assert.ok(doors.every(x=>x<25));
await seek(36);assert.equal(await page.locator('#room-reveal-2').getAttribute('height'),'225');assert.equal(await page.locator('#sharing-lines').getAttribute('opacity'),'1.000');assert.equal(await page.locator('#map-cell-8').getAttribute('fill'),'#8651cb');
await page.locator('#canvas').screenshot({path:base+'preview.png'});
// 5: A stays; B leaves only after C arrives; C is continuous at the join.
await page.locator('#tab-handover').click();await seek(0);const a0=await position('hold-a'),b0=await position('hold-b');
await seek(13.95);const cBefore=await position('hold-c');await seek(14);near(await position('hold-c'),cBefore,1);
await seek(18);near(await position('hold-a'),a0);near(await position('hold-b'),b0);assert.match(await page.locator('#phase-title').innerText(),/交接/);
await seek(30);assert.notDeepEqual(await position('hold-b'),b0);near(await position('hold-a'),a0);const c30=await position('hold-c');await seek(36);near(await position('hold-c'),c30);
// controls, reference comparison, modal and keyboard.
await page.locator('#show-trails').uncheck();assert.equal(await page.locator('#incoming-trail').getAttribute('points'),'');await page.locator('#show-trails').check();
await page.locator('#show-labels').uncheck();assert.equal(await page.locator('.actor-label').first().getAttribute('visibility'),'hidden');await page.locator('#show-labels').check();
await page.locator('#show-reference').check();assert.equal(await page.locator('#reference-comparison').isVisible(),true);await page.locator('#reference-button').click();assert.equal(await page.locator('#reference-dialog').evaluate(el=>el.open),true);await page.keyboard.press('Escape');
await seek(10);await page.locator('#forward').click();assert.equal(await page.locator('#clock').innerText(),'11.0');await page.locator('#back').click();assert.equal(await page.locator('#clock').innerText(),'10.0');
await page.locator('#loop').uncheck();await seek(35.8);await page.locator('#play').click();await page.waitForFunction(()=>document.getElementById('clock').textContent==='36.0'&&document.getElementById('play').textContent.includes('播放'));assert.match(await page.locator('#play').innerText(),/播放/);
await page.locator('#loop').check();await seek(35.8);await page.locator('#play').click();await page.waitForFunction(()=>Number(document.getElementById('clock').textContent)<1);await page.locator('#play').click();
await page.locator('#restart').click();await page.waitForFunction(()=>Number(document.getElementById('clock').textContent)>.1&&Number(document.getElementById('clock').textContent)<2);await page.locator('#play').click();const paused=await page.locator('#clock').innerText();await page.waitForTimeout(100);assert.equal(await page.locator('#clock').innerText(),paused);
await page.locator('h1').click();await page.keyboard.press('1');assert.equal(await page.locator('#tab-patrol').getAttribute('aria-selected'),'true');await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#clock').innerText(),'1.0');
await page.locator('#tab-patrol').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#tab-boundary').getAttribute('aria-selected'),'true');
// mobile controls and reference checkbox remain available without horizontal overflow.
await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.locator('#tab-exploration').click();await seek(25);await page.screenshot({path:'.work/task_schematics_20261027/mobile.png',fullPage:true});
// Single copied HTML remains functional; direct hash selects the right mode.
fs.copyFileSync(base+'index.html','.work/task_schematics_20261027/standalone.html');
await page.goto(pathToFileURL(root+'/.work/task_schematics_20261027/standalone.html').href+'#handover');assert.equal(await page.locator('#tab-handover').getAttribute('aria-selected'),'true');assert.equal(await page.locator('#reference-thumb').evaluate(el=>el.complete&&el.naturalWidth>0),true);
assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
fs.writeFileSync('.work/task_schematics_20261027/verification.json',JSON.stringify({passed:true,modes:5,keyframeSamples:samples.length,checks:['patrol repeat','boundary fixed branch continuity','stages stop/execution/confirmation','exploration door paths/reveal/map','handover persistent/arrival/overlap/departure','controls','loop/end','references','mobile','standalone/hash'],errors,externalRequests:requests,samples},null,2));
console.log('PASS: five modes, '+samples.length+' keyframes, expected stage transitions, controls, references, mobile and offline standalone');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
