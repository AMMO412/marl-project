const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1150 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  // 1) 首页默认应是多任务融合运行，且没有"区域封控"独立导航项
  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const landing = await page.evaluate(() => ({
    run: state.run.id, tasks: state.run.report.jobs.length,
    nav: [...document.querySelectorAll('.nav')].map((b) => b.dataset.page),
    ckButtonHidden: document.querySelector('#open-containment').hidden,
    taskOptions: [...document.querySelectorAll('#task-select option')].map((o) => o.textContent),
  }));

  // 2) 新建区域封控演示
  await page.locator('#open-config').click();
  const defaultScenario = await page.inputValue('#config-scenario');
  await page.selectOption('#config-scenario', 'interop_containment');
  await page.locator('#submit-run').click();
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.report && state.run.report.jobs && state.run.report.jobs.some((j) => j.jtype === 'blockade') && state.run.replay && state.run.replay.containment && state.run.replay.containment.result); }
    catch (e) { return false; }
  }, null, { timeout: 240000 });
  await page.waitForTimeout(1500);
  const afterRun = await page.evaluate(() => ({
    page: state.page, run: state.run.id,
    ckButtonHidden: document.querySelector('#open-containment').hidden,
    verdict: state.run.replay.containment.result.verdict,
    hasPlan: !!(state.run.plan && state.run.plan.assignments),
    planPaths: state.run.plan ? Math.max(...state.run.plan.assignments.map((a) => a.path.length)) : 0,
  }));
  await page.screenshot({ path: path.resolve('.work/containment_20261031/overview-after-run.png'), fullPage: false });

  // 3) 从总览进入区域封控视图
  await page.locator('#open-containment').click();
  await page.waitForTimeout(900);
  const inCk = await page.evaluate(() => ({
    page: state.page,
    camAll: document.querySelector('#ck-cam-all').classList.contains('active'),
    ticker: document.querySelector('#ck-ticker').textContent,
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
  }));
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 0; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/full-chain-t0.png') });
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 14; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/full-chain-t14.png') });
  // 4) 回到封控区视图
  await page.locator('#ck-cam-area').click();
  await page.waitForTimeout(300);
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 56; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/area-56.png') });
  await page.locator('#ck-cam-all').click();
  await page.waitForTimeout(300);
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 60; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/full-chain-t60.png') });

  console.log(JSON.stringify({ landing, defaultScenario, afterRun, inCk, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
