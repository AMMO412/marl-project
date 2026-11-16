function displayRun(data, {autoplay = false, keepView = false} = {}) {
  const live = data.live;
  const previousLive=state.run?.id===data.id&&state.run?.live;
  const previousTime=state.t;
  const arrived=performance.now();
  if(live){state.liveRate=previousLive?Math.max(0.1,Math.min(20,(live.sim_s-previousLive.sim_s)/Math.max(.1,(arrived-(state.liveArrival||arrived-700))/1000))):4;state.liveArrival=arrived;}
  const sameJobs = keepView && state.run?.report.jobs.map(j => j.job_id).join() ===
    data.report.jobs.map(j => j.job_id).join();
  if (!keepView) {
    closeTheater();
    $('#show-trails').checked = true;
    $('#full-trails').checked = false;
    state.focus = null;
    state.zoom = 1;
    lastEventKey = '';
  }
  const taskIds = new Set(data.report.jobs.map(j => j.job_id));
  if (state.focus?.type === 'job' && !taskIds.has(state.focus.id)) state.focus = null;
  if (state.focus?.jobId && !taskIds.has(state.focus.jobId)) state.focus.jobId = null;
  state.run = data;
  if (!keepView) {
    state.selectedTaskId = data.report.jobs[0]?.job_id || null;
    window.WorkbenchUI?.reset();
    state.ckView = state.hlView = false;
    state.ovView = 'map';
  }
  document.body.classList.toggle('recording-data', !!data.report.recording);
  state.t = live ? (live.paused||!previousLive?live.sim_s:Math.max(live.sim_s-6,Math.min(previousTime,live.sim_s))) : keepView ? data.replay.end : 0;
  state.frames = live ? [] : makeFrames(data);
  state.livePositions = live ? new Map(data.report.platforms.map(p => [p.pid, p])) : null;
  state.liveFrame = null;
  if (live) {
    const frame = {jobs:Object.fromEntries(data.report.jobs.map(job=>[job.job_id,{pids:[],behavior:{},phase:null}])),lost:[],plans:data.report.plans||0,retries:data.report.retries||0,timeouts:data.report.timeouts||0};
    for (const job of data.report.jobs) {
      const row = frame.jobs[job.job_id];
      row.status = job.status === 'assigned' ? 'running' : job.status;
      row.progress = job.progress;
      row.attempts = job.attempts;
      if (row.status === 'pending' || row.status === 'excluded') row.pids = [];
      if (row.status === 'running' || row.status === 'cancelling') {
        row.pids = live.assignments.filter(a => a.id === job.job_id).map(a => a.platform);
      }
    }
    frame.lost = data.report.platforms.filter(p => !p.alive).map(p => p.pid);
    state.liveFrame = frame;
  }
  state.eventRows = data.trace.map((e, index) => {
    if (e.kind === 'behavior_event' && e.event?.job_id && !e.job_id) e = {...e, job_id:e.event.job_id};
    return {...e, index};
  }).filter(e => events[e.kind] && !(e.kind === 'behavior_event' &&
    ['behavior_structure','behavior_detail','approach_route','return_sample','air_wait_sample'].includes(e.event?.kind)));

  const runSelect = $('#run-select');
  if (live && ![...runSelect.options].some(option => option.value === data.id)) {
    runSelect.add(new Option('实时演示 · ' + shortRun(data.id), data.id));
  }
  runSelect.value = data.id;
  runSelect.disabled = Boolean(live);
  $('#run-mode').textContent = modes[data.report.mode] || data.report.mode;
  $('#run-semantic').textContent = data.report.recording ? data.report.recording_source.note :
    (live ? '实时演示 · ' : '') + (data.report.motion === 'real' ? '逐步运动' : '瞬移') +
    (data.report.avoid ? ' · 静态建筑绕障' : '') +
    (data.report.behavior ? ' · 到位行为' : '') + ' · ' + (data.report.objective || 'makespan');
  for (const id of ['play','restart','step-back','step-next','jump-end','speed','scrubber']) {
    $('#' + id).disabled = Boolean(live) && id!=='play';
  }
  setPlaying(autoplay && !live);
  if (live) {
    $('#play').textContent = live.paused ? '▶ 继续实时运行' : 'Ⅱ 暂停实时运行';
    $('#play-state').textContent = (live.paused ? '仿真已暂停' : '实时运行') + ' · 配置 ' + live.revision;
    if(state.busy)updateRunControls();
  } else {
    $('#busy-banner>span:last-of-type').textContent = '正在计算规划、模拟执行并生成报告…';
  }

  const end = live ? live.sim_s : data.replay.end;
  $('#stat-end').textContent = end;
  $('#duration').textContent = end;
  $('#scrubber').max = end;
  $('#timeline-mid').textContent = stamp(end / 2);
  $('#timeline-end').textContent = stamp(end);
  $('#task-count').textContent = data.report.jobs.length;
  $('#side-jobs').textContent = String(data.report.jobs.length).padStart(2, '0');
  $('#fleet-note').textContent = [...new Set(data.replay.workers.map(w => w.kind_name))].join(' · ');
  if (!sameJobs) {
    const options = data.report.jobs.map(j => `<option value="${esc(j.job_id)}">${esc(j.job_id)} · ${esc(taskLabel(j))}</option>`).join('');
    $('#task-select').innerHTML = '<option value="">选择一项任务，观看执行过程</option>' + options;
    $('#theater-task').innerHTML = options;
  }
  $('#model-note').textContent = live ? '实时跟随 · 选择任务可在地图上聚焦' : '选任务后打开大画幅执行回放';
  if (!keepView) setBounds();
  if (!keepView) {
    window.ContainmentPage?.load(data);
    window.HoldPage?.load(data);
    applyOverviewMode();
  }
  renderTime();
  if (!live || !keepView) {
    renderRuns();
    renderFiles();
  }
  draw();
}

