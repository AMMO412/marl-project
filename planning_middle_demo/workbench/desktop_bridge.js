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
    '.desktop-mode{--ink:#30435b;--muted:#7f93a8;--green:#1f6fc3;--green-dark:#155a9e;--green-light:#edf4fd;--line:#e3eaf3;--bg:#f7f9fc;--side:#1f3552;--white:#fff}',
    '.desktop-mode body{background:#f7f9fc!important;color:#30435b!important}',
    '.desktop-mode .card{border-color:#e3eaf3!important;box-shadow:0 2px 3px #19384a08!important}',
    '.desktop-mode .card-heading h2{color:#304d6b!important}',
    '.desktop-mode .eyebrow{color:#8fa2b6!important}',
    '.desktop-mode .stat{background:#fff!important;border-color:#e3eaf3!important}',
    '.desktop-mode .stat-icon{color:#5b8fc9!important;background:#eef4fc!important}',
    '.desktop-mode .stat-number{color:#304d6b!important}',
    '.desktop-mode .clock-stat{background:#edf4fd!important;border-color:#d8e6f5!important}',
    '.desktop-mode .button.primary{background:#1f6fc3!important;border-color:#1f6fc3!important}',
    '.desktop-mode .map-toolbar,.desktop-mode .map-selection,.desktop-mode .player{background:#fff!important}',
    '.desktop-mode .canvas-wrap,.desktop-mode #scene{background:#fbfcfe!important}',
    '.desktop-mode #ck-canvas,.desktop-mode #hl-canvas{background:#fbfcfe!important;border-color:#e3eaf3!important}',
    '.desktop-mode #overview-ck-view,.desktop-mode .ck-body,.desktop-mode .ck-map-card,.desktop-mode .ck-panel{background:#f7f9fc!important}',
    '.desktop-mode .map-card{border-color:#e3eaf3!important}',
    '.desktop-mode .map-legend{border-top-color:#eef2f7!important;background:#fff!important}',
    '.desktop-mode .progress-track{background:#eef2f7!important}',
    '.desktop-mode .task-row.selected{background:#f1f6fd!important}',
    '.desktop-mode .behavior-tile{border-left-color:#8fb4dd!important}',
    '.desktop-mode .behavior-tile.selected{background:#f1f6fd!important}',
    '.desktop-mode .ck-kpis>div{background:#fff!important;border-color:#e3eaf3!important}',
    '.desktop-mode .ck-panel,.desktop-mode .ck-side .card{background:#fff!important;border-color:#e3eaf3!important}',
    '.desktop-mode .sidebar{display:none!important}',
    '.desktop-mode main{margin-left:0!important;padding:12px 18px 0!important;max-width:none!important}',
    '.desktop-mode .topbar,.desktop-mode .context-strip,.desktop-mode .run-strip,.desktop-mode footer{display:none!important}',
    '.desktop-mode .stats{margin-top:0!important}',
    '.desktop-mode .canvas-wrap{height:calc(100vh - 430px)!important;min-height:330px!important}',
    '.desktop-mode .right-column{display:none!important}',
    '.desktop-mode .overview-grid{grid-template-columns:minmax(0,1fr)!important}',
    '.desktop-mode .ck-layout{grid-template-columns:minmax(0,1fr)!important}',
    '.desktop-mode .ck-side{display:none!important}',
    '.desktop-mode #ck-canvas,.desktop-mode #hl-canvas{height:520px!important;min-height:520px!important}',
    '.desktop-mode .toast{left:50%!important}',
    '.desktop-mode .busy-banner{right:18px!important}'
  ].join('');
  document.head.appendChild(style);

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
  function selectRun(id) {
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
    var button = q('[data-page="' + page + '"]');
    if (!button) return false;
    button.click();
    return true;
  }
  function containmentActive() {
    var view = q('#overview-ck-view');
    return !!(view && !view.hidden);
  }
  function playerButton() {
    return containmentActive() ? q('#ck-play') : q('#play');
  }
  function play() {
    var button = playerButton();
    if (button && button.textContent.indexOf('暂') < 0) button.click();
    return true;
  }
  function pause() {
    var button = playerButton();
    if (button && button.textContent.indexOf('暂') >= 0) button.click();
    return true;
  }
  function setTime(seconds) {
    var scrubber = containmentActive() ? q('#ck-scrub') : q('#scrubber');
    if (!scrubber) return false;
    scrubber.value = Number(seconds) || 0;
    return fire(scrubber, 'input');
  }
  function setLayer(name, visible) {
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
    if (!element) return false;
    element.checked = !!visible;
    return fire(element, 'change');
  }
  function fit() {
    window.dispatchEvent(new Event('resize'));
    var button = q('#fit-map');
    if (button) button.click();
    try { if (typeof showOverviewMode === 'function') showOverviewMode('containment'); } catch (error) { }
    var areaButton = q('#ck-cam-area');
    if (areaButton) areaButton.click();
    var containmentFit = q('#ck-fit');
    if (containmentFit) containmentFit.click();
    var ckCanvas = q('#ck-canvas');
    if (ckCanvas) ckCanvas.scrollIntoView({ block: 'center' });
    return true;
  }
  function startReplay(taskId, seconds, runId) {
    var tries = 0;
    var timer = window.setInterval(function () {
      var duration = Number(((q('#duration') || {}).textContent || '0').replace(/[^0-9.\-]/g, '')) || 0;
      var currentRun = (q('#run-select') || {}).value || '';
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
        fit();
        setTime(seconds);
        play();
      } else if (++tries > 40) {
        window.clearInterval(timer);
      }
    }, 500);
    return true;
  }
  function state() {
    var activePage = q('.nav.active');
    var ck = containmentActive();
    var playButton = playerButton();
    var clock = ck ? (q('#ck-time') || {}).textContent : (q('#stat-clock') || {}).textContent;
    var duration = ck ? Number((q('#ck-scrub') || {}).max || 0) : Number(((q('#stat-end') || {}).textContent || '0').replace(/[^0-9.\-]/g, ''));
    return {
      runId: (q('#run-select') || {}).value || '',
      taskId: (q('#task-select') || {}).value || '',
      time: Number(String(clock || '0').replace(/[^0-9.\-]/g, '')) || 0,
      duration: Number(duration) || 0,
      playing: !!playButton && playButton.textContent.indexOf('暂') >= 0,
      page: activePage ? activePage.getAttribute('data-page') : 'overview'
    };
  }
  function post() {
    try {
      if (window.chrome && window.chrome.webview) {
        window.chrome.webview.postMessage({ type: 'state', state: state() });
      }
    } catch (error) { /* browser mode: no bridge */ }
  }

  window.MarlDesktop = {
    version: 1,
    ready: true,
    getState: state,
    selectRun: selectRun,
    selectTask: selectTask,
    navigate: navigate,
    play: play,
    pause: pause,
    setTime: setTime,
    setLayer: setLayer,
    fit: fit,
    refresh: refresh,
    startReplay: startReplay
  };

  setTimeout(function () {
    try {
      if (window.chrome && window.chrome.webview) {
        window.chrome.webview.postMessage({ type: 'ready' });
      }
    } catch (error) { }
    post();
  }, 600);
  window.setInterval(post, 1000);
})();
