const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8766/?source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  await page.evaluate(() => { const p = document.querySelector('#ck-play'); if (p && p.textContent.includes('暂停')) p.click(); });
  await page.waitForTimeout(400);
  const seek = async (t) => { await page.evaluate((tt) => { const s = document.querySelector('#ck-scrub'); s.value = tt; s.dispatchEvent(new Event('input')); }, t); await page.waitForTimeout(450); };

  await seek(9);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v11-t9-no-routes.png') });
  await seek(70);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v11-t70-no-routes.png') });
  const off = await page.evaluate(() => ({ routesBtn: document.querySelector('#ck-routes').className, visible: !document.querySelector('#ck-routes').classList.contains('active') }));

  // 打开"规划路径"看规划线（按需）
  await page.locator('#ck-routes').click();
  await page.waitForTimeout(400);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v11-t70-routes-on.png') });
  const on = await page.evaluate(() => ({ active: document.querySelector('#ck-routes').classList.contains('active') }));

  console.log(JSON.stringify({ off, on, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
