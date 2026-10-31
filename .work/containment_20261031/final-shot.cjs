const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1150 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8899/?page=containment&source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.containment); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  await page.waitForTimeout(700);
  for (const [t, name] of [[56, 'final-56s.png'], [78, 'final-78s.png']]) {
    await page.evaluate((tt) => { const s = document.querySelector('#ck-scrub'); s.value = tt; s.dispatchEvent(new Event('input')); }, t);
    await page.waitForTimeout(450);
    await page.locator('#page-containment').screenshot({ path: path.resolve('.work/containment_20261031/' + name) });
  }
  console.log(JSON.stringify({ errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
