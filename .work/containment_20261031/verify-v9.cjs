const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8766/?source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });

  // 全局分配视图：T+54 拦阻瞬间
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(500);
  for (const [t, name] of [[54, 'v9-map-54.png'], [120, 'v9-map-120.png']]) {
    await page.evaluate((tt) => { const s = document.querySelector('#scrubber'); s.value = tt; s.dispatchEvent(new Event('input')); }, t);
    await page.waitForTimeout(600);
    await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/' + name) });
  }
  // 区域封控页签：T+70
  await page.locator('[data-ov="containment"]').click();
  await page.waitForTimeout(600);
  await page.evaluate(() => { const s = document.querySelector('#ck-scrub'); s.value = 70; s.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(500);
  const air = await page.evaluate(() => {
    const st = state.run.replay.containment.structure;
    return { posts: st.post_plan.map((p) => [p.pid, p.role, p.altitude_m || null]), chips: [...document.querySelectorAll('.ck-chips span')].map((x) => x.textContent) };
  });
  await page.locator('#page-overview').screenshot({ path: path.resolve('.work/containment_20261031/v9-ck-tab.png') });
  console.log(JSON.stringify({ air, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
