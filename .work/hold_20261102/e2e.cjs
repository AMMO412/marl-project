// 要点坚守（T-HLD）工作台 e2e：新建演示 → 页签/KPI/甘特/画布断言 → 定时截图
const { chromium } = require('C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright');
const path = require('path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8899';
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1280 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => { try { return !!(typeof state !== 'undefined' && state.run); } catch (e) { return false; } }, null, { timeout: 30000 });

  await page.locator('#open-config').click();
  await page.selectOption('#config-scenario', 'interop_hold');
  const note = await page.locator('#config-scope-note').textContent();
  const hidden = await page.evaluate(() => [...document.querySelectorAll('#config-avoid,#config-behavior')].map((x) => x.closest('label').hidden));
  const ticks = await page.inputValue('#config-form [name=max_ticks]');
  await page.locator('#submit-run').click();

  await page.waitForFunction(() => {
    try { return typeof state !== 'undefined' && state.run && state.run.replay && state.run.replay.hold; }
    catch (e) { return false; }
  }, null, { timeout: 300000 });
  await page.waitForTimeout(1500);

  const info = await page.evaluate(() => ({
    run: state.run.id,
    page: state.page,
    ovView: state.ovView,
    activeTab: document.querySelector('.ov-tab.active')?.dataset.ov,
    tabsHidden: document.querySelector('#overview-tabs').hidden,
    hlHidden: document.querySelector('#overview-hold-view').hidden,
    verdict: state.run.replay.hold.result.verdict,
    kpis: [...document.querySelectorAll('#hl-body .ck-kpi')].map((x) => x.querySelector('.ck-kpi-label').textContent + '=' + x.querySelector('.ck-kpi-value').textContent),
    ganttRows: document.querySelectorAll('.hl-gantt-row').length,
    bars: document.querySelectorAll('.hl-bar').length,
    items: document.querySelectorAll('#hl-body .ck-items li').length,
    timeline: document.querySelectorAll('#hl-timeline li').length,
    canvasW: document.querySelector('#hl-canvas').width,
    canvasH: document.querySelector('#hl-canvas').height,
    canvasCssH: document.querySelector('#hl-canvas').getBoundingClientRect().height,
    structure: {
      key: state.run.replay.hold.structure.key_point,
      positions: state.run.replay.hold.structure.positions.length,
      threats: state.run.replay.hold.structure.threats.length,
      roles: state.run.replay.hold.structure.roles,
    },
    mode: state.run.report.mode, motion: state.run.report.motion,
    behavior: state.run.report.behavior, planner: state.run.report.planner,
    planFiles: state.run.manifest?.plan_files,
  }));

  // 暂停并跳到 T+120 s（第一次接替已完成、增援已到位）
  await page.evaluate(() => {
    if (window.HoldPage) {
      const btn = document.querySelector('#hl-play');
      if (btn && btn.textContent.indexOf('暂停') >= 0) btn.click();
      const scrub = document.querySelector('#hl-scrub');
      scrub.value = 120;
      scrub.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await page.waitForTimeout(600);
  // 先拍 T+3 s（还没建立控制）：探测圈应当只在已到位平台上，不在计划阵位上
  await page.evaluate(() => {
    const scrub = document.querySelector('#hl-scrub');
    scrub.value = 3;
    scrub.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(400);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/hold_20261102/hold_map_card_t3.png') });
  await page.evaluate(() => {
    const scrub = document.querySelector('#hl-scrub');
    scrub.value = 120;
    scrub.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(400);
  await page.locator('#overview-hold-view').screenshot({ path: path.resolve('.work/hold_20261102/hold_task_view_120s.png') });
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/hold_20261102/hold_map_card_120s.png') });

  const at120 = await page.evaluate(() => ({
    hlTime: window.HoldPage.time(),
    ticker: document.querySelector('#hl-ticker')?.textContent?.slice(0, 80),
    occupantMarks: [...document.querySelectorAll('#hl-gantt .hl-mark')].length,
  }));

  // "全程 · 集结→撤离" 镜头
  await page.locator('#hl-cam-all').click();
  await page.waitForTimeout(500);
  await page.locator('.ck-map-card').screenshot({ path: path.resolve('.work/hold_20261102/hold_map_card_all.png') });
  await page.locator('#hl-cam-area').click();
  await page.waitForTimeout(300);

  // 切到全局分配（看点覆盖层）再切回，验证时刻同步
  await page.locator('.ov-tab[data-ov="map"]').click();
  await page.waitForTimeout(500);
  const onMap = await page.evaluate(() => ({
    ovView: state.ovView,
    holdHidden: document.querySelector('#overview-hold-view').hidden,
    mapHidden: document.querySelector('#overview-map-view').hidden,
    t: state.t,
  }));
  await page.locator('#overview-map-view').screenshot({ path: path.resolve('.work/hold_20261102/hold_map_overlay.png') });

  await page.locator('.ov-tab[data-ov="hold"]').click();
  await page.waitForTimeout(500);
  const after = await page.evaluate(() => ({
    ovView: state.ovView,
    holdHidden: document.querySelector('#overview-hold-view').hidden,
    hlTime: window.HoldPage.time(),
  }));

  console.log(JSON.stringify({ note, hidden, ticks, info, at120, onMap, after, errors }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
