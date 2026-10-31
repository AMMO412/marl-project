const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const landing = await page.evaluate(() => ({
    run: state.run.id, tasks: state.run.report.jobs.length,
    ckTabHidden: document.querySelector('#overview-tabs').hidden,
    sourceSelect: !!document.querySelector('#task-source'),
  }));

  await page.locator('#open-config').click();
  await page.selectOption('#config-scenario', 'interop_containment');
  await page.locator('#submit-run').click();
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment && state.run.replay.containment.result); }
    catch (e) { return false; }
  }, null, { timeout: 240000 });
  await page.waitForTimeout(1500);
  const afterRun = await page.evaluate(() => ({
    run: state.run.id, page: state.page, ckView: state.ckView,
    mapHidden: document.querySelector('#overview-map-view').hidden,
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
  }));

  // 封控视图（自动打开）：T+70 覆盖"拦阻完成 + 巡视中"
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 70; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('#page-overview').screenshot({ path: path.resolve('.work/containment_20261031/v3-ck-view.png') });

  // 回到全局分配看机动与任务位置
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(700);
  const mapMode = await page.evaluate(() => ({
    ckView: state.ckView, mapHidden: document.querySelector('#overview-map-view').hidden,
    badge: document.querySelector('#view-badge').textContent,
  }));
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/v3-overview-map.png') });

  // 再看一眼封控区近景（巡视）
  await page.locator('[data-ov="containment"]').click();
  await page.waitForTimeout(500);
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 130; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v3-ck-area.png') });

  console.log(JSON.stringify({ landing, afterRun, mapMode, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });

