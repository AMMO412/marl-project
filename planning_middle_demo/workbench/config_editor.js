(() => {
  const dialog = $('#editor-dialog');
  const source = $('#editor-source');
  const note = $('#editor-source-note');
  const error = $('#editor-error');
  const submit = $('#editor-submit');
  const tasks = $('#editor-tasks');
  const units = $('#editor-units');
  const targets = $('#editor-targets');
  const observationLibrary = $('#editor-observation-library');
  const addObservation = $('#editor-add-observation');
  const targetLibrary = $('#editor-target-library');
  const librarySlot = $('#editor-library-slot');
  const addLibraryTarget = $('#editor-add-library-target');
  const addTask = $('#editor-add-task');
  const newType = $('#editor-new-type');
  const addUnit = $('#editor-add-unit');
  const newUnitClass = $('#editor-new-unit-class');
  const addTarget = $('#editor-add-target');
  const targetTask = $('#editor-target-task');
  const targetSlot = $('#editor-target-slot');
  const preset = $('#editor-preset');
  const scenarioSelect = $('#config-scenario');
  const retiredScenes = new Set(['interop_relay','interop_neutral','asl_city','assault_city']);
  const legacyOptions = [...scenarioSelect.options].map(option => ({value:option.value, text:option.text}));
  const liveSetting = document.createElement('label');
  liveSetting.className = 'checkbox-field live-setting';
  const liveCheckbox = document.createElement('input');
  liveCheckbox.type = 'checkbox';
  liveCheckbox.name = 'live';
  liveCheckbox.checked = false;
  const liveLabel = document.createElement('span');
  liveSetting.append(liveCheckbox, liveLabel);
  scenarioSelect.closest('label').after(liveSetting);
  const modeHelp=document.createElement('p');modeHelp.id='live-mode-help';modeHelp.className='form-note';liveSetting.after(modeHelp);
  liveCheckbox.addEventListener('change',updateLiveSetting);
  function updateLiveSetting() {
    const template = state.templates?.[scenarioSelect.value];
    liveSetting.hidden = false; liveCheckbox.disabled = false;
    liveLabel.textContent = '实时运行（可暂停查看）';
    document.getElementById('live-mode-help').textContent = liveCheckbox.checked ? '边计算边显示：地图上的“暂停实时运行”会暂停计算，可查看或编辑当前状态。' : '先完成整轮计算，再播放结果；播放时暂停只影响回放。';
  }
  function syncTemplates() {
    const selected = scenarioSelect.value;
    const editorSelected = preset.value;
    const options = Object.entries(state.templates || {}).filter(([id]) => !retiredScenes.has(id));
    scenarioSelect.replaceChildren(...options.map(([id, t]) => new Option(t.label, id)),
      ...legacyOptions.filter(option => !retiredScenes.has(option.value) && !state.templates?.[option.value]).map(option => new Option(option.text,option.value)));
    preset.replaceChildren(...options.map(([id, t]) => new Option(t.label, id)));
    const fallback = state.catalog?.default_preset || options[0]?.[0];
    scenarioSelect.value = [...scenarioSelect.options].some(option => option.value === selected)
      ? selected : fallback;
    preset.value = state.templates?.[editorSelected] ? editorSelected : scenarioSelect.value;
    updateConfig();
    updateLiveSetting();
  }
  window.addEventListener('workbench-templates', syncTemplates);
  scenarioSelect.addEventListener('change', updateLiveSetting);
  if (state.templates) syncTemplates();
  else updateLiveSetting();
  const statuses = {READY: '可用', OFFLINE: '停用', LOST: '失联', BUSY: '占用', DAMAGED: '受损'};
  const classNames = {UGV: '轮式（UGV）', TANK: '履带（TANK）', PLANE: '固定翼（PLANE）', WING: '飞翼（WING）'};
  const classRanges = {UGV: [1, 20], TANK: [21, 30], PLANE: [31, 40], WING: [41, 50]};
  for (const [value, name] of Object.entries(classNames)) newUnitClass.add(new Option(name, value));
  const platformGroups = new Map();
  let unitRows = [];
  const geometryNames = {
    point: '单点', key_point: '关键点', target_list: '点列表',
    route: '路线', area: '区域', defense_area: '防守区域',
    sector: '扇区', patrol_area: '巡逻区域'
  };
  const pointKeys = new Set(['point', 'start', 'goal', 'staging_center', 'assessment_post',
    'withdraw_point', 'reserve_point', 'intercept_post', 'assembly_point', 'relay_point',
    'attack_window', 'direction']);
  const boolKeys = new Set(['authorized', 'compliance', 'track_until_stop', 'move_after_contact', 'allowed', 'swap_requires_arrival',
    'positive_id_required', 'patrol_enabled', 'follow_boundary', 'enabled', 'required']);
  const pointListKeys = new Set(['route', 'checkpoints', 'support_points', 'entry_points',
    'defense_positions', 'handover_points']);
  const numberKeys = new Set(['speed_mps', 'move_after_s', 'track_outside_s', 't_start_s',
    'count', 'ratio', 'interval_s', 'handover_tol_m', 'relief_cycles', 'enemy_ratio',
    'arrive_within_s', 'deadline_s', 'width', 'facing_deg', 'min_units', 'bearing_deg',
    'width_deg', 't_s', 'max_range_m', 'required_level', 'required_duration',
    'required_control_s', 'payload_required', 'assessment_delay', 'confirmation_deadline',
    'execute_deadline', 'withdraw_ring', 'withdraw_deadline', 'observe_radius',
    'observe_angle', 'objective_radius', 'staging_radius', 'arrive_tol', 'sync_tol',
    'confirm_radius', 'waves', 'ammo_per_platform', 'required_control_s']);
  let config;
  let loadToken = 0;
  let submitting = false;
  let liveId = null;
  let pausedId = null;
  let liveRevision = null;
  let liveTimer;
  let replayTime = 0;
  let rowSeq = 0;
  let recommendationQueue = Promise.resolve();

  const clone = value => JSON.parse(JSON.stringify(value ?? null));
  const isLiveSource = () => source.value === 'live' || source.value === 'run';
  const isNumber = value => typeof value === 'number' && Number.isFinite(value);
  const labelOf = key => config?.param_labels?.[key] || key;

  function numberValue(input, label) {
    if (input.value.trim() === '' || !Number.isFinite(Number(input.value))) {
      throw Error(label + '需要填写数字');
    }
    return Number(input.value);
  }

  function button(text, className = 'text-button param-add') {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = className;
    node.textContent = text;
    return node;
  }

  function chip(text, title) {
    const node = button(text, 'param-chip');
    if (title) node.title = title;
    return node;
  }

  function textRow(label, value, kind = 'text') {
    const wrapper = document.createElement('label');
    wrapper.className = 'param-field';
    const name = document.createElement('span');
    name.textContent = label;
    const input = document.createElement(kind === 'long' ? 'textarea' : 'input');
    if (kind === 'long') input.rows = 2;
    else input.type = 'text';
    input.value = value ?? '';
    wrapper.append(name, input);
    return {el: wrapper, input, get: () => input.value};
  }

  function numberRow(label, value) {
    const wrapper = document.createElement('label');
    wrapper.className = 'param-field';
    const name = document.createElement('span');
    name.textContent = label;
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.value = value ?? '';
    wrapper.append(name, input);
    return {el: wrapper, input, get: () => numberValue(input, label)};
  }

  function selectRow(label, value, options) {
    const wrapper = document.createElement('label');
    wrapper.className = 'param-field';
    const name = document.createElement('span');
    name.textContent = label;
    const select = document.createElement('select');
    for (const [key, text] of Object.entries(options)) select.add(new Option(text, key));
    select.value = value ?? '';
    wrapper.append(name, select);
    return {el: wrapper, input: select, get: () => select.value};
  }

  function inferKind(value) {
    if (isNumber(value)) return 'number';
    if (typeof value === 'boolean') return 'bool';
    if (typeof value === 'string') return 'text';
    if (Array.isArray(value)) {
      if (value.length === 2 && value.every(isNumber)) return 'point';
      if (!value.length) return 'empty_list';
      if (value.every(item => Array.isArray(item) && item.length === 2 && item.every(isNumber))) {
        return 'point_list';
      }
      if (value.every(item => typeof item === 'string')) return 'string_list';
      if (value.every(item => isNumber(item))) return 'number_list';
      if (value.every(item => item && typeof item === 'object' && !Array.isArray(item))) {
        return 'object_list';
      }
      return 'json';
    }
    if (value && typeof value === 'object') return 'object';
    return 'text';
  }

  function defaultForKey(key, valueKind) {
    if (valueKind === 'point' || pointKeys.has(key)) return [0, 0];
    if (boolKeys.has(key)) return false;
    if (pointListKeys.has(key)) return [];
    if (numberKeys.has(key)) return 0;
    return '';
  }

  function objectControl(value, valueKind, labels = {}) {
    const body = document.createElement('div');
    const fields = document.createElement('div');
    fields.className = 'param-fields';
    const children = new Map();
    function addChild(key, childValue) {
      if (children.has(key)) return;
      const row = paramRow(key, childValue, labels[key] ? {label: labels[key]} : {});
      children.set(key, row);
      fields.append(row.el);
    }
    for (const [key, childValue] of Object.entries(value || {})) addChild(key, childValue);
    body.append(fields);
    const actions = document.createElement('div');
    actions.className = 'param-actions';
    const add = chip('＋ 添加项');
    add.title = '为这个对象新增一个键（例如平台编号、角色名）';
    add.onclick = () => {
      const key = window.prompt('新增项键名（例如平台编号 U1、角色名 boundary）', '');
      if (!key || children.has(key)) return;
      addChild(key, defaultForKey(key, valueKind));
    };
    actions.append(add);
    body.append(actions);
    return {
      el: body,
      get: () => Object.fromEntries([...children].map(([key, row]) => [key, row.get()]))
    };
  }

  function objectListControl(value, spec) {
    const body = document.createElement('div');
    const list = document.createElement('div');
    list.className = 'param-list';
    let items = (Array.isArray(value) ? value : []).map(item => clone(item));
    let nodes = [];
    const title = (item, index) => {
      if (item && typeof item === 'object') {
        const name = item.id || item.target_id || item.gate_id;
        if (name) return String(name);
      }
      return '第 ' + (index + 1) + ' 项';
    };
    function capture() {
      nodes.forEach((node, index) => {
        try { items[index] = node.get(); } catch { /* keep previous value */ }
      });
    }
    function render() {
      list.replaceChildren();
      nodes = items.map((item, index) => {
        const card = document.createElement('div');
        card.className = 'param-item';
        const head = document.createElement('div');
        head.className = 'param-item-head';
        const name = document.createElement('b');
        name.textContent = title(item, index);
        const remove = button('删除');
        remove.onclick = () => {
          capture();
          items.splice(index, 1);
          render();
        };
        head.append(name, remove);
        const inner = objectControl(item && typeof item === 'object' && !Array.isArray(item) ? item : {});
        card.append(head, inner.el);
        return {el: card, get: inner.get};
      });
      list.append(...nodes.map(node => node.el));
    }
    render();
    body.append(list);
    const actions = document.createElement('div');
    actions.className = 'param-actions';
    const add = chip('＋ 添加一项');
    add.onclick = () => {
      capture();
      const template = spec?.item ?? {};
      items.push(clone(template));
      render();
    };
    actions.append(add);
    body.append(actions);
    return {el: body, get: () => nodes.map(node => node.get())};
  }

  function pointListControl(value) {
    const body = document.createElement('div');
    const list = document.createElement('div');
    list.className = 'param-list';
    let points = (Array.isArray(value) ? value : []).map(point => clone(point));
    let rows = [];
    function capture() {
      rows.forEach((row, index) => {
        try { points[index] = row.get(); } catch { /* keep previous value */ }
      });
    }
    function render() {
      list.replaceChildren();
      rows = points.map((point, index) => {
        const card = document.createElement('div');
        card.className = 'param-item';
        const head = document.createElement('div');
        head.className = 'param-item-head';
        const name = document.createElement('b');
        name.textContent = '点 ' + (index + 1);
        const remove = button('删除');
        remove.onclick = () => {
          capture();
          points.splice(index, 1);
          render();
        };
        head.append(name, remove);
        const row = pointControl(point, '坐标');
        card.append(head, row.el);
        return {el: card, get: row.get};
      });
      list.append(...rows.map(row => row.el));
    }
    render();
    body.append(list);
    const actions = document.createElement('div');
    actions.className = 'param-actions';
    const add = chip('＋ 添加点');
    add.onclick = () => {
      capture();
      points.push([0, 0]);
      render();
    };
    actions.append(add);
    body.append(actions);
    return {el: body, get: () => rows.map(row => row.get())};
  }

  function pointControl(value, axesLabel, axes) {
    const body = document.createElement('div');
    body.className = 'param-point';
    const values = Array.isArray(value) ? value : [0, 0];
    const names = axes || ['X', 'Y'];
    const inputs = names.map((name, index) => {
      const wrapper = document.createElement('label');
      wrapper.textContent = name;
      const input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.value = values[index] ?? '';
      wrapper.append(input);
      body.append(wrapper);
      return {input, name: axesLabel + ' ' + name};
    });
    return {
      el: body,
      get: () => inputs.map(item => numberValue(item.input, item.name))
    };
  }

  function paramRow(key, value, spec = {}, onRemove) {
    const kind = spec.kind || inferKind(value);
    const label = spec.label || labelOf(key);
    const wide = ['object', 'object_list', 'point_list', 'json', 'empty_list', 'number_list']
      .includes(kind) || (kind === 'string_list');
    const frame = document.createElement('div');
    frame.className = 'param-frame' + (wide ? ' wide' : '') +
      (kind === 'object' ? ' param-group' : '');
    const head = document.createElement('div');
    head.className = 'param-field-head';
    const name = document.createElement('span');
    name.textContent = label;
    name.title = key;
    head.append(name);
    if (onRemove) {
      const remove = button('移除', 'text-button param-add');
      remove.title = '从任务参数中移除';
      remove.onclick = onRemove;
      head.append(remove);
    }
    frame.append(head);
    const body = document.createElement('div');
    frame.append(body);
    let get;
    if (spec.options) {
      const options = {...spec.options};
      if (value && !(value in options)) options[value] = String(value);
      const control = selectRow(label, value ?? Object.keys(options)[0], options);
      control.input.setAttribute('aria-label', label);
      body.append(control.input);
      get = control.get;
    } else if (kind === 'number') {
      const input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.value = value ?? '';
      body.append(input);
      get = () => numberValue(input, label);
    } else if (kind === 'bool') {
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = Boolean(value);
      body.append(input);
      get = () => input.checked;
    } else if (kind === 'text' || kind === 'json') {
      const long = kind === 'json' || String(value ?? '').length > 40;
      const input = document.createElement(long ? 'textarea' : 'input');
      if (long) input.rows = kind === 'json' ? 3 : 2;
      else input.type = 'text';
      input.value = kind === 'json' ? JSON.stringify(value, null, 2) : (value ?? '');
      body.append(input);
      get = () => {
        if (kind !== 'json') return value === null && input.value === '' ? null : input.value;
        try {
          return JSON.parse(input.value);
        } catch {
          throw Error(label + '的格式无效');
        }
      };
    } else if (kind === 'point') {
      const control = pointControl(value, label, spec.axes);
      body.append(control.el);
      get = control.get;
    } else if (kind === 'string_list' || kind === 'empty_list') {
      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = '用逗号分隔多个值';
      input.value = (Array.isArray(value) ? value : []).join(', ');
      body.append(input);
      get = () => input.value.split(/[,，]/).map(item => item.trim()).filter(Boolean);
    } else if (kind === 'number_list') {
      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = '用逗号分隔多个数字';
      input.value = (Array.isArray(value) ? value : []).join(', ');
      body.append(input);
      get = () => input.value.split(/[,，]/).map(item => item.trim()).filter(Boolean)
        .map(item => {
          if (!Number.isFinite(Number(item))) throw Error(label + '中有无效数字');
          return Number(item);
        });
    } else if (kind === 'point_list') {
      const control = pointListControl(value);
      body.append(control.el);
      get = control.get;
    } else if (kind === 'object_list') {
      const control = objectListControl(value, spec);
      body.append(control.el);
      get = control.get;
    } else if (kind === 'object') {
      const control = objectControl(value, spec.value_kind, spec.labels);
      body.append(control.el);
      get = control.get;
    } else {
      const control = objectControl(value, spec.value_kind);
      body.append(control.el);
      get = control.get;
    }
    return {el: frame, get, key, kind};
  }

  function card(parent, title, included) {
    const row = document.createElement('div');
    row.className = 'editor-row';
    const toggle = document.createElement('label');
    const enabled = document.createElement('input');
    enabled.type = 'checkbox';
    enabled.checked = included;
    toggle.append(enabled, ' 纳入本轮');
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = title;
    const fields = document.createElement('div');
    fields.className = 'editor-fields';
    details.append(summary, fields);
    row.append(toggle, details);
    parent.append(row);
    return {row, enabled, fields, details};
  }

  function plainCard(parent, title) {
    const row = document.createElement('div');
    row.className = 'editor-row';
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = title;
    const fields = document.createElement('div');
    fields.className = 'editor-fields';
    details.append(summary, fields);
    row.append(details);
    parent.append(row);
    return {row, fields, details};
  }

  function taskRowByRef(ref) {
    return [...tasks.children].find(row => row.ref === ref);
  }

  function allTaskRows() {
    return [...tasks.children].filter(row => row.taskId);
  }

  function findTaskRow(taskId) {
    return [...tasks.children].find(row => row.originalTaskId === taskId) ||
      [...tasks.children].find(row => row.taskId?.value.trim() === taskId);
  }

  function slotSpec(slot) {
    return config?.target_slots?.[slot];
  }

  function slotAllowed(slot, taskType) {
    const spec = slotSpec(slot);
    return Boolean(spec && spec.task_types.includes(taskType));
  }

  function refreshTargetTools() {
    if (!config) return;
    const rows = allTaskRows().filter(row => !row.pendingDelete &&
      !(isLiveSource() && row.completed));
    const previous = targetTask.value;
    targetTask.replaceChildren(...rows.map(row =>
      new Option((row.taskId.value.trim() || '未命名任务') + ' · ' + (config.task_types[row.typeNode.get()]?.label || row.typeNode.get()), row.ref)));
    if (rows.some(row => row.ref === previous)) targetTask.value = previous;
    updateTargetSlots();
    refreshObservationLinks();
  }

  function updateTargetSlots() {
    const row = taskRowByRef(targetTask.value);
    if (!row) {
      targetSlot.replaceChildren();
      addTarget.disabled = true;
      return;
    }
    const type = row.typeNode.get();
    const used = new Set([...targets.children].map(item => item.slot + '|' + item.taskRef));
    const options = Object.entries(config.target_slots || {}).filter(([name, spec]) =>
      name !== 'hold' && spec.task_types.includes(type) &&
      (spec.multi || !used.has(name + '|' + row.ref)));
    targetSlot.replaceChildren(...options.map(([name, spec]) => new Option(spec.label, name)));
    addTarget.disabled = !config.editable || options.length === 0;
  }

  function observationRows() {
    return [...observationLibrary.children];
  }

  const librarySlotByTask = {'T-PTL': 'observation', 'T-RCN': 'tracking',
    'T-SEC': 'intruder', 'T-ASL': 'assault'};
  const targetRows = () => [...observationLibrary.children, ...targetLibrary.children];
  const associationLocked = row => !config.editable || row.relayTracking || (isLiveSource() && row.completed);
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function pointSegmentDistance(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const length2 = dx * dx + dy * dy;
    const t = length2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) : 0;
    return distance(p, [a[0] + t * dx, a[1] + t * dy]);
  }

  function inside(point, polygon) {
    let result = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [ax, ay] = polygon[i], [bx, by] = polygon[j];
      const [x, y] = point;
      if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) result = !result;
    }
    return result;
  }

  function pathDistance(start, goal, points, closed) {
    if (closed && (inside(start, points) || inside(goal, points))) return 0;
    if (!points.length) return Infinity;
    if (points.length === 1) return pointSegmentDistance(points[0], start, goal);
    const orientation = (a, b, p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    let best = Infinity;
    for (let i = 0; i < points.length - (closed ? 0 : 1); i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      if (orientation(start, goal, a) * orientation(start, goal, b) < 0 &&
          orientation(a, b, start) * orientation(a, b, goal) < 0) return 0;
      best = Math.min(best, pointSegmentDistance(a, start, goal), pointSegmentDistance(b, start, goal),
        pointSegmentDistance(start, a, b), pointSegmentDistance(goal, a, b));
    }
    return best;
  }

  function targetMatch(task, spec, slot) {
    const shape = task.associationShape();
    if (!shape?.points.length) return Infinity;
    const {points, kind} = shape;
    const closed = ['area', 'sector', 'patrol_area', 'defense_area'].includes(kind);
    const aim = task.aimPoint();
    if (slot === 'hold' || slot === 'assault') return distance(spec.point, aim);
    if (slot === 'tracking') {
      if (kind !== 'area' || !(task.paramsNode.has('search_points') || task.paramsNode.has('search_starts'))
          || !inside(spec.start, points) || inside(spec.goal, points)) return Infinity;
      return distance(spec.start, aim);
    }
    if (slot === 'intruder') {
      return closed && pathDistance(spec.start, spec.goal, points, closed) < 1e-6
        ? pointSegmentDistance(aim, spec.start, spec.goal) : Infinity;
    }
    const window = task.associationWindow();
    const anchor = spec.start_task_id && findTaskRow(spec.start_task_id);
    const release = (anchor ? anchor.associationWindow().start : 0) + spec.start_s;
    if (release >= window.end) return Infinity;
    const scale = config.formation.meta?.cell_size_m || 1;
    const duration = distance(spec.start, spec.goal) * scale / spec.speed_mps;
    const at = t => {
      const progress = duration > 0 ? Math.max(0, Math.min(1, (t - release) / duration)) : 0;
      return spec.start.map((coordinate, index) => coordinate + progress * (spec.goal[index] - coordinate));
    };
    const separation = pathDistance(at(window.start), at(window.end), points, closed);
    return separation * scale <= task.associationRadius() ? separation : Infinity;
  }

  function updateAutomaticLinks(rows, definitions) {
    const occupied = new Set();
    const pending = rows.filter(row => !associationLocked(row) && row.targetLinkMode.get() === 'auto');
    for (const row of rows) {
      if (!pending.includes(row)) for (const key of row.targetKeys) occupied.add(key);
    }
    const matches = [];
    for (const row of pending) {
      if (!row.included.checked) continue;
      for (const target of definitions) {
        const slot = target.librarySlot;
        if (slot !== row.targetSlot || (slot !== 'observation' && occupied.has(target.libraryKey))) continue;
        try {
          const score = targetMatch(row, target.getConfig(), slot);
          if (Number.isFinite(score)) matches.push({row, target, score});
        } catch {
          // Incomplete form values are checked when previewing or saving.
        }
      }
    }
    const before = new Map(pending.map(row => [row, row.targetKeys]));
    for (const row of pending) row.targetKeys = new Set();
    matches.sort((a, b) => a.score - b.score);
    for (const {row, target} of matches) {
      const slot = target.librarySlot;
      if (slot !== 'observation' && occupied.has(target.libraryKey)) continue;
      if (!['observation', 'intruder'].includes(slot) && row.targetKeys.size) continue;
      row.targetKeys.add(target.libraryKey);
      if (slot !== 'observation') occupied.add(target.libraryKey);
    }
    for (const row of pending) {
      const previous = before.get(row);
      if (row.targetKeys.size !== previous.size || [...row.targetKeys].some(key => !previous.has(key))) row.markDirty();
    }
  }

  function refreshObservationLinks() {
    if (!config) return;
    const rows = allTaskRows().filter(row => !row.pendingDelete && row.targetBox);
    const definitions = targetRows();
    updateAutomaticLinks(rows, definitions);
    for (const row of rows) {
      const options = definitions.filter(target => target.librarySlot === row.targetSlot);
      const inputs = options.map(target => {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = row.targetKeys.has(target.libraryKey);
        const owner = ['tracking', 'intruder'].includes(row.targetSlot)
          && rows.find(task => task !== row && task.targetKeys.has(target.libraryKey));
        input.disabled = associationLocked(row) || Boolean(owner);
        if (owner) label.title = '当前由 ' + owner.taskId.value.trim() + ' 驱动';
        input.addEventListener('change', () => {
          row.targetLinkMode.input.value = 'manual';
          if (input.checked) {
            if (!['observation', 'intruder'].includes(row.targetSlot)) row.targetKeys.clear();
            row.targetKeys.add(target.libraryKey);
          } else row.targetKeys.delete(target.libraryKey);
          row.markDirty();
          refreshObservationLinks();
        });
        label.append(input, ' ' + target.displayName() + (owner ? '（' + owner.taskId.value.trim() + '）' : ''));
        return label;
      });
      row.targetBox.replaceChildren(...inputs);
      if (row.relayTracking) row.targetBox.textContent = '本任务的跟踪目标已由接力演示配置。';
      else if (!inputs.length) row.targetBox.textContent = '可在红方目标配置中先添加此用途的目标。';
    }
    for (const target of definitions) target.refresh(rows);
    addObservation.disabled = !config.editable || observationRows().length >= 100;
    addLibraryTarget.disabled = !config.editable || targetLibrary.children.length >= 100;
  }

  function observationCard(spec, open = false) {
    const {row, fields, details} = plainCard(observationLibrary, spec.target_id);
    row.classList.add('editor-target-row');
    row.libraryKey = 'observation-' + (++rowSeq);
    row.librarySlot = 'observation';
    const id = textRow('目标编号', spec.target_id);
    id.input.readOnly = !open;
    const start = paramRow('start', spec.start, {kind: 'point', label: '起点坐标'});
    const goal = paramRow('goal', spec.goal, {kind: 'point', label: '终点坐标'});
    const speed = numberRow('移动速度（米/秒）', spec.speed_mps);
    const release = numberRow('出场时间或延时（秒）', spec.start_s ?? 0);
    const clock = selectRow('出场计时', '', {'': '从仿真开始计时'});
    const summary = details.querySelector('summary');
    const usedBy = document.createElement('p');
    usedBy.className = 'editor-target-note';
    const remove = button('删除观察目标', 'text-button');
    let initialAnchor = spec.start_task_id;
    fields.append(id.el, start.el, goal.el, speed.el, clock.el, release.el, usedBy, remove);
    row.displayName = () => id.get().trim() || '未命名目标';
    row.refresh = rows => {
      const patrols = rows.filter(task => task.targetSlot === 'observation');
      const linked = patrols.filter(task => task.targetKeys.has(row.libraryKey));
      const names = linked.map(task => task.taskId.value.trim()).filter(Boolean);
      const previous = clock.input.value;
      const previousLabel = clock.input.selectedOptions[0]?.textContent;
      const anchor = patrols.find(task => initialAnchor && task.taskId.value.trim() === initialAnchor);
      clock.input.replaceChildren(new Option('从仿真开始计时', ''),
        ...patrols.map(task => new Option(task.taskId.value.trim() + ' 开始执行后', task.ref)));
      if (previous && !patrols.some(task => task.ref === previous)) {
        clock.input.add(new Option(previousLabel?.replace(/（不可用）$/, '') + '（不可用）', previous));
      }
      clock.input.value = anchor?.ref || previous;
      if (anchor) initialAnchor = undefined;
      summary.textContent = row.displayName() + ' · ' + (names.length ? names.join('、') : '未关联任务');
      usedBy.textContent = names.length
        ? '改动会应用到关联任务 ' + names.join('、') + '。解除全部关联后可删除。'
        : '该目标可随本轮演示保存，之后再关联到巡逻任务。';
      remove.disabled = !config.editable || linked.length > 0;
    };
    fields.addEventListener('change', refreshObservationLinks);
    remove.onclick = () => {
      if (remove.disabled) return;
      row.remove();
      refreshObservationLinks();
    };
    row.getConfig = () => {
      const target = {target_id: id.get().trim(), start: start.get(), goal: goal.get(),
        speed_mps: speed.get(), start_s: release.get()};
      const anchor = taskRowByRef(clock.get()) || (initialAnchor && findTaskRow(initialAnchor));
      if (clock.get() && (!anchor || anchor.pendingDelete || anchor.typeNode.get() !== 'T-PTL')) {
        throw Error(row.displayName() + ' 的出场触发任务已不可用，请重新选择出场计时。');
      }
      if (anchor) target.start_task_id = anchor.taskId.value.trim();
      return target;
    };
    if (!config.editable) {
      for (const input of fields.querySelectorAll('input, select, button')) input.disabled = true;
    }
    details.open = open;
    return row;
  }

  function libraryTargetCard(entry, open = false) {
    const {row, fields, details} = plainCard(targetLibrary, entry.target_id);
    const spec = slotSpec(entry.slot);
    row.classList.add('editor-target-row');
    row.libraryKey = 'target-' + (++rowSeq);
    row.librarySlot = entry.slot;
    const nodes = new Map(spec.fields.map(field => [field.key,
      paramRow(field.key, entry[field.key] ?? spec.defaults[field.key], {kind: field.kind, label: field.label})]));
    const id = nodes.get('target_id');
    id.el.querySelector('input').readOnly = !open;
    row.displayName = () => id.get().trim() || '未命名目标';
    const note = document.createElement('p');
    note.className = 'editor-target-note';
    const remove = button('删除目标', 'text-button');
    const summary = details.querySelector('summary');
    fields.append(...[...nodes.values()].map(node => node.el), note, remove);
    row.getConfig = () => ({...entry, ...Object.fromEntries([...nodes].map(([key, node]) => [key, node.get()])),
      target_id: id.get().trim()});
    row.refresh = rows => {
      const linked = rows.filter(task => task.targetKeys.has(row.libraryKey));
      const names = linked.map(task => task.taskId.value.trim()).join('、');
      summary.textContent = row.displayName() + ' · ' + spec.label + ' · ' + (names || '未关联任务');
      note.textContent = names ? '关联任务 ' + names + '。解除关联后可删除。' : spec.help;
      remove.disabled = !config.editable || linked.length > 0;
    };
    remove.onclick = () => {
      row.remove();
      refreshObservationLinks();
    };
    fields.addEventListener('change', refreshObservationLinks);
    if (!config.editable) for (const input of fields.querySelectorAll('input, select, button')) input.disabled = true;
    details.open = open;
    return row;
  }

  function loadTaskTargets(data) {
    // Keep task-local targets in their established execution fields.
    // Opening a form must not migrate them into an unsupported global library.
    for (const raw of data.message.tasks) taskCard(raw, data.completed.includes(raw.task_id));
    for (const target of data.targets || []) targetCard(target, findTaskRow(target.task_id));
  }

  function nextTargetId(slot, index) {
    const base = {tracking: 'RCN-TGT', observation: 'PTL-TGT', relay: 'RELAY-TGT',
      intruder: 'IN', assault: 'ASL-TGT', hold: 'HLD-PT'}[slot] || 'TGT';
    let n = index + 1;
    const ids = new Set([...targetRows().map(row => row.displayName()),
      ...[...targets.children].map(row => row.targetId?.value.trim())]);
    while (ids.has(base + '-' + n)) n++;
    return base + '-' + n;
  }

  function targetCard(entry, taskRow) {
    const spec = slotSpec(entry.slot);
    if (!spec) return null;
    const locked = !config.editable || (isLiveSource() && taskRow?.completed);
    const titleId = entry.target_id || '新目标';
    const {row, fields, details} = plainCard(targets,
      titleId + ' · ' + spec.label + ' · ' + (entry.task_id || taskRow?.taskId.value.trim() || ''));
    row.className += ' editor-target-row';
    row.targetRef = taskRow?.ref || entry.taskRef;
    row.slot = entry.slot;
    const nodes = new Map();
    const values = {...(spec.defaults || {}), ...entry};
    for (const field of spec.fields) {
      const value = values[field.key] ?? spec.defaults?.[field.key];
      const node = paramRow(field.key, value, {kind: field.kind, label: field.label});
      if (field.kind === 'point' && !Array.isArray(value)) {
        // Fall back to the task's aim point so a new target starts near its task.
        const base = taskRow?.aimPoint?.() || [0, 0];
        node.get = () => [Number(node.el.querySelectorAll('input')[0]?.value || base[0]),
          Number(node.el.querySelectorAll('input')[1]?.value || base[1])];
      }
      nodes.set(field.key, node);
      fields.append(node.el);
    }
    const inputOf = node => node?.el.querySelector('input, textarea');
    row.targetId = inputOf(nodes.get('target_id'));
    const kind = entry.kind;
    const summary = details.querySelector('summary');
    const updateTitle = () => {
      const id = inputOf(nodes.get('target_id'))?.value.trim();
      summary.textContent = (id || '新目标') + ' · ' + spec.label + ' · ' +
        (taskRow?.taskId.value.trim() || entry.task_id || '');
      row.targetId = inputOf(nodes.get('target_id'));
    };
    fields.addEventListener('input', updateTitle);
    row.applyMapPoints = moved => {
      for (const key of ['point', 'start', 'goal']) {
        if (!Array.isArray(moved[key]) || !nodes.has(key)) continue;
        const inputs = nodes.get(key).el.querySelectorAll('input');
        moved[key].forEach((value, index) => { inputs[index].value = value; });
      }
    };
    if (locked) {
      for (const input of fields.querySelectorAll('input, select, textarea')) input.disabled = true;
      fields.append(Object.assign(document.createElement('p'), {
        className: 'editor-target-note',
        textContent: '已完成任务的目标保持锁定，红方目标只影响后续任务。'
      }));
    } else if (spec.deletable) {
      const actions = document.createElement('div');
      actions.className = 'editor-task-actions';
      const remove = button('删除目标', 'text-button');
      remove.onclick = () => {
        row.pendingDelete = !row.pendingDelete;
        row.classList.toggle('editor-task-deleted', row.pendingDelete);
        fields.hidden = row.pendingDelete;
        remove.textContent = row.pendingDelete ? '撤销删除' : '删除目标';
        if (row.pendingDelete) {
          details.open = false;
          summary.textContent = (row.targetId?.value.trim() || '新目标') + ' · 待删除';
        } else {
          updateTitle();
        }
        updateTargetSlots();
      };
      actions.append(remove);
      row.append(actions);
    } else {
      fields.append(Object.assign(document.createElement('p'), {
        className: 'editor-target-note',
        textContent: '突击目标点由任务本身派生，不能删除；坐标改动写回任务的 target。'
      }));
    }
    row.getConfig = () => {
      if (row.pendingDelete) return null;
      const value = {slot: entry.slot, taskRef: row.targetRef};
      if (entry.slot === 'assault') value.kind = kind || 'point';
      for (const [key, node] of nodes) {
        try {
          value[key] = node.get();
        } catch (err) {
          details.open = true;
          throw Error(summary.textContent + ' · ' + err.message);
        }
      }
      return value;
    };
    return row;
  }

  function addTargetFor(taskRow) {
    const slot = targetSlot.value;
    const spec = slotSpec(slot);
    if (!spec || !taskRow) return;
    const base = taskRow.aimPoint();
    const entry = {slot, task_id: taskRow.taskId.value.trim(), ...clone(spec.defaults || {})};
    for (const field of spec.fields) {
      if (field.kind === 'point') {
        entry[field.key] = field.key === 'goal' ? [base[0] + 20, base[1]] : base;
      }
    }
    entry.target_id = nextTargetId(slot, targets.children.length);
    if (slot === 'assault') {
      entry.kind = taskRow.geometryKind();
      entry.point = base;
    }
    const row = targetCard(entry, taskRow);
    if (row) {
      row.open = true;
      row.scrollIntoView({block: 'nearest'});
    }
    updateTargetSlots();
  }

  function syncTargets() {
    for (const row of [...targets.children]) {
      const taskRow = taskRowByRef(row.targetRef);
      if (!taskRow || taskRow.pendingDelete || !slotAllowed(row.slot, taskRow.typeNode.get())) {
        row.remove();
      }
    }
    for (const taskRow of allTaskRows()) {
      if (taskRow.typeNode.get() !== 'T-ASL' || taskRow.pendingDelete) continue;
      if (![...targets.children].some(row => row.slot === 'assault' && row.targetRef === taskRow.ref)) {
        const base = taskRow.aimPoint();
        targetCard({slot: 'assault', task_id: taskRow.taskId.value.trim(), kind: taskRow.geometryKind(),
          target_id: '', object_label: '', point: base}, taskRow);
      }
    }
    refreshTargetTools();
  }

  function patrolRadius(value, onRemove) {
    const radii = typeof value === 'number' ? {ground: value, air: value} : (value || {});
    const ground = numberRow('地面探测半径（米）', radii.ground);
    const air = numberRow('空中探测半径（米）', radii.air);
    const group = document.createElement('div');
    group.className = 'param-group';
    const head = document.createElement('div');
    head.className = 'param-field-head';
    const title = document.createElement('span');
    title.textContent = '探测半径';
    const remove = button('移除');
    remove.onclick = onRemove;
    head.append(title, remove);
    const fields = document.createElement('div');
    fields.className = 'param-fields';
    fields.append(ground.el, air.el);
    group.append(head, fields);
    return {el: group, get() {
      const values = {};
      for (const [key, node] of [['ground', ground], ['air', air]]) {
        if (node.input.value === '' && !(key in radii)) continue;
        const radius = node.get();
        if (radius <= 0) throw Error(node.el.textContent + '必须大于 0');
        values[key] = radius;
      }
      if (!Object.keys(values).length) throw Error('至少设置一种平台的探测半径');
      return values;
    }};
  }

  function taskDependencies(row, initial, disabled) {
    const selection = new Set(initial);
    const fields = document.createElement('fieldset');
    fields.className = 'param-group patrol-dependencies';
    const label = document.createElement('legend');
    label.textContent = '前置任务';
    fields.append(label);
    const list = document.createElement('div');
    fields.append(list);
    return {el: fields, get: () => [...selection], refresh() {
      const options = new Map(allTaskRows().filter(other => other !== row && !other.pendingDelete)
        .map(other => [other.taskId.value.trim(), other.taskId.value.trim() + ' · ' +
          config.task_types[other.typeNode.get()]?.label]));
      for (const id of selection) {
        if (!options.has(id)) options.set(id, id + '（当前不可选）');
      }
      fields.hidden = !options.size;
      list.replaceChildren(...[...options].map(([id, text]) => {
        const item = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = selection.has(id);
        input.disabled = disabled;
        input.addEventListener('change', () => {
          if (input.checked) selection.add(id);
          else selection.delete(id);
        });
        item.append(input, text);
        return item;
      }));
    }};
  }

  function taskMap(canvas, row, slots) {
    const context = canvas.getContext('2d');
    const width = canvas.width, height = canvas.height;
    const formation = config.formation;
    const areas = new Set(['area', 'patrol_area', 'defense_area', 'sector']);
    const obstacles = (formation.constraints || []).filter(zone => zone.type === 'no_go')
      .map(zone => zone.area?.polygon || zone.area).filter(points => points?.length);
    const shapes = allTaskRows().filter(other => other === row ||
      (other.included.checked && !other.pendingDelete && !other.completed))
      .map(other => ({...other.mapShape?.(), current: other === row}))
      .filter(shape => shape.points?.length);
    const poses = unitRows.flatMap(unitRow => {
      try {
        const unit = unitRow.getConfig(false);
        return unit?.status === 'READY' ? [[unit.position.x, unit.position.y]] : [];
      } catch { return []; }
    });
    const points = shapes.flatMap(shape => shape.points).concat(poses);
    if (!points.length) return;
    const xs = points.map(([x]) => x), ys = points.map(([, y]) => y);
    const extent = formation.meta?.map_scene_bounds || formation.meta?.scene_bounds ||
      [Math.min(...xs) - 12, Math.min(...ys) - 12, Math.max(...xs) + 12, Math.max(...ys) + 12];
    const [xmin, ymin, xmax, ymax] = extent;
    const scale = Math.min((width - 24) / (xmax - xmin), (height - 24) / (ymax - ymin));
    const left = (width - (xmax - xmin) * scale) / 2;
    const top = (height - (ymax - ymin) * scale) / 2;
    const project = ([x, y]) => [left + (x - xmin) * scale, top + (ymax - y) * scale];
    function draw(points, closed, color, fill) {
      context.beginPath();
      points.forEach((point, index) => {
        const [x, y] = project(point);
        if (points.length === 1) context.arc(x, y, 4, 0, Math.PI * 2);
        else if (!index) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      if (closed) context.closePath();
      if (fill) {
        context.fillStyle = fill;
        context.fill();
      }
      context.strokeStyle = color;
      context.stroke();
    }
    context.clearRect(0, 0, width, height);
    context.lineWidth = 1;
    for (const obstacle of obstacles) draw(obstacle, true, '#b8c2be', '#e1e8e4');
    for (const pose of poses) draw([pose], false, '#527bb0', '#dbe9fd');
    for (const target of targetRows().filter(item => row.targetKeys?.has(item.libraryKey))) {
      try {
        const spec = target.getConfig();
        if (spec.start) draw([spec.start, spec.goal], false, '#a8442f', null);
        draw([spec.start || spec.point], false, '#a8442f', '#fff');
      } catch {
        // The editor validates partially entered coordinates on preview/save.
      }
    }
    for (const shape of [...shapes.filter(shape => !shape.current), ...shapes.filter(shape => shape.current)]) {
      context.lineWidth = shape.current ? 2.5 : 1.5;
      const closed = areas.has(shape.kind);
      const color = shape.current ? '#08785c' : '#ad773f';
      draw(shape.points, closed, color, closed ? color + '24' : null);
      context.fillStyle = color;
      context.font = '13px sans-serif';
      const [x, y] = project(shape.points[0]);
      context.fillText(shape.id, x + 5, y - 5);
    }
    context.lineWidth = 1;
    slots.forEach((slot, index) => {
      if (!slot.point) return;
      draw([slot.point], false, '#08785c', '#ffffff');
      const [x, y] = project(slot.point);
      context.fillStyle = '#08785c';
      context.fillText(String(index + 1), x + 5, y + 12);
    });
    return event => {
      const box = canvas.getBoundingClientRect();
      return [xmin + ((event.clientX - box.left) * width / box.width - left) / scale,
        ymax - ((event.clientY - box.top) * height / box.height - top) / scale];
    };
  }

  function taskTools(row, pins, applyPlacement, fresh, template) {
    const box = document.createElement('div');
    box.className = 'patrol-editor';
    const canvas = document.createElement('canvas');
    canvas.width = 600;
    canvas.height = 280;
    canvas.setAttribute('aria-label', '任务地图，绿色为当前任务，棕色为已有任务，灰色为障碍');
    const hint = document.createElement('p');
    hint.className = 'editor-hint';
    hint.textContent = (fresh ? '已载入' + template.label + '演示模板。' : '') +
      '绿色为当前任务，棕色为已有任务，灰色为障碍，蓝点为可纳入的平台。';
    const actions = document.createElement('div');
    actions.className = 'patrol-actions';
    const recommend = button('推荐任务位置', 'button');
    const place = button('在地图上移动', 'button');
    const trial = button('试算平台', 'button');
    const reset = button('还原席位默认分配', 'button');
    actions.append(recommend, place, trial, reset);
    const status = document.createElement('p');
    status.className = 'patrol-status';
    status.setAttribute('role', 'status');
    const slots = document.createElement('div');
    slots.className = 'patrol-slots';
    box.append(hint, canvas, actions, status, slots);

    let requestId = 0;
    let projectClick;
    let latestSlots = [];
    function renderSlots() {
      slots.replaceChildren();
      reset.hidden = !Object.keys(pins).length;
      const ready = new Map(unitRows.flatMap(unitRow => {
        try {
          const unit = unitRow.getConfig(false);
          return unit?.status === 'READY'
            ? [[unit.unit_id, {kind: unit.platform_class,
                label: unit.unit_id + ' · ' + (classNames[unit.platform_class] || unit.platform_class)}]]
            : [];
        } catch { return []; }
      }));
      for (const [index, slot] of latestSlots.entries()) {
        const options = Object.create(null);
        const assigned = ready.get(slot.unit_id);
        options[''] = !slot.pinned_unit && !slot.pinned_class && assigned
          ? '自动 · ' + assigned.label : '自动分配';
        const eligible = slot.eligible.filter(id => ready.has(id) &&
          !latestSlots.some(other => other !== slot && other.pinned_unit === id));
        const kinds = new Set(eligible.map(id => ready.get(id).kind));
        for (const kind of kinds) {
          const selected = slot.pinned_class === kind && assigned ? ' · ' + slot.unit_id : '';
          options['class:' + kind] = classNames[kind] + ' · 自动选台' + selected;
        }
        for (const id of eligible) options['unit:' + id] = ready.get(id).label;
        const value = slot.pinned_class ? 'class:' + slot.pinned_class :
          slot.pinned_unit ? 'unit:' + slot.pinned_unit : '';
        if (value && !(value in options)) {
          options[value] = (classNames[slot.pinned_class] || slot.pinned_unit) + '（当前不可用）';
        }
        const [role, name] = (slot.role || '').split(':');
        const roleName = {search:'侦察起点', patrol:'起巡位', boundary:'边界段', gate:'门哨',
          intercept:'机动拦截', reserve:'预备队', post:'阵位', support:'支援', relay:'中继',
          air:'空中观察', scout:'侦察席', assault:'突击席', assessor:'评估席'}[role] || '席位';
        const field = selectRow(roleName + ' ' + (name && name !== 'standby' && name !== 'watch' ? name : index + 1),
          value, options);
        field.input.onchange = () => {
          const selection = field.get();
          pins[slot.key] = selection.startsWith('class:')
            ? {platform_class: selection.slice(6)} : selection.slice(5) || null;
          row.markDirty();
          setTimeout(() => preview(false), 0);
        };
        slots.append(field.el);
      }
    }
    function show(message, error = false) {
      status.textContent = message;
      status.toggleAttribute('data-error', Boolean(error));
    }
    function repaint() { projectClick = taskMap(canvas, row, latestSlots); }
    async function preview(choosePlace, center) {
      const id = ++requestId;
      show('正在试算任务位置和平台…');
      try {
        const {selectedTasks, selectedUnits, selectedTargets, observationTargets, libraryTargets} = collectDraft();
        const selectedIds = new Set(allTaskRows().filter(item => item.included.checked || item.completed)
          .filter(item => !item.pendingDelete).map(item => item.taskId.value.trim()));
        const taskId = row.taskId.value.trim();
        const included = selectedTasks.filter(task => selectedIds.has(task.task_id));
        for (const task of config.message.tasks) {
          if (config.completed.includes(task.task_id) && !included.some(item => item.task_id === task.task_id)) {
            included.push(task);
          }
        }
        const occupied = (config.occupied || []).filter(item => item.task_id !== taskId &&
          selectedIds.has(item.task_id) && selectedUnits.some(unit => unit.unit_id === item.unit_id));
        const result = await api('/api/editor/task-preview', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({task_id: taskId, now: isLiveSource() ? config.sim_s + 1 : 0,
            recommend: choosePlace, center, completed: config.completed, occupied, objective: config.objective,
            max_ticks: Number($('#editor-ticks').value) || config.max_ticks,
            message: {...config.message, tasks: included},
            formation: {...config.formation, formation: {...config.formation.formation, units: selectedUnits}},
            targets: selectedTargets.filter(target => selectedIds.has(target.task_id))})
        });
        if (id !== requestId || !row.isConnected) return;
        if ((choosePlace || center) && result.target) applyPlacement(result);
        latestSlots = result.slots || [];
        repaint();
        renderSlots();
        const starts = latestSlots.filter(slot => slot.start_s != null).map(slot => slot.start_s);
        const summary = starts.length ? '已试算 ' + starts.length + ' / ' + latestSlots.length +
          ' 个席位，首个席位预计 ' + Math.round(Math.min(...starts)) + ' 秒到位。' : '';
        const overlap = result.overlap.length ? '与 ' + result.overlap.join('、') + ' 的时段和区域有重叠。' : '';
        const timing = result.timing;
        const estimate = timing ? '末个席位预计 ' + Math.ceil(timing.ready_s) +
          ' 秒到位，作业预计 ' + Math.ceil(timing.finish_s) + ' 秒结束，' +
          '返航按直线粗估至 ' + Math.ceil(timing.home_s) + ' 秒；绕障或等待会增加用时。' : '';
        show([result.error, summary, estimate, overlap, ...(timing?.warnings || [])]
          .filter(Boolean).join(' '), result.error);
      } catch (err) {
        if (id === requestId) show(err.message, true);
      }
    }
    recommend.onclick = () => preview(true);
    trial.onclick = () => preview(false);
    reset.onclick = () => {
      for (const key of Object.keys(pins)) delete pins[key];
      row.markDirty();
      preview(false);
    };
    place.onclick = () => {
      const placing = canvas.toggleAttribute('data-placing');
      place.setAttribute('aria-pressed', String(placing));
      if (placing) show('点击地图设置任务点，或移动任务区域的中心。');
    };
    canvas.onclick = event => {
      if (!projectClick || !canvas.hasAttribute('data-placing')) return;
      canvas.removeAttribute('data-placing');
      place.setAttribute('aria-pressed', 'false');
      preview(false, projectClick(event));
    };
    return {box, repaint, preview, renderSlots, invalidate() {
      requestId++;
      show('配置已修改，可重新试算。');
    }};
  }

  function taskCard(task, completed = false, fresh = false) {
    const types = Object.fromEntries(Object.entries(config.task_types)
      .map(([key, template]) => [key, template.label]));
    const template = config.task_types[task.task_type] || {};
    const patrol = task.task_type === 'T-PTL';
    const pins = clone(task.params._slot_units || {});
    const isLive = isLiveSource();
    const included = isLive ? !(config.excluded || []).includes(task.task_id) : !completed;
    const {row, enabled, fields, details} = card(tasks, '', included);
    row.ref = 'task-' + (++rowSeq);
    row.completed = completed;
    row.included = enabled;
    if (isLive) enabled.parentElement.title = '取消勾选会停止本轮安排，任务配置仍保留';
    if (!types[task.task_type]) {
      const display = document.createElement('pre');
      display.textContent = JSON.stringify(task, null, 2);
      fields.append(display);
      enabled.disabled = true;
      row.getConfig = () => null;
      return details;
    }
    const id = textRow('任务编号', task.task_id);
    row.taskId = id.input;
    row.originalTaskId = fresh ? null : task.task_id;
    const type = selectRow('类型', task.task_type, types);
    row.typeNode = type;
    const priority = numberRow('优先级（1–5）', task.priority);
    const hasHoldDuration = ['T-SEC', 'T-HLD'].includes(task.task_type);
    const durationKey = hasHoldDuration && (task.params.hold_duration_s !== undefined ||
      task.params.duration_s === undefined) ? 'hold_duration_s' : 'duration_s';
    const duration = numberRow('作业时长（秒）', task.params[durationKey] ?? 120);
    const start = numberRow('时间窗开始（秒）', task.window.start_s);
    const end = numberRow('时间窗结束（秒）', task.window.end_s);
    row.associationWindow = () => ({start: start.get(), end: end.get()});
    const min = numberRow('最少平台', task.min_units);
    const max = numberRow('最多平台（可留空）', task.max_units);
    const initialDeps = task.depends_on ?? task.prerequisites ?? [];
    const deps = taskDependencies(row, initialDeps, !config.editable || (isLive && completed));
    const advanced = document.createElement('details');
    advanced.className = 'patrol-advanced';
    const advancedSummary = document.createElement('summary');
    advancedSummary.textContent = '高级设置';
    const advancedFields = document.createElement('div');
    advancedFields.className = 'editor-fields';
    advanced.append(advancedSummary, advancedFields);
    fields.append(id.el, type.el);
    const basic = [priority.el, duration.el, start.el, end.el, min.el, max.el, deps.el];
    advancedFields.append(...basic);
    advanced.addEventListener('toggle', () => {
      if (advanced.open) deps.refresh();
    });

    const initialKind = Object.keys(geometryNames).find(key => Object.hasOwn(task.target, key)) || 'point';
    const geometryType = selectRow('目标形状', initialKind, patrol
      ? {...{patrol_area: '沿区域巡逻', route: '按航线巡逻'}, [initialKind]: initialKind === 'route'
        ? '按航线巡逻' : initialKind === 'patrol_area' ? '沿区域巡逻' : geometryNames[initialKind]}
      : geometryNames);
    const geometryBox = document.createElement('div');
    geometryBox.className = 'param-frame wide';
    const geometryHead = document.createElement('div');
    geometryHead.className = 'param-field-head';
    geometryHead.append(Object.assign(document.createElement('span'), {textContent: '目标坐标'}));
    const geometryNote = document.createElement('small');
    geometryNote.className = 'editor-hint';
    geometryBox.append(geometryHead, geometryNote);
    let geometryControl;
    function buildGeometry(kind, value) {
      const place = document.createElement('div');
      const control = ['point', 'key_point'].includes(kind)
        ? pointControl(value ?? [0, 0], '坐标') : pointListControl(value?.polygon ?? value ?? []);
      place.append(control.el);
      geometryControl = control;
      return place;
    }
    function syncGeometryNote() {
      const area = ['area', 'defense_area', 'sector', 'patrol_area'].includes(geometryType.get());
      geometryNote.textContent = area
        ? '区域顶点按边界顺序填写，修改单个顶点会改变区域形状。'
        : geometryType.get() === 'route' ? '按航点顺序填写。' : '';
      geometryNote.hidden = !geometryNote.textContent;
    }
    let geometryPlace = buildGeometry(geometryType.get(), task.target[geometryType.get()]);
    let geometryConfigured = false;
    geometryBox.append(geometryPlace);
    function setGeometry(kind, points) {
      geometryType.input.value = kind;
      geometryPlace.remove();
      geometryPlace = buildGeometry(kind, points);
      geometryBox.append(geometryPlace);
      syncGeometryNote();
      geometryConfigured = true;
      dirty = true;
    }
    geometryType.input.addEventListener('change', () => {
      const kind = geometryType.get();
      let previous;
      if (patrol) {
        try { previous = geometryControl.get(); } catch { /* invalid coordinates can be replaced */ }
      }
      setGeometry(kind, patrol && Array.isArray(previous?.[0]) ? previous : undefined);
      if (patrol && kind === 'route') {
        for (const key of ['checkpoints', 'follow_boundary']) {
          rendered.get(key)?.el.remove();
          rendered.delete(key);
        }
        renderOptional();
      }
    });
    syncGeometryNote();
    const isAssault = () => type.get() === 'T-ASL';
    if (isAssault()) {
      geometryType.el.hidden = true;
      geometryBox.hidden = true;
      fields.append(Object.assign(document.createElement('p'), {
        className: 'editor-target-note wide',
        textContent: '突击目标点在“红方目标配置”中设定；任务仍按该点规划与执行。'
      }));
    } else {
      fields.append(geometryType.el);
      advancedFields.append(geometryBox);
    }
    fields.append(advanced);

    const excluded = new Set(['tracking_target', 'observation_target', 'observation_target_ids', 'target_library_ids', 'relay_target',
      'intruders', 'duration_s', 'hold_duration_s']);
    const inheritedPins = ['start_units', 'air_unit', 'scout_unit', 'assessor_unit'];
    const isExcluded = key => excluded.has(key) || key.startsWith('_') || inheritedPins.includes(key) ||
      (patrol && geometryType.get() === 'route' && ['follow_boundary', 'checkpoints'].includes(key)) ||
      (type.get() === 'T-ASL' && (key === 'target_id' || key === 'object_label'));
    const catalog = template.params || [];
    const catalogByKey = new Map(catalog.map(spec => [spec.key, spec]));
    const rendered = new Map();
    const optional = document.createElement('details');
    optional.className = 'param-optional';
    const optionalSummary = document.createElement('summary');
    const optionalActions = document.createElement('div');
    optionalActions.className = 'param-actions';
    optional.append(optionalSummary, optionalActions);
    const paramParent = advancedFields;
    paramParent.append(optional);
    function renderOptional() {
      const missing = catalog.filter(spec => !isExcluded(spec.key) && !rendered.has(spec.key));
      optional.hidden = !missing.length;
      optionalSummary.textContent = '添加该类型的可选参数（' + missing.length + '）';
      optionalActions.replaceChildren(...missing.map(spec => {
        const chipNode = chip('＋ ' + spec.label);
        chipNode.title = spec.key + (spec.hint ? ' · ' + spec.hint : '');
        chipNode.onclick = () => {
          const seed = template.demo?.params[spec.key] ?? spec.template;
          addParam(spec.key, clone(seed), spec);
          dirty = true;
          tools?.invalidate();
        };
        return chipNode;
      }));
    }
    function addParam(key, value, spec) {
      if (rendered.has(key)) return;
      const remove = () => {
        node.el.remove();
        rendered.delete(key);
        renderOptional();
        dirty = true;
        tools?.invalidate();
      };
      const isRadius = (patrol || task.task_type === 'T-RCN') && key === 'sensor_radius_m';
      const primary = isRadius || ['coverage_target', 'hold_criteria', 'control_level', 'target_start_mode'].includes(key) ||
        (key === 'effect' && isAssault());
      const node = isRadius ? patrolRadius(value, remove) : paramRow(key, value, spec || {}, remove);
      node.spec = spec;
      rendered.set(key, node);
      if (primary) fields.insertBefore(node.el, advanced);
      else paramParent.insertBefore(node.el, optional);
      renderOptional();
    }
    for (const [key, value] of Object.entries(task.params || {})) {
      if (isExcluded(key)) continue;
      addParam(key, value, catalogByKey.get(key));
    }
    renderOptional();
    row.paramsNode = {has: key => rendered.has(key) || key in (task.params || {})};
    row.aimPoint = () => {
      const kind = geometryType.get();
      const value = geometryControl.get();
      if (['point', 'key_point'].includes(kind)) return value;
      if (kind === 'target_list' || (kind === 'route' && !patrol)) return value[0] || [0, 0];
      if (!value.length) return [0, 0];
      return [value.reduce((sum, point) => sum + point[0], 0) / value.length,
        value.reduce((sum, point) => sum + point[1], 0) / value.length];
    };
    row.geometryKind = () => geometryType.get();
    row.associationShape = () => {
      const kind = geometryType.get();
      const value = geometryControl.get();
      return {kind, points: ['point', 'key_point'].includes(kind) ? [value] : value};
    };
    row.associationRadius = () => {
      const value = rendered.get('sensor_radius_m')?.get() ?? task.params.sensor_radius_m;
      if (typeof value === 'number') return value;
      return Math.max(value?.ground ?? 0, value?.air ?? 0);
    };
    row.mapShape = () => {
      try {
        if (['assault', 'hold'].includes(row.targetSlot)) {
          const linked = targetRows().find(target => row.targetKeys.has(target.libraryKey));
          if (linked) return {id: id.get(), kind: 'point', points: [linked.getConfig().point]};
        }
        const kind = geometryType.get();
        if (isAssault()) {
          const targetRow = [...targets.children].find(item => item.targetRef === row.ref && item.slot === 'assault');
          const point = targetRow?.getConfig()?.point;
          if (point) return {id: id.get(), kind: 'point', points: [point]};
        }
        const value = geometryControl.get();
        return {id: id.get(), kind, points: ['point', 'key_point'].includes(kind) ? [value] : value};
      } catch { return null; }
    };

    function updateTitle() {
      details.querySelector('summary').textContent = id.get().trim() + ' · ' +
        (types[type.get()] || type.get()) + (completed ? ' · 已完成' : '');
    }
    id.input.addEventListener('input', () => {
      updateTitle();
      refreshObservationLinks();
    });
    updateTitle();
    type.input.addEventListener('change', () => {
      const nextCard = createTaskDraft(id.get(), type.get(), deps.get());
      const nextRow = nextCard.parentElement;
      nextRow.originalTaskId = row.originalTaskId;
      nextRow.included.checked = enabled.checked;
      row.replaceWith(nextRow);
      syncTargets();
      nextCard.open = true;
    });
    if (isLive && config.message.tasks.some(t => t.task_id === task.task_id)) id.input.readOnly = true;
    if (!config.editable || (isLive && completed)) {
      for (const input of fields.querySelectorAll('input, select, textarea')) input.disabled = true;
      enabled.disabled = true;
    }
    if (config.editable && !(isLive && completed)) {
      const actions = document.createElement('div');
      actions.className = 'editor-task-actions';
      const remove = button('删除任务');
      remove.onclick = () => {
        row.pendingDelete = !row.pendingDelete;
        row.classList.toggle('editor-task-deleted', row.pendingDelete);
        fields.hidden = row.pendingDelete;
        enabled.disabled = row.pendingDelete;
        remove.textContent = row.pendingDelete ? '撤销删除' : '删除任务';
        if (row.pendingDelete) {
          details.open = false;
          details.querySelector('summary').textContent = id.get().trim() + ' · 待删除';
        } else {
          updateTitle();
        }
        syncTargets();
      };
      actions.append(remove);
      row.append(actions);
    }
    let dirty = false;
    row.markDirty = () => { dirty = true; };
    let tools;
    if (config.editable && !completed) {
      tools = taskTools(row, pins, result => {
        const [kind, points] = Object.entries(result.target).find(([key]) => key in geometryNames);
        if (!(['hold', 'assault'].includes(row.targetSlot) && row.targetKeys.size)) setGeometry(kind, points);
        for (const [key, value] of Object.entries(result.geometry_params)) {
          const node = rendered.get(key);
          if (!node) continue;
          node.el.remove();
          rendered.delete(key);
          addParam(key, value, catalogByKey.get(key));
        }
        for (const moved of result.targets) {
          const targetRow = [...targets.children].find(item => item.targetRef === row.ref &&
            item.slot === moved.slot && item.targetId?.value.trim() === moved.target_id);
          targetRow?.applyMapPoints(moved);
        }
        refreshObservationLinks();
      }, fresh, template);
      fields.insertBefore(tools.box, advanced);
      row.refreshPlatformPreview = () => {
        tools.invalidate();
        if (details.open) {
          tools.repaint();
          tools.renderSlots();
        }
      };
      let firstOpen = true;
      details.addEventListener('toggle', () => {
        if (!details.open) return;
        tools.repaint();
        tools.renderSlots();
        if (!fresh && firstOpen && enabled.checked) tools.preview(false);
        firstOpen = false;
      });
      if (fresh) {
        row.recommendation = recommendationQueue.then(() => {
          if (row.isConnected && !geometryConfigured && enabled.checked) return tools.preview(true);
        });
        recommendationQueue = row.recommendation;
      }
    }
    for (const event of ['input', 'change']) fields.addEventListener(event, e => {
      dirty = true;
      tools?.invalidate();
      if (e.target === min.input) tools?.renderSlots();
      tools?.repaint();
      if (event === 'change' && !e.target.closest('.editor-observation-links')) refreshObservationLinks();
    });
    row.getConfig = () => {
      if (row.pendingDelete || (!isLive && !enabled.checked)) return null;
      if (isLive && !dirty) return task;
      try {
        const redKeys = ['tracking_target', 'observation_target', 'relay_target', 'intruders'];
        const params = Object.fromEntries(Object.entries(task.params)
          .filter(([key]) => redKeys.includes(key) || (key.startsWith('_') && key !== '_slot_units')));
        for (const [key, node] of rendered) params[key] = node.get();
        params[durationKey] = duration.get();
        if (hasHoldDuration && 'duration_s' in task.params && 'hold_duration_s' in task.params) {
          params.duration_s = params.hold_duration_s;
        }
        for (const key of inheritedPins) {
          if (Object.hasOwn(task.params, key)) params[key] = clone(task.params[key]);
        }
        if (fresh || dirty || task.params._workbench_task) params._workbench_task = true;
        if (task.params._workbench_patrol) params._workbench_patrol = true;
        if (Object.keys(pins).length) params._slot_units = {...pins};
        const count = min.get();
        if (!Number.isInteger(count) || count < 1 || count > 50) throw Error('最少平台须为 1–50 的整数');
        const kind = geometryType.get();
        const geometry = geometryControl.get();
        const sourceGeometry = task.target[kind];
        const target = {[kind]: sourceGeometry?.polygon ? {...sourceGeometry, polygon: geometry} : geometry};
        const {prerequisites, ...original} = task;
        return {...original, task_id: id.get().trim(), task_type: type.get(),
          priority: priority.get(), min_units: count,
          max_units: max.input.value === '' ? null : max.get(),
          window: {start_s: start.get(), end_s: end.get()},
          target, params,
          depends_on: deps.get()};
      } catch (err) {
        details.open = true;
        throw Error(updateErrorPrefix() + err.message);
      }
    };
    function updateErrorPrefix() {
      return id.input.value.trim() + ' · ';
    }
    return details;
  }

  const sensorNames = {eo: '光电（EO）', ir: '红外（IR）', sar: '合成孔径雷达（SAR）'};
  const classProfiles = {
    UGV: {payload_kg: 600, sensor: {type: 'eo', range_m: 2500, fov_deg: 60, resolution_m: 0.30},
      motion: {max_speed_mps: 8, max_accel_mps2: 1.2, max_yaw_rate_rad_s: 0.70,
        min_turn_radius_m: 11.4, max_climb_rate_mps: 0, max_altitude_m: 0}},
    TANK: {payload_kg: 2000, sensor: {type: 'eo', range_m: 3000, fov_deg: 50, resolution_m: 0.25},
      motion: {max_speed_mps: 8, max_accel_mps2: 1.0, max_yaw_rate_rad_s: 0.60,
        min_turn_radius_m: 13.3, max_climb_rate_mps: 0, max_altitude_m: 0}},
    PLANE: {payload_kg: 150, sensor: {type: 'sar', range_m: 8000, fov_deg: 120, resolution_m: 1.0},
      motion: {max_speed_mps: 30, max_accel_mps2: 2.5, max_yaw_rate_rad_s: 0.45,
        min_turn_radius_m: 66.7, max_climb_rate_mps: 5, max_altitude_m: 3000}},
    WING: {payload_kg: 100, sensor: {type: 'ir', range_m: 5000, fov_deg: 90, resolution_m: 0.50},
      motion: {max_speed_mps: 25, max_accel_mps2: 2.0, max_yaw_rate_rad_s: 0.40,
        min_turn_radius_m: 62.5, max_climb_rate_mps: 4, max_altitude_m: 2000}},
  };
  const classDescriptions = {
    UGV: '地面机动，转弯半径较小',
    TANK: '地面平台，载荷最高',
    PLANE: '空中平台，速度和探测距离最高',
    WING: '空中平台，采用红外传感器',
  };

  function loadPlatformGroups(platforms) {
    units.replaceChildren();
    unitRows = [];
    platformGroups.clear();
    for (const [cls, name] of Object.entries(classNames)) {
      const details = document.createElement('details');
      details.className = 'editor-platform-group';
      details.dataset.platformClass = cls;
      const summary = document.createElement('summary');
      const title = document.createElement('strong');
      title.textContent = name;
      const count = document.createElement('span');
      count.className = 'editor-platform-count';
      const {motion, payload_kg, sensor} = classProfiles[cls];
      const profile = document.createElement('span');
      profile.className = 'editor-platform-profile';
      profile.textContent = classDescriptions[cls] + '。具体速度、载荷模型值、传感器和续航以各平台配置为准。';
      summary.append(title, count, profile);

      const body = document.createElement('div');
      body.className = 'editor-platform-body';
      const controls = document.createElement('div');
      controls.className = 'editor-platform-controls';
      const enable = button('全部可用', 'button');
      const disable = button('全部停用', 'button');
      enable.onclick = () => setPlatformGroupStatus(cls, 'READY');
      disable.onclick = () => setPlatformGroupStatus(cls, 'OFFLINE');
      controls.append(enable, disable);
      controls.hidden = !config.editable;
      const rows = document.createElement('div');
      const empty = document.createElement('p');
      empty.className = 'editor-hint';
      empty.textContent = '此类别暂无平台。';
      body.append(controls, empty, rows);
      details.append(summary, body);
      units.append(details);
      platformGroups.set(cls, {details, rows, count, empty, enable, disable});
    }
    for (const unit of platforms) unitCard(unit);
    for (const cls of platformGroups.keys()) updatePlatformGroup(cls);
  }

  function updatePlatformGroup(cls) {
    const {rows, count, empty, enable, disable} = platformGroups.get(cls);
    const active = [...rows.children].filter(row => !row.pendingDelete);
    const editable = active.filter(row => !row.statusNode.disabled);
    const ready = active.filter(row => row.statusNode.value === 'READY').length;
    count.textContent = ready + ' / ' + active.length + ' 台可用';
    empty.hidden = Boolean(rows.children.length);
    enable.disabled = !editable.some(row => row.statusNode.value !== 'READY');
    disable.disabled = !editable.some(row => row.statusNode.value !== 'OFFLINE');
  }

  function setPlatformGroupStatus(cls, status) {
    for (const row of platformGroups.get(cls).rows.children) {
      if (!row.pendingDelete && !row.statusNode.disabled && row.statusNode.value !== status) {
        row.statusNode.value = status;
        row.updateStatus();
      }
    }
    updatePlatformGroup(cls);
    refreshPlatformPreviews();
  }

  function refreshPlatformPreviews() {
    for (const row of allTaskRows()) row.refreshPlatformPreview?.();
  }

  function placeUnitInGroup(row, cls) {
    const group = platformGroups.get(cls);
    const number = row => row.robotNode.value === '' ? Infinity : Number(row.robotNode.value);
    const next = [...group.rows.children].find(other => other !== row && number(other) > number(row));
    if (row.parentElement !== group.rows || row.nextElementSibling !== (next ?? null)) {
      group.rows.insertBefore(row, next ?? null);
    }
    return group;
  }

  function unitCard(unit, fresh = false) {
    const isLive = isLiveSource();
    const cls = unit.platform_class;
    const {row, enabled, fields, details} = card(platformGroups.get(cls).rows, '', true);
    const availability = document.createElement('label');
    availability.className = 'editor-platform-availability';
    const ready = document.createElement('input');
    ready.type = 'checkbox';
    availability.append(ready, '可用');
    row.prepend(availability);
    const profile = classProfiles[unit.platform_class] || classProfiles.UGV;
    const sensorValue = typeof unit.sensor === 'object' && unit.sensor
      ? unit.sensor
      : typeof unit.sensor === 'string' && unit.sensor
        ? {...profile.sensor, type: unit.sensor}
        : profile.sensor;
    const motionValue = unit.motion || profile.motion;
    const id = textRow('平台编号', unit.unit_id);
    const robot = numberRow('机器人编号', unit.robot_id);
    const platform = selectRow('平台类别', unit.platform_class, classNames);
    const type = textRow('平台型号（platform_type）', unit.platform_type ?? '');
    const status = selectRow('可用状态', unit.status || 'READY', statuses);
    const x = numberRow('位置 X', unit.position?.x ?? unit.position?.[0] ?? 0);
    const y = numberRow('位置 Y', unit.position?.y ?? unit.position?.[1] ?? 0);
    const z = numberRow('高度（米）', unit.altitude_m ?? 0);
    const yaw = numberRow('航向（弧度）', unit.heading_rad ?? 0);
    const speed = numberRow('速度（米/秒）', unit.speed_mps ?? profile.motion.max_speed_mps);
    const endurance = numberRow('续航（秒）', unit.endurance_s ?? 600);
    const payloadKg = numberRow('载荷（模型值）', unit.payload ?? {UGV:6,TANK:8,PLANE:2,WING:1.5}[unit.platform_class]);
    const sensorType = selectRow('传感器类别', sensorValue.type || 'eo', sensorNames);
    const sensorRange = numberRow('探测距离（米）', sensorValue.range_m ?? profile.sensor.range_m);
    const sensorFov = numberRow('视场（度）', sensorValue.fov_deg ?? profile.sensor.fov_deg);
    const sensorResolution = numberRow('分辨率（米）', sensorValue.resolution_m ?? profile.sensor.resolution_m);
    const maxSpeed = numberRow('最大速度（米/秒）', motionValue.max_speed_mps ?? profile.motion.max_speed_mps);
    const maxAccel = numberRow('最大加速度（米/秒²）', motionValue.max_accel_mps2 ?? profile.motion.max_accel_mps2);
    const maxYaw = numberRow('最大角速度（弧度/秒）', motionValue.max_yaw_rate_rad_s ?? profile.motion.max_yaw_rate_rad_s);
    const turnRadius = numberRow('最小转弯半径（米）', motionValue.min_turn_radius_m ?? profile.motion.min_turn_radius_m);
    const climbRate = numberRow('最大爬升率（米/秒）', motionValue.max_climb_rate_mps ?? profile.motion.max_climb_rate_mps);
    const ceiling = numberRow('最大高度（米）', motionValue.max_altitude_m ?? profile.motion.max_altitude_m);
    const extras = new Map();
    for (const key of ['battery', 'work_rate', 'move_cost', 'work_cost', 'vertical_speed_mps']) {
      if (key in unit) extras.set(key, paramRow(key, unit[key]));
    }
    fields.append(id.el, robot.el, platform.el, type.el, status.el, x.el, y.el, z.el,
      yaw.el, speed.el, endurance.el, payloadKg.el, sensorType.el, sensorRange.el,
      sensorFov.el, sensorResolution.el, maxSpeed.el, maxAccel.el, maxYaw.el,
      turnRadius.el, climbRate.el, ceiling.el, ...[...extras.values()].map(node => node.el));
    for(const control of [sensorRange,sensorFov,sensorResolution,maxSpeed,maxAccel,maxYaw,turnRadius,climbRate,ceiling]) control.el.hidden=true;
    row.unitId = id.input;
    row.robotNode = robot.input;
    row.statusNode = status.input;
    row.included = enabled;
    row.originalRobotId = fresh ? null : unit.robot_id;
    unitRows.push(row);
    let groupClass = cls;
    let dirty = false;
    const updateTitle = () => {
      const unitId = id.input.value.trim() || '新平台';
      details.querySelector('summary').textContent =
        unitId + ' · ' + (row.pendingDelete ? '待删除' : statuses[status.get()]);
      ready.checked = status.get() === 'READY';
      ready.indeterminate = !['READY', 'OFFLINE'].includes(status.get());
      ready.disabled = status.input.disabled || Boolean(row.pendingDelete);
      ready.setAttribute('aria-label', unitId + ' 可用');
    };
    id.input.addEventListener('input', updateTitle);
    row.updateStatus = () => {
      dirty = true;
      updateTitle();
    };
    status.input.addEventListener('change', () => {
      row.updateStatus();
      updatePlatformGroup(groupClass);
    });
    ready.addEventListener('change', () => {
      status.input.value = ready.checked ? 'READY' : 'OFFLINE';
      status.input.dispatchEvent(new Event('change', {bubbles: true}));
    });
    const numberHint = document.createElement('p');
    numberHint.className = 'editor-hint editor-platform-number-hint';
    fields.prepend(numberHint);
    function updateNumberHint() {
      const [low, high] = classRanges[groupClass];
      numberHint.hidden = robot.input.value !== '';
      numberHint.textContent = '需要一个可用的机器人编号（' + low + '–' + high +
        '）。腾出名额后填写空闲编号。';
    }
    robot.input.addEventListener('change', () => {
      placeUnitInGroup(row, groupClass);
      updateNumberHint();
    });
    platform.input.addEventListener('change', () => {
      const previous = groupClass;
      groupClass = platform.get();
      robot.input.value = nextRobotId(groupClass, row) ?? '';
      placeUnitInGroup(row, groupClass).details.open = true;
      platform.input.focus();
      updatePlatformGroup(previous);
      updatePlatformGroup(groupClass);
      updateNumberHint();
      if (!fresh) return;
      const next = classProfiles[platform.get()] || classProfiles.UGV;
      payloadKg.input.value = {UGV:6,TANK:8,PLANE:2,WING:1.5}[platform.get()];
      sensorType.input.value = next.sensor.type;
      sensorRange.input.value = next.sensor.range_m;
      sensorFov.input.value = next.sensor.fov_deg;
      sensorResolution.input.value = next.sensor.resolution_m;
      maxSpeed.input.value = next.motion.max_speed_mps;
      maxAccel.input.value = next.motion.max_accel_mps2;
      maxYaw.input.value = next.motion.max_yaw_rate_rad_s;
      turnRadius.input.value = next.motion.min_turn_radius_m;
      climbRate.input.value = next.motion.max_climb_rate_mps;
      ceiling.input.value = next.motion.max_altitude_m;
    });
    placeUnitInGroup(row, groupClass);
    updateNumberHint();
    if (isLive) {
      enabled.parentElement.hidden = true;
      if (!fresh) {
        robot.input.readOnly = id.input.readOnly = true;
        platform.input.disabled = true;
        if (unit.status === 'LOST') status.input.disabled = true;
      }
    }
    if (!config.editable) {
      for (const input of fields.querySelectorAll('input, select, textarea')) input.disabled = true;
      enabled.disabled = true;
    }
    updateTitle();
    if (config.editable) {
      const actions = document.createElement('div');
      actions.className = 'editor-task-actions';
      const remove = button('删除平台');
      remove.onclick = () => {
        row.pendingDelete = !row.pendingDelete;
        row.classList.toggle('editor-task-deleted', row.pendingDelete);
        fields.hidden = row.pendingDelete;
        enabled.disabled = row.pendingDelete;
        remove.textContent = row.pendingDelete ? '撤销删除' : '删除平台';
        updateTitle();
        updatePlatformGroup(groupClass);
        refreshPlatformPreviews();
      };
      actions.append(remove);
      details.append(actions);
    }
    fields.addEventListener('input', () => {dirty = true;});
    fields.addEventListener('change', () => {
      dirty = true;
      refreshPlatformPreviews();
    });
    enabled.addEventListener('change', refreshPlatformPreviews);
    row.getConfig = (revealError = true) => {
      if (row.pendingDelete || !enabled.checked) return null;
      if (isLive && !dirty) return unit;
      try {
        const payload = payloadKg.get();
        const value = {...unit, unit_id: id.get().trim(), robot_id: robot.get(),
          platform_class: platform.get(), status: status.get(),
          position: {x: x.get(), y: y.get()}, altitude_m: z.get(),
          heading_rad: yaw.get(), speed_mps: speed.get(),
          endurance_s: endurance.get(),
          payload: payload,
          sensor: sensorType.get(),
          motion: {max_speed_mps: maxSpeed.get(), max_accel_mps2: maxAccel.get(),
            max_yaw_rate_rad_s: maxYaw.get(), min_turn_radius_m: turnRadius.get(),
            max_climb_rate_mps: climbRate.get(), max_altitude_m: ceiling.get()}};
        delete value.motion; delete value.payload_kg;
        if (type.input.value.trim()) value.platform_type = type.input.value.trim();
        else delete value.platform_type;
        for (const [key, node] of extras) value[key] = node.get();
        if (platform.get() !== unit.platform_class) delete value.capabilities;
        return value;
      } catch (err) {
        if (revealError) {
          platformGroups.get(groupClass).details.open = details.open = true;
        }
        throw Error(id.input.value.trim() + ' · ' + err.message);
      }
    };
    return details;
  }

  function nextRobotId(cls, currentRow = null) {
    const [low, high] = classRanges[cls];
    const used = new Set();
    for (const row of unitRows) {
      if (isLiveSource() && row.originalRobotId !== null) used.add(row.originalRobotId);
      if (row !== currentRow && !row.pendingDelete && row.included.checked) {
        used.add(Number(row.robotNode.value));
      }
    }
    for (let value = low; value <= high; value++) if (!used.has(value)) return value;
    return null;
  }

  function nextUnitNo() {
    const ids = new Set(unitRows.map(row => row.unitId.value.trim()));
    let n = 1;
    while (ids.has('UNIT-' + n)) n++;
    return n;
  }

  function showError(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  function setNewTaskTypes() {
    const previous = newType.value;
    newType.replaceChildren(...Object.entries(config.task_types)
      .map(([key, template]) => new Option(template.label, key)));
    newType.value = config.task_types[previous] ? previous
      : (['interop_patrol', 'interop_patrol_sdf50'].includes(config.preset) ? 'T-PTL' : 'T-RCN');
    newType.disabled = !config.editable;
  }

  async function loadConfig() {
    const token = ++loadToken;
    const id = ['run','initial'].includes(source.value) ? state.run?.id : null;
    config = null;
    recommendationQueue = Promise.resolve();
    tasks.replaceChildren();
    units.replaceChildren();
    platformGroups.clear();
    unitRows = [];
    targets.replaceChildren();
    observationLibrary.replaceChildren();
    targetLibrary.replaceChildren();
    submit.disabled = addTask.disabled = addUnit.disabled = newUnitClass.disabled =
      addTarget.disabled = addObservation.disabled = addLibraryTarget.disabled = newType.disabled = true;
    note.textContent = '正在读取配置…';
    $('#editor-preset-field').hidden = source.value !== 'preset';
    showError('');
    try {
      if (source.value === 'run' && !id) throw Error('请先选择一条运行记录');
      const data = await api(id ? '/api/editor/' + encodeURIComponent(id) + (source.value === 'run' ? '?at_s=' + replayTime : '')
        : '/api/editor?preset=' + encodeURIComponent(preset.value) + '&map_id=' + encodeURIComponent(window.BrowserIntegration.mapId()));
      if (token !== loadToken) return;
      config = data;
      window.ThreatEditor?.load(data,source.value==='preset'||source.value==='initial');
      setNewTaskTypes();
      note.textContent = !data.editable ? '已显示该模板或运行保存的配置。' : id
        ? (source.value === 'run' ? '已恢复暂停时刻的运行状态；完成项锁定，修改后从此处续算。' : '已读取初始配置，保存后另建完整运行。')
        : '已读取所选模板的任务、平台和红方目标。展开条目即可修改。';
      loadTaskTargets(data);
      loadPlatformGroups(data.formation.formation.units);
      refreshTargetTools();
      submit.disabled = addTask.disabled = addUnit.disabled = newUnitClass.disabled = !data.editable;
      const defaultTicks = {interop_asl: 900, interop_containment: 1200, interop_hold: 900};
      $('#editor-ticks').value = data.max_ticks || defaultTicks[data.preset] || 600;
      $('#editor-ticks').closest('label').hidden = source.value === 'run';
      submit.textContent = source.value === 'run' ? '应用修改并续算当前运行' : '保存并生成新回放';
      $('#editor-timing').textContent = id
        ? (source.value === 'run' ? '沿用暂停时刻和运行编号；更新前完整版本自动备份。' : '初始配置重新计算，另建运行编号。')
        : '时间窗以新一轮起点计时。保存会生成独立演示。';
    } catch (err) {
      if (token !== loadToken) return;
      note.textContent = '';
      showError(err.message);
    }
  }

  const open = $('#edit-config');
  open.onclick = async () => {
    if (state.busy && !liveId) return toast('当前运行采用快速模式，请等待运行结果');
    setPlaying(false);
    replayTime = Math.floor(state.t);
    if (state.run && !state.run.live) setTime(replayTime);
    source.disabled = false;
    $('#editor-ticks').closest('label').hidden = false;
    $('#editor-timing').textContent = '时间窗以新一轮起点计时。勾选本轮要规划的任务和平台。';
    submit.textContent = '保存并生成回放';
    preset.value = scenarioSelect.value;
    source.value = 'preset';
    if (liveId && state.busy) {
      if (open.disabled) return;
      open.disabled = true;
      try {
        const current = await liveCommand(liveId, {action: 'pause'});
        pausedId = current.config.run_id;
        liveRevision = current.revision;
        config = current.config;
        window.ThreatEditor?.load(config,false);
        setNewTaskTypes();
        source.value = 'live';
        source.disabled = true;
        $('#editor-preset-field').hidden = true;
        $('#editor-ticks').closest('label').hidden = true;
        $('#editor-timing').textContent = config.editable
          ? '沿用当前仿真时间。修改过的在途任务会撤销旧指令并重新执行。'
          : '可查看当前任务及平台状态，点击继续演示恢复仿真。';
        note.textContent = '已暂停在 ' + config.sim_s + ' 秒。' +
          (config.editable ? '已完成任务保持锁定。' : '此场景的配置为只读。');
        submit.textContent = config.editable ? '应用并继续规划' : '继续演示';
        showError('');
        tasks.replaceChildren();
        targets.replaceChildren();
        loadTaskTargets(config);
        loadPlatformGroups(config.formation.formation.units);
        refreshTargetTools();
        submit.disabled = false;
        addTask.disabled = addUnit.disabled = newUnitClass.disabled = !config.editable;
        dialog.showModal();
      } catch (err) {
        toast(err.message);
      } finally {
        open.disabled = false;
      }
      return;
    }
    if (state.run?.scenario?._meta?.interop?.message && state.run.id === $('#run-select').value) {
      source.value = 'run';
    }
    dialog.showModal();
    loadConfig();
  };
  source.onchange = loadConfig;
  preset.onchange = loadConfig;
  const editPreset = document.createElement('button');
  editPreset.type = 'button';
  editPreset.className = 'button';
  editPreset.textContent = '查看或编辑所选模板';
  editPreset.onclick = () => {
    $('#config-dialog').close();
    open.click();
    if (dialog.open) {
      source.value = 'preset';
      loadConfig();
    }
  };
  $('#config-dialog .dialog-footer').prepend(editPreset);
  const threatButton=button('威胁区设置','button');threatButton.id='open-threat-editor';threatButton.onclick=async()=>{$('#config-dialog').close();preset.value=scenarioSelect.value;source.value='preset';dialog.showModal();await loadConfig();document.getElementById('threat-editor').scrollIntoView({block:'start'});};$('#config-dialog .dialog-footer').prepend(threatButton);
  $('#editor-close').onclick = () => { if (!submitting) dialog.close(); };
  dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    if (!pausedId) return;
    const id = pausedId;
    pausedId = null;
    liveCommand(id, {action: 'resume'}).catch(err => toast(err.message));
  });
  function createTaskDraft(taskId, type, dependsOn = []) {
    const template = config.task_types[type];
    const isLive = isLiveSource();
    const start = isLive ? config.sim_s + 1 : 0;
    const draft = clone(template.demo);
    const horizon = isLive ? (config.max_ticks || Math.max(start + 60,
      ...config.message.tasks.map(task => task.window.end_s))) : Number($('#editor-ticks').value);
    const end = Math.max(start + 1, horizon);
    draft.task_id = taskId;
    draft.depends_on = dependsOn;
    draft.params._workbench_task = true;
    if (type === 'T-PTL') {
      draft.params._workbench_patrol = true;
      delete draft.params.observation_target;
    }
    draft.window = {start_s: start, end_s: end};
    const card = taskCard(draft, false, true);
    for (const target of template.demo_targets) {
      if (target.slot === 'observation') continue;
      targetCard({...clone(target), task_id: taskId,
        target_id: nextTargetId(target.slot, target.index || 0)}, card.parentElement);
    }
    return card;
  }

  addTask.onclick = () => {
    const ids = [...(config.deleted_task_ids || []),
      ...[...tasks.children].map(row => row.taskId?.value.trim())];
    let next = 1n;
    for (const id of ids) {
      const match = id?.match(/^T([0-9]+)$/);
      if (!match) continue;
      const number = BigInt(match[1]);
      if (number >= next) next = number + 1n;
    }
    const card = createTaskDraft('T' + next, newType.value);
    card.open = true;
    syncTargets();
  };
  addUnit.onclick = () => {
    const cls = newUnitClass.value;
    const unit = {unit_id: 'UNIT-' + nextUnitNo(), robot_id: nextRobotId(cls),
      platform_class: cls, position: {x: 0, y: 0}, altitude_m: 0, heading_rad: 0,
      speed_mps: 2, endurance_s: 600, status: 'READY', capabilities: {}};
    unitCard(unit, true).open = true;
    platformGroups.get(cls).details.open = true;
    updatePlatformGroup(cls);
    refreshPlatformPreviews();
  };
  targetTask.addEventListener('change', updateTargetSlots);
  addTarget.onclick = () => addTargetFor(taskRowByRef(targetTask.value));
  addObservation.onclick = () => {
    const ids = [...targetRows().map(row => row.displayName()),
      ...[...targets.children].map(row => row.targetId?.value.trim())];
    let index = 1n;
    for (const id of ids) {
      const match = id?.match(/^OBS-([0-9]+)$/);
      if (!match) continue;
      const number = BigInt(match[1]);
      if (number >= index) index = number + 1n;
    }
    const patrol = allTaskRows().find(row => row.targetSlot === 'observation' &&
      !row.completed && !row.pendingDelete && row.included.checked);
    const base = config.message.tasks.find(task => task.task_type === 'T-PTL')?.target.patrol_area;
    const points = base?.polygon || base;
    const start = patrol?.aimPoint() || (points?.length ? [0, 1].map(axis =>
      points.reduce((sum, point) => sum + point[axis], 0) / points.length) : [0, 0]);
    const goal = [start[0] + 20, start[1]];
    observationCard({target_id: 'OBS-' + index, start, goal, speed_mps: 2,
      start_s: isLiveSource() ? config.sim_s + 1 : 0}, true);
    refreshObservationLinks();
  };
  addLibraryTarget.onclick = () => {
    const slot = librarySlot.value;
    const spec = slotSpec(slot);
    const task = allTaskRows().find(row => row.targetSlot === slot &&
      !row.completed && !row.pendingDelete && row.included.checked);
    const template = config.task_types[spec.task_types[0]];
    const example = template.demo_targets.find(target => target.slot === slot);
    const entry = {slot, ...clone(spec.defaults), target_id: nextTargetId(slot, 0)};
    for (const field of spec.fields) {
      if (field.key !== 'target_id' && example?.[field.key] != null) entry[field.key] = clone(example[field.key]);
    }
    const raw = Object.values(template.demo.target)[0];
    const sample = raw?.polygon || (Array.isArray(raw?.[0]) ? raw : [raw]);
    const shape = task?.associationShape()?.points || sample;
    const base = task?.aimPoint() || shape[0];
    if (slot === 'hold' || slot === 'assault') {
      entry.point = task ? base : entry.point || base;
    } else if (task || !entry.start || !entry.goal) {
      const outerX = Math.max(base[0], ...shape.map(point => point[0])) + 15;
      const outer = [outerX, base[1]];
      entry.start = slot === 'tracking' ? base : outer;
      entry.goal = slot === 'tracking' ? outer : base;
    }
    libraryTargetCard(entry, true);
    refreshObservationLinks();
  };
  function collectDraft() {
    const rows = [...tasks.children];
    const definitions = observationRows();
    const observationTargets = definitions.map(row => row.getConfig());
    const libraryRows = [...targetLibrary.children];
    const libraryTargets = libraryRows.map(row => row.getConfig());
    const idsByKey = new Map([...definitions, ...libraryRows].map(row => [row.libraryKey, row.displayName()]));
    const configs = rows.map(row => {
      let task = row.getConfig();
      if (task && row.targetKeys) {
        const params = {...task.params};
        const field = row.targetSlot === 'observation' ? 'observation_target_ids' : 'target_library_ids';
        delete params[field];
        if (row.targetKeys.size) params[field] = [...row.targetKeys].map(key => idsByKey.get(key));
        if (row.targetKeys.size || row.targetLinkMode.get() === 'manual' || '_target_link_mode' in params) {
          params._target_link_mode = row.targetLinkMode.get();
        }
        task = {...task, params};
      }
      return {row, task};
    }).filter(item => item.task);
    const selectedTasks = configs.map(item => item.task);
    const idByRef = new Map(configs.map(({row, task}) => [row.ref, task.task_id]));
    const selectedTargets = [...targets.children]
      .map(row => row.getConfig()).filter(Boolean)
      .map(target => ({...target, task_id: idByRef.get(target.taskRef) ?? target.taskRef}))
      .filter(target => selectedTasks.some(task => task.task_id === target.task_id))
      .map(({taskRef, ...target}) => target);
    const selectedUnits = unitRows.map(row => row.getConfig()).filter(Boolean);
    return {rows, configs, selectedTasks, selectedTargets, selectedUnits, observationTargets, libraryTargets};
  }
  $('#editor-form').onsubmit = async event => {
    event.preventDefault();
    if(pausedId&&!config?.editable){dialog.close();return;}
    if (!config?.editable || submitting || (state.busy && !pausedId)) return;
    submitting = submit.disabled = true;
    showError('');
    try {
      await Promise.all(allTaskRows().filter(row => row.included.checked && !row.pendingDelete).map(row => row.recommendation));
      const {rows, configs, selectedTasks, selectedTargets, selectedUnits} = collectDraft();
      const changes={tasks:selectedTasks, units:selectedUnits, targets:selectedTargets,
        exclude_tasks:configs.filter(item=>!item.row.included.checked).map(item=>item.task.task_id),
        delete_tasks:rows.filter(row=>row.pendingDelete&&row.originalTaskId).map(row=>row.originalTaskId)};
      if(pausedId){
        await liveCommand(pausedId,{action:'apply',revision:liveRevision,sim_s:config.sim_s,...changes});
        pausedId=null;dialog.close();toast('修改已应用，继续当前运行');return;
      }
      let payload;
      if(source.value==='run'){
        payload={replay_edit:{source_run:config.run_id,sim_s:config.sim_s,snapshot_token:config.snapshot_token,...changes}};
      } else {
        const request=window.BrowserIntegration.request({scenario:config.preset,planner:'interop',mode:'normal',
          ...(source.value==='initial'?{map_id:config.request.map_id}:{}),
          objective:$('#config-objective').value||config.objective||'makespan',
          max_ticks:Number($('#editor-ticks').value),motion:'real',avoid:true,behavior:true});
        payload={...request,randomize_tasks:false,reseed_on_run:false,
          edit:{source_run:source.value==='initial'?config.run_id:null,tasks:selectedTasks,units:selectedUnits,targets:selectedTargets,threats:window.ThreatEditor.get()}};
      }
      const response=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      dialog.close();watchProcess(response.id);
      toast(source.value==='run'?'正在从暂停时刻续算，完成后更新当前运行':'正在生成新的完整运行');
    } catch(err){showError(err.message);}
    finally{submitting=submit.disabled=false;}
  };

  function liveCommand(id, data) {
    return api('/api/live/' + encodeURIComponent(id), {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
  }

  let pollToken = 0;
  window.addEventListener('workbench-process', event => {
    const id = event.detail;
    const token = ++pollToken;
    liveId = null;
    clearTimeout(liveTimer);
    if (!id) return;
    let cursor = '';
    let failures = 0;
    async function poll() {
      try {
        const data = await api('/api/live/' + encodeURIComponent(id) +
          '/view?cursor=' + encodeURIComponent(cursor));
        if (token !== pollToken || data.process.state !== 'running') return;
        liveId = id;
        failures = 0;
        if (data.view) {
          const keepView = state.run?.id === id;
          if (!keepView) {
            state.loadToken++;
            setPage('overview');
          }
          displayRun(data.view, {keepView});
          cursor = data.version;
        }
      } catch (err) {
        if (token !== pollToken || !liveId) return;
        if (++failures === 3) toast('正在恢复实时地图连接 · ' + err.message);
      }
      if (token === pollToken) liveTimer = setTimeout(poll, 700);
    }
    poll();
  });
})();

for(const id of ['editor-observation-library','editor-target-library','editor-add-observation','editor-add-library-target','editor-library-slot']) { const node=document.getElementById(id); if(node)node.hidden=true; }
document.getElementById('editor-library-slot')?.closest('.editor-target-tools')?.setAttribute('hidden','');