function setTemplates(templates) {
  state.templates = templates;
  window.dispatchEvent(new CustomEvent('workbench-templates'));
}

function drawCoordinateGrid(context, W, H, project, scale, cx, cy) {
  if (!$('#show-grid').checked || !Number.isFinite(scale) || scale <= 0) return;
  const magnitude = 10 ** Math.floor(Math.log10(90 / scale));
  const raw = 90 / scale / magnitude;
  const step = (raw <= 1 ? 1 : raw <= 2 ? 2 : raw <= 5 ? 5 : 10) * magnitude;
  const minorStep = step / 10;
  const left = cx - W / (2 * scale), right = cx + W / (2 * scale);
  const bottom = cy - H / (2 * scale), top = cy + H / (2 * scale);
  const format = value => Number(value.toFixed(Math.max(0, -Math.floor(Math.log10(step))))).toString();
  context.save();
  context.font = '11px "Segoe UI", "Microsoft YaHei"';
  // Draw unlabelled subdivisions first, leaving the major lines and axes legible.
  context.strokeStyle = '#4c746522';
  context.lineWidth = .45;
  context.beginPath();
  for (let i = Math.ceil(left / minorStep); i <= Math.floor(right / minorStep); i++) {
    if (i % 10 === 0) continue;
    const px = project([i * minorStep, cy])[0];
    context.moveTo(px, 0);context.lineTo(px, H);
  }
  for (let i = Math.ceil(bottom / minorStep); i <= Math.floor(top / minorStep); i++) {
    if (i % 10 === 0) continue;
    const py = project([cx, i * minorStep])[1];
    context.moveTo(0, py);context.lineTo(W, py);
  }
  context.stroke();
  for (let x = Math.ceil(left / step) * step; x <= right; x += step) {
    const px = project([x, cy])[0];
    context.beginPath();context.moveTo(px, 0);context.lineTo(px, H);
    context.strokeStyle = Math.abs(x) < step * 1e-6 ? '#417b79aa' : '#4c746542';
    context.lineWidth = Math.abs(x) < step * 1e-6 ? 1.3 : .7;
    context.stroke();
    const label = 'X ' + format(x);
    const width = context.measureText(label).width;
    context.fillStyle = '#ffffffd9';context.fillRect(px + 3, 3, width + 4, 16);
    context.fillStyle = '#254f49';context.fillText(label, px + 5, 15);
  }
  for (let y = Math.ceil(bottom / step) * step; y <= top; y += step) {
    const py = project([cx, y])[1];
    context.beginPath();context.moveTo(0, py);context.lineTo(W, py);
    context.strokeStyle = Math.abs(y) < step * 1e-6 ? '#417b79aa' : '#4c746542';
    context.lineWidth = Math.abs(y) < step * 1e-6 ? 1.3 : .7;
    context.stroke();
    const label = 'Y ' + format(y);
    context.fillStyle = '#ffffffd9';
    context.fillRect(3, py - 14, context.measureText(label).width + 6, 16);
    context.fillStyle = '#254f49';context.fillText(label, 5, py - 2);
  }
  context.restore();
}

const coordinateReadout = document.createElement('output');
coordinateReadout.id = 'coordinate-readout';
coordinateReadout.hidden = true;
$('.canvas-wrap').append(coordinateReadout);
let coordinateView = null;
let coordinatePointer = null;
let keyPointHits = [];

