const {chromium}=require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const {pathToFileURL}=require('url');
const fs=require('fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1500,height:1050}});
  const url=pathToFileURL('D:/Desktop/MARL项目/planning_middle_demo/outputs/behavior_20261028_verify/behavior_demo.html').href;
  await page.goto(url+'?job=J5&t=156');
  await page.screenshot({path:'D:/Desktop/MARL项目/.work/behavior_display_20261028/latest-hold.png',fullPage:true});
  await page.goto(url+'?job=J3&t=220');
  await page.screenshot({path:'D:/Desktop/MARL项目/.work/behavior_display_20261028/latest-recon.png',fullPage:true});
  console.log(JSON.stringify(await page.evaluate(()=>({width:innerWidth,total:DATA.total,jobs:DATA.jobs.length}))))
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
