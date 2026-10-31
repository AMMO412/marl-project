const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 760 } });
  await page.goto('http://127.0.0.1:8766/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.resolve('.work/containment_20261031/v8-hint-top.png') });
  console.log('ok');
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
