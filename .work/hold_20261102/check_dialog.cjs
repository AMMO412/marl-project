// 排查：确认 8899（worktree 版本）的“新建演示”里有 要点坚守（T-HLD）
const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8899';
  const out = process.argv[3] || '.work/hold_20261102/dialog_8899.png';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.catalog); } catch (e) { return false; } }, null, { timeout: 30000 });
  const catalog = await page.evaluate(() => ({
    version: state.catalog.version,
    features: state.catalog.features,
    scenarios: state.catalog.scenarios,
  }));
  await page.locator('#open-config').click();
  await page.waitForTimeout(400);
  const options = await page.evaluate(() => [...document.querySelectorAll('#config-scenario option')].map((o) => ({
    value: o.value, text: o.textContent, disabled: o.disabled,
  })));
  const hasHold = options.some((o) => o.value === 'interop_hold');
  if (hasHold) {
    await page.selectOption('#config-scenario', 'interop_hold');
    await page.waitForTimeout(300);
  }
  const note = await page.locator('#config-scope-note').textContent();
  await page.locator('#config-dialog').screenshot({ path: path.resolve(out) });
  console.log(JSON.stringify({ base, catalog, options, hasHold, note, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
