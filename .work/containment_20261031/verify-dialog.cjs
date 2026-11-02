const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8766/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.locator('#open-config').click();
  const states = [];
  for (const value of ['interop_containment', 'interop_neutral', 'interop_asl', 'asl_city']) {
    await page.selectOption('#config-scenario', value);
    await page.waitForTimeout(150);
    states.push(await page.evaluate(() => ({
      value: document.querySelector('#config-scenario').value,
      ticks: document.querySelector('#config-form [name=max_ticks]').value,
      note: document.querySelector('#config-scope-note').textContent.slice(0, 34),
      effectVisible: !document.querySelector('#config-effect-field').hidden,
    })));
  }
  await page.locator('#close-config').click();
  console.log(JSON.stringify({ states, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
