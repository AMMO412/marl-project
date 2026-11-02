"""Local workbench for the existing v2 planner. Python standard library only."""
import argparse
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'workbench'
OUTPUTS = ROOT / 'outputs'
SCENARIOS = {'simple_city': '城市道路场景', 'fleet_demo': '基础编成场景',
             'asl_city': '城市十字路口机动突击',
             'interop_neutral': '融合版五类任务样例（4.1 统一接口）',
             'interop_containment': '区域封控演示（T-SEC）',
             'interop_hold': '要点坚守演示（T-HLD）',
             'interop_asl': '融合版机动突击样例（T-ASL）'}
# 融合统一层覆盖五类任务：中性四类 + T-ASL（打击/判定仍由基座行为层执行）。
INTEROP_SCENARIOS = {'interop_neutral', 'interop_containment', 'interop_hold',
                     'interop_asl'}
# 4.1 原生场景：工作台直接读消息+编成表，规划走 interop，运行时用派生 v2 视图。
INTEROP_PAIRS = {'interop_neutral': ('mixed_inspection.message.json',
                                     'mixed_inspection.formation.json'),
                 'interop_containment': ('area_containment.message.json',
                                         'area_containment.formation.json'),
                 'interop_hold': ('key_point_hold.message.json',
                                  'key_point_hold.formation.json'),
                 'interop_asl': ('asl_junction.message.json',
                                 'asl_junction.formation.json')}
# 带静态障碍地图、可以开绕障的场景（其余场景没有真实障碍，绕障无意义）
AVOID_SCENARIOS = {'simple_city', 'asl_city', 'interop_containment',
                   'interop_hold', 'interop_asl'}
MODES = {'normal': '正常执行', 'failure': '失败重试', 'timeout': '超时恢复',
         'kill': '成员失联', 'deviation': '进度偏差'}
ARTIFACTS = {'manifest.json', 'scenario.json', 'report.json', 'trace.jsonl',
             'summary.txt', 'report.html', 'trajectory.html', 'request.json', 'worker.log',
             'behavior_trace.json', 'behavior_demo.html',
             'plan.json', 'assignments.csv', 'commands.csv', 'report.md',
             'ros2_commands.txt'}
SOURCES = {'readme': ROOT / 'README_v2.md', 'planner': ROOT / 'planner_v2.py',
           'coordinator': ROOT / 'coordinator_v2.py', 'fleet': ROOT / 'mock_fleet.py',
           'contracts': ROOT / 'contracts_v2.py'}
WORKBENCH_VERSION = '2026-11-02-hold-task-view'


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('参数必须是 JSON 对象')
    allowed = {'scenario', 'mode', 'motion', 'avoid', 'max_ticks', 'objective',
               'behavior', 'effect_kind', 'planner'}
    if set(data) - allowed:
        raise ValueError('存在不支持的参数')
    result = dict(scenario='simple_city', mode='normal', motion='real',
                  avoid=True, max_ticks=200, objective='makespan',
                  behavior=True, effect_kind='damage', planner='base')
    result.update(data)
    # Disabled browser fields may arrive as null from older clients.
    if result['scenario'] != 'asl_city' and result['effect_kind'] is None:
        result['effect_kind'] = 'damage'
    for key, choices in [('scenario', SCENARIOS), ('mode', MODES),
                         ('motion', ('real', 'teleport')),
                         ('planner', {'base': '基座 planner_v2',
                                      'interop': '融合统一层'}),
                         ('objective', ('makespan', 'energy', 'dispersion'))]:
        if not isinstance(result[key], str) or result[key] not in choices:
            raise ValueError('无效参数：' + key)
    if result['planner'] == 'interop' and result['scenario'] not in INTEROP_SCENARIOS:
        raise ValueError('融合统一层支持五类任务样例（%s）；其它历史场景请选基座'
                         '规划器' % '/'.join(sorted(INTEROP_SCENARIOS)))
    if result['scenario'] in INTEROP_PAIRS and result['planner'] != 'interop':
        raise ValueError('该场景是 4.1 原生输入，只能用融合统一层规划器（避免'
                         '有损转换后交给基座规划器）')
    # 效果类型（T-ASL 规范 §7）：毁伤/压制/夺占，接受中文标签，归一化为 token
    from assessment import normalize_effect_kind
    if not isinstance(result['effect_kind'], str):
        raise ValueError('无效参数：effect_kind')
    result['effect_kind'] = normalize_effect_kind(result['effect_kind'])
    if type(result['max_ticks']) is not int or not 10 <= result['max_ticks'] <= 700:
        raise ValueError('仿真上限应为 10–700 步')
    # 城市突击要走近 200 步机动再进五阶段，200 步会在途中截断；
    # 未显式指定步数时按该场景给出够用的默认值。
    if 'max_ticks' not in data and result['scenario'] == 'asl_city':
        result['max_ticks'] = 620
    if 'max_ticks' not in data and result['scenario'] == 'interop_neutral':
        result['max_ticks'] = 260
    if result['scenario'] == 'interop_containment':
        # 区域封控必须逐步运动 + 行为层：闭环的"到位→占位→警告→拦阻"才是任务本身，
        # 瞬移快进只剩一张计划表，看不出控制过程。
        result['motion'] = 'real'
        result['avoid'] = True
        result['behavior'] = True
        if 'max_ticks' not in data:
            result['max_ticks'] = 320
    if result['scenario'] == 'interop_hold':
        # 要点坚守同理：机动进场 → 占位 → 接替 → 增援 → 撤离是任务本身，
        # 瞬移快进会把轮换和增援的时序全压平。
        result['motion'] = 'real'
        result['avoid'] = True
        result['behavior'] = True
        if 'max_ticks' not in data:
            result['max_ticks'] = 280
    if 'max_ticks' not in data and result['scenario'] == 'interop_asl':
        result['max_ticks'] = 700
    if 'avoid' not in data and result['scenario'] in INTEROP_PAIRS:
        result['avoid'] = result['scenario'] in ('interop_containment',
                                                 'interop_hold',
                                                 'interop_asl')
    if result['scenario'] == 'interop_asl':
        # 4.1 原生突击样例：行为与效果判定必须开，且只能逐步运动 + 城市避障。
        if result['motion'] != 'real':
            raise ValueError('融合版机动突击需要逐步运动（motion=real）')
        result['avoid'] = True
        result['behavior'] = True
    if type(result['avoid']) is not bool:
        raise ValueError('avoid 必须是布尔值')
    if type(result['behavior']) is not bool:
        raise ValueError('behavior 必须是布尔值')
    if result['avoid'] and (result['motion'] != 'real'
                            or result['scenario'] not in AVOID_SCENARIOS):
        raise ValueError('绕障只适用于带静态障碍地图的场景（%s）的逐步运动模式'
                         % '/'.join(sorted(AVOID_SCENARIOS)))
    # 到位行为依赖真实运动 + 建筑绕障：不满足时自动降级（与 simulate 内部
    # 逻辑一致），而非报错——teleport 快进检查规划时不必为行为层报错。
    if result['behavior'] and not (result['motion'] == 'real' and result['avoid']):
        result['behavior'] = False
    return result


def run_worker(out):
    """Reuse the planner and its exporters; retain every run in a fresh directory."""
    from run_demo_v2 import simulate
    from reporting_v2 import render_html, render_text
    from trajectory_v2 import render
    config = validate_config(read_json(out / 'request.json'))
    custom = None
    scenario41 = None
    inputs = {}
    nav = None
    if config['scenario'] in INTEROP_PAIRS:
        # 4.1 原生场景：消息+编成表是权威输入；v2 字段只是运行替身视图，
        # 不写成可复用的旧场景文件，避免把有损转换当成等价场景。
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, to_v2_dict
        message_name, formation_name = INTEROP_PAIRS[config['scenario']]
        message_path = ROOT / 'interop' / 'scenarios' / message_name
        formation_path = ROOT / 'interop' / 'scenarios' / formation_name
        raw_message = read_json(message_path)
        raw_formation = read_json(formation_path)
        scenario41 = parse_message(raw_message, raw_formation)
        scenario = to_v2_dict(scenario41, raw_message, raw_formation)
        scenario['objective'] = ('energy' if config['objective'] == 'energy'
                                 else 'makespan')
        custom = InteropPlanner(scenario41, objective=config['objective'],
                                data=scenario)
        source = message_path
        inputs = {'message': str(message_path), 'formation': str(formation_path),
                  'message_sha256': hashlib.sha256(message_path.read_bytes()).hexdigest(),
                  'formation_sha256': hashlib.sha256(formation_path.read_bytes()).hexdigest()}
        # 融合层样例没有 _meta.sdf；静态地图改由 4.1 编成表的 no_go 约束构造，
        # 行为层（绕障/占位）才在同一张地图上跑，不去猜 simple_city 坐标。
        if config['avoid']:
            from interop.runtime import nav_from_scenario
            nav = nav_from_scenario(scenario41)
    else:
        source = ROOT / 'scenarios' / (config['scenario'] + '.json')
        scenario = read_json(source)
        scenario['objective'] = config['objective']
        inputs = {'scenario': str(source),
                  'scenario_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    # 效果类型注入（T-ASL 规范 §7）：新建演示选择的效果分类写进突击作业
    # 的 _behavior.effect_kind，行为层与评估接口据此走对应判定分支。
    # 4.1 原生突击样例以消息里的 effect 为权威，工作台不覆盖。
    if config['scenario'] != 'interop_asl':
        for job in scenario.get('jobs', []):
            if job.get('type') == 'assault':
                bh = job.setdefault('_behavior', {})
                bh['effect_kind'] = config['effect_kind']
    content = json.dumps(scenario, ensure_ascii=False, indent=2)
    if custom is None and config['planner'] == 'interop':
        from interop.runtime import planner_from_v2
        custom = planner_from_v2(scenario, objective=scenario.get('objective'))
    report, audit = simulate(scenario, mode=config['mode'], motion=config['motion'],
                             avoid=config['avoid'], max_ticks=config['max_ticks'],
                             behavior=config['behavior'], planner=custom, nav=nav)

    plan_files = []
    if scenario41 is not None:
        # 一并保存 4.2 计划产物，工作台可直接下载/核对：路径、指令、
        # ros2_commands.txt 与 run 的反馈轨迹是两份不同来源的数据。
        from interop.output import write_outputs
        from interop.scheduler import Planner
        objective = {'makespan': 'timeliness', 'dispersion': 'balanced'}.get(
            config['objective'], config['objective'])
        plan = Planner(scenario41, objective=objective).plan()
        bundle = out / '.plan_bundle'
        write_outputs(plan, scenario41, str(bundle),
                      input_paths={'message': inputs.get('message'),
                                   'formation': inputs.get('formation')},
                      extra=dict(planner='interop', source='workbench'))
        for name in ('plan.json', 'assignments.csv', 'commands.csv',
                     'report.md', 'ros2_commands.txt'):
            if (bundle / name).is_file():
                (out / name).write_bytes((bundle / name).read_bytes())
                plan_files.append(name)
        shutil.rmtree(bundle, ignore_errors=True)
    manifest = dict(protocol=report['protocol'], python=sys.version,
                    scenario=str(source),
                    inputs=inputs,
                    plan_files=plan_files,
                    scenario_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source_scenario_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    generated_at=datetime.now().astimezone().isoformat(),
                    backend='mock_only', external_integration_verified=False,
                    planner=config['planner'],
                    workbench_config=config, **{k: report[k] for k in
                    ('mode', 'motion', 'avoid', 'behavior', 'max_ticks', 'H', 'K', 'dev_threshold')})
    (out / 'scenario.json').write_text(content, encoding='utf-8')
    for name, value in [('report.json', report), ('manifest.json', manifest)]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'trace.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n'
                                           for e in audit), encoding='utf-8')
    (out / 'summary.txt').write_text(render_text(scenario, report, audit), encoding='utf-8')
    (out / 'report.html').write_text(render_html(scenario, report, audit), encoding='utf-8')
    render(out)


