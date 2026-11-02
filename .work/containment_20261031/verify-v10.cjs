const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8766/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });

  await page.locator('#open-config').click();
  const dialog = await page.evaluate(() => ({
    selected: document.querySelector('#config-scenario').value,
    groups: [...document.querySelectorAll('#config-scenario optgroup')].map((g) => [g.label, [...g.querySelectorAll('option')].map((o) => o.textContent)]),
    ticks: document.querySelector('#config-form [name=max_ticks]').value,
    note: document.querySelector('#config-scope-note').textContent,
  }));
  await page.locator('#submit-run').click();
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment && state.run.replay.containment.result); }
    catch (e) { return false; }
  }, null, { timeout: 240000 });
  await page.waitForTimeout(1500);

  const run = await page.evaluate(() => ({ id: state.run.id, page: state.page, ckView: state.ckView }));
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 9; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v10-ck-t9.png') });
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 70; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v10-ck-t70.png') });
  await page.locator('#page-overview').screenshot({ path: path.resolve('.work/containment_20261031/v10-ck-page.png') });
  console.log(JSON.stringify({ dialog, run, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
