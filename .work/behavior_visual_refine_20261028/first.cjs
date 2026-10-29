const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const {pathToFileURL}=require('url');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});const page=await browser.newPage({viewport:{width:1600,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const url=pathToFileURL(process.cwd()+'/planning_middle_demo/outputs/behavior_20261028_verify/behavior_demo.html').href;
await page.goto(url+'?job=J5&t=156');await page.screenshot({path:'.work/behavior_visual_refine_20261028/hold-first.png',fullPage:true});console.log(JSON.stringify({errors,hold:await page.locator('#hold-status').textContent(),route:await page.locator('#route-status').textContent()}));
await page.goto(url+'?job=J3&t=230');await page.screenshot({path:'.work/behavior_visual_refine_20261028/recon-first.png',fullPage:true});await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
