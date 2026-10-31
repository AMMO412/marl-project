const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const runId = process.argv[2];
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8899/?source=' + runId, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.evaluate(() => { const d = document.querySelector('#config-dialog'); if (d && d.open) d.close(); });
  await page.locator('#fit-map').click();
  await page.waitForTimeout(700);
  await page.locator('.map-card').screenshot({ path: path.resolve('.work/containment_20261031/overview-map.png') });
  const info = await page.evaluate(() => ({
    run: state.run.id,
    hasCkStructure: !!(state.run.replay.containment && state.run.replay.containment.structure),
    ckButtonVisible: !document.querySelector('#open-containment').hidden,
    taskCount: state.run.report.jobs.length,
  }));
  console.log(JSON.stringify({ info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
