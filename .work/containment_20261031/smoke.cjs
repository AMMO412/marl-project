const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  const before = await page.evaluate(() => ({ run: state.run.id, page: state.page }));
  await page.locator('.nav[data-page="containment"]').click();
  await page.waitForTimeout(900);
  const after = await page.evaluate(() => ({
    page: state.page,
    kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
    canvasH: document.querySelector('#ck-canvas') ? document.querySelector('#ck-canvas').height : 0,
    ticker: (document.querySelector('#ck-ticker') || {}).textContent,
  }));
  await page.locator('.nav[data-page="overview"]').click();
  await page.waitForTimeout(500);
  const back = await page.evaluate(() => ({ page: state.page, overviewVisible: document.querySelector('#page-overview').classList.contains('active') }));
  console.log(JSON.stringify({ before, after, back, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
