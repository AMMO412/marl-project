const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const base = 'http://127.0.0.1:8899';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });

  await page.locator('#open-config').click();
  await page.selectOption('#config-scenario', 'interop_containment');
  const note = await page.locator('#config-scope-note').textContent();
  const hidden = await page.evaluate(() => [...document.querySelectorAll('#config-avoid,#config-behavior')].map((x) => x.closest('label').hidden));
  const ticks = await page.inputValue('#config-form [name=max_ticks]');
  await page.locator('#submit-run').click();

  await page.waitForFunction(() => {
    try { return typeof state !== 'undefined' && state.page === 'containment' && state.run && state.run.replay && state.run.replay.containment; }
    catch (e) { return false; }
  }, null, { timeout: 240000 });
  await page.waitForTimeout(1200);
  const info = await page.evaluate(() => ({
    run: state.run.id,
    page: state.page,
    verdict: state.run.replay.containment.result.verdict,
    kpis: [...document.querySelectorAll('#ck-body .ck-kpi')].map((x) => x.querySelector('.ck-kpi-label').textContent + '=' + x.querySelector('.ck-kpi-value').textContent),
    rows: document.querySelectorAll('.ck-table tbody tr').length,
    canvasW: document.querySelector('#ck-canvas').width,
    mode: state.run.report.mode, motion: state.run.report.motion, behavior: state.run.report.behavior,
    planner: state.run.report.planner,
  }));
  await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/e2e-page.png') });
  console.log(JSON.stringify({ note, hidden, ticks, info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
