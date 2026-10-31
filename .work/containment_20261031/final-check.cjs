const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  // 默认页：多任务运行，无封控页签
  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const landing = await page.evaluate(() => ({
    run: state.run.id, tasks: state.run.report.jobs.length,
    tabsHidden: document.querySelector('#overview-tabs').hidden,
    ckView: state.ckView,
    sourceSelect: !!document.querySelector('#task-source'),
  }));

  // 区域封控运行：页签出现并默认打开封控视图
  await page.goto('http://127.0.0.1:8899/?source=workbench_20261031_161356_779332', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.waitForTimeout(800);
  const ck = await page.evaluate(() => ({
    run: state.run.id, ckView: state.ckView,
    tabsHidden: document.querySelector('#overview-tabs').hidden,
    tabs: [...document.querySelectorAll('#overview-tabs .ov-tab')].map((b) => b.textContent + (b.classList.contains('active') ? '*' : '')),
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
    nav: [...document.querySelectorAll('.nav')].map((b) => b.dataset.page),
    sourceSelect: !!document.querySelector('#task-source'),
  }));

  // 深链 ?page=containment
  await page.goto('http://127.0.0.1:8899/?page=containment&source=workbench_20261031_161356_779332', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.waitForTimeout(700);
  const deep = await page.evaluate(() => ({ ckView: state.ckView, page: state.page }));

  console.log(JSON.stringify({ landing, ck, deep, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
