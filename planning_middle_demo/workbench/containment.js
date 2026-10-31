/* 区域封控（T-SEC）回放页
 *
 * 数据只来自 /api/runs 返回的 replay.containment（由 trajectory_v2 从审计记录
 * 抽取）：封控边界、分段占位、通道口、角色、逐目标轨迹、控制时间线与逐项判定。
 * 本文件不重算几何、不推算指标——画错一条边界就会把"守住/漏了"讲反。
 *
 * 与总览页共用 state.run，但有自己的时钟：总览看全局任务，这里看一封控区的
 * "谁守哪一段、目标从哪来、警告/拦阻/放行发生在第几秒"。
 */
(function () {
  'use strict';

  const C = {
    data: null, jobId: null, t: 0, playing: false, speed: 3,
    raf: null, last: 0, built: false, bounds: null,
    cam: 'all', visible: false,
  };
  const COLORS = {
    area: '#b4552d', sector: '#0f766e', gate: '#7c3aed',
    unauthorized: '#dc2626', warned: '#d97706', intercepting: '#7c3aed',
    held: '#0d9488', breach: '#991b1b', withdrawn: '#64748b',
    passed: '#2563eb', waiting: '#94a3b8', post: '#334155',
  };
  // 边界段配色与"封控区轮廓"明确区分：段线是任务色，轮廓只是虚线围栏。
  const SECTOR_COLORS = ['#1d4ed8', '#0f766e', '#7c3aed', '#b45309', '#be123c'];
  const EVENT_TICK = {
    control_established: '#0f766e', control_interrupted: '#b45309',
    control_restored: '#0f766e', target_appeared: '#94a3b8',
    target_detected: '#d97706', warning_issued: '#d97706',
    warning_effective: '#64748b', intercept_assigned: '#7c3aed',
    intercepted: '#0d9488', breach: '#991b1b', authorized_pass: '#2563eb',
  };
  const STATE_COLOR = {
    '待出现': COLORS.waiting, '监视': COLORS.warned, '已警告': COLORS.warned,
    '拦截中': COLORS.intercepting, '已拦阻': COLORS.held,
    '未授权进入': COLORS.breach, '已撤离': COLORS.withdrawn, '已放行': COLORS.passed,
  };
  const EVENT_TEXT = {
    target_appeared: '目标出现', target_detected: '发现目标',
    target_authorized: '识别为已授权', target_unauthorized: '识别为未授权',
    warning_issued: '发出警告', warning_effective: '警告有效·撤离',
    intercept_assigned: '指派拦阻', intercept_denied: '授权不足未拦阻',
    intercepted: '拦阻到位', breach: '未授权进入', authorized_pass: '授权放行',
    control_established: '控制建立', control_interrupted: '控制中断',
    control_restored: '控制恢复',
  };
  const ROLE_TEXT = {
    boundary: '边界段', gate: '通道哨位', intercept: '机动拦截',
    reserve: '预备队', air: '空中监视',
  };

  const el = (s) => document.querySelector(s);
  // app.js 用 `const state = {...}` 声明，属于全局词法绑定，不会挂到 window 上；
  // 这里按名字取，取不到就当作"尚未载入"，不要因为 window.state 为空就画空页。
  function appState() {
    try { return typeof state !== 'undefined' ? state : null; } catch (e) { return null; }
  }
  function palette() {
    try { return typeof taskPalette !== 'undefined' ? taskPalette : ['#288d79']; }
    catch (e) { return ['#288d79']; }
  }
  const num = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const roleName = (role) => {
    const [kind, detail] = String(role || '').split(':');
    const label = ROLE_TEXT[kind] || role || '未分工';
    return detail ? label + ' · ' + detail : label;
  };
  const stateColor = (state) => STATE_COLOR[state] || COLORS.waiting;

  function page() { return document.getElementById('page-containment'); }

  // ---------------------------------------------------------------- 数据
  function load(run) {
    C.data = (run && run.replay && run.replay.containment) || null;
    C.jobId = C.data ? C.data.job_id : null;
    C.built = false;
    C.playing = false;
    C.autoPlayed = false;
    C.cam = 'all';
    C.camAuto = true;
    C.t = 0;
    C.bounds = null;
    if (!C.data) { renderEmpty(run); return; }
    renderAll();
  }

  function structure() { return C.data.structure; }
  function result() { return C.data.result || {}; }
  function metrics() { return result().metrics || {}; }
  function endTime() {
    const st = structure();
    let end = (result().sim_s || 0) + 1;
    for (const t of (result().targets || [])) {
      for (const p of (t.track || [])) end = Math.max(end, p[0]);
    }
    for (const e of (C.data.events || [])) end = Math.max(end, e.t || 0);
    for (const w of workers()) {
      for (const s of (w.samples || [])) {
        if (s.job === C.jobId) end = Math.max(end, s.t);
      }
    }
    return Math.max(end, (st && st.duration_s) || 0);
  }

  function workers() {
    const s = appState();
    return (s && s.run && s.run.replay && s.run.replay.workers) || [];
  }

  function currentRun() {
    const s = appState();
    return (s && s.run) || null;
  }

  // 4.2 计划（工作台按 run 一起给出）：规划器从集结地到占位点的路径与角色。
  function planAssignments() {
    const run = currentRun();
    const plan = run && run.plan;
    if (!plan || !Array.isArray(plan.assignments)) return [];
    return plan.assignments.filter((a) => !a.task_id || a.task_id === C.jobId);
  }

  function assemblyPoints() {
    const fromPlan = planAssignments()
      .map((a) => (a.path && a.path.length ? a.path[0] : null))
      .filter(Boolean);
    if (fromPlan.length) return fromPlan;
    const run = currentRun();
    const platforms = (run && run.scenario && run.scenario.platforms) || [];
    return platforms.map((p) => p.pos).filter(Boolean);
  }

  function workerOf(assignment) {
    return workers().find((w) => Number(w.no) === Number(assignment.robot_id)) || null;
  }

  function workerSamples(pid) {
    const w = workers().find((x) => x.pid === pid);
    return (w && w.samples) ? w.samples.filter((s) => s.job === C.jobId) : [];
  }

  // ---------------------------------------------------------------- 面板
  function renderEmpty(run) {
    const host = el('#ck-body');
    if (!host) return;
    host.innerHTML = '<div class="ck-empty"><div class="ck-empty-icon">◈</div>' +
      '<h3>本次运行不含区域封控</h3>' +
      '<p>“区域封控”页只回放 T-SEC 任务的实际执行记录：边界段占位、通道哨位、' +
      '未授权目标接近、警告与拦阻、授权放行。当前运行' +
      (run ? '（' + esc(run.id) + '）' : '') + '没有这些记录，因此不画示意图。</p>' +
      '<button class="button primary" id="ck-start">运行一次区域封控演示 →</button></div>';
    const btn = el('#ck-start');
    if (btn) btn.addEventListener('click', () => {
      const dialog = el('#config-dialog');
      const select = el('#config-scenario');
      if (select) { select.value = 'interop_containment'; }
      if (dialog && dialog.showModal) dialog.showModal();
      if (select) select.dispatchEvent(new Event('change'));
    });
  }

  function verdictPill() {
    const v = result().verdict;
    const label = { succeeded: '判定 成功', failed: '判定 失败', pending: '结果待确认' }[v] || '未判定';
    return '<span class="ck-verdict ' + esc(v || 'none') + '">' + esc(label) + '</span>';
  }

  function renderAll() {
    const st = structure();
    if (!st) { renderEmpty(currentRun()); return; }
    const m = metrics();
    const area = st.area || [];
    let width = 0, height = 0;
    if (area.length) {
      const xs = area.map((p) => p[0]), ys = area.map((p) => p[1]);
      width = Math.round(Math.max(...xs) - Math.min(...xs));
      height = Math.round(Math.max(...ys) - Math.min(...ys));
    }
    // 空中监视只在对空/高度层上有意义，这里把机数与高度直接标出来，
    // 免得"图上有架飞机"却不知道它飞多高、算不算封控兵力。
    const airPosts = (st.post_plan || []).filter((p) =>
      String(p.role || '').startsWith('air') || p.air);
    const airChip = airPosts.length
      ? '<span>空中监视 ' + airPosts.length + ' 台 · ' +
        num((airPosts[0].altitude_m || m.air_altitude_m || 0), 0) + ' m</span>'
      : '';
    const cards = [
      ['未授权进入', num(m.unauthorized_entries, 0) + ' 次',
        '拒止进入主判据 · 要求 0 次', m.unauthorized_entries === 0],
      ['漏控率', (num((m.leak_rate || 0) * 100, 0)) + '%',
        '未授权进入 / 未授权接近', (m.leak_rate || 0) <= 0.0001],
      ['拦截成功率', m.intercept_attempts ? num((m.intercept_rate || 0) * 100, 0) + '%' : '未触发',
        (m.intercept_attempts || 0) + ' 次拦阻中成功 ' + (m.intercepted || 0), true],
      ['边界监视覆盖率', num((m.boundary_coverage || 0) * 100, 0) + '%',
        '传感器半径 ' + num(st.sensor_radius_m, 0) + ' m · 按在位平台统计', null],
      ['持续占位率', num((m.occupancy_ratio || 0) * 100, 0) + '%',
        '占位/门哨在岗时长占比 · 中断 ' + (m.interruptions || 0) + ' 次', null],
      ['平均响应时间', m.mean_response_s == null ? '未触发' : num(m.mean_response_s, 1) + ' s',
        '发现 → 指派拦阻；警告时延 ' + (m.mean_warning_latency_s == null ? '—' : num(m.mean_warning_latency_s, 1) + ' s'), null],
    ];
    const kpis = cards.map(([label, value, note, ok]) =>
      '<article class="ck-kpi' + (ok === true ? ' ok' : ok === false ? ' bad' : '') + '">' +
      '<div class="ck-kpi-label">' + esc(label) + '</div>' +
      '<div class="ck-kpi-value">' + esc(value) + '</div>' +
      '<div class="ck-kpi-note">' + esc(note) + '</div></article>').join('');

    const targets = (result().targets || []);
    const rows = targets.map((t) => {
      const cls = t.authorized ? 'au' : 'un';
      const cell = (v) => (v == null ? '—' : num(v, 1) + 's');
      return '<tr><td><b>' + esc(t.target_id) + '</b><span class="ck-tag ' + cls + '">' +
        (t.authorized ? '已授权' : '未授权') + '</span></td>' +
        '<td>' + cell(t.detected_at_s) + '</td>' +
        '<td>' + cell(t.warned_at_s) + '</td>' +
        '<td>' + cell(t.intercepted_at_s) + '</td>' +
        '<td><span class="ck-state" style="--c:' + stateColor(t.state) + '">' +
        esc(t.state) + '</span></td></tr>';
    }).join('') || '<tr><td colspan="5" class="muted">本次记录没有目标接近事件</td></tr>';

    const items = (result().items || []).map((it) =>
      '<li class="' + (it.ok ? 'ok' : 'bad') + '">' +
      '<span class="ck-check">' + (it.ok ? '✓' : '✕') + '</span>' +
      '<span><b>' + esc(it.label) + '</b> = ' + esc(String(it.value)) +
      '（要求 ' + esc(String(it.target)) + '）' +
      (it.required ? '' : '<em class="muted"> 辅助</em>') + '</span></li>').join('');

    const events = (C.data.events || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0));
    const timeline = events.map((e) =>
      '<li data-t="' + (e.t || 0) + '"><time>' + num(e.t || 0, 0) + 's</time>' +
      '<span>' + esc(EVENT_TEXT[e.kind] || e.kind) +
      (e.target_id ? ' · ' + esc(e.target_id) : '') +
      (e.pid ? ' · ' + esc(shortPid(e.pid)) : '') + '</span></li>').join('') ||
      '<li class="muted">尚无控制过程事件</li>';

    const host = el('#ck-body');
    host.innerHTML =
      '<div class="ck-head">' +
        '<div class="ck-head-main"><div><div class="eyebrow">AREA CONTAINMENT · T-SEC</div>' +
        '<h2>' + esc(C.jobId) + ' 区域封控' + verdictPill() + '</h2></div>' +
        '<div class="ck-head-right"><div class="ck-chips">' +
          '<span>封控区 ' + width + ' × ' + height + ' m</span>' +
          '<span>周长 ' + num(st.perimeter_m, 0) + ' m</span>' +
          '<span>控制等级 ' + esc(st.control_level_label || st.control_level) + '</span>' +
          '<span>交战授权 ' + esc(st.engagement_authority_label || st.engagement_authority) + '</span>' +
          '<span>封控时段 ' + num(st.duration_s, 0) + ' s</span>' +
          '<span>' + (st.post_plan || []).length + ' 台在位</span>' +
          airChip +
        '</div>' +
        '<button class="button small" data-ck-back>← 返回全局分配</button></div></div>' +
        '<p class="ck-reason">' + esc(result().reason || '') + '</p>' +
      '</div>' +
      '<div class="ck-kpis">' + kpis + '</div>' +
      '<div class="ck-layout">' +
        '<article class="card ck-map-card">' +
          '<div class="card-heading"><div><div class="eyebrow">CONTROL PICTURE</div>' +
          '<h2>边界 · 占位 · 接近事件</h2></div>' +
          '<div class="ck-map-actions">' +
            '<button class="button small' + (C.cam === 'all' ? ' active' : '') + '" id="ck-cam-all">全程 · 集结→占位</button>' +
            '<button class="button small' + (C.cam === 'area' ? ' active' : '') + '" id="ck-cam-area">封控区</button>' +
            '<button class="button small" id="ck-fit">⌖ 适应视图</button>' +
          '</div></div>' +
          '<div class="ck-legend" id="ck-legend">' +
            '<span><i style="background:' + COLORS.area + '"></i>封控边界</span>' +
            '<span><i style="background:' + COLORS.sector + '"></i>边界段</span>' +
            '<span><i style="background:' + COLORS.gate + '"></i>通道口</span>' +
            '<span><i class="dash" style="border-color:#64748b"></i>规划路径</span>' +
            '<span><i style="background:' + COLORS.unauthorized + '"></i>未授权</span>' +
            '<span><i style="background:' + COLORS.passed + '"></i>已授权</span>' +
            '<span><i style="background:' + COLORS.held + '"></i>已拦阻</span>' +
          '</div>' +
          '<canvas id="ck-canvas"></canvas>' +
          '<div class="ck-ticker" id="ck-ticker"></div>' +
          '<div class="ck-ribbon" id="ck-ribbon" aria-label="控制过程事件分布"></div>' +
          '<div class="ck-clock">' +
            '<button class="button small" id="ck-play">▶ 播放</button>' +
            '<input type="range" id="ck-scrub" min="0" max="' + Math.round(endTime()) + '" value="0" step="0.5">' +
            '<span id="ck-time">0.0 / ' + Math.round(endTime()) + ' s</span>' +
            '<label class="ck-speed">速度<select id="ck-rate">' +
              [1, 3, 6].map((v) => '<option value="' + v + '"' + (v === C.speed ? ' selected' : '') + '>' + v + '×</option>').join('') +
            '</select></label>' +
          '</div>' +
        '</article>' +
        '<aside class="ck-side">' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">EVENT CLOSURE</div>' +
          '<h2>目标闭合</h2></div><span class="pill">' + targets.length + ' 个</span></div>' +
          '<div class="table-scroll"><table class="ck-table"><thead><tr><th>目标</th><th>发现</th><th>警告</th><th>拦阻</th><th>结果</th></tr></thead><tbody>' +
          rows + '</tbody></table></div>' +
          '<p class="card-foot">“—”表示该环节未发生：已授权目标不警告不拦阻，撤离目标不拦阻。</p></article>' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">VERDICT ITEMS</div>' +
          '<h2>逐项判定</h2></div></div><ul class="ck-items">' + (items || '<li class="muted">未记录判定项</li>') + '</ul>' +
          '<p class="card-foot">' + esc(result().evidence || '') + '</p></article>' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">CONTROL TIMELINE</div>' +
          '<h2>控制状态时间线</h2></div></div><ul class="ck-timeline" id="ck-timeline">' + timeline + '</ul></article>' +
        '</aside>' +
      '</div>';
    bind();
  }

  function shortPid(pid) { return String(pid || '').replace('rover_', '#'); }

  function bind() {
    const play = el('#ck-play'), scrub = el('#ck-scrub'), rate = el('#ck-rate');
    if (play) play.addEventListener('click', () => setPlaying(!C.playing));
    if (scrub) scrub.addEventListener('input', () => { setPlaying(false); seek(Number(scrub.value)); });
    if (rate) rate.addEventListener('change', () => { C.speed = Number(rate.value) || 3; });
    const fit = el('#ck-fit');
    if (fit) fit.addEventListener('click', () => { C.bounds = null; draw(); });
    const setCam = (mode) => {
      C.cam = mode;
      C.camAuto = false;
      C.bounds = null;
      syncCamButtons();
      draw();
    };
    const camAll = el('#ck-cam-all'), camArea = el('#ck-cam-area');
    if (camAll) camAll.addEventListener('click', () => setCam('all'));
    if (camArea) camArea.addEventListener('click', () => setCam('area'));
    buildRibbon();
    updateTicker();
    const timeline = el('#ck-timeline');
    if (timeline) timeline.addEventListener('click', (e) => {
      const li = e.target.closest('li[data-t]');
      if (li) { setPlaying(false); seek(Number(li.dataset.t)); }
    });
    const canvas = el('#ck-canvas');
    if (canvas) canvas.addEventListener('click', (e) => {
      // 点目标/平台查看该对象在该时刻的状态
      const rect = canvas.getBoundingClientRect();
      const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
      const box = el('#ck-pick');
      if (box) box.innerHTML = hit || '';
    });
    C.built = true;
    requestAnimationFrame(() => { resize(); draw(); });
  }

  // ---------------------------------------------------------------- 时钟
  function setPlaying(on) {
    C.playing = !!on;
    const btn = el('#ck-play');
    if (btn) btn.textContent = C.playing ? 'Ⅱ 暂停' : '▶ 播放';
    if (C.playing) {
      if (C.t >= endTime()) C.t = 0;
      C.last = performance.now();
      if (!C.raf) C.raf = requestAnimationFrame(tick);
    }
  }

  function seek(t) {
    C.t = Math.max(0, Math.min(endTime(), t));
    // 机动段看"集结→占位"的全程，控制建立后自动收到封控区（用户手动选过
    // 相机后不再自动切，避免镜头自己乱跳）。
    if (C.camAuto) {
      const ce = controlEstablishedAt();
      if (ce != null && C.t >= ce) {
        C.camAuto = false;
        C.cam = 'area';
        C.bounds = null;
        syncCamButtons();
      }
    }
    const scrub = el('#ck-scrub'), label = el('#ck-time');
    if (scrub) scrub.value = C.t;
    if (label) label.textContent = num(C.t, 1) + ' / ' + Math.round(endTime()) + ' s';
    updateTicker();
    draw();
  }

  function controlEstablishedAt() {
    const ev = (C.data.events || []).find((e) => e.kind === 'control_established');
    return ev ? (ev.t || 0) : null;
  }

  function syncCamButtons() {
    const all = el('#ck-cam-all'), area = el('#ck-cam-area');
    if (all) all.classList.toggle('active', C.cam === 'all');
    if (area) area.classList.toggle('active', C.cam === 'area');
  }

  // 事件分布条：把"第几秒发生了什么"直接铺在时间轴上，点一下跳到那一刻。
  function buildRibbon() {
    const ribbon = el('#ck-ribbon');
    if (!ribbon) return;
    const end = Math.max(1, endTime());
    ribbon.innerHTML = (C.data.events || []).map((e) => {
      const pct = Math.max(0, Math.min(100, (e.t || 0) / end * 100));
      const color = EVENT_TICK[e.kind] || '#94a3b8';
      const title = (EVENT_TEXT[e.kind] || e.kind) +
        (e.target_id ? ' · ' + e.target_id : '') + ' · T+' + Math.round(e.t || 0) + 's';
      return '<i style="left:' + pct.toFixed(2) + '%;--c:' + color + '" title="' +
        esc(title) + '" data-t="' + (e.t || 0) + '"></i>';
    }).join('');
    ribbon.onclick = (ev) => {
      const tick = ev.target.closest('i[data-t]');
      if (tick) { setPlaying(false); seek(Number(tick.dataset.t)); }
    };
  }

  function phaseNow(t) {
    const events = (C.data.events || []).filter((e) => (e.t || 0) <= t);
    const has = (k) => events.some((e) => e.kind === k);
    const last = events.filter((e) => e.kind === 'intercept_assigned').pop();
    const held = events.filter((e) => e.kind === 'intercepted').pop();
    if (!has('control_established')) return { label: '机动集结', color: '#64748b' };
    if (last && (!held || held.t < last.t)) return { label: '拦阻', color: '#7c3aed' };
    if (has('warning_issued') && !held) return { label: '警告', color: '#d97706' };
    return { label: '封控在位', color: '#0f766e' };
  }

  function updateTicker() {
    const box = el('#ck-ticker');
    if (!box || !C.data) return;
    const events = (C.data.events || []).filter((e) => (e.t || 0) <= C.t)
      .sort((a, b) => (a.t || 0) - (b.t || 0));
    const phase = phaseNow(C.t);
    const last = events[events.length - 1];
    const phaseChip = '<span class="ck-phase" style="--c:' + phase.color + '">' +
      esc(phase.label) + '</span>';
    if (!last) {
      const routes = planAssignments().length;
      box.innerHTML = phaseChip + (routes
        ? '<em>平台按 4.2 计划路径从集结待机区前往各自占位点，封控尚未建立</em>'
        : '<em>平台正在前往占位点，封控尚未建立</em>');
      return;
    }
    box.innerHTML = phaseChip +
      '<time>T+' + Math.round(last.t || 0) + 's</time>' +
      '<b>' + esc(EVENT_TEXT[last.kind] || last.kind) + '</b>' +
      (last.target_id ? '<span>' + esc(last.target_id) + '</span>' : '') +
      (last.pid ? '<span>' + esc(shortPid(last.pid)) + '</span>' : '');
  }

  function tick(now) {
    C.raf = null;
    if (!C.playing || !C.data || !C.visible) return;
    const dt = Math.min(0.12, (now - C.last) / 1000);
    C.last = now;
    C.t += dt * C.speed;
    if (C.t >= endTime()) { C.t = endTime(); setPlaying(false); }
    seek(C.t);
    if (C.playing) C.raf = requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- 画布
  function resize() {
    const canvas = el('#ck-canvas');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(rect.width * dpr) ||
        canvas.height !== Math.round(rect.height * dpr)) {
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
    }
  }

  function computeBounds() {
    const st = structure();
    const pts = [];
    (st.area || []).forEach((p) => pts.push(p));
    for (const post of (st.post_plan || [])) if (post.point) pts.push(post.point);
    for (const gate of (st.gates || [])) if (gate.point) pts.push(gate.point);
    for (const t of (result().targets || [])) {
      if (t.start) pts.push(t.start);
      if (t.goal) pts.push(t.goal);
      (t.track || []).forEach((p) => pts.push([p[1], p[2]]));
    }
    if (C.cam === 'all') {
      // 全程视图把"集结 → 规划路径 → 占位"一起纳入取景
      for (const a of planAssignments()) {
        for (const p of (a.path || [])) pts.push(p);
      }
      for (const p of assemblyPoints()) pts.push(p);
    }
    // 出发阵地可能在几百米外；把它算进取景会把封控区压成一个小方块。
    // 取景只按封控区本身，平台出画时仍按其真实坐标绘制。
    if (!pts.length) return [0, 0, 100, 100];
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const pad = Math.max(12, Math.max(Math.max(...xs) - Math.min(...xs),
                                      Math.max(...ys) - Math.min(...ys)) * 0.08);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad,
            Math.max(...xs) + pad, Math.max(...ys) + pad];
  }

  function projectFactory(canvas) {
    const rect = canvas.getBoundingClientRect();
    const b = C.bounds || (C.bounds = computeBounds());
    const W = rect.width, H = rect.height;
    const scale = Math.min((W - 40) / (b[2] - b[0]), (H - 40) / (b[3] - b[1]));
    const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    return [(p) => [W / 2 + (p[0] - cx) * scale, H / 2 - (p[1] - cy) * scale], scale];
  }

  function targetAt(tgt, t) {
    const track = tgt.track || [];
    if (!track.length) return [tgt.start[0], tgt.start[1]];
    let prev = track[0];
    for (const p of track) {
      if (p[0] <= t) prev = p; else {
        const f = (t - prev[0]) / Math.max(1e-6, p[0] - prev[0]);
        return [prev[1] + (p[1] - prev[1]) * f, prev[2] + (p[2] - prev[2]) * f];
      }
    }
    return [prev[1], prev[2]];
  }

  // 结果里的 state 是“最终状态”；回放要的是“此刻状态”，按事件时序回推，
  // 否则 T+55 s 就会把还没被拦阻的目标标成“已拦阻”。
  function targetStateAt(tgt, t) {
    const kinds = new Set((C.data.events || [])
      .filter((e) => e.target_id === tgt.target_id && (e.t || 0) <= t)
      .map((e) => e.kind));
    if (kinds.has('breach')) return '未授权进入';
    if (kinds.has('intercepted')) return '已拦阻';
    if (kinds.has('warning_effective')) return '已撤离';
    if (kinds.has('authorized_pass')) return '已放行';
    if (kinds.has('intercept_assigned')) return '拦截中';
    if (kinds.has('warning_issued')) return '已警告';
    if (kinds.has('target_detected')) return '监视';
    return '待出现';
  }

  function agentAt(pid, t) {
    const samples = workerSamples(pid);
    if (!samples.length) return null;
    let prev = samples[0];
    for (const s of samples) {
      if (s.t <= t) prev = s; else {
        const f = (t - prev.t) / Math.max(1e-6, s.t - prev.t);
        return { x: prev.x + (s.x - prev.x) * f, y: prev.y + (s.y - prev.y) * f,
                 yaw: prev.yaw || 0, phase: prev.phase };
      }
    }
    return { x: prev.x, y: prev.y, yaw: prev.yaw || 0, phase: prev.phase };
  }

  function hitTest() { return ''; }

  // 是否"在岗"：平台会沿自己的边界段巡视，不能再用"离指定点几米"判断，
  // 否则巡视中的平台会被画成灰色脱岗、监视圈也消失。
  function distToPolyline(p, poly) {
    let best = Infinity;
    for (let i = 1; i < poly.length; i++) {
      const a = poly[i - 1], b = poly[i];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const len2 = dx * dx + dy * dy;
      const t = len2 <= 1e-9 ? 0 : Math.max(0, Math.min(1,
        ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
      const qx = a[0] + dx * t, qy = a[1] + dy * t;
      best = Math.min(best, Math.hypot(p[0] - qx, p[1] - qy));
    }
    return best;
  }

  function onStation(st, pid, pos) {
    const role = String((st.roles || {})[pid] || '');
    if (role.startsWith('air')) return true;   // 空中监视一直在自己的空域里
    const sector = (st.sectors || []).find((s) => s.pid === pid);
    if (sector && sector.boundary && sector.boundary.length > 1) {
      const band = (st.standoff_m || 12) + 25;
      return distToPolyline(pos, sector.boundary) <= band;
    }
    const gate = (st.gates || []).find((g) => {
      const role = String((st.roles || {})[pid] || '');
      return role === 'gate:' + (g.gate_id || '');
    });
    if (gate) {
      const radius = (gate.width || 12) / 2 + 20;
      return Math.hypot(pos[0] - gate.point[0], pos[1] - gate.point[1]) <= radius;
    }
    const post = (st.post_plan || []).find((p) => p.pid === pid);
    return post ? Math.hypot(pos[0] - post.point[0], pos[1] - post.point[1]) <= 20 : false;
  }

  function draw() {
    const canvas = el('#ck-canvas');
    if (!canvas || !C.data) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 4) return;
    const dpr = window.devicePixelRatio || 1;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = '#f4f6f1';
    ctx.fillRect(0, 0, rect.width, rect.height);
    const st = structure();
    const [P, scale] = projectFactory(canvas);
    const t = C.t;
    const labelBoxes = [];
    // 标注避让：同一时刻各平台/目标可能挤在一起（如集结待命时），
    // 逐字叠加会糊成一团，按矩形碰撞跳过次要标注。
    const placeLabel = (text, x, y, color) => {
      ctx.font = '10px "Segoe UI","Microsoft YaHei"';
      const w = ctx.measureText(text).width + 6;
      const candidates = [[x, y], [x, y + 16], [x, y - 16], [x, y + 30]];
      for (const [cx, cy] of candidates) {
        const box = [cx - 2, cy - 11, w, 14];
        const clash = labelBoxes.some((b) => !(box[0] > b[0] + b[2] || box[0] + box[2] < b[0]
          || box[1] > b[1] + b[3] || box[1] + box[3] < b[1]));
        if (clash) continue;
        labelBoxes.push(box);
        ctx.fillStyle = 'rgba(255,255,255,0.82)';
        ctx.fillRect(box[0], box[1], box[2], box[3]);
        ctx.fillStyle = color || '#0f172a';
        ctx.fillText(text, box[0] + 3, cy);
        return true;
      }
      return false;
    };
    const poly = (pts, close = true) => {
      if (!pts || pts.length < 2) return;
      ctx.beginPath();
      pts.forEach((p, i) => { const a = P(p); i ? ctx.lineTo(...a) : ctx.moveTo(...a); });
      if (close) ctx.closePath();
    };

    // 规划路径（4.2 计划里的 A* 航迹）与集结点：先画，压在所有要素下面
    const routes = planAssignments();
    if (routes.length) {
      for (const route of routes) {
        const path = route.path || [];
        if (path.length < 2) continue;
        const w = workerOf(route);
        const color = (w && w.color) || '#64748b';
        poly(path, false);
        ctx.setLineDash([7, 5]);
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
        // 终点箭头：标清"规划去哪个占位点"
        const a = P(path[path.length - 2]), b = P(path[path.length - 1]);
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(b[0], b[1]);
        ctx.lineTo(b[0] - 8 * Math.cos(ang - 0.4), b[1] - 8 * Math.sin(ang - 0.4));
        ctx.lineTo(b[0] - 8 * Math.cos(ang + 0.4), b[1] - 8 * Math.sin(ang + 0.4));
        ctx.closePath();
        ctx.fill();
      }
      const start = assemblyPoints();
      if (start.length) {
        const cx = start.reduce((s, p) => s + p[0], 0) / start.length;
        const cy = start.reduce((s, p) => s + p[1], 0) / start.length;
        const c = P([cx, cy]);
        ctx.beginPath();
        ctx.arc(c[0], c[1], 9, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(71,85,105,0.16)';
        ctx.fill();
        ctx.strokeStyle = '#475569';
        ctx.setLineDash([3, 2]);
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#334155';
        ctx.font = '11px "Segoe UI","Microsoft YaHei"';
        placeLabel('集结待机区', c[0] + 12, c[1] + 4, '#334155');
      }
    }

    // 封控区
    if (st.area && st.area.length) {
      poly(st.area);
      ctx.fillStyle = 'rgba(194,65,12,0.06)';
      ctx.fill();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = COLORS.area;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.setLineDash([]);
      const c = P(st.center || st.area[0]);
      ctx.fillStyle = 'rgba(194,65,12,0.85)';
      ctx.font = '11px "Segoe UI","Microsoft YaHei"';
      ctx.textAlign = 'center';
      ctx.fillText('封控区 · ' + Math.round(st.perimeter_m || 0) + ' m 边界', c[0], c[1] - 6);
      ctx.textAlign = 'left';
    }

    // 每段边界：按平台着色，段中点写占位平台
    // 每段边界：按段号着色，段中点写占位平台
    (st.sectors || []).forEach((sector, i) => {
      const color = SECTOR_COLORS[i % SECTOR_COLORS.length];
      poly(sector.boundary, false);
      ctx.strokeStyle = color;
      ctx.lineWidth = 4;
      ctx.stroke();
      const post = (st.post_plan || []).find((p) => p.pid === sector.pid);
      if (post) {
        const a = P(post.point), b = P(post.mid || post.point);
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
        ctx.setLineDash([]);
      }
    });

    // 通道口
    (st.gates || []).forEach((gate) => {
      const dir = gate.direction || [0, 1];
      const ang = Math.atan2(dir[1], dir[0]);
      const nx = -Math.sin(ang), ny = Math.cos(ang);
      const half = (gate.width || 12) / 2;
      const p1 = [gate.point[0] - nx * half, gate.point[1] - ny * half];
      const p2 = [gate.point[0] + nx * half, gate.point[1] + ny * half];
      const a = P(p1), b = P(p2);
      ctx.strokeStyle = COLORS.gate;
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
      const mid = P(gate.point);
      ctx.fillStyle = COLORS.gate;
      ctx.font = '10px "Segoe UI","Microsoft YaHei"';
      const W = canvas.getBoundingClientRect().width;
      const right = mid[0] > W / 2;
      ctx.textAlign = right ? 'right' : 'left';
      ctx.fillText((gate.gate_id || '通道') + ' 通道口', mid[0] + (right ? -7 : 7),
        mid[1] - 9);
      ctx.textAlign = 'left';
    });

    // 在位平台的监视范围与站位
    const roles = st.roles || {};
    (st.post_plan || []).forEach((post) => {
      const agent = agentAt(post.pid, t);
      const onPost = agent ? onStation(st, post.pid, [agent.x, agent.y]) : false;
      const roleKind = String(post.role || '').split(':')[0];
      if (onPost && roleKind !== 'intercept' && roleKind !== 'reserve') {
        const c = P([agent.x, agent.y]);
        const r = Math.max(6, (st.sensor_radius_m || 35) * scale);
        ctx.beginPath();
        ctx.arc(c[0], c[1], r, 0, Math.PI * 2);
        ctx.fillStyle = roleKind === 'air'
          ? 'rgba(37,99,235,0.06)' : 'rgba(13,148,136,0.07)';
        ctx.fill();
        ctx.strokeStyle = roleKind === 'air'
          ? 'rgba(37,99,235,0.45)' : 'rgba(13,148,136,0.35)';
        ctx.setLineDash([2, 3]);
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
      }
      const q = P(post.point);
      ctx.beginPath();
      ctx.arc(q[0], q[1], 3.2, 0, Math.PI * 2);
      ctx.fillStyle = onPost ? COLORS.post : '#94a3b8';
      ctx.fill();
    });

    // 目标轨迹与当前位姿
    const events = (C.data.events || []);
    for (const tgt of (result().targets || [])) {
      const track = (tgt.track || []).filter((p) => p[0] <= t);
      if (track.length > 1) {
        poly(track.map((p) => [p[1], p[2]]), false);
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = tgt.authorized ? COLORS.passed : COLORS.unauthorized;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
      }
      // 起点与目标点
      const s = P(tgt.start), g = P(tgt.goal);
      ctx.strokeStyle = tgt.authorized ? 'rgba(37,99,235,0.5)' : 'rgba(220,38,38,0.5)';
      ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(...s); ctx.lineTo(...g); ctx.stroke();
      ctx.setLineDash([]);
      if (t < (tgt.track?.[0]?.[0] ?? 0)) continue;
      const pos = targetAt(tgt, t);
      const q = P(pos);
      const state = targetStateAt(tgt, t);
      if (state === '待出现') continue;
      const color = stateColor(state);
      ctx.beginPath();
      ctx.arc(q[0], q[1], 7, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = '#0f172a';
      ctx.font = '11px "Segoe UI","Microsoft YaHei"';
      const label = tgt.target_id + (tgt.authorized ? ' · 已授权' : '');
      placeLabel(label, q[0] + 11, q[1] - 4, '#0f172a');
      placeLabel(state, q[0] + 11, q[1] + 9, color);
      // 警告圈：只在警告之后的一小段时间显示
      const warnedAt = events.find((e) => e.kind === 'warning_issued' && e.target_id === tgt.target_id);
      if (warnedAt && t >= warnedAt.t && t <= warnedAt.t + 6) {
        const r = 10 + (t - warnedAt.t) * 9;
        ctx.beginPath();
        ctx.arc(q[0], q[1], r, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(217,119,6,' + Math.max(0, 1 - (t - warnedAt.t) / 6) + ')';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    // 拦阻连线
    for (const tgt of (result().targets || [])) {
      if (!tgt.interceptor) continue;
      const assigned = events.find((e) => e.kind === 'intercept_assigned' && e.target_id === tgt.target_id);
      const done = events.find((e) => e.kind === 'intercepted' && e.target_id === tgt.target_id);
      if (!assigned || t < assigned.t || (done && t > done.t + 2)) continue;
      const a = agentAt(tgt.interceptor, t);
      if (!a) continue;
      const p1 = P([a.x, a.y]), p2 = P(targetAt(tgt, t));
      ctx.strokeStyle = 'rgba(124,58,237,0.85)';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 3]);
      ctx.beginPath(); ctx.moveTo(...p1); ctx.lineTo(...p2); ctx.stroke();
      ctx.setLineDash([]);
      const mid = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
      ctx.fillStyle = '#7c3aed';
      ctx.font = '10px "Segoe UI","Microsoft YaHei"';
      ctx.fillText('拦阻', mid[0] + 4, mid[1] - 4);
    }

    // 平台
    for (const pid of Object.keys(roles)) {
      const a = agentAt(pid, t);
      if (!a) continue;
      const w = workers().find((x) => x.pid === pid);
      const q = P([a.x, a.y]);
      const onPost = onStation(st, pid, [a.x, a.y]);
      const color = onPost ? '#0f766e' : '#475569';
      if (typeof window.drawPlatformIcon === 'function') {
        window.drawPlatformIcon(ctx, w ? w.kind : 'UGV', q[0], q[1], 11, a.yaw, color);
      } else {
        ctx.beginPath(); ctx.arc(q[0], q[1], 5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
      }
      if (onPost || String(st.roles[pid] || '').startsWith('intercept')) {
        let text = shortPid(pid) + ' ' + roleName(st.roles[pid]).split(' · ')[0];
        const airPost = (st.post_plan || []).find((p) => p.pid === pid && p.altitude_m);
        if (airPost) text += ' · ' + num(airPost.altitude_m, 0) + ' m';
        placeLabel(text, q[0] + 11, q[1] - 6, '#0f172a');
      }
    }

    // 图例时间
    ctx.fillStyle = 'rgba(255,255,255,0.92)';
    ctx.fillRect(rect.width - 132, 10, 122, 26);
    ctx.strokeStyle = '#dbe3dc';
    ctx.strokeRect(rect.width - 132, 10, 122, 26);
    ctx.fillStyle = '#0f172a';
    ctx.font = '12px "Segoe UI","Microsoft YaHei"';
    ctx.fillText('T+' + num(t, 1) + ' s', rect.width - 122, 27);
  }

  // ---------------------------------------------------------------- 对外
  // 区域封控是"演示总览"的一个视图（与全局分配并列），不是独立页面：
  // show/hide 由 app.js 的视图切换调用，页面级导航不参与。
  function show() {
    C.visible = true;
    if (!C.built) renderAll();
    requestAnimationFrame(() => {
      resize();
      draw();
      if (C.data && !C.autoPlayed) { C.autoPlayed = true; setPlaying(true); }
    });
  }

  function hide() {
    C.visible = false;
    C.playing = false;
    const btn = el('#ck-play');
    if (btn) btn.textContent = '▶ 播放';
  }

  // 两个视角共用同一轮运行，切换时把时刻带过去，避免"切过去又是 T+0"。
  function syncTime(t) {
    C.t = Math.max(0, Math.min(endTime(), Number(t) || 0));
    const scrub = el('#ck-scrub'), label = el('#ck-time');
    if (scrub) scrub.value = C.t;
    if (label) label.textContent = num(C.t, 1) + ' / ' + Math.round(endTime()) + ' s';
  }

  function time() { return C.t; }

  window.ContainmentPage = {
    load: load,
    show: show,
    hide: hide,
    draw: draw,
    syncTime: syncTime,
    time: time,
    hasData: () => !!C.data,
  };
})();
