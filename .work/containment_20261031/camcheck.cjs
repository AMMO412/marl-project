const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8899/?page=containment&source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  const snap = async () => page.evaluate(() => ({
    t: Number(document.querySelector('#ck-scrub').value),
    cam: document.querySelector('#ck-cam-area').classList.contains('active') ? 'area'
      : document.querySelector('#ck-cam-all').classList.contains('active') ? 'all' : 'none',
    ticker: document.querySelector('#ck-ticker').textContent,
  }));
  await page.waitForTimeout(600);
  const early = await snap();
  await page.waitForTimeout(11000);
  const later = await snap();
  console.log(JSON.stringify({ early, later, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
