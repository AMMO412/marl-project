// 只读校验：载入既有 T-HLD 运行，确认页签/画布/无 console 错误（不新建运行）
const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const runId = process.argv[2];
  const base = 'http://127.0.0.1:8899';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1280 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/?source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.hold); }
    catch (e) { return false; }
  }, null, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.evaluate(() => {
    if (window.HoldPage) {
      const btn = document.querySelector('#hl-play');
      if (btn && btn.textContent.indexOf('暂停') >= 0) btn.click();
      const scrub = document.querySelector('#hl-scrub');
      scrub.value = 120;
      scrub.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await page.waitForTimeout(500);
  const info = await page.evaluate(() => ({
    run: state.run.id,
    ovView: state.ovView,
    activeTab: document.querySelector('.ov-tab.active')?.dataset.ov,
    holdHidden: document.querySelector('#overview-hold-view').hidden,
    canvasCssH: document.querySelector('#hl-canvas').getBoundingClientRect().height,
    ganttRows: document.querySelectorAll('.hl-gantt-row').length,
    kpis: document.querySelectorAll('#hl-body .ck-kpi').length,
    verdict: state.run.replay.hold.result.verdict,
  }));
  await page.locator('#overview-hold-view').screenshot({ path: path.resolve('.work/hold_20261102/hold_css_check.png') });
  await page.locator('.ov-tab[data-ov="map"]').click();
  await page.waitForTimeout(400);
  const overlay = await page.evaluate(() => ({
    ovView: state.ovView,
    mapHidden: document.querySelector('#overview-map-view').hidden,
    holdHidden: document.querySelector('#overview-hold-view').hidden,
  }));
  await page.locator('.ck-map-card, #overview-map-view').first().screenshot({ path: path.resolve('.work/hold_20261102/hold_css_overlay.png') });
  console.log(JSON.stringify({ info, overlay, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
