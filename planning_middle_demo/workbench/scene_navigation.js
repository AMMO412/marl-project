/* Shared display-only map controls. Never modifies actor coordinates or recorded data. */
(function (root) {
  'use strict';
  const bound = new WeakSet();
  const cameras = new WeakMap();
  let pointer = null;
  function project(canvas, bounds) {
    const r = canvas.getBoundingClientRect();
    const scale = Math.min((r.width - 40) / (bounds[2] - bounds[0]), (r.height - 40) / (bounds[3] - bounds[1]));
    const cx = (bounds[0] + bounds[2]) / 2, cy = (bounds[1] + bounds[3]) / 2;
    return { scale, cx, cy, width: r.width, height: r.height,
      point: p => [r.width / 2 + (p[0] - cx) * scale, r.height / 2 - (p[1] - cy) * scale] };
  }
  function zoom(canvas, api, factor, screen) {
    const b = api.getBounds(), v = project(canvas, b);
    if (!(v.scale > 0)) return false;
    const span = Math.max(b[2] - b[0], b[3] - b[1]);
    if (span / factor < .25 || span / factor > 1e7) return false;
    const px = screen ? screen[0] - v.width / 2 : 0, py = screen ? screen[1] - v.height / 2 : 0;
    const cx = v.cx + px / v.scale - px / (v.scale * factor);
    const cy = v.cy - py / v.scale + py / (v.scale * factor);
    const hw = (b[2] - b[0]) / (2 * factor), hh = (b[3] - b[1]) / (2 * factor);
    api.setBounds([cx - hw, cy - hh, cx + hw, cy + hh]);
    return true;
  }
  function bind(canvas, api) {
    cameras.set(canvas, api);
    if (bound.has(canvas)) return;
    bound.add(canvas); canvas.style.touchAction = 'none'; canvas.style.cursor = 'grab';
    let drag = null, moved = false;
    canvas.addEventListener('wheel', e => {
      e.preventDefault(); const r = canvas.getBoundingClientRect();
      zoom(canvas, cameras.get(canvas), Math.exp(-Math.max(-150, Math.min(150, e.deltaY)) * .006), [e.clientX - r.left, e.clientY - r.top]);
    }, { passive: false });
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, bounds: cameras.get(canvas).getBounds().slice() };
      moved = false; canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', e => {
      const api = cameras.get(canvas), r = canvas.getBoundingClientRect(), v = project(canvas, api.getBounds());
      pointer = { x: v.cx + (e.clientX - r.left - r.width / 2) / v.scale, y: v.cy - (e.clientY - r.top - r.height / 2) / v.scale };
      root.dispatchEvent(new CustomEvent('scene-coordinate', { detail: pointer }));
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true; const base = project(canvas, drag.bounds), b = drag.bounds;
      api.setBounds([b[0] - dx / base.scale, b[1] + dy / base.scale, b[2] - dx / base.scale, b[3] + dy / base.scale]);
      canvas.style.cursor = 'grabbing';
    });
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(type, () => { drag = null; canvas.style.cursor = 'grab'; });
    canvas.addEventListener('click', e => { if (moved) { e.stopImmediatePropagation(); moved = false; } }, true);
    canvas.addEventListener('pointerleave', () => { pointer = null; root.dispatchEvent(new CustomEvent('scene-coordinate', { detail: null })); });
  }
  // Grid routine adapted from the colleague's live_map_adapter.js (2026-11-05).
