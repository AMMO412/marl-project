const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const runId = process.argv[2] || 'workbench_20261031_151116_511769';
  const base = 'http://127.0.0.1:8899';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/?page=containment&source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll('#ck-body .ck-kpi').length >= 6, null, { timeout: 15000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  await page.waitForTimeout(600);
  await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/page-top.png') });

  // 播放到事件密集时段（约 T+55s），核对画面上的警告/拦阻
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 55; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/map-55s.png') });

  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 120; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(400);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/containment_20261031/map-120s.png') });

  const summary = await page.evaluate(() => ({
    verdict: (typeof state !== 'undefined' ? state.run.replay.containment.result.verdict : null),
    kpis: [...document.querySelectorAll('#ck-body .ck-kpi')].map((x) => [x.querySelector('.ck-kpi-label').textContent, x.querySelector('.ck-kpi-value').textContent]),
    rows: document.querySelectorAll('.ck-table tbody tr').length,
    items: document.querySelectorAll('.ck-items li').length,
    timeline: document.querySelectorAll('#ck-timeline li').length,
    canvas: (() => { const c = document.querySelector('#ck-canvas'); return c ? [c.width, c.height] : null; })(),
  }));
  // 运行一次真实播放，确认时钟推进
  await page.locator('#ck-play').click();
  await page.waitForTimeout(1800);
  const clock = await page.evaluate(() => document.querySelector('#ck-time').textContent);
  await page.locator('#ck-play').click();
  await page.setViewportSize({ width: 760, height: 1000 });
  await page.waitForTimeout(400);
  await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/page-narrow.png') });

  console.log(JSON.stringify({ summary, clock, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });

