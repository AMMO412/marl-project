const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const info = await page.evaluate(() => ({
    defaultCatalogRun: state.catalog.default_run,
    runs: state.catalog.runs.map((r) => [r.id, r.scenario, r.total, r.planner]),
    runSelect: [...document.querySelectorAll('#run-select option')].map((o) => o.textContent),
    taskOptions: [...document.querySelectorAll('#task-select option')].map((o) => o.textContent),
    scenarioOptions: [...document.querySelectorAll('#config-scenario option')].map((o) => [o.value, o.textContent, o.selected]),
    navPages: [...document.querySelectorAll('.nav')].map((b) => b.dataset.page),
    currentRun: state.run.id,
  }));
  await page.locator('#open-config').click();
  const dialog = await page.evaluate(() => ({
    selected: document.querySelector('#config-scenario').value,
    formNote: document.querySelector('#config-scope-note').textContent,
    avoidHidden: document.querySelector('#config-avoid').closest('label').hidden,
  }));
  console.log(JSON.stringify({ info, dialog, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