function drawGrid(context, W, H, project, scale, cx, cy) {
  if (!Number.isFinite(scale) || scale <= 0) return;
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
  context.strokeStyle = '#6c8fb51a';
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
    context.strokeStyle = Math.abs(x) < step * 1e-6 ? '#417bada0' : '#6c8fb543';
    context.lineWidth = Math.abs(x) < step * 1e-6 ? 1.3 : .7;
    context.stroke();
    const label = 'X ' + format(x);
    const width = context.measureText(label).width;
    context.fillStyle = '#ffffffd9';context.fillRect(px + 3, 3, width + 4, 16);
    context.fillStyle = '#436b99';context.fillText(label, px + 5, 15);
  }
  for (let y = Math.ceil(bottom / step) * step; y <= top; y += step) {
    const py = project([cx, y])[1];
    context.beginPath();context.moveTo(0, py);context.lineTo(W, py);
    context.strokeStyle = Math.abs(y) < step * 1e-6 ? '#417bada0' : '#6c8fb543';
    context.lineWidth = Math.abs(y) < step * 1e-6 ? 1.3 : .7;
    context.stroke();
    const label = 'Y ' + format(y);
    context.fillStyle = '#ffffffd9';
    context.fillRect(3, py - 14, context.measureText(label).width + 6, 16);
    context.fillStyle = '#436b99';context.fillText(label, 5, py - 2);
  }
  context.restore();
}


  function drawSceneContext(ctx, run, P, layers) {
    ctx.save();
    if (layers.threats !== false) for (const threat of (run.threats || [])) {
      const points = (threat.polygon || []).map(P); if (points.length < 3) continue;
      const scope = threat.applies_to || 'ground';
      const style = scope === 'air'
        ? { fill: 'rgba(37,99,235,0.10)', stroke: '#2563eb', labelFill: '#eff6ff', labelText: '#1d4ed8', text: '仅对空（地面可通行）' }
        : scope === 'all'
          ? { fill: 'rgba(185,28,28,0.11)', stroke: '#b91c1c', labelFill: '#fef2f2', labelText: '#991b1b', text: '空地均作用' }
          : { fill: 'rgba(194,65,12,0.11)', stroke: '#c2410c', labelFill: '#fff7ed', labelText: '#9a3412', text: '仅对地（空中可通行）' };
      ctx.beginPath(); points.forEach((p,i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.closePath();
      ctx.fillStyle=style.fill;ctx.fill();ctx.strokeStyle=style.stroke;ctx.lineWidth=1.8;ctx.setLineDash([6,4]);ctx.stroke();ctx.setLineDash([]);
      const x=Math.min(...points.map(p=>p[0])), y=Math.min(...points.map(p=>p[1]));
      // “仅对空”等措辞直接说明平台适用范围，避免地面平台经过空中威胁框时
      // 被误解为违反了执行约束。
      const text='威胁区 I='+Number(threat.intensity).toFixed(2)+' · '+style.text;
      ctx.font='10px "Microsoft YaHei"';ctx.fillStyle=style.labelFill;ctx.fillRect(x,y-17,ctx.measureText(text).width+8,16);ctx.fillStyle=style.labelText;ctx.fillText(text,x+4,y-5);
    }
    const workers = (run.replay || {}).workers || [];
    if (layers.units !== false && workers.length) {
      const colors={UGV:'#3f6fa3',TANK:'#8a6b3d',PLANE:'#2f8f86',WING:'#7657a8'};
      for(const w of workers) { if(!w.start)continue;const q=P(w.start);ctx.beginPath();ctx.arc(q[0],q[1],3,0,Math.PI*2);ctx.strokeStyle=colors[w.kind]||'#64748b';ctx.lineWidth=1;ctx.stroke(); }
      const starts=workers.map(w=>w.start).filter(Boolean);
      if(starts.length){const q=P([starts.reduce((n,p)=>n+p[0],0)/starts.length,Math.max(...starts.map(p=>p[1]))]);const counts={};workers.forEach(w=>counts[w.kind]=(counts[w.kind]||0)+1);const names={UGV:'轮式车',TANK:'履带车',PLANE:'固定翼',WING:'飞翼'};const text='出发阵地（初始待命区，非任务区）· 编成 '+workers.length+' 台（'+Object.keys(counts).map(k=>(names[k]||k)+' '+counts[k]).join(' · ')+'）';ctx.font='10px "Microsoft YaHei"';ctx.fillStyle='#ffffffdd';ctx.fillRect(q[0]-10,q[1]-34,ctx.measureText(text).width+8,16);ctx.fillStyle='#47647e';ctx.fillText(text,q[0]-6,q[1]-22);}
    }
    ctx.restore();
  }

  // Match the main map: recent recorded movement, including partial edges.
  function drawRecordedTrails(ctx, run, P, time, visible) {
    let count=0;ctx.save();ctx.lineWidth=1.7;ctx.globalAlpha=.72;
    const full=!!document.getElementById('full-trails')?.checked;
    if(visible)for(const worker of ((run.replay||{}).workers||[])) {
      for(const segment of root.ReplayPose.trails(worker.samples||[],time,{
        full,seconds:10,interpolate:run.report?.motion==='real'
      })) {
        ctx.beginPath();segment.map(p=>P([p.x,p.y])).forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));
        ctx.strokeStyle=({UGV:'#3f6fa3',TANK:'#8a6b3d',PLANE:'#2f8f86',WING:'#7657a8'})[worker.kind]||'#4f86b8';
        ctx.setLineDash(String(segment.at(-1).command||'').startsWith('return:')?[5,3]:[]);ctx.stroke();count++;
      }
    }
    ctx.restore();ctx.canvas.dataset.recordedTrailSegments=String(count);return count;
  }

  root.SceneNavigation = { drawRecordedTrails, drawSceneContext, bind, zoom, project, drawGrid, getPointer: () => pointer };
})(window);
