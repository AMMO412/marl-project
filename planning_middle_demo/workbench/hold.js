/* 要点坚守（T-HLD）回放页
 *
 * 数据只来自 /api/runs 返回的 replay.hold（由 trajectory_v2 从审计记录抽取）：
 * 要点、阵位（含朝向）、威胁方向、在位区间、轮换/增援/撤离时间线与逐项判定。
 * 本文件不重算几何、不推算指标——阵位点和威胁扇区都是后端算好的顶点。
 *
 * 与总览页共用 state.run，但有自己的时钟：总览看全局任务，这里看"谁守哪个
 * 阵位、第几秒接替、增援第几秒到、最后是不是按时撤了"。
 */
(function () {
  'use strict';

  const C = {
    data: null, jobId: null, t: 0, playing: false, speed: 3,
    raf: null, last: 0, built: false, bounds: null,
    cam: 'area', visible: false, showRoutes: false,
  };
  const COLORS = {
    key: '#1d4ed8', post: '#0f766e', postOff: '#94a3b8',
    reserve: '#7c3aed', support: '#0891b2', relay: '#64748b',
    threat: '#b91c1c', enemy: '#b91c1c', reinforce: '#ea580c',
    withdraw: '#475569', effect: '#b45309', air: '#2563eb',
  };
  const EVENT_TICK = {
    control_established: '#0f766e', control_interrupted: '#b45309',
    control_restored: '#0f766e', control_lost: '#991b1b',
    observation_gap: '#b45309', observation_restored: '#0f766e',
    enemy_attack: '#b91c1c', post_lost: '#991b1b',
    post_suppressed: '#b45309', post_restored: '#0f766e',
    counter_attack: '#b45309', attack_repelled: '#0f766e',
    attack_unresolved: '#b45309', effect_adjudicated: '#b45309',
    handover_start: '#1d4ed8', handover_complete: '#1d4ed8',
    reinforce_triggered: '#ea580c', reinforce_arrived: '#0f766e',
    reinforce_timeout: '#991b1b', relief_skipped: '#94a3b8',
    withdraw_started: '#475569', withdrawn: '#0f766e',
    withdraw_timeout: '#991b1b',
  };
  const EVENT_TEXT = {
    control_established: '控制建立', control_interrupted: '控制中断',
    control_restored: '控制恢复', control_lost: '控制权丧失',
    observation_gap: '观察中断', observation_restored: '观察恢复',
    enemy_attack: '敌方进攻', post_lost: '阵位失守',
    post_suppressed: '阵位被压制', post_restored: '阵位恢复',
    counter_attack: '阵内反击（抽象效果）', counter_attack_denied: '无反击授权',
    counter_attack_out_of_range: '超出反击范围',
    effect_adjudicated: '效果桩判定', attack_repelled: '进攻被击退（桩判定）',
    attack_unresolved: '进攻未解除',
    handover_start: '接替开始', handover_complete: '接替完成',
    handover_timeout: '接替超时', handover_aborted: '接替中止',
    relief_skipped: '轮换跳过',
    reinforce_triggered: '增援触发', reinforce_arrived: '增援到位',
    reinforce_timeout: '增援超时', reinforce_unavailable: '无可用增援',
    reinforce_aborted: '增援中止',
    withdraw_started: '撤离开始', withdrawn: '撤离完成',
    withdraw_timeout: '撤离超时',
  };

  const el = (s) => document.querySelector(s);
  function appState() {
    try { return typeof state !== 'undefined' ? state : null; } catch (e) { return null; }
  }
  const num = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const shortPid = (pid) => String(pid || '').replace('rover_', '#');

  // ---------------------------------------------------------------- 数据
  function load(run) {
    C.data = (run && run.replay && run.replay.hold) || null;
    C.jobId = C.data ? C.data.job_id : null;
    C.built = false;
    C.playing = false;
    C.autoPlayed = false;
    C.cam = 'area';
    C.camAuto = false;
    C.showRoutes = false;
    C.t = 0;
    C.bounds = null;
    if (!C.data) { renderEmpty(run); return; }
    renderAll();
  }

  function structure() { return C.data.structure || {}; }
  function result() { return C.data.result || {}; }
  function metrics() { return result().metrics || {}; }
  function workers() {
    const s = appState();
    return (s && s.run && s.run.replay && s.run.replay.workers) || [];
  }
  function currentRun() {
    const s = appState();
    return (s && s.run) || null;
  }
  function planAssignments() {
    const run = currentRun();
    const plan = run && run.plan;
    if (!plan || !Array.isArray(plan.assignments)) return [];
    return plan.assignments.filter((a) => !a.task_id || a.task_id === C.jobId);
  }

  function endTime() {
    let end = (result().sim_s || 0) + 1;
    for (const e of (C.data.events || [])) end = Math.max(end, (e.t || 0) + 1);
    const st = structure();
    const dur = Number(st.duration_s || 0);
    const est = (result().metrics || {}).control_established_at_s;
    if (est != null && dur) end = Math.max(end, est + dur + (st.withdraw || {}).deadline_s || 0);
    for (const w of workers()) {
      for (const s of (w.samples || [])) {
        if (s.job === C.jobId) end = Math.max(end, s.t);
      }
    }
    return Math.ceil(Math.max(end, 10));
  }

  function workerSamples(pid) {
    const w = workers().find((x) => x.pid === pid);
    return (w && w.samples) ? w.samples.filter((s) => s.job === C.jobId) : [];
  }

  function agentAt(pid, t) {
    const samples = workerSamples(pid);
    if (!samples.length) return null;
    let prev = samples[0];
    for (const s of samples) {
      if (s.t <= t) prev = s;
      else {
        const f = (t - prev.t) / Math.max(1e-6, s.t - prev.t);
        return { x: prev.x + (s.x - prev.x) * f, y: prev.y + (s.y - prev.y) * f,
                 yaw: prev.yaw || 0, phase: prev.phase };
      }
    }
    return { x: prev.x, y: prev.y, yaw: prev.yaw || 0, phase: prev.phase };
  }

  // 某阵位在 t 时刻由谁在位：直接查后端记录的占用区间，不在前端反推。
  function occupantAt(postId, t) {
    for (const position of (result().positions || [])) {
      if (position.id !== postId) continue;
      for (const row of (position.occupants || [])) {
        const leave = row.leave_s == null ? Infinity : row.leave_s;
        if (t >= (row.enter_s || 0) && t < leave) return row.pid;
      }
    }
    return null;
  }

  function eventAt(kinds, t) {
    return (C.data.events || []).find(
      (e) => kinds.includes(e.kind) && (e.t || 0) <= t) || null;
  }

  function phaseNow(t) {
    const st = structure();
    const est = metrics().control_established_at_s;
    const wd = (C.data.events || []).find((e) => e.kind === 'withdraw_started');
    if (wd && t >= (wd.t || 0)) {
      const done = (C.data.events || []).find((e) => e.kind === 'withdrawn');
      return done && t >= (done.t || 0) ? '已撤离' : '撤离中';
    }
    if (est == null) return '机动进场';
    if (t < est) return '机动进场';
    const h = (C.data.events || []).find(
      (e) => e.kind === 'handover_start' && t < (e.t || 0) + 12);
    if (h && t >= (h.t || 0)) return '接替';
    const r = (C.data.events || []).find(
      (e) => e.kind === 'reinforce_triggered' && t < (e.t || 0) + 20);
    if (r && t >= (r.t || 0)) return '增援';
    return '坚守在位';
  }

  // ---------------------------------------------------------------- 面板
  function renderEmpty(run) {
    const host = el('#hl-body');
    if (!host) return;
    host.innerHTML = '<div class="ck-empty"><div class="ck-empty-icon">◈</div>' +
      '<h3>本次运行不含要点坚守</h3>' +
      '<p>“要点坚守”页只回放 T-HLD 任务的实际执行记录：阵位占位、观察中断、' +
      '接替轮换、增援与撤离、以及桩判定的抽象效果。当前运行' +
      (run ? '（' + esc(run.id) + '）' : '') + '没有这些记录，因此不画示意图。</p>' +
      '<button class="button primary" id="hl-start">运行一次要点坚守演示 →</button></div>';
    const btn = el('#hl-start');
    if (btn) btn.addEventListener('click', () => {
      const dialog = el('#config-dialog');
      const select = el('#config-scenario');
      if (select) select.value = 'interop_hold';
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
    if (!st || !st.positions) { renderEmpty(currentRun()); return; }
    const m = metrics();
    const est = m.control_established_at_s;
    const cards = [
      ['控制保持率', num((m.control_hold_ratio || 0) * 100, 0) + '%',
        '控制在位时间 / 坚守时段 · 要求 ' +
        num((result().items || []).find((i) => i.id === 'control_hold_ratio')?.target * 100 || 90, 0) + '%',
        (m.control_hold_ratio || 0) >= 0.9],
      ['控制中断时间', num(m.control_interruption_s, 1) + ' s',
        '在位数量低于下限的累计时长 · 下限 ' + (st.min_on_post || 0) + ' 台',
        (m.control_interruption_s || 0) <= 30],
      ['最长观察中断', num(m.observation_gap_max_s, 1) + ' s',
        '阵位覆盖为空的最长连续时长 · 允许 ' + num((st.observation_gap_max_s || 8), 0) + ' s',
        (m.observation_gap_max_s || 0) <= (st.observation_gap_max_s || 8)],
      ['增援到达', (m.reinforcements || []).length
        ? num((m.reinforcements[0] || {}).arrival_s, 1) + ' s' : '未触发',
        (m.reinforcements || []).length
          ? '触发 → 到位；共 ' + m.reinforcements.length + ' 次'
          : '本次没有触发增援条件', null],
      ['敌方突破', num(m.enemy_breaches, 0) + ' 次',
        '敌方进入要点/阵位的事件数 · 进攻 ' + num(m.enemy_attacks, 0) + ' 次', (m.enemy_breaches || 0) === 0],
      ['接替与损失', num(m.relief_count, 0) + ' / ' + num(m.our_losses, 0),
        '完成接替次数 / 我方损失台数（损失计代价，非失败必要条件）', null],
    ];
    const kpis = cards.map(([label, value, note, ok]) =>
      '<article class="ck-kpi' + (ok === true ? ' ok' : ok === false ? ' bad' : '') + '">' +
      '<div class="ck-kpi-label">' + esc(label) + '</div>' +
      '<div class="ck-kpi-value">' + esc(value) + '</div>' +
      '<div class="ck-kpi-note">' + esc(note) + '</div></article>').join('');

    const items = (result().items || []).map((it) =>
      '<li class="' + (it.ok ? 'ok' : 'bad') + '">' +
      '<span class="ck-check">' + (it.ok ? '✓' : '✕') + '</span>' +
      '<span><b>' + esc(it.label) + '</b> = ' + esc(String(it.value)) +
      (it.target == null ? '' : '（要求 ' + esc(String(it.target)) + '）') +
      (it.required ? '' : '<em class="muted"> 辅助</em>') +
      (it.note ? '<em class="muted"> · ' + esc(it.note) + '</em>' : '') + '</span></li>').join('');

    const events = (C.data.events || []).slice().sort((a, b) => (a.t || 0) - (b.t || 0));
    const timeline = events.map((e) =>
      '<li data-t="' + (e.t || 0) + '"><time>' + num(e.t || 0, 0) + 's</time>' +
      '<span>' + esc(EVENT_TEXT[e.kind] || e.kind) +
      (e.post_id ? ' · ' + esc(e.post_id) : '') +
      (e.pid ? ' · ' + esc(shortPid(e.pid)) : '') +
      (e.attack_kind ? ' · ' + esc(e.attack_kind) : '') +
      (e.overall ? ' · ' + esc(e.overall) : '') +
      '</span></li>').join('') || '<li class="muted">尚无坚守过程事件</li>';

    const effects = (C.data.result && C.data.result.effects) || [];
    const effectRow = effects.length
      ? effects.map((e) => '<li><b>' + esc(e.post_id) + '</b> · 压制桩判定 ' +
        esc(e.overall) + ' · <em class="muted">verified=false · ' +
        esc(e.adjudicator) + '</em></li>').join('')
      : '<li class="muted">本次未触发阵内反击（抽象效果）</li>';

    const host = el('#hl-body');
    host.innerHTML =
      '<div class="ck-head">' +
        '<div class="ck-head-main"><div><div class="eyebrow">KEY POINT HOLD · T-HLD</div>' +
        '<h2>' + esc(C.jobId) + ' 要点坚守' + verdictPill() + '</h2></div>' +
        '<div class="ck-head-right"><div class="ck-chips">' +
          '<span>要点 ' + (st.key_point || []).map((v) => num(v, 0)).join(', ') + '</span>' +
          '<span>' + (st.positions || []).length + ' 个阵位</span>' +
          '<span>在位下限 ' + num(st.min_on_post, 0) + ' 台</span>' +
          '<span>全向覆盖 ' + num((m.observation_coverage_mean || 0) * 100, 0) + '%</span>' +
          (st.air_units && st.air_units.length
            ? '<span>空中观察 ' + st.air_units.length + ' 架 · ' +
              num(st.air_altitude_m, 0) + ' m</span>' : '') +
          '<span>判定口径 ' + esc(st.hold_criteria_label || st.hold_criteria) + '</span>' +
          '<span>坚守时段 ' + num(st.duration_s, 0) + ' s</span>' +
          '<span>控制建立 ' + (est == null ? '未建立' : num(est, 1) + ' s') + '</span>' +
        '</div>' +
        '<button class="button small" data-hl-back>← 返回全局分配</button></div></div>' +
        '<p class="ck-reason">' + esc(result().reason || '') + '</p>' +
        '<p class="ck-reason muted">' + esc(st.scope || '') + '</p>' +
      '</div>' +
      '<div class="ck-kpis">' + kpis + '</div>' +
      '<div class="ck-layout">' +
        '<article class="card ck-map-card">' +
          '<div class="card-heading"><div><div class="eyebrow">HOLD PICTURE</div>' +
          '<h2>要点 · 阵位 · 威胁方向</h2></div>' +
          '<div class="ck-map-actions">' +
            '<button class="button small' + (C.cam === 'all' ? ' active' : '') + '" id="hl-cam-all">全程 · 集结→撤离</button>' +
            '<button class="button small' + (C.cam === 'area' ? ' active' : '') + '" id="hl-cam-area">要点区</button>' +
            '<button class="button small' + (C.showRoutes ? ' active' : '') + '" id="hl-routes" title="只影响显示，不改变回放数据">规划路径</button>' +
            '<button class="button small" id="hl-fit">⌖ 适应视图</button>' +
          '</div></div>' +
          '<div class="ck-legend" id="hl-legend">' +
            '<span><i style="background:' + COLORS.key + '"></i>要点</span>' +
            '<span><i style="background:' + COLORS.post + '"></i>阵位在位</span>' +
            '<span><i style="background:' + COLORS.postOff + '"></i>阵位空缺</span>' +
            '<span><i style="background:' + COLORS.post + '55"></i>探测圈（跟随在位平台）</span>' +
            '<span><i style="background:' + COLORS.threat + '"></i>威胁方向</span>' +
            '<span><i style="background:' + COLORS.air + '"></i>空中观察</span>' +
            '<span><i style="background:' + COLORS.reinforce + '"></i>增援</span>' +
            '<span><i style="background:' + COLORS.withdraw + '"></i>撤离</span>' +
          '</div>' +
          '<canvas id="hl-canvas"></canvas>' +
          '<div class="ck-ticker" id="hl-ticker"></div>' +
          '<div class="ck-ribbon" id="hl-ribbon" aria-label="坚守过程事件分布"></div>' +
          '<div class="ck-clock">' +
            '<button class="button small" id="hl-play">▶ 播放</button>' +
            '<input type="range" id="hl-scrub" min="0" max="' + Math.round(endTime()) + '" value="0" step="0.5">' +
            '<span id="hl-time">0.0 / ' + Math.round(endTime()) + ' s</span>' +
            '<label class="ck-speed">速度<select id="hl-rate">' +
              [1, 3, 6].map((v) => '<option value="' + v + '"' + (v === C.speed ? ' selected' : '') + '>' + v + '×</option>').join('') +
            '</select></label>' +
          '</div>' +
        '</article>' +
        '<aside class="ck-side">' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">POST OCCUPANCY</div>' +
          '<h2>阵位在位甘特</h2></div><span class="pill">' + (st.positions || []).length + ' 个</span></div>' +
          '<div class="hl-gantt" id="hl-gantt"></div>' +
          '<p class="card-foot">条=实际进入/离开记录（换人即断开）；◆=接替完成时刻，▲=增援到位。</p></article>' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">VERDICT ITEMS</div>' +
          '<h2>逐项判定</h2></div></div><ul class="ck-items">' + (items || '<li class="muted">未记录判定项</li>') + '</ul>' +
          '<p class="card-foot">' + esc(result().evidence || '') + '</p></article>' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">ABSTRACT EFFECT</div>' +
          '<h2>桩判定（未验证）</h2></div></div><ul class="ck-items">' + effectRow + '</ul>' +
          '<p class="card-foot">效果类条目不作战果：由 assessment.Adjudicator 桩判定输出，verified=false。</p></article>' +
          '<article class="card"><div class="card-heading"><div><div class="eyebrow">HOLD TIMELINE</div>' +
          '<h2>坚守过程时间线</h2></div></div><ul class="ck-timeline" id="hl-timeline">' + timeline + '</ul></article>' +
        '</aside>' +
      '</div>';
    bind();
  }

  function bind() {
    const play = el('#hl-play'), scrub = el('#hl-scrub'), rate = el('#hl-rate');
    if (play) play.addEventListener('click', () => setPlaying(!C.playing));
    if (scrub) scrub.addEventListener('input', () => { setPlaying(false); seek(Number(scrub.value)); });
    if (rate) rate.addEventListener('change', () => { C.speed = Number(rate.value) || 3; });
    const fit = el('#hl-fit');
    if (fit) fit.addEventListener('click', () => { C.bounds = null; draw(); });
    const setCam = (mode) => {
      C.cam = mode; C.camAuto = false; C.bounds = null;
      const all = el('#hl-cam-all'), area = el('#hl-cam-area');
      if (all) all.classList.toggle('active', mode === 'all');
      if (area) area.classList.toggle('active', mode === 'area');
      draw();
    };
    const camAll = el('#hl-cam-all'), camArea = el('#hl-cam-area');
    if (camAll) camAll.addEventListener('click', () => setCam('all'));
    if (camArea) camArea.addEventListener('click', () => setCam('area'));
    const routesBtn = el('#hl-routes');
    if (routesBtn) routesBtn.addEventListener('click', () => {
      C.showRoutes = !C.showRoutes;
      routesBtn.classList.toggle('active', C.showRoutes);
      draw();
    });
    buildRibbon();
    buildGantt();
    updateTicker();
    const timeline = el('#hl-timeline');
    if (timeline) timeline.addEventListener('click', (e) => {
      const li = e.target.closest('li[data-t]');
      if (li) { setPlaying(false); seek(Number(li.dataset.t)); }
    });
    C.built = true;
    requestAnimationFrame(() => { resize(); draw(); });
  }

  // ---------------------------------------------------------------- 时钟
  function setPlaying(on) {
    C.playing = !!on;
    const btn = el('#hl-play');
    if (btn) btn.textContent = C.playing ? 'Ⅱ 暂停' : '▶ 播放';
    if (C.playing) {
      if (C.t >= endTime()) C.t = 0;
      C.last = performance.now();
      if (!C.raf) C.raf = requestAnimationFrame(tick);
    }
  }

  function seek(t) {
    C.t = Math.max(0, Math.min(endTime(), t));
    const scrub = el('#hl-scrub'), label = el('#hl-time');
    if (scrub) scrub.value = C.t;
    if (label) label.textContent = num(C.t, 1) + ' / ' + Math.round(endTime()) + ' s';
    updateTicker();
    draw();
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

  // 事件分布条：把"第几秒发生了什么"铺在时间轴上，点一下跳到那一刻。
  function buildRibbon() {
    const ribbon = el('#hl-ribbon');
    if (!ribbon) return;
    const end = Math.max(1, endTime());
    ribbon.innerHTML = (C.data.events || []).map((e) => {
      const pct = Math.max(0, Math.min(100, (e.t || 0) / end * 100));
      const color = EVENT_TICK[e.kind] || '#94a3b8';
      const title = (EVENT_TEXT[e.kind] || e.kind) +
        (e.post_id ? ' · ' + e.post_id : '') + ' · T+' + Math.round(e.t || 0) + 's';
      return '<i style="left:' + pct.toFixed(2) + '%;--c:' + color + '" title="' +
        esc(title) + '" data-t="' + (e.t || 0) + '"></i>';
    }).join('');
    ribbon.addEventListener('click', (ev) => {
      const item = ev.target.closest('i[data-t]');
      if (item) { setPlaying(false); seek(Number(item.dataset.t)); }
    });
  }

  // 阵位在位甘特：每行一个阵位，条来自后端记录的进入/离开区间。
  function buildGantt() {
    const host = el('#hl-gantt');
    if (!host) return;
    const end = Math.max(1, endTime());
    const pct = (v) => Math.max(0, Math.min(100, (v / end) * 100));
    const handovers = (result().handovers || []);
    const arrivals = (result().reinforcements || []);
    host.innerHTML = (structure().positions || []).map((position) => {
      const rows = (result().positions || []).find((p) => p.id === position.id);
      const bars = ((rows && rows.occupants) || []).map((row) => {
        const left = pct(row.enter_s || 0);
        const right = pct(row.leave_s == null ? end : row.leave_s);
        return '<i class="hl-bar" style="left:' + left.toFixed(2) + '%;width:' +
          Math.max(0.6, right - left).toFixed(2) + '%" title="' +
          esc(shortPid(row.pid) + ' ' + num(row.enter_s, 0) + '→' +
              (row.leave_s == null ? '结束' : num(row.leave_s, 0)) + 's') + '"></i>';
      }).join('');
      const marks = handovers.filter((h) => h.post_id === position.id).map((h) =>
        '<b class="hl-mark" style="left:' + pct(h.completed_s || 0).toFixed(2) +
        '%" title="接替完成 ' + num(h.completed_s, 0) + 's"></b>').join('');
      const reinf = arrivals.filter((r) => r.post_id === position.id).map((r) =>
        '<b class="hl-mark reinf" style="left:' + pct(r.arrived_s || 0).toFixed(2) +
        '%" title="增援到位 ' + num(r.arrived_s, 0) + 's"></b>').join('');
      return '<div class="hl-gantt-row"><span class="hl-gantt-label">' + esc(position.id) +
        '<em>' + num(position.facing_deg, 0) + '°</em></span>' +
        '<div class="hl-gantt-track">' + bars + marks + reinf + '</div></div>';
    }).join('') || '<p class="muted">没有阵位在位记录</p>';
  }

  function updateTicker() {
    const box = el('#hl-ticker');
    if (!box) return;
    const phase = phaseNow(C.t);
    const chip = (text, cls) => '<span class="ck-chip ' + (cls || '') + '">' + esc(text) + '</span>';
    const manned = (structure().positions || []).map((p) => {
      const pid = occupantAt(p.id, C.t);
      return chip(p.id + (pid ? ' · ' + shortPid(pid) : ' · 空缺'), pid ? 'on' : 'out');
    }).join('');
    box.innerHTML = chip('T+' + num(C.t, 1) + ' s · ' + phase, 'phase') + manned;
  }

  // ---------------------------------------------------------------- 画布
  function resize() {
    const canvas = el('#hl-canvas');
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
    if (st.key_point) pts.push(st.key_point);
    for (const p of (st.positions || [])) pts.push(p.point);
    for (const s of (st.threat_sectors || [])) (s.polygon || []).forEach((p) => pts.push(p));
    if (C.cam === 'all') {
      for (const a of planAssignments()) for (const p of (a.path || [])) pts.push(p);
      if (st.standby) pts.push(st.standby);
      const w = st.withdraw || {};
      (w.route || []).forEach((p) => pts.push(p));
    }
    if (!pts.length) return [0, 0, 100, 100];
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    // 探测圈/盘旋圈比阵位本身大得多：按半径外扩，否则"圆形覆盖"被画布裁掉。
    const ringPad = Math.max(Number(st.sensor_radius_m) || 0,
                             Number(st.air_orbit_radius_m) || 0) * 0.9;
    const pad = Math.max(10, Math.max(Math.max(...xs) - Math.min(...xs),
                                      Math.max(...ys) - Math.min(...ys)) * 0.08,
                         ringPad);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad,
            Math.max(...xs) + pad, Math.max(...ys) + pad];
  }

  function draw() {
    const canvas = el('#hl-canvas');
    if (!canvas || !C.data) return;
    const st = structure();
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = window.devicePixelRatio || 1;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = '#f7faf8';
    ctx.fillRect(0, 0, rect.width, rect.height);

    const b = C.bounds || (C.bounds = computeBounds());
    const W = rect.width, H = rect.height;
    const scale = Math.min((W - 40) / Math.max(1e-6, b[2] - b[0]),
                           (H - 40) / Math.max(1e-6, b[3] - b[1]));
    const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    const P = (p) => [W / 2 + (p[0] - cx) * scale, H / 2 - (p[1] - cy) * scale];
    const t = C.t;
    const roles = st.roles || {};
    const labels = [];
    const placed = [];
    const placeLabel = (text, x, y, color) => {
      ctx.font = '11px "Segoe UI","Microsoft YaHei"';
      const w = ctx.measureText(text).width + 10, h = 17;
      // 矩形避让：放不下就不画，宁缺不叠字（与封控页同一规则）。首个候选
      // 偏移留出 16 px，避开 11 px 半径的平台图标（否则图标压住阵位编号）。
      for (const [dx, dy] of [[16, -26], [16, 8], [-w - 16, -26], [-w - 16, 8],
        [16, -48], [-w - 16, 30], [22, 24], [-w - 22, -44]]) {
        const box = { x: x + dx, y: y + dy, w, h };
        if (box.x < 4 || box.y < 4 || box.x + w > W - 4 || box.y + h > H - 4) continue;
        if (placed.some((b) => box.x < b.x + b.w + 3 && box.x + w + 3 > b.x &&
          box.y < b.y + b.h + 2 && box.y + h + 2 > b.y)) continue;
        placed.push(box);
        ctx.fillStyle = 'rgba(255,255,255,0.9)';
        ctx.fillRect(box.x, box.y, w, h);
        ctx.fillStyle = color;
        ctx.fillText(text, box.x + 5, box.y + 12);
        labels.push(box);
        return;
      }
    };

    // 威胁扇区（后端算好的顶点）：淡填充 + 细实线，不用虚线。
    // 标注放在扇区外缘中点，不堆在要点上——两个方向的文字会在圆心挤成一团。
    for (const sector of (st.threat_sectors || [])) {
      const poly = (sector.polygon || []).map(P);
      if (poly.length < 3) continue;
      ctx.beginPath();
      poly.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
      ctx.closePath();
      ctx.fillStyle = 'rgba(185,28,28,0.07)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(185,28,28,0.32)';
      ctx.lineWidth = 1.1;
      ctx.stroke();
      const edge = (sector.polygon || [])[Math.max(1,
        Math.floor((sector.polygon || []).length / 2))];
      if (edge) {
        // 标签放在扇区内部（0.78 半径处）：边缘一圈留给阵位点，文字不压标记。
        const q = P(edge);
        const kp0 = P(st.key_point);
        placeLabel('威胁 ' + (sector.id || '') + ' · ' +
          num(sector.bearing_deg, 0) + '°',
          kp0[0] + (q[0] - kp0[0]) * 0.55,
          kp0[1] + (q[1] - kp0[1]) * 0.55, COLORS.threat);
      }
    }

    // 撤离路线（只有开了"规划路径"才画，默认干净）
    if (C.showRoutes) {
      const route = (st.withdraw || {}).route || [];
      if (route.length > 1) {
        ctx.beginPath();
        route.map(P).forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
        ctx.strokeStyle = COLORS.withdraw + '99';
        ctx.lineWidth = 1.8;
        ctx.stroke();
        placeLabel('撤离路线', ...P(route[route.length - 1]), COLORS.withdraw);
      }
      for (const a of planAssignments()) {
        if (!(a.path || []).length) continue;
        ctx.beginPath();
        a.path.map(P).forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
        ctx.strokeStyle = '#33415555';
        ctx.lineWidth = a.role && String(a.role).startsWith('reserve') ? 1.6 : 1.2;
        ctx.stroke();
      }
    }

    // 要点
    const kp = P(st.key_point);
    ctx.beginPath();
    ctx.moveTo(kp[0], kp[1] - 9);
    ctx.lineTo(kp[0] + 9, kp[1]);
    ctx.lineTo(kp[0], kp[1] + 9);
    ctx.lineTo(kp[0] - 9, kp[1]);
    ctx.closePath();
    ctx.fillStyle = COLORS.key;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = COLORS.key;
    ctx.font = '600 12px "Segoe UI","Microsoft YaHei"';
    ctx.fillText('要点', kp[0] + 12, kp[1] + 4);

    // 预备队/支援/中继站位：标签直接带当前在位平台编号，平台自己就不再单独
    // 标一遍（默认配置里支援位/中继位常常就是预备队点或要点本身）。
    const rolePid = (kind) => Object.keys(roles).find(
      (pid) => String(roles[pid]).split(':')[0] === kind);
    const same = (a, b) => !!a && !!b &&
      Math.abs(a[0] - b[0]) < 1 && Math.abs(a[1] - b[1]) < 1;
    const station = (point, text, color) => {
      if (!point) return;
      const q = P(point);
      ctx.beginPath();
      ctx.rect(q[0] - 4, q[1] - 4, 8, 8);
      ctx.fillStyle = color + '33';
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.stroke();
      placeLabel(text, q[0], q[1], color);
    };
    const reservePid = rolePid('reserve');
    station(st.standby, '预备队' + (reservePid ? ' · ' + shortPid(reservePid) : ''),
            COLORS.reserve);
    const supportPid = rolePid('support');
    for (const point of (st.support_points || [])) {
      if (same(point, st.standby)) continue;
      station(point, '支援位' + (supportPid ? ' · ' + shortPid(supportPid) : ''),
              COLORS.support);
    }
    if (st.relay_point && !same(st.relay_point, st.key_point)) {
      const relayPid = rolePid('relay');
      station(st.relay_point,
              '中继位' + (relayPid ? ' · ' + shortPid(relayPid) : ''),
              COLORS.relay);
    }

    // 探测圈：圆心跟着**在位平台**的实时位置走，不是画在计划阵位点上。
    // 静态画在阵位上会骗人——T+0 全员还在集结地时图上就已经"有覆盖"了。
    // 没有人在位的阵位不画圈，缺口因此是看得见的（与覆盖判据同一口径）。
    const sensorR = (Number(st.sensor_radius_m) || 0) * scale;
    const suppressedAt = (postId, now) => {
      let sup = false;
      for (const e of (C.data.events || [])) {
        if (e.post_id !== postId || (e.t || 0) > now) continue;
        if (e.kind === 'post_suppressed') sup = true;
        else if (e.kind === 'post_restored') sup = false;
      }
      return sup;
    };
    if (sensorR > 4) {
      for (const position of (st.positions || [])) {
        const pid = occupantAt(position.id, t);
        if (!pid) continue;
        if (suppressedAt(position.id, t)) continue;   // 被压制的阵位不算覆盖
        const a = agentAt(pid, t);
        if (!a || !Number.isFinite(a.x)) continue;
        const q = P([a.x, a.y]);
        ctx.beginPath();
        ctx.arc(q[0], q[1], sensorR, 0, Math.PI * 2);
        ctx.strokeStyle = COLORS.post + '48';
        ctx.lineWidth = 1.1;
        ctx.stroke();
      }
    }
    // 空中观察席的盘旋航线（这是固定航线，画在要点为圆心的位置才是对的）
    if ((st.air_units || []).length) {
      const orbit = (Number(st.air_orbit_radius_m) || 45) * scale;
      const kp0 = P(st.key_point);
      if (orbit > 4) {
        ctx.beginPath();
        ctx.arc(kp0[0], kp0[1], orbit, 0, Math.PI * 2);
        ctx.strokeStyle = COLORS.air + '55';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
    }

    // 阵位：环 + 朝向刻线；在位=实心，空缺=空心
    for (const position of (st.positions || [])) {
      const q = P(position.point);
      const pid = occupantAt(position.id, t);
      const color = pid ? COLORS.post : COLORS.postOff;
      const rad = Math.max(4.5, 6);
      ctx.beginPath();
      ctx.arc(q[0], q[1], rad, 0, Math.PI * 2);
      ctx.fillStyle = pid ? color : '#ffffff';
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
      // 朝向：0°=北，顺时针
      const facing = (Number(position.facing_deg) || 0) * Math.PI / 180;
      const fx = Math.sin(facing), fy = -Math.cos(facing);
      ctx.beginPath();
      ctx.moveTo(q[0] + fx * (rad + 1), q[1] + fy * (rad + 1));
      ctx.lineTo(q[0] + fx * (rad + 9), q[1] + fy * (rad + 9));
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.4;
      ctx.stroke();
      placeLabel(position.id + (pid ? ' · ' + shortPid(pid) : ' · 空缺'),
                 q[0], q[1], color);
    }

    // 增援路线：触发后到到位前，画一条实线（说明"谁去哪"）
    for (const r of (result().reinforcements || [])) {
      if (t < (r.triggered_s || 0)) continue;
      const a = agentAt(r.pid, Math.min(t, r.arrived_s || t));
      const post = (st.positions || []).find((p) => p.id === r.post_id);
      if (!a || !post) continue;
      const p1 = P([a.x, a.y]), p2 = P(post.point);
      ctx.beginPath();
      ctx.moveTo(...p1);
      ctx.lineTo(...p2);
      ctx.strokeStyle = COLORS.reinforce + 'cc';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = COLORS.reinforce;
      ctx.font = '10px "Segoe UI","Microsoft YaHei"';
      ctx.fillText('增援', (p1[0] + p2[0]) / 2 + 4, (p1[1] + p2[1]) / 2 - 4);
    }

    // 我方平台
    for (const pid of Object.keys(roles)) {
      const a = agentAt(pid, t);
      if (!a) continue;
      const w = workers().find((x) => x.pid === pid);
      const q = P([a.x, a.y]);
      const kind = String(roles[pid] || '').split(':')[0];
      const color = kind === 'reserve' ? COLORS.reserve
        : kind === 'support' ? COLORS.support
          : kind === 'relay' ? COLORS.relay
            : kind === 'air' ? COLORS.air : COLORS.post;
      if (typeof window.drawPlatformIcon === 'function') {
        window.drawPlatformIcon(ctx, w ? w.kind : 'UGV', q[0], q[1], 11, a.yaw, color);
      } else {
        ctx.beginPath();
        ctx.arc(q[0], q[1], 5, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }
      if (kind === 'air') {
        placeLabel('空中观察 ' + shortPid(pid) + ' · ' +
          num(st.air_altitude_m, 0) + ' m', q[0], q[1] - 16, COLORS.air);
        continue;
      }
      // 平台只在"不在自己阵位"时补编号：在位的身份已经由阵位标签给出，
      // 预备队/支援/中继的身份已经由站位标签给出，再标一遍只会糊成一团。
      const onOwnPost = kind === 'post' && occupantAt(roles[pid].split(':')[1], t) === pid;
      if (!onOwnPost && kind === 'post') placeLabel(shortPid(pid), q[0], q[1] - 14, '#0f172a');
    }

    // 时钟角标
    ctx.fillStyle = 'rgba(255,255,255,0.92)';
    ctx.fillRect(rect.width - 138, 10, 128, 26);
    ctx.strokeStyle = '#dbe3dc';
    ctx.strokeRect(rect.width - 138, 10, 128, 26);
    ctx.fillStyle = '#0f172a';
    ctx.font = '12px "Segoe UI","Microsoft YaHei"';
    ctx.fillText('T+' + num(t, 1) + ' s · ' + phaseNow(t), rect.width - 128, 27);
  }

  // ---------------------------------------------------------------- 对外
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
    const btn = el('#hl-play');
    if (btn) btn.textContent = '▶ 播放';
  }

  function syncTime(t) {
    C.t = Math.max(0, Math.min(endTime(), Number(t) || 0));
    const scrub = el('#hl-scrub'), label = el('#hl-time');
    if (scrub) scrub.value = C.t;
    if (label) label.textContent = num(C.t, 1) + ' / ' + Math.round(endTime()) + ' s';
  }

  function time() { return C.t; }

  window.HoldPage = {
    load: load,
    show: show,
    hide: hide,
    draw: draw,
    syncTime: syncTime,
    time: time,
    hasData: () => !!C.data,
  };
})();
