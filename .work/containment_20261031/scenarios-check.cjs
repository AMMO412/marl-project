const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:8899/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });

  // 任务与分配页：默认运行应仍有多个任务
  await page.locator('.nav[data-page="tasks"]').click();
  await page.waitForTimeout(400);
  const tasks = await page.evaluate(() => ({
    rows: [...document.querySelectorAll('#task-table tr')].map((r) => r.querySelector('td')?.textContent.trim().slice(0, 40)),
    runSelect: [...document.querySelectorAll('#run-select option')].map((o) => o.textContent.slice(0, 60)),
  }));

  // 新建演示：三个场景仍可选，asl_city 仍是机动突击入口
  await page.locator('#open-config').click();
  const scenarios = await page.evaluate(() => [...document.querySelectorAll('#config-scenario option')].map((o) => [o.value, o.selected]));
  await page.selectOption('#config-scenario', 'asl_city');
  await page.waitForTimeout(200);
  const asl = await page.evaluate(() => ({
    note: document.querySelector('#config-scope-note').textContent,
    avoidHidden: document.querySelector('#config-avoid').closest('label').hidden,
    effectVisible: !document.querySelector('#config-effect-field').hidden,
  }));
  await page.selectOption('#config-scenario', 'interop_containment');
  await page.waitForTimeout(200);
  const ck = await page.evaluate(() => ({
    note: document.querySelector('#config-scope-note').textContent,
    ticks: document.querySelector('#config-form [name=max_ticks]').value,
  }));
  console.log(JSON.stringify({ tasks, scenarios, asl, ck, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
