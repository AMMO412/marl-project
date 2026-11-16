/*
 * Desktop shell bridge.
 *
 * The browser workbench stays unchanged when opened normally.  When the
 * WinForms shell loads /?desktop=1 this file trims the web chrome and exposes
 * a small, stable API for the native toolbar.
 */
(function () {
  var params = new URLSearchParams(window.location.search);
  if (params.get('desktop') !== '1') return;

  document.documentElement.classList.add('desktop-mode');
  var style = document.createElement('style');
  style.textContent = [
    '.desktop-mode{--ink:#30435b;--green:#1f6fc3;--line:#e3eaf3;--bg:#fff}',
    '.desktop-mode body{margin:0!important;background:#fff!important;overflow:hidden!important}',
    '.desktop-mode body>aside,.desktop-mode body>main,.desktop-mode body>footer{display:none!important}',
    '#desktop-scene-host{position:fixed;inset:0;overflow:hidden;background:#fff}',
    '#desktop-scene-host>canvas{display:block!important;width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;border:0!important}'
  ].join('');
  document.head.appendChild(style);

  // Transfer only the existing canvas to a dedicated renderer surface.
  // The page controls remain available to the bridge, outside the visible surface.
  var originalSceneParent = q('#scene').parentNode;
  var host = document.createElement('div');
  var layerValues = { buildings: true, boundary: true, units: true, planned: false, targets: true, grid: true, threats: true, trails: true };
  window.MarlDesktopLayers = layerValues;
  host.id = 'desktop-scene-host';
  document.body.appendChild(host);
  function mountCanvas() {
    var hold = q('#overview-hold-view');
    var canvas = containmentActive() ? q('#ck-canvas') :
      (hold && !hold.hidden ? q('#hl-canvas') : q('#scene'));
    if (canvas && canvas.parentNode !== host) {
      var previous = host.firstElementChild;
      if (previous && previous.id === 'scene') originalSceneParent.appendChild(previous);
      host.replaceChildren(canvas);
      window.dispatchEvent(new Event('resize'));
      Object.keys(layerValues).forEach(function (name) { setLayer(name, layerValues[name]); });
      if (canvas.id === 'scene' && !canvas.desktopCoordinates) {
        canvas.desktopCoordinates = true;
        canvas.addEventListener('pointermove', function (event) {
          var rect = canvas.getBoundingClientRect(), scale = mapScale();
          window.dispatchEvent(new CustomEvent('scene-coordinate', { detail: {
            x: (bounds[0] + bounds[2]) / 2 + (event.clientX - rect.left - rect.width / 2) / scale,
            y: (bounds[1] + bounds[3]) / 2 - (event.clientY - rect.top - rect.height / 2) / scale
          } }));
        });
      }
    }
  }
  var resizeFrame=0;
  function redrawSceneSize() {
    if(resizeFrame)return;
    resizeFrame=requestAnimationFrame(function(){
      resizeFrame=0;
      var active=renderer();
      if(active)active.draw();else if(typeof draw==='function')draw();
    });
  }
  new ResizeObserver(redrawSceneSize).observe(host);
  window.addEventListener('resize',redrawSceneSize);
  window.setInterval(mountCanvas, 200);
  window.addEventListener('scene-coordinate', function (event) {
    var p = event.detail;
    if (window.chrome && window.chrome.webview)
      window.chrome.webview.postMessage({ type: 'coordinate', text: p ? 'X ' + p.x.toFixed(2) + '   Y ' + p.y.toFixed(2) : 'X —  Y —' });
  });

  function postLegend() {
    if (typeof drawPlatformIcon !== 'function' || !window.chrome || !window.chrome.webview) return;
    var icons = {}, colors = { UGV: '#3f6fa3', TANK: '#8a6b3d', PLANE: '#2f8f86', WING: '#7657a8' };
    Object.keys(colors).forEach(function (kind) {
      var image = document.createElement('canvas'); image.width = image.height = 48;
      drawPlatformIcon(image.getContext('2d'), kind, 24, 24, 17, 0, colors[kind]);
      icons[kind] = image.toDataURL('image/png');
    });
    window.chrome.webview.postMessage({ type: 'legend', icons: icons });
  }

  function q(selector) { return document.querySelector(selector); }
  function fire(element, type) {
    if (!element) return false;
    element.dispatchEvent(new Event(type, { bubbles: true }));
    return true;
  }
  function click(selector) {
    var element = q(selector);
    if (!element) return false;
    element.click();
    return true;
  }
  function refresh() {
    return click('#refresh');
  }
  var wantedRun = '', runQueue = Promise.resolve();
  function selectRun(id) {
    if (typeof refreshCatalog === 'function') {
      wantedRun = id;
      pause();
      runQueue = runQueue.catch(function () {}).then(function () {
        if (wantedRun !== id) return;
        return refreshCatalog(id);
      }).catch(function (error) {
        if (window.chrome && window.chrome.webview) window.chrome.webview.postMessage({ type: 'error', text: String(error) });
      });
      return true;
    }
    var element = q('#run-select');
    if (!element) return false;
    var found = false;
    for (var i = 0; i < element.options.length; i++) {
      if (element.options[i].value === id) { found = true; break; }
    }
    if (!found) {
      // A run created after the page loaded is not in the select yet.
      click('#refresh');
      window.setTimeout(function () {
        var later = q('#run-select');
        if (later) { later.value = id; fire(later, 'change'); }
      }, 1000);
      return true;
    }
    element.value = id;
    return fire(element, 'change');
  }
  function selectTask(id) {
    var element = q('#task-select');
    if (!element) return false;
    element.value = id;
    return fire(element, 'change');
  }
  function navigate(page) {
    if (state.page === page) return true;
    var button = q('[data-page="' + page + '"]');
    if (!button) return false;
    button.click();
    return true;
  }
  function containmentActive() {
    var view = q('#overview-ck-view');
    return !!(view && !view.hidden);
  }
  function holdActive() { var view = q('#overview-hold-view'); return !!(view && !view.hidden); }
  function prefix() { return containmentActive() ? 'ck-' : holdActive() ? 'hl-' : ''; }
  function renderer() { return containmentActive() ? window.ContainmentPage : holdActive() ? window.HoldPage : null; }
  function playerButton() {
    return q('#' + prefix() + 'play');
  }
  var backgroundPlayback = false, backgroundPlaying = false;
  var backgroundTime = 0, backgroundEnd = 0, backgroundLast = 0, backgroundSpeed = 1;
  function playRenderer() {
    var button = playerButton();
    if (button && button.textContent.indexOf('暂') < 0) button.click();
    return true;
  }
  function pauseRenderer() {
    var button = playerButton();
    if (button && button.textContent.indexOf('暂') >= 0) button.click();
    return true;
  }
  function seekRenderer(seconds) {
    var scrubber = prefix() ? q('#' + prefix() + 'scrub') : q('#scrubber');
    if (!scrubber) return false;
    scrubber.value = Number(seconds) || 0;
    return fire(scrubber, 'input');
  }
  function advanceBackgroundClock() {
    if (!backgroundPlayback) return;
    var now = performance.now();
    if (backgroundPlaying) {
      backgroundTime = Math.min(backgroundEnd, backgroundTime + Math.max(0, now - backgroundLast) / 1000 * backgroundSpeed);
      seekRenderer(backgroundTime);
      if (backgroundTime >= backgroundEnd) backgroundPlaying = false;
    }
    backgroundLast = now;
  }
  function setBackgroundPlayback(enabled) {
    enabled = !!enabled;
    if (enabled === backgroundPlayback) return true;
    if (enabled) {
      var snapshot = sceneState();
      backgroundTime = snapshot.time; backgroundEnd = snapshot.duration;
      backgroundPlaying = snapshot.playing; backgroundLast = performance.now();
      var rate = prefix() ? q('#' + prefix() + 'rate') : q('#speed');
      backgroundSpeed = Number(rate && rate.value) || 1;
      pauseRenderer(); backgroundPlayback = true;
    } else {
      advanceBackgroundClock(); backgroundPlayback = false;
      seekRenderer(backgroundTime);
      if (backgroundPlaying) playRenderer(); else pauseRenderer();
    }
    return true;
  }
  function play() {
    if (!backgroundPlayback) return playRenderer();
    if (backgroundTime >= backgroundEnd) backgroundTime = 0;
    backgroundLast = performance.now(); backgroundPlaying = true;
    return true;
  }
  function pause() {
    advanceBackgroundClock(); backgroundPlaying = false;
    return pauseRenderer();
  }
  function setTime(seconds) {
    if (backgroundPlayback) {
      backgroundTime = Math.max(0, Math.min(backgroundEnd, Number(seconds) || 0));
      backgroundLast = performance.now();
    }
    return seekRenderer(seconds);
  }
  function setLayer(name, visible) {
    if (name === 'buildings' || name === 'obstacles') visible = true;
    layerValues[name] = !!visible;
    if (containmentActive() && window.ContainmentPage && window.ContainmentPage.setLayer)
      return window.ContainmentPage.setLayer(name, visible);
    if (holdActive()) return window.HoldPage.setLayer(name,visible);
    var map = {
      buildings: 'show-obstacles',
      obstacles: 'show-obstacles',
      threats: 'show-threats',
      planned: 'show-planned',
      trails: 'show-trails',
      labels: 'show-labels',
      sensor: 'show-sensor-range',
      grid: 'show-grid'
    };
    var element = q('#' + (map[name] || name));
    if (!element) { if (typeof draw === 'function') draw(); return name === 'grid'; }
    element.checked = !!visible;
    return fire(element, 'change');
  }
  function fit(mode) {
    if (typeof showOverviewMode === 'function') {
      const run = state.run;
      const only = run && run.report.jobs.length === 1;
      showOverviewMode(only && run.replay.containment ? 'containment' : only && run.replay.hold ? 'hold' : 'map');
    }
    mountCanvas();
    if (mode === 'starts' && state.run) {
      const points=state.run.replay.workers.map(w=>w.start).filter(Boolean);
      if(!points.length)return false;
      const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
      const b=[Math.min(...xs)-15,Math.min(...ys)-15,Math.max(...xs)+15,Math.max(...ys)+15];
      if(renderer()) renderer().setCameraBounds(b);
      else {state.focus=null;bounds=b;state.zoom=1;draw();}
      return true;
    }
    if (renderer()) renderer().fitView(mode || 'all');
    else if (mode === 'area') {
      const job=state.run.replay.jobs.find(j=>j.job_id===state.selectedTaskId)||state.run.replay.jobs[0];
      const behavior=(state.run.replay.behaviors||[]).find(b=>b.job_id===job.job_id);
      const points=taskArea(job)||behavior?.area||[job.pos];
      const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
      const pad=Math.max(18,Math.max(Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys))*.25);
      state.focus={type:'job',id:job.job_id};state.selectedTaskId=job.job_id;state.zoom=1;
      bounds=[Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad];draw();
    }
    else if (typeof fullBounds === 'function') { state.focus = null; bounds = fullBounds(); state.zoom = 1; draw(); }
    window.dispatchEvent(new Event('resize'));
    return true;
  }
  function zoom(factor) {
    if (renderer()) return renderer().zoom(factor);
    return click(factor > 1 ? '#map-zoom-in' : '#map-zoom-out');
  }
  function focusPlatform(id) {
    if (!state.run) return false;
    var worker = state.run.replay.workers.find(function (item) { return item.pid === id; });
    if (!worker) return false;
    state.t = sceneState().time;
    var position = workerAt(worker);
    if (renderer() && renderer().centerAt) return renderer().centerAt([position.x, position.y]);
    focus('worker', id);
    return true;
  }
  function setSpeed(value) {
    advanceBackgroundClock(); backgroundSpeed = Number(value) || 1;
    var select = prefix() ? q('#' + prefix() + 'rate') : q('#speed');
    if (!select) return false;
    if (!Array.prototype.some.call(select.options, function (o) { return Number(o.value) === Number(value); }))
      select.add(new Option(value + '×', value));
    select.value = value;
    return fire(select, 'change');
  }
  function startReplay(taskId, seconds, runId) {
    var tries = 0;
    var timer = window.setInterval(function () {
      if (runId && wantedRun && runId !== wantedRun) { window.clearInterval(timer); return; }
      var duration = Number(((q('#duration') || {}).textContent || '0').replace(/[^0-9.\-]/g, '')) || 0;
      var currentRun = (typeof state === 'object' && state.run && state.run.id) || '';
      if (duration > 0 && (!runId || currentRun === runId)) {
        window.clearInterval(timer);
        var taskTries = 0;
        var chooseTask = function () {
          if (!taskId) return;
          var select = q('#task-select');
          var found = false;
          if (select) {
            for (var i = 0; i < select.options.length; i++) {
              if (select.options[i].value === taskId) { found = true; break; }
            }
          }
          if (found) { selectTask(taskId); return; }
          if (++taskTries < 12) window.setTimeout(chooseTask, 300);
        };
        chooseTask();
        fit(state.run.replay.jobs.length===1 && state.run.replay.jobs[0].type==='recon' ? 'area' : 'all');
        setTime(seconds);
        play();
      } else if (++tries > 40) {
        window.clearInterval(timer);
      }
    }, 500);
    return true;
  }
  function sceneState() {
    advanceBackgroundClock();
    var activePage = q('.nav.active');
    var ck = containmentActive();
    var playButton = playerButton();
    var clock = prefix() ? (q('#' + prefix() + 'time') || {}).textContent : (q('#stat-clock') || {}).textContent;
    var duration = prefix() ? Number((q('#' + prefix() + 'scrub') || {}).max || 0) : Number(((q('#stat-end') || {}).textContent || '0').replace(/[^0-9.\-]/g, ''));
    var currentTime = backgroundPlayback ? backgroundTime : (parseFloat(clock) || 0);
    var progress = {};
    try {
      var snapshot = state.frames[Math.min(state.frames.length - 1, Math.floor(currentTime))];
      (state.run.report.jobs || []).forEach(function (job) {
        var task = snapshot && snapshot.jobs[job.job_id];
        if (task) progress[job.job_id] = task.status === 'succeeded' ? 100 :
          (job.work > 0 ? Math.max(0, Math.min(100, task.progress / job.work * 100)) : 0);
      });
    } catch (error) { /* No loaded run yet. */ }
    return {
      layers: Object.assign({}, layerValues),
      cameraBounds: renderer() ? renderer().cameraBounds() : (typeof bounds !== 'undefined' ? bounds.slice() : null),
      taskProgress: progress,
      runId: (typeof state === 'object' && state.run && state.run.id) || '',
      taskId: (q('#task-select') || {}).value || '',
      time: currentTime,
      duration: Number(duration) || 0,
      playing: backgroundPlayback ? backgroundPlaying : !!playButton && playButton.textContent.indexOf('暂') >= 0,
      page: activePage ? activePage.getAttribute('data-page') : 'overview'
    };
  }
  var altitudeRun = null;
  function post() {
    try {
      if (window.chrome && window.chrome.webview) {
        window.chrome.webview.postMessage({ type: 'state', state: sceneState() });
        // Transfer recorded z once per loaded replay; native chart applies its clock.
        if (state.run && altitudeRun !== state.run) {
          window.chrome.webview.postMessage({ type: 'altitude', runId: state.run.id,
            aircraft: (state.run.replay.workers || []).filter(w => ['PLANE','WING'].includes(w.kind))
              .sort((a,b) => a.pid.localeCompare(b.pid, undefined, {numeric:true}))
              .map(w => ({id:w.pid, samples:(w.samples || []).map(p => [p.t,Number.isFinite(p.z)?p.z:null,!!p.lost])})) });
          altitudeRun = state.run;
        }
      }
    } catch (error) { /* browser mode: no bridge */ }
  }

  window.MarlDesktop = {
    version: 1,
    ready: true,
    clearRun: function () { pause();wantedRun='';state.loadToken++;state.run=null;state.frames=[];state.selectedTaskId=null;const c=host.querySelector('canvas');if(c)c.getContext('2d').clearRect(0,0,c.width,c.height);return true; },
    getState: sceneState,
    selectRun: selectRun,
    selectTask: selectTask,
    navigate: navigate,
    play: play,
    pause: pause,
    setTime: setTime,
    setBackgroundPlayback: setBackgroundPlayback,
    setLayer: setLayer,
    fit: fit,
    zoom: zoom,
    focusPlatform: focusPlatform,
    setSpeed: setSpeed,
    refresh: refresh,
    startReplay: startReplay
  };

  setTimeout(function () {
    postLegend();
    try {
      if (window.chrome && window.chrome.webview) {
        window.chrome.webview.postMessage({ type: 'ready' });
      }
    } catch (error) { }
    post();
  }, 600);
  window.setInterval(post, 1000);
})();
