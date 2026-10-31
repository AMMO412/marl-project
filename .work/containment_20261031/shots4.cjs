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
  await page.waitForTimeout(500);
  const seek = async (t) => { await page.evaluate((tt) => { const s = document.querySelector('#ck-scrub'); s.value = tt; s.dispatchEvent(new Event('input')); }, t); await page.waitForTimeout(450); };

  // 区域封控页签（默认打开）
  await seek(70);
  await page.locator('#page-overview').screenshot({ path: path.resolve('.work/containment_20261031/v4-ck-tab.png') });
  await seek(130);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/v4-ck-area.png') });

  // 全局分配页签
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(700);
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/v4-map-tab.png') });

  const info = await page.evaluate(() => ({
    run: state.run.id, ckView: state.ckView,
    tabsVisible: !document.querySelector('#overview-tabs').hidden,
    labels: [...document.querySelectorAll('#overview-tabs .ov-tab')].map((b) => b.textContent + (b.classList.contains('active') ? '*' : '')),
  }));
  console.log(JSON.stringify({ info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