def compact_plan(doc, max_points=90):
    """把 4.2 plan.json 压成前端够用的形态（去掉逐指令明细）。

    区域封控页要画"从集结地到占位点的规划路径"和计划角色，只要 assignments；
    commands 有几百条六分量速度指令，原样塞进页面既慢也没人看。
    """
    assignments = []
    for item in doc.get('assignments') or []:
        path = item.get('path') or []
        if len(path) > max_points:
            step = max(1, len(path) // max_points)
            path = path[::step] + [path[-1]]
        assignments.append(dict(
            unit_id=item.get('unit_id'), robot_id=item.get('robot_id'),
            task_id=item.get('parent_task_id'), role=item.get('role') or '',
            target=item.get('target'), start_s=item.get('start_s'),
            end_s=item.get('end_s'), travel_s=item.get('travel_s'),
            path_length_m=item.get('path_length_m'),
            path=[[round(float(p[0]), 2), round(float(p[1]), 2)] for p in path]))
    return dict(plan_id=doc.get('plan_id'), assignments=assignments,
                metrics=doc.get('metrics') or {},
                objective=doc.get('objective'),
                makespan_s=(doc.get('metrics') or {}).get('makespan_s'))


def run_path(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('无效运行编号')
    path = OUTPUTS / run_id
    if not path.is_dir():
        raise FileNotFoundError('运行不存在')
    return path


def load_run(run_id):
    if run_id == 'behavior_20261028_verify':
        from workbench_recording import load_recording
        return load_recording(ROOT)
    from trajectory_v2 import build_replay_data
    out = run_path(run_id)
    scenario, report = read_json(out / 'scenario.json'), read_json(out / 'report.json')
    trace = [json.loads(line) for line in (out / 'trace.jsonl').read_text(encoding='utf-8').splitlines()
             if line.strip()]
    replay = build_replay_data(scenario, report, trace)
    obstacles, geometry_note = [], ''
    roads, landmarks, fleet_state = [], [], {}
    meta = scenario.get('_meta', {})
    bundle = meta.get('interop') or {}
    formation = bundle.get('formation') or {}
    if formation:
        # Render the geometry from this run's authoritative 4.1 input snapshot.
        # This also repairs historical interop runs without changing their evidence.
        for item in formation.get('constraints') or []:
            polygon = (item.get('area') or {}).get('polygon')
            if item.get('type') == 'no_go' and polygon:
                obstacles.append(dict(id=item.get('constraint_id'),
                                      label=item.get('source') or item.get('constraint_id'),
                                      source='interop_constraint', polygon=polygon))
        geometry_note = '障碍来自本轮编成表 no_go 约束；道路和地标仅作同源场景底图。'
        scene_meta = formation.get('meta') or {}
        state_path = ROOT / 'scenarios' / 'sdf_initial_state.json'
        if state_path.is_file():
            initial = read_json(state_path)
            source_name = str(initial.get('source', '')).replace('\\', '/').split('/')[-1]
            if (scene_meta.get('scene') == initial.get('world')
                    and scene_meta.get('source_sdf') == source_name):
                roads = initial.get('roads') or []
                landmarks = [dict(name=x.get('name'), pose=x.get('pose'),
                                  uri=x.get('uri'), kind=x.get('kind'))
                             for x in initial.get('landmarks') or []]
                by_no = {r['no']: r for r in initial.get('robots') or []}
                for platform in scenario.get('platforms') or []:
                    row = by_no.get(platform.get('robot_no'))
                    if row:
                        fleet_state[str(platform['robot_no'])] = {
                            k: row.get(k) for k in
                            ('kind', 'kind_label', 'chassis_size', 'envelope_size',
                             'envelope_radius', 'start', 'start_z', 'can_climb',
                             'control_plugin', 'mesh')}
    elif meta.get('sdf'):
        try:
            from city_nav import load_sdf_obstacles
            sdf = Path(meta['sdf'])
            if not sdf.is_absolute():
                sdf = ROOT.parent / sdf
            geometry = load_sdf_obstacles(
                sdf, bounds=meta.get('bounds'),
                transform=dict(scale=meta.get('scale', 1.0),
                               offset_x=meta.get('offset_x', 0.0),
                               offset_y=meta.get('offset_y', 0.0)),
                models_dir=(ROOT.parent / meta['models']
                            if meta.get('models') else None))
            # 统一字段：city_nav 用 footprint 标记几何来源，前端用 source 区分
            # "建筑（DAE 包围盒）/ 花坛围墙（显式盒体）"，两者别混着画。
            obstacles = [dict(id=o.get('id'), label=o.get('label') or o.get('id'),
                              source=o.get('footprint') or o.get('source') or 'box',
                              size=o.get('size_m') or o.get('size'),
                              polygon=o['polygon'])
                         for o in geometry['obstacles']]
            geometry_note = geometry['provenance']['rule']
        except (OSError, ValueError, KeyError) as exc:
            geometry_note = str(exc)
        # 场景底图与编成初始状态：道路/地标/平台尺寸来自 sdf_initial_state.json，
        # 和规划输入同源；读不到就退回只画障碍，不臆造。
        state_path = ROOT / 'scenarios' / 'sdf_initial_state.json'
        if state_path.is_file():
            try:
                initial = read_json(state_path)
                roads = initial.get('roads') or []
                landmarks = [dict(name=x.get('name'), pose=x.get('pose'),
                                  uri=x.get('uri'), kind=x.get('kind'))
                             for x in (initial.get('landmarks') or [])]
                by_no = {r['no']: r for r in initial.get('robots') or []}
                for item in scenario.get('platforms') or []:
                    row = by_no.get(item.get('robot_no'))
                    if row:
                        fleet_state[str(item.get('robot_no'))] = dict(
                            kind=row['kind'], kind_label=row['kind_label'],
                            chassis_size=row.get('chassis_size'),
                            envelope_size=row.get('envelope_size'),
                            envelope_radius=row.get('envelope_radius'),
                            start=row.get('start'), start_z=row.get('start_z'),
                            can_climb=row.get('can_climb'),
                            control_plugin=row.get('control_plugin'),
                            mesh=row.get('mesh'))
            except (OSError, ValueError, KeyError):
                roads, landmarks, fleet_state = [], [], {}
    elif 'simple_city.world' in str(meta.get('source', '')):
        try:
            from city_nav import bounds_from_scenario, load_obstacles
            geometry = load_obstacles(transform=meta,
                                      bounds=bounds_from_scenario(scenario))
            obstacles = geometry['obstacles']
            geometry_note = geometry['provenance']['rule']
        except (OSError, ValueError, KeyError) as exc:
            geometry_note = str(exc)
    from workbench_scene import scene_map
    try:
        backdrop = scene_map(scenario)
    except (OSError, ValueError, KeyError) as exc:
        backdrop = dict(error=str(exc))
    plan_payload = None
    plan_path = out / 'plan.json'
    if plan_path.is_file():
        try:
            plan_payload = compact_plan(read_json(plan_path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            plan_payload = dict(error=str(exc))
    return dict(id=run_id, scenario=scenario, report=report, trace=trace, replay=replay,
                manifest=read_json(out / 'manifest.json') if (out / 'manifest.json').exists() else {},
                obstacles=obstacles, geometry_note=geometry_note, scene_map=backdrop,
                roads=roads, landmarks=landmarks, fleet_state=fleet_state, plan=plan_payload,
                files=[n for n in sorted(ARTIFACTS) if (out / n).is_file()])


class Workbench:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.current = None

    def status(self):
        if self.process is None:
            return None
        code = self.process.poll()
        return dict(id=self.current, state='running' if code is None else
                    ('complete' if code == 0 else 'error'), exit_code=code)

    def start(self, data):
        config = validate_config(data)
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError('已有仿真正在运行，请等待完成')
            run_id = datetime.now().strftime('workbench_%Y%m%d_%H%M%S_%f')
            out = OUTPUTS / run_id
            out.mkdir(parents=True, exist_ok=False)
            (out / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            with (out / 'worker.log').open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                                 '--worker', str(out)], stdout=log, stderr=log,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.current = run_id
            return self.status()

    @staticmethod
    def _scenario_label(out):
        """运行列表里每条记录的场景名：优先工作台请求里的场景键，
        退回 manifest 里的场景文件名；都没有就不显示（老记录）。
        用户反馈"以前的其他任务怎么没了"——不是没了，是最新记录只有
        一个突击作业，而运行下拉里看不出哪条记录含几个任务、什么场景。"""
        try:
            m = read_json(out / 'manifest.json')
            key = (m.get('workbench_config') or {}).get('scenario')
            if key:
                return str(key)
            path = str(m.get('scenario') or '')
            if path:
                return Path(path).stem
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        return None

    def catalog(self):
        runs = []
        for out in sorted(OUTPUTS.iterdir(), reverse=True):
            if not out.is_dir() or not (out / 'report.json').is_file():
                continue
            if not (out / 'trace.jsonl').is_file():
                continue
            if out.name.startswith('workbench_') and not (out / 'trajectory.html').is_file():
                continue
            # Do not expose a partial run before the subprocess finishes exporting.
            if self.process and out.name == self.current and self.process.poll() is None:
                continue
            try:
                r = read_json(out / 'report.json')
                runs.append(dict(id=out.name, done=r['done'], total=len(r['jobs']),
                                 scenario=self._scenario_label(out),
                                 mode=r.get('mode', 'normal'), motion=r.get('motion', 'teleport'),
                                 avoid=r.get('avoid', False), behavior=r.get('behavior', False),
                                 behavior_details=r.get('behavior_details', False),
                                 objective=r.get('objective'),
                                 planner=r.get('planner', 'base_v2'),
                                 end=r.get('simulated_until_s'), energy=r.get('used_energy'),
                                 settled=r.get('settled'), retries=r.get('retries', 0),
                                 timeouts=r.get('timeouts', 0)))
            except (OSError, ValueError, KeyError):
                continue
        # 默认运行：优先多任务融合层运行，其次其它融合层运行、asl_city 行为运行。
        # 单任务的区域封控运行不抢占首页——它有自己的入口，首页仍看"全局分配"。
        interop_runs = [r for r in runs if r.get('planner') == 'interop']
        default_run = next((r['id'] for r in interop_runs
                            if int(r.get('total') or 0) >= 2), None)
        default_run = default_run or next((r['id'] for r in interop_runs), None)
        asl_runs = [r for r in runs
                    if r['behavior_details'] and r.get('scenario') == 'asl_city']
        default_run = default_run or next((r['id'] for r in asl_runs), None)
        default_run = default_run or next((r['id'] for r in runs if r['behavior_details']), None)
        default_run = default_run or next((r['id'] for r in runs if r['id'] == 'workbench_behavior_20261028'), None)
        default_run = default_run or next((r['id'] for r in runs if r['behavior']), None)
        default_run = default_run or next((r['id'] for r in runs if r['id'] == 'avoid_run'), None)
        if (OUTPUTS / 'behavior_20261028_verify' / 'behavior_trace.json').is_file():
            saved = read_json(OUTPUTS / 'behavior_20261028_verify' / 'behavior_trace.json')
            runs.append(dict(id='behavior_20261028_verify',
                             done=sum(j['phase'] == '完成' for j in saved['jobs']),
                             total=len(saved['jobs']), mode='recording', motion='real',
                             avoid=True, behavior=True, behavior_details=True,
                             recording=True, objective='原始专项记录',
                             end=saved['total'], energy=None, settled=True,
                             retries=None, timeouts=None))
        return dict(service='planning-middle-workbench/v1',
                    version=WORKBENCH_VERSION,
                    features=dict(planner=True,
                                  containment=True,
                                  hold=True,
                                  interop_scenario='interop_neutral',
                                  plan_schema='0.3'),
                    default_run=default_run,
                    scenarios=SCENARIOS,
                    modes=MODES, runs=runs, process=self.status())


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, body, content_type='application/json; charset=utf-8', code=200):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == '/api/catalog':
                    return self.send(app.catalog())
                if path.startswith('/api/runs/'):
                    return self.send(load_run(path.split('/')[-1]))
                if path.startswith('/api/source/'):
                    source = SOURCES.get(path.split('/')[-1])
                    if source is None:
                        raise FileNotFoundError()
                    return self.send(dict(name=source.name, text=source.read_text(encoding='utf-8')))
                if path.startswith('/artifacts/'):
                    parts = path.split('/')
                    if len(parts) != 4 or parts[3] not in ARTIFACTS:
                        raise FileNotFoundError()
                    file = run_path(parts[2]) / parts[3]
                elif path == '/demos/behavior':
                    file = OUTPUTS / 'behavior_20261028_verify' / 'behavior_demo.html'
                    if not file.is_file():
                        file = OUTPUTS / 'behavior_demo' / 'behavior_demo.html'
                elif path == '/demos/schematic':
                    file = ROOT.parent / 'outputs' / '任务动态示意_20261027' / 'index.html'
                elif path in ('/', '/index.html', '/app.js', '/containment.js',
                              '/hold.js', '/task_details.js', '/styles.css',
                              '/favicon.svg'):
                    file = STATIC / ('index.html' if path == '/' else path[1:])
                else:
                    raise FileNotFoundError()
                body = file.read_bytes()
                mime = mimetypes.guess_type(file.name)[0] or 'text/plain'
                return self.send(body, mime + '; charset=utf-8')
            except FileNotFoundError:
                self.send({'error': '文件或运行不存在'}, code=404)
            except (ValueError, KeyError, TypeError) as exc:
                self.send({'error': str(exc)}, code=400)

        def do_POST(self):
            # Read the declared body before any early rejection. Closing a
            # socket with unread request bytes makes Windows send RST, and the
            # client can lose the 403/404 response (intermittent
            # ConnectionAbortedError in tests and in the browser).
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = -1
            body = b''
            if length > 0 and length <= (1 << 20):
                body = self.rfile.read(length)
            elif length > (1 << 20):
                self.close_connection = True
            # A local-only API: reject browser requests from any other origin.
            origin = self.headers.get('Origin')
            expected = 'http://' + self.headers.get('Host', '')
            if origin and origin != expected:
                return self.send({'error': '仅允许工作台本身发起运行'}, code=403)
            if self.path != '/api/runs':
                return self.send({'error': '接口不存在'}, code=404)
            try:
                if length < 1 or length > 4096:
                    raise ValueError('请求大小无效')
                data = json.loads(body)
                self.send(app.start(data), code=202)
            except RuntimeError as exc:
                self.send({'error': str(exc)}, code=409)
            except (ValueError, TypeError) as exc:
                self.send({'error': str(exc)}, code=400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--open-path', default='/',
                        help='--open 时打开的页面路径，例如 /?new=interop')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run_worker(args.worker)
        return
    OUTPUTS.mkdir(exist_ok=True)
    server = None
    tried = []
    ports = [args.port] if args.port == 0 else [args.port + i for i in range(6)]
    for port in ports:
        tried.append(port)
        try:
            server = LocalServer(('127.0.0.1', port), make_handler(Workbench()))
            break
        except OSError:
            if not args.open:
                break
            # 端口被占用：如果占用者是**当前版本**的工作台，直接复用；
            # 如果是旧进程（没有 features.planner），不要静默打开旧页面，
            # 自动换下一个端口启动新版本。
            url = 'http://127.0.0.1:%d' % port
            try:
                with urlopen(url + '/api/catalog', timeout=2) as response:
                    existing = json.load(response)
                if (existing.get('service') == 'planning-middle-workbench/v1'
                        and existing.get('version') == WORKBENCH_VERSION
                        and (existing.get('features') or {}).get('planner')):
                    print('已连接现有工作台（%s）：%s'
                          % (existing.get('version', 'unknown'), url), flush=True)
                    webbrowser.open(url + args.open_path)
                    return
                print('端口 %d 上是旧版工作台，改在下一个可用端口启动。' % port,
                      flush=True)
            except (OSError, ValueError):
                print('端口 %d 已被其他程序占用，尝试下一个端口。' % port,
                      flush=True)
            continue
    if server is None:
        parser.exit(2, '端口 %s 均被占用；请用 --port 指定其他端口。\n'
                    % '/'.join(str(p) for p in tried))
    url = 'http://127.0.0.1:%d' % server.server_port
    print('MARL workbench %s: %s' % (WORKBENCH_VERSION, url), flush=True)
    if args.open:
        webbrowser.open(url + args.open_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
