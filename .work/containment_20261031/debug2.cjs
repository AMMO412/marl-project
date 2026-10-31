const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('requestfailed', (r) => errors.push('reqfail: ' + r.url() + ' ' + r.failure().errorText));
  await page.goto('http://127.0.0.1:8899/?page=containment&source=workbench_20261031_151116_511769', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  const info = await page.evaluate(() => {
    let s = null;
    try { s = (typeof state !== 'undefined') ? state : null; } catch (e) { }
    return {
      hasState: !!s,
      runId: s && s.run ? s.run.id : null,
      containment: !!(s && s.run && s.run.replay && s.run.replay.containment),
      page: s ? s.page : null,
      cp: typeof window.ContainmentPage,
      ckBody: (document.querySelector('#ck-body') || {}).innerHTML.slice(0, 260),
      kpis: document.querySelectorAll('#ck-body .ck-kpi').length,
    };
  });
  console.log(JSON.stringify({ info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
