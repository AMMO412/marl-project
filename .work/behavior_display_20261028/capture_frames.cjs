const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const {pathToFileURL}=require('url');
const fs=require('fs');
(async()=>{
 const folder='D:/Desktop/MARL项目/.work/behavior_display_20261028/frames';fs.mkdirSync(folder,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1300,height:850}});
 await page.goto(pathToFileURL('D:/Desktop/MARL项目/planning_middle_demo/outputs/behavior_20261028_verify/behavior_demo.html').href);
 for(let t=154;t<=175;t++){
  await page.evaluate(t=>seekTo(t),t);
  await page.locator('.stage').screenshot({path:folder+'/'+String(t).padStart(3,'0')+'.png'});
 }
 await browser.close();console.log('Captured 22 existing-record frames.');
})().catch(e=>{console.error(e);process.exit(1)});
