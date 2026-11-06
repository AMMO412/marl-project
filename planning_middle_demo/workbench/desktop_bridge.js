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
  function selectRun(id) {
    var element = q('#run-select');
    if (!element) return false;
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
  function play() {
    var button = q('#play');
    if (button && button.textContent.indexOf('暂') < 0) button.click();
    return true;
  }
  function pause() {
    var button = q('#play');
    if (button && button.textContent.indexOf('暂') >= 0) button.click();
    return true;
  }
  function setTime(seconds) {
    var scrubber = q('#scrubber');
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
    var allButton = q('#ck-cam-all');
    if (allButton) allButton.click();
    var containmentFit = q('#ck-fit');
    if (containmentFit) containmentFit.click();
    return true;
  }
  function startReplay(taskId, seconds) {
    var tries = 0;
    var timer = window.setInterval(function () {
      var duration = Number(((q('#duration') || {}).textContent || '0').replace(/[^0-9.\-]/g, '')) || 0;
      if (duration > 0) {
        window.clearInterval(timer);
        if (taskId) selectTask(taskId);
        setTime(seconds);
        play();
        fit();
      } else if (++tries > 40) {
        window.clearInterval(timer);
      }
    }, 500);
    return true;
  }
  function state() {
    var playButton = q('#play');
    var activePage = q('.nav.active');
    return {
      runId: (q('#run-select') || {}).value || '',
      taskId: (q('#task-select') || {}).value || '',
      time: Number(((q('#stat-clock') || {}).textContent || '0').replace(/[^0-9.\-]/g, '')) || 0,
      duration: Number(((q('#stat-end') || {}).textContent || '0').replace(/[^0-9.\-]/g, '')) || 0,
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
