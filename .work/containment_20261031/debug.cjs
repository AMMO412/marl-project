const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message + '\n' + (e.stack || '')));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('requestfailed', (r) => errors.push('reqfail: ' + r.url() + ' ' + r.failure().errorText));
  await page.goto('http://127.0.0.1:8899/?page=containment&source=workbench_20261031_151116_511769', { waitUntil: 'networkidle' });
  await page.waitForTimeout(4000);
  const info = await page.evaluate(() => ({
    hasState: typeof window.state !== 'undefined',
    runId: window.state && state.run ? state.run.id : null,
    hasReplay: !!(window.state && state.run && state.run.replay),
    replayKeys: window.state && state.run && state.run.replay ? Object.keys(state.run.replay) : null,
    containment: !!(window.state && state.run && state.run.replay && state.run.replay.containment),
    page: window.state ? state.page : null,
    cp: typeof window.ContainmentPage,
    navBtns: [...document.querySelectorAll('.nav')].map((b) => b.dataset.page),
    pages: [...document.querySelectorAll('.page')].map((p) => p.id),
    bodyHtml: (document.querySelector('#ck-body') || {}).innerHTML ? 'has' : 'empty',
  }));
  console.log(JSON.stringify({ info, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