function clearCoordinateView() {
  coordinateView = null;
  keyPointHits = [];
  coordinateReadout.hidden = true;
}

function containsMapPoint(polygon, x, y) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [ax, ay] = polygon[j], [bx, by] = polygon[i];
    const cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax);
    if (Math.abs(cross) < 1e-8 && x >= Math.min(ax, bx) - 1e-8 && x <= Math.max(ax, bx) + 1e-8 &&
        y >= Math.min(ay, by) - 1e-8 && y <= Math.max(ay, by) + 1e-8) return true;
    if ((ay > y) !== (by > y) && x < ax + (y - ay) * (bx - ax) / (by - ay)) inside = !inside;
  }
  return inside;
}

function formatMapXYZ(x, y, z) {
  return [x, y, z].map(value => Number.isFinite(value) ? value.toFixed(2) : '—').join(', ');
}

function drawMapKeyPoints(context, project, inView, placeLabel) {
  if (!$('#show-key-points').checked) return;
  const color = '#654786';
  const centers = [], corners = [];
  for (const item of mapGeometry('obstacles')) {
    const polygon = item.polygon;
    if (!item.is_building || !polygon || polygon.length < 3) continue;
    const vertices = polygon.filter((point, index) => index !== polygon.length - 1 ||
      point[0] !== polygon[0][0] || point[1] !== polygon[0][1]);
    const [sumX, sumY] = vertices.reduce(([x, y], point) => [x + point[0], y + point[1]], [0, 0]);
    centers.push({item, point: [sumX / vertices.length, sumY / vertices.length], kind: '中心'});
    vertices.forEach((point, index) => corners.push({item, point, kind: '角点 ' + (index + 1)}));
  }
  for (const {item, point, kind} of [...centers, ...corners]) {
    const [x, y] = project(point);
    if (!inView(x, y)) continue;
    context.beginPath();
    context.arc(x, y, kind === '中心' ? 4 : 2.6, 0, Math.PI * 2);
    context.fillStyle = color;
    context.fill();
    context.strokeStyle = '#fff';
    context.lineWidth = 1;
    context.stroke();
    const xyz = formatMapXYZ(...point, item.top_z);
    keyPointHits.push({x, y, text: (item.label || item.id) + ' · ' + kind + ' · ' + xyz});
    placeLabel(kind + ' (' + xyz + ')', x, y, color, false, true);
  }
}

function updateCoordinateReadout() {
  coordinateReadout.hidden = true;
  if (!coordinateView || !coordinatePointer) return;
  const grid = $('#show-grid').checked, keys = $('#show-key-points').checked;
  if (!grid && !keys) return;
  const rect = canvas.getBoundingClientRect();
  const px = coordinatePointer.x - rect.left, py = coordinatePointer.y - rect.top;
  if (px < 0 || py < 0 || px > rect.width || py > rect.height) return;
  if (state.hits.some(hit => hit.type === 'fit' &&
    Math.abs(px - hit.x) <= hit.w / 2 && Math.abs(py - hit.y) <= hit.h / 2)) return;
  let closest = null, best = 8;
  if (keys) for (const point of keyPointHits) {
    const distance = Math.hypot(px - point.x, py - point.y);
    if (distance < best) { closest = point; best = distance; }
  }
  if (closest) {
    coordinateReadout.textContent = closest.text;
  } else {
    if (!grid) return;
    const {scale, cx, cy} = coordinateView;
    const x = (px - rect.width / 2) / scale + cx;
    const y = (rect.height / 2 - py) / scale + cy;
    const surfaces = mapGeometry('obstacles').filter(item =>
      item.polygon?.length >= 3 && containsMapPoint(item.polygon, x, y));
    const top = surfaces.filter(item => Number.isFinite(item.top_z))
      .reduce((highest, item) => !highest || item.top_z > highest.top_z ? item : highest, null);
    const z = top ? top.top_z : surfaces.length ? null : 0;
    coordinateReadout.textContent = 'X / Y / Z  ' + formatMapXYZ(x, y, z) +
      (top ? ' · ' + (top.label || top.id) : surfaces.length ? ' · 无高度数据' : '');
  }
  coordinateReadout.hidden = false;
}

for (const id of ['show-grid', 'show-key-points']) $('#' + id).addEventListener('change', draw);
canvas.addEventListener('mousemove', event => {
  coordinatePointer = {x: event.clientX, y: event.clientY};
  updateCoordinateReadout();
});
canvas.addEventListener('mouseleave', () => {
  coordinatePointer = null;
  coordinateReadout.hidden = true;
});
