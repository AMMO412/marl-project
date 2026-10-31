const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8899/?source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  await page.evaluate(() => { const p = document.querySelector('#ck-play'); if (p && p.textContent.includes('暂停')) p.click(); });
  await page.waitForTimeout(400);

  // 封控视图里把时间拖到 90 s
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 90; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(600);
  const mapSync = await page.evaluate(() => ({ t: state.t, playerShows: document.querySelector('#clock') ? document.querySelector('#clock').textContent : null }));
  await page.locator('[data-ov="containment"]').click();
  await page.waitForTimeout(600);
  const ckSync = await page.evaluate(() => ({ t: Number(document.querySelector('#ck-scrub').value) }));

  // 最终截图
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 70; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('#page-overview').screenshot({ path: path.resolve('.work/containment_20261031/v5-ck-tab.png') });
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 130; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v5-ck-area.png') });
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(700);
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/v5-map-tab.png') });

  console.log(JSON.stringify({ mapSync, ckSync, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
