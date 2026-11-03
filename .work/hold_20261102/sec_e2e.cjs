// 区域封控（T-SEC）工作台 e2e：新建演示 → 页签/KPI/画布断言 → 截图
const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8899';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1280 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.catalog); } catch (e) { return false; } }, null, { timeout: 30000 });

  await page.locator('#open-config').click();
  await page.selectOption('#config-scenario', 'interop_containment');
  await page.locator('#submit-run').click();

  await page.waitForFunction(() => {
    try { return typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment; }
    catch (e) { return false; }
  }, null, { timeout: 300000 });
  await page.waitForTimeout(1500);

  const info = await page.evaluate(() => ({
    run: state.run.id,
    ovView: state.ovView,
    activeTab: document.querySelector('.ov-tab.active')?.dataset.ov,
    verdict: state.run.replay.containment.result.verdict,
    kpis: [...document.querySelectorAll('#ck-body .ck-kpi')].map((x) => x.querySelector('.ck-kpi-label').textContent + '=' + x.querySelector('.ck-kpi-value').textContent),
    targets: (state.run.replay.containment.result.targets || []).map((t) => t.target_id + ':' + t.state),
    canvasW: document.querySelector('#ck-canvas').width,
    canvasH: document.querySelector('#ck-canvas').height,
    area: state.run.replay.containment.structure.area,
    cameras: [...document.querySelectorAll('#ck-cam-all,#ck-cam-area')].map((b) => b.id),
  }));
  await page.evaluate(() => {
    if (window.ContainmentPage) {
      const btn = document.querySelector('#ck-play');
      if (btn && btn.textContent.indexOf('暂停') >= 0) btn.click();
      const scrub = document.querySelector('#ck-scrub');
      if (scrub) { scrub.value = 60; scrub.dispatchEvent(new Event('input', { bubbles: true })); }
    }
  });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/hold_20261102/sec_map_card.png') });
  await page.locator('#overview-ck-view').screenshot({ path: path.resolve('.work/hold_20261102/sec_page.png') });
  console.log(JSON.stringify({ base, info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
