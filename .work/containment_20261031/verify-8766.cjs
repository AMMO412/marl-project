const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const base = 'http://127.0.0.1:8766';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const landing = await page.evaluate(() => ({ run: state.run.id, tasks: state.run.report.jobs.length, tabsHidden: document.querySelector('#overview-tabs').hidden }));

  // 新建演示 → 区域封控（验证"无效参数"已修）
  await page.locator('#open-config').click();
  await page.selectOption('#config-scenario', 'interop_containment');
  const optionText = await page.locator('#config-scenario option[value="interop_containment"]').textContent();
  await page.locator('#submit-run').click();
  await page.waitForFunction(() => {
    try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment && state.run.replay.containment.result); }
    catch (e) { return false; }
  }, null, { timeout: 240000 });
  await page.waitForTimeout(1500);
  const afterRun = await page.evaluate(() => ({
    run: state.run.id, page: state.page, ckView: state.ckView,
    tabsHidden: document.querySelector('#overview-tabs').hidden,
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
  }));

  // 切到全局分配，拖到控制建立之后看区域框 + 探测半径圈
  await page.locator('[data-ov="map"]').click();
  await page.waitForTimeout(500);
  await page.evaluate(() => { const s = document.querySelector('#scrubber'); if (s) { s.value = 110; s.dispatchEvent(new Event('input')); } });
  await page.waitForTimeout(700);
  const mapState = await page.evaluate(() => ({ t: state.t, ckView: state.ckView, ckStructure: !!(state.run.replay.containment && state.run.replay.containment.structure) }));
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/v6-map-circles.png') });

  console.log(JSON.stringify({ landing, optionText, afterRun, mapState, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
