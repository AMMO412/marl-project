const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const base = 'http://127.0.0.1:8766';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  // 默认 4 任务运行：应出现"本轮没有封控记录"的说明与一键入口
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.waitForTimeout(500);
  const hint = await page.evaluate(() => {
    const box = document.querySelector('#ck-hint');
    const btn = document.querySelector('[data-ck-run]');
    return { hidden: box.hidden, text: box.textContent.slice(0, 80), button: btn ? btn.dataset.ckRun : null };
  });
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/v8-hint.png') });

  // 点一键入口 → 载入封控运行并切到区域封控页签
  await page.locator('[data-ck-run]').click();
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment && state.ckView); }
    catch (e) { return false; }
  }, null, { timeout: 60000 });
  await page.waitForTimeout(800);
  const after = await page.evaluate(() => ({
    run: state.run.id, ckView: state.ckView,
    hintHidden: document.querySelector('#ck-hint').hidden,
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
  }));
  console.log(JSON.stringify({ hint, after, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
