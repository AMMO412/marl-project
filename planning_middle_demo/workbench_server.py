"""Local workbench for the existing v2 planner. Python standard library only."""
import argparse
from copy import deepcopy
from datetime import datetime
import os
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'workbench'
SCENARIO_DIR = ROOT / 'interop' / 'scenarios'
DEFAULT_OUTPUTS = ROOT.parent / 'desktop_app' / 'dist' / 'data' / 'runs'
if not DEFAULT_OUTPUTS.is_dir():
    DEFAULT_OUTPUTS = ROOT / 'outputs'
OUTPUTS = Path(os.environ.get('MARL_WORKBENCH_OUTPUTS') or DEFAULT_OUTPUTS)
SCENARIOS = {'interop_containment': '区域封控（T-SEC）',
             'interop_hold': '要点坚守（T-HLD）',
             'interop_patrol': '巡逻警戒（T-PTL）',
             'interop_recon': '协同侦察（T-RCN）',
             'interop_asl': '机动突击（T-ASL）'}

from interop.benchmark_scenarios import build_suite

_BENCHMARK_SUITE = build_suite()
BENCHMARK_SCENARIOS = {
    key: '算法测试 · ' + bundle.label
    for key, bundle in _BENCHMARK_SUITE.items()
}
from workbench_cases import CASES
CASE_SCENARIOS = {key: value[0] for key, value in CASES.items()}
ALL_SCENARIOS = dict(SCENARIOS, **BENCHMARK_SCENARIOS, **CASE_SCENARIOS)

# 融合统一层覆盖五类任务：中性四类 + T-ASL（打击/判定仍由基座行为层执行）。
INTEROP_SCENARIOS = {
    'interop_containment', 'interop_hold', 'interop_patrol',
    'interop_recon', 'interop_asl'
} | set(BENCHMARK_SCENARIOS) | set(CASE_SCENARIOS)
# 4.1 原生场景：工作台直接读消息+编成表，规划走 interop，运行时用派生 v2 视图。
INTEROP_PAIRS = {'interop_containment': ('area_containment.message.json',
                                         'area_containment.formation.json'),
                 'interop_hold': ('key_point_hold.message.json',
                                  'key_point_hold.formation.json'),
                 'interop_patrol': ('area_patrol.message.json',
                                    'area_patrol.formation.json'),
                 'interop_recon': ('crossroad_recon.message.json',
                                   'crossroad_recon.formation.json'),
                 'interop_asl': ('asl_junction.message.json',
                                 'asl_junction.formation.json')}
INTEROP_PAIRS.update({
    'interop_integrated': ('integrated_case.message.json', 'integrated_case.formation.json'),
    'interop_campus_motion20': ('campus_motion20.message.json', 'campus_motion20.formation.json')})
# 带静态障碍地图、可以开绕障的场景（其余场景没有真实障碍，绕障无意义）
AVOID_SCENARIOS = set(ALL_SCENARIOS)
MODES = {'normal': '正常执行', 'failure': '失败重试', 'timeout': '超时恢复',
         'kill': '成员失联', 'deviation': '进度偏差'}
ARTIFACTS = {'manifest.json', 'scenario.json', 'report.json', 'trace.jsonl',
             'summary.txt', 'report.html', 'trajectory.html', 'request.json', 'worker.log',
             'behavior_trace.json', 'behavior_demo.html',
             'plan.json', 'assignments.csv', 'commands.csv', 'report.md',
             'ros2_commands.txt', 'ros2_plan_node.py',
             'desktop_input.json', 'input_message.json', 'input_formation.json',
             'agent_tasks.md', 'agent_tasks.csv', 'agent_tasks.json',
             'planning_history.json', 'execution_plan.json'}
ARTIFACTS.update({'motion_commands.json', 'motion_commands.csv'})
ARTIFACTS.update({
    'chain_viewer.html', 'chain_summary.json', 'chain_verification.json',
    'chain_raw.json', 'initial_config.json', 'final_config.json', 'run_meta.json'})
SOURCES = {'entry': ROOT.parent / 'README.md',
           'interop_readme': ROOT / 'interop' / 'README.md',
           'readme': ROOT / 'README_v2.md', 'planner': ROOT / 'planner_v2.py',
           'coordinator': ROOT / 'coordinator_v2.py', 'fleet': ROOT / 'mock_fleet.py',
           'contracts': ROOT / 'contracts_v2.py'}
WORKBENCH_VERSION = '2026-11-16-dispatched-asl-roles-v39'


class LocalServer(ThreadingHTTPServer):
    request_queue_size = 64
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def editor_config(run_id=None, preset='interop_containment'):
    """Return one editable 4.1 input bundle for native and browser editors."""
    from workbench_target_editor import editor_target_slots, editor_targets
    from workbench_task_editor import (editor_param_labels, editor_task_types,
                                       is_editable_task)

    if run_id:
        from desktop_workflow import get_config
        config = get_config(sys.modules[__name__], preset, run_id)
        draft = config['draft']
        message, formation = draft['message'], draft['formation']
        completed = []
        source = config['input_source']
    else:
        message, formation = interop_inputs_for(preset)
        completed = []
        source = 'template'
    return dict(
        message=message,
        formation=formation,
        preset=preset,
        run_id=run_id,
        completed=completed,
        task_types=editor_task_types(),
        targets=editor_targets(message),
        target_slots=editor_target_slots(),
        param_labels=editor_param_labels(),
        editable=all(is_editable_task(task) for task in message['tasks']),
        input_source=source,
    )


def edited_inputs(edit, preset='interop_containment', objective='timeliness'):
    """Validate task and platform edits without creating a run directory."""
    from contracts_v2 import check_scenario_v2
    from interop.message import parse_message
    from interop.runtime import OBJECTIVE_MAP, to_v2_dict
    from interop.templates import decompose
    from workbench_patrol_editor import check_task_drafts
    from workbench_target_editor import apply_targets
    from workbench_task_editor import is_editable_task

    required = {'source_run', 'tasks', 'units'}
    allowed = required | {'targets'}
    if not isinstance(edit, dict) or not required <= set(edit) or set(edit) - allowed:
        raise ValueError('配置应包含来源、任务和平台')
    source = edit['source_run']
    if source is not None and (not isinstance(source, str) or not source):
        raise ValueError('无效的来源运行')
    base = editor_config(source, preset)
    if not base['editable']:
        raise ValueError('该模板仅支持查看配置')
    tasks, units = deepcopy(edit['tasks']), edit['units']
    if 'targets' in edit:
        tasks = apply_targets(tasks, edit['targets'])
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 50:
        raise ValueError('请选择 1 至 50 项任务')
    if not isinstance(units, list) or not 1 <= len(units) <= 50:
        raise ValueError('请选择 1 至 50 台平台')
    if not all(is_editable_task(task) for task in tasks):
        raise ValueError('配置编辑支持五类演示任务')
    message, formation = base['message'], base['formation']
    message['tasks'] = tasks
    formation['formation']['units'] = units
    scenario = parse_message(message, formation)
    decompose(scenario)
    check_task_drafts(
        scenario, objective=OBJECTIVE_MAP.get(objective, 'timeliness'))
    check_scenario_v2(to_v2_dict(scenario))
    return message, formation


def interop_inputs_for(scenario_key):
    """Return the authoritative 4.1 message/formation for current and test scenes."""
    if scenario_key in INTEROP_PAIRS:
        message_name, formation_name = INTEROP_PAIRS[scenario_key]
        message = read_json(ROOT / 'interop' / 'scenarios' / message_name)
        formation = read_json(ROOT / 'interop' / 'scenarios' / formation_name)
        if scenario_key in CASES:
            from workbench_cases import adapt_inputs
            return adapt_inputs(message, formation)
        return message, formation
    bundle = _BENCHMARK_SUITE.get(scenario_key)
    if bundle is None:
        raise ValueError('场景没有 4.1 输入：' + scenario_key)
    return deepcopy(bundle.message), deepcopy(bundle.formation)


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('参数必须是 JSON 对象')
    allowed = {'scenario', 'mode', 'motion', 'avoid', 'max_ticks', 'objective',
               'behavior', 'effect_kind', 'planner', 'map_id',
               'randomize_tasks', 'task_seed', 'reseed_on_run', 'live'}
    if set(data) - allowed:
        raise ValueError('存在不支持的参数')
    result = dict(scenario='interop_containment', mode='normal', motion='real',
                  avoid=True, objective='makespan', behavior=True,
                  effect_kind='damage', planner='interop',
                  randomize_tasks=True, task_seed=0, reseed_on_run=True, live=False)
    result.update(data)
    if result['objective'] == 'dispersion':
        result['objective'] = 'exposure'
    for key, choices in [('scenario', ALL_SCENARIOS), ('mode', MODES),
                         ('motion', ('real',)), ('planner', ('interop',)),
                         ('objective', ('makespan', 'energy', 'balanced', 'exposure'))]:
        if not isinstance(result[key], str) or result[key] not in choices:
            raise ValueError(
                '无效参数：' + key
                + '；仅支持六个交付演示、四个算法测试、两个综合案例和逐步运动'
            )
    from interop.urban_maps import MAP_IDS
    map_defaults = {
        'interop_bench_deadlines': 'downtown',
        'interop_bench_chokepoint': 'downtown',
        'interop_bench_threats': 'mixed',
    }
    if 'map_id' not in data:
        result['map_id'] = map_defaults.get(result['scenario'], 'residential')
    if result['scenario'] in CASES:
        result.update(map_id='source', randomize_tasks=False, reseed_on_run=False)
    if not isinstance(result['map_id'], str) or result['map_id'] not in (*MAP_IDS, 'source'):
        raise ValueError(
            '无效地图；仅支持住宅街区、密集城区和公园与斜街混合片区'
        )
    if result['map_id'] == 'source' and result['scenario'] not in CASES:
        raise ValueError('原始地图仅用于同事综合案例')
    for key in ('avoid', 'behavior', 'randomize_tasks', 'reseed_on_run', 'live'):
        if type(result[key]) is not bool:
            raise ValueError(key + ' 必须是布尔值')
    if type(result['task_seed']) is not int or not 0 <= result['task_seed'] <= 2147483647:
        raise ValueError('task_seed 必须是 0–2147483647 的整数')
    if result['randomize_tasks'] and result['task_seed'] == 0:
        from interop.random_tasks import new_task_seed
        result['task_seed'] = new_task_seed()
    if not result['randomize_tasks']:
        result['reseed_on_run'] = False
    defaults = {'interop_containment': 320, 'interop_hold': 280,
                'interop_patrol': 320, 'interop_recon': 220,
                'interop_asl': 700}
    result['max_ticks'] = data.get(
        'max_ticks', CASES[result['scenario']][1] if result['scenario'] in CASES else defaults.get(result['scenario'], 700))
    if type(result['max_ticks']) is not int or not 10 <= result['max_ticks'] <= 1200:
        raise ValueError('仿真上限应为 10–1200 步')
    from assessment import normalize_effect_kind
    effect = result['effect_kind']
    if effect is None:
        effect = 'damage'
    if not isinstance(effect, str):
        raise ValueError('无效参数：effect_kind')
    result['effect_kind'] = normalize_effect_kind(effect)
    from demo_modes import PROGRESS_MODES
    result.update(avoid=True, behavior=result['mode'] not in PROGRESS_MODES)
    if result['scenario'] in CASES:
        result['behavior'] = CASES[result['scenario']][2]
    return result


def compare_objectives(scenario_key):
    """Plan the same scenario under four objectives; no simulation is started."""
    if scenario_key not in INTEROP_SCENARIOS:
        raise ValueError('四目标对比只支持融合版场景（interop_*）')
    from interop.cost import OBJECTIVE_LABELS
    from interop.message import parse_message
    from interop.scheduler import Planner

    raw_message, raw_formation = interop_inputs_for(scenario_key)
    scenario = parse_message(raw_message, raw_formation)
    order = ('timeliness', 'energy', 'balanced', 'exposure')
    results = []
    for objective in order:
        started = time.perf_counter()
        plan = Planner(scenario, objective=objective).plan()
        elapsed = (time.perf_counter() - started) * 1000.0
        metrics = plan.objective_metrics or {}
        results.append(dict(
            objective=objective,
            label=OBJECTIVE_LABELS.get(objective, objective),
            assigned=plan.metrics.assigned_subtasks,
            total=plan.metrics.assigned_subtasks + plan.metrics.unassigned_subtasks,
            makespan_s=plan.metrics.makespan_s,
            total_energy=metrics.get('total_energy', 0.0),
            total_exposure=metrics.get('total_exposure', 0.0),
            detection_probability=metrics.get('detection_probability', 0.0),
            unassigned=[u.get('reason') for u in plan.unassigned],
            runtime_ms=round(elapsed, 1),
        ))
    threats = []
    for item in scenario.constraints:
        if item.get('type') != 'threat':
            continue
        polygon = (item.get('area') or {}).get('polygon') or []
        threats.append(dict(
            id=item.get('constraint_id'),
            intensity=item.get('intensity', 1.0),
            applies_to=item.get('applies_to', 'ground'),
            polygon=polygon,
        ))
    return dict(
        scenario=scenario_key,
        objectives=list(order),
        results=results,
        threats=threats,
        note='规划层结果，未执行；同一场景、同一编成，仅切换目标。'
             '不同目标可能给出相同计划，需结合完成数与硬约束看。',
    )


def run_worker(out):
    """Reuse the planner and its exporters; retain every run in a fresh directory."""
    from run_demo_v2 import simulate
    from reporting_v2 import render_text
    from chain_trace import ChainRecorder, export_chain
    config = validate_config(read_json(out / 'request.json'))
    desktop_input = read_json(out / 'desktop_input.json') if (out / 'desktop_input.json').is_file() else None
    from workbench_replay_editor import SEED_FILE, run_seed
    seed_path = out / SEED_FILE
    replay_seed = read_json(seed_path) if seed_path.is_file() else None
    if replay_seed is not None:
        bundle = replay_seed['scenario']['_meta']['interop']
        desktop_input = dict(request=config, message=bundle['message'], formation=bundle['formation'])
    custom = None
    scenario41 = None
    raw_message = None
    raw_formation = None
    chain_recorder = None
    inputs = {}
    nav = None
    if config['scenario'] in INTEROP_SCENARIOS:
        # 4.1 原生场景：消息+编成表是权威输入；v2 字段只是运行替身视图，
        # 不写成可复用的旧场景文件，避免把有损转换当成等价场景。
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, to_v2_dict
        if desktop_input is None and config['scenario'] in INTEROP_SCENARIOS:
            from desktop_workflow import validate_draft
            message, formation = interop_inputs_for(config['scenario'])
            desktop_input, _ = validate_draft(sys.modules[__name__],
                dict(request=config, message=message, formation=formation))
        if desktop_input is not None:
            from desktop_workflow import validate_draft
            desktop_input, _ = validate_draft(sys.modules[__name__], desktop_input, materialize_inputs=replay_seed is None)
            message_path, formation_path = out / 'input_message.json', out / 'input_formation.json'
            for path, value in ((message_path, desktop_input['message']), (formation_path, desktop_input['formation'])):
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        elif config['scenario'] in BENCHMARK_SCENARIOS or config['scenario'] in CASES:
            raw_message, raw_formation = interop_inputs_for(config['scenario'])
            message_path = out / 'input_message.json'
            formation_path = out / 'input_formation.json'
            for path, value in (
                (message_path, raw_message),
                (formation_path, raw_formation),
            ):
                path.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
        else:
            message_name, formation_name = INTEROP_PAIRS[config['scenario']]
            message_path = ROOT / 'interop' / 'scenarios' / message_name
            formation_path = ROOT / 'interop' / 'scenarios' / formation_name
        raw_message = read_json(message_path)
        raw_formation = read_json(formation_path)
        scenario41 = parse_message(raw_message, raw_formation)
        scenario = to_v2_dict(scenario41, raw_message, raw_formation)
        scenario['objective'] = {'energy': 'energy',
                                 'exposure': 'exposure',
                                 'balanced': 'balanced'}.get(
                                     config['objective'], 'makespan')
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
            nav = nav_from_scenario(
                scenario41, avoid_threats=(config['objective'] == 'exposure'))
    else:
        source = ROOT / 'scenarios' / (config['scenario'] + '.json')
        scenario = read_json(source)
        scenario['objective'] = config['objective']
        inputs = {'scenario': str(source),
                  'scenario_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    # 效果类型注入（T-ASL 规范 §7）：新建演示选择的效果分类写进突击作业
    # 的 _behavior.effect_kind，行为层与评估接口据此走对应判定分支。
    # 4.1 原生突击样例以消息里的 effect 为权威，工作台不覆盖。
    if scenario41 is None:
        for job in scenario.get('jobs', []):
            if job.get('type') == 'assault':
                bh = job.setdefault('_behavior', {})
                bh['effect_kind'] = config['effect_kind']
    content = json.dumps(scenario, ensure_ascii=False, indent=2)
    if custom is None and config['planner'] == 'interop':
        from interop.runtime import planner_from_v2
        custom = planner_from_v2(scenario, objective=scenario.get('objective'))
    if raw_message is not None and raw_formation is not None:
        chain_recorder = ChainRecorder(raw_message, raw_formation, planner=custom)
    if replay_seed is not None:
        scenario, scenario41, report, audit = run_seed(replay_seed, out, recorder=chain_recorder)
        custom = chain_recorder.planner
    else:
        if scenario41 is not None:
            from motion import MOTION_MODEL
            seed_path.write_text(json.dumps(dict(scenario=deepcopy(scenario), config=deepcopy(config),
                history=[], motion_model=MOTION_MODEL), ensure_ascii=False), encoding='utf-8')
        live = None
        if config.get('live'):
            from workbench_live import LiveRun
            live = LiveRun(out, scenario, config=config)
        report, audit = simulate(scenario, mode=config['mode'], motion=config['motion'],
                             avoid=config['avoid'], max_ticks=config['max_ticks'],
                             behavior=config['behavior'], planner=custom, nav=nav,
                             before_tick=(chain_recorder.before_tick if chain_recorder else None),
                             after_tick=(lambda core, fleet, tick: live(core, fleet, tick + 1)) if live else None,
                             run_id=out.name)
        if scenario41 is not None:
            scenario41 = custom.scenario
    content = json.dumps(scenario, ensure_ascii=False, indent=2)
    if scenario41 is not None:
        final_bundle = scenario['_meta']['interop']
        for path, value in ((message_path, final_bundle['message']), (formation_path, final_bundle['formation'])):
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        inputs.update(message_sha256=hashlib.sha256(message_path.read_bytes()).hexdigest(),
                      formation_sha256=hashlib.sha256(formation_path.read_bytes()).hexdigest())
    if config['planner'] == 'base' and config['objective'] in ('exposure', 'balanced'):
        # 基座历史场景（simple_city/asl_city）没有 constraints，也没有均衡代价；
        # 这两个目标在基座都会退化为完工时间，必须在报告里说明。
        report['limitation'] = (report.get('limitation', '')
                                + '；本场景无威胁区/均衡代价，目标按完工时间处理')

    plan_files = []
    if scenario41 is not None:
        # 一并保存 4.2 计划产物，工作台可直接下载/核对：路径、指令、
        # ros2_commands.txt 与 run 的反馈轨迹是两份不同来源的数据。
        from interop.output import write_outputs
        from interop.scheduler import Planner
        objective = {'makespan': 'timeliness'}.get(
            config['objective'], config['objective'])
        # Export the first rolling-planning snapshot that actually produced
        # the initial dispatch. Re-planning here after the simulation can
        # choose a different unit set because finished/in-flight tasks are no
        # longer present in the live snapshot.
        plan = custom.initial_plan or Planner(
            scenario41, objective=objective).plan()
        # 把计划层指标挂到运行报告，结果卡可直接显示目标、makespan、
        # 总暴露量与 P；不改动仿真报告原有字段。
        report['plan_objective'] = plan.objective
        report['plan_objective_metrics'] = plan.objective_metrics
        report['plan_assignments'] = len(plan.assignments)
        report['plan_unassigned'] = len(plan.unassigned)
        bundle = out / '.plan_bundle'
        write_outputs(plan, scenario41, str(bundle),
                      input_paths={'message': inputs.get('message'),
                                   'formation': inputs.get('formation')},
                      extra=dict(planner='interop', source='workbench'))
        for name in ('plan.json', 'assignments.csv', 'commands.csv',
                     'ros2_plan_node.py', 'agent_tasks.md',
                     'agent_tasks.csv', 'agent_tasks.json'):
            if (bundle / name).is_file():
                (out / name).write_bytes((bundle / name).read_bytes())
                plan_files.append(name)
        shutil.rmtree(bundle, ignore_errors=True)
    if scenario41 is not None:
        from trajectory_v2 import build_replay_data
        replay = build_replay_data(scenario, report, audit)
        # Retain the independent static plan as a reference, but never compare
        # its members/routes with unrelated actual dispatches.
        from execution_evidence import bind_execution
        evidence = bind_execution(custom.plan_history, audit,
                                  report['simulated_until_s'], config['objective'])
        evidence['plan_id'] = 'DISPATCH-' + out.name
        for name, value in (('planning_history.json', custom.plan_history),
                            ('execution_plan.json', evidence)):
            (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            plan_files.append(name)
        report['reference_plan_metrics'] = report['plan_objective_metrics']
        report['plan_objective_metrics'] = evidence['metrics']
        report['plan_metrics_source'] = 'runtime_dispatch'
        report['comparison_complete'] = evidence['comparison_complete']
        report['comparison_scope'] = evidence['note']
        report['plan_assignments'] = len(evidence['assignments'])
        from interop.agent_tasks import build_agent_tasks, agent_artifact, ARTIFACT_NAMES
        agent_data = build_agent_tasks(evidence, raw_formation['formation']['units'])
        agent_data['note'] = evidence['note']
        for name in ARTIFACT_NAMES:
            (out / name).write_bytes(agent_artifact(agent_data, name))
        full_x, full_p = execution_exposure(replay, scenario41.constraints)
        report['execution_exposure_total'] = round(full_x, 3)
        report['execution_detection_probability_total'] = round(full_p, 4)
        exec_x, exec_p = execution_exposure(replay, scenario41.constraints, evidence['intervals'])
        report['execution_exposure'] = round(exec_x, 3)
        report['execution_detection_probability'] = round(exec_p, 4)
    if chain_recorder is not None:
        from interop.config_resolution import config_resolution
        report['timing_resolution'] = config_resolution(audit,chain_recorder.commands,chain_recorder.feedback,
            report['simulated_until_s'],max(1,int(scenario.get('K',8))))
        if chain_recorder.motion is not None:
            report['motion_commands'] = chain_recorder.motion.write(out,report,
                {cid:row.get('subtask_id') for cid,row in chain_recorder.command_rows.items()})
            plan_files.extend(['motion_commands.json','motion_commands.csv'])
    chain_summary = None
    if chain_recorder is not None:
        chain_summary = export_chain(
            out, chain_recorder, scenario41, raw_message, raw_formation,
            report, audit, config['scenario'])
        report['chain_verification'] = dict(
            passed=chain_summary['passed'],
            failed_checks=list(chain_summary['failed_checks']),
            stats=deepcopy(chain_summary['stats']))
    (out / 'run_meta.json').write_text(json.dumps(dict(
        workbench_version=WORKBENCH_VERSION, run_id=out.name, edit_mode='resume' if replay_seed else ('live' if config.get('live') else 'new_run'),
        scenario=config['scenario'], map_id=config['map_id'],
        task_seed=config['task_seed'], mock_only=True,
        input_snapshot=SEED_FILE if seed_path.is_file() else 'scenario.json',
        archive_policy='actual_commands_and_feedback',
        imported_case=config['scenario'] in CASES), ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = dict(protocol=report['protocol'], python=sys.version,
                    scenario=str(source),
                    inputs=inputs,
                    plan_files=plan_files,
                    chain=dict(
                        verification='chain_verification.json',
                        viewer='chain_viewer.html',
                        passed=(chain_summary or {}).get('passed'),
                    ),
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
    (out / 'summary.txt').write_text(render_text(scenario, report, audit, include_events=False), encoding='utf-8')



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
            subtask_id=item.get('subtask_id'), parent_task_id=item.get('parent_task_id'),
            task_type=item.get('task_type'), window=item.get('window'),
            depends_on=item.get('depends_on'), coordination=item.get('coordination'),
            status=item.get('status'),
            runtime_plan_id=item.get('runtime_plan_id'), attempt=item.get('attempt'),
            command_id=item.get('command_id'),
            path_length_m=item.get('path_length_m'),
            path=[[round(float(p[0]), 2), round(float(p[1]), 2)] for p in path]))
    return dict(plan_id=doc.get('plan_id'), assignments=assignments,
                metrics=doc.get('metrics') or {},
                objective=doc.get('objective'),
                makespan_s=(doc.get('metrics') or {}).get('makespan_s'))


def _inside_polygon(polygon, x, y):
    inside = False
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        if (y1 > y) != (y2 > y):
            cross = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < cross:
                inside = not inside
    return inside


def execution_exposure(replay, constraints, intervals=None):
    """Exposure actually accumulated by recorded execution samples.

    Planning exposure is computed from planned routes.  The behavior layer can
    choose a different route, so this second metric is needed to avoid showing
    "plan 0" while the recorded trajectory visibly crosses a threat zone.
    """
    threats = []
    for item in constraints or []:
        if item.get('type') != 'threat':
            continue
        polygon = (item.get('area') or {}).get('polygon') or []
        if len(polygon) >= 3:
            threats.append((float(item.get('intensity', 1.0)),
                            str(item.get('applies_to', 'ground')), polygon))
    if not threats:
        return 0.0, 0.0
    from interop.cost import CLASS_PROTECTION, CLASS_SIGNATURE
    total = 0.0
    for worker in replay.get('workers') or []:
        kind = str(worker.get('kind'))
        if kind not in ('UGV', 'TANK', 'PLANE', 'WING'):
            continue
        factor = CLASS_SIGNATURE.get(kind, 1.0) * max(
            0.0, 1.0 - CLASS_PROTECTION.get(kind, 0.0))
        samples = sorted((p for p in worker.get('samples') or []
                          if math.isfinite(float(p.get('t', 0)))),
                         key=lambda p: float(p['t']))
        for first, second in zip(samples, samples[1:]):
            t0, t1 = float(first['t']), float(second['t'])
            dt = t1 - t0
            if dt <= 0:
                continue
            spans = [(t0, t1)]
            if intervals is not None:
                spans = [(max(t0, c['start_s']), min(t1, c['end_s']))
                         for c in intervals.get(worker.get('pid'), [])
                         if c['command_id'] == first.get('command')]
            for begin, finish in spans:
                if finish <= begin:
                    continue
                ratio = ((begin + finish) / 2 - t0) / dt
                x = float(first['x']) + (float(second['x']) - float(first['x'])) * ratio
                y = float(first['y']) + (float(second['y']) - float(first['y'])) * ratio
                for intensity, applies_to, polygon in threats:
                    if applies_to == 'ground' and kind not in ('UGV', 'TANK'):
                        continue
                    if applies_to == 'air' and kind not in ('PLANE', 'WING'):
                        continue
                    if _inside_polygon(polygon, x, y):
                        total += intensity * (finish-begin) * factor
    probability = 1.0 - math.exp(-0.1 * total)
    return total, probability


def plan_objective_metrics(out):
    """Read plan-level metrics from an existing plan.json, if present."""
    path = out / 'plan.json'
    if not path.is_file():
        return {}
    try:
        doc = read_json(path)
        return doc.get('objective_metrics') or {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def run_roots():
    roots = [OUTPUTS]
    legacy = ROOT / 'outputs'
    if not os.environ.get('MARL_WORKBENCH_OUTPUTS') and OUTPUTS == DEFAULT_OUTPUTS and legacy != OUTPUTS and legacy.is_dir():
        roots.append(legacy)
    return roots


def run_path(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('无效运行编号')
    for root in run_roots():
        path = root / run_id
        if path.is_dir():
            return path
    raise FileNotFoundError('运行不存在')


def load_run(run_id):
    if run_id == 'behavior_20261028_verify':
        from workbench_recording import load_recording
        return load_recording(ROOT)
    from trajectory_v2 import build_replay_data
    out = run_path(run_id)
    scenario, report = read_json(out / 'scenario.json'), read_json(out / 'report.json')
    trace = [json.loads(line) for line in (out / 'trace.jsonl').read_text(encoding='utf-8').splitlines()
             if line.strip()]
    return run_view(run_id, out, scenario, report, trace)


def run_view(run_id, out, scenario, report, trace):
    from trajectory_v2 import build_replay_data
    replay = build_replay_data(scenario, report, trace)
    obstacles, geometry_note = [], ''
    threats = []
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
            elif item.get('type') == 'threat' and polygon:
                threats.append(dict(id=item.get('constraint_id') or 'THREAT',
                                    label=item.get('constraint_id') or '威胁区',
                                    intensity=item.get('intensity', 1.0),
                                    applies_to=item.get('applies_to', 'ground'),
                                    polygon=polygon))
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
    plan_doc = None
    execution_plan = read_json(out / 'execution_plan.json') if (out / 'execution_plan.json').is_file() else None
    plan_path = out / 'plan.json'
    if plan_path.is_file():
        try:
            plan_doc = read_json(plan_path)
            plan_payload = compact_plan(plan_doc)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            plan_payload = dict(error=str(exc))
    reference_plan = plan_payload
    if execution_plan is not None:
        plan_doc = execution_plan
        plan_payload = compact_plan(execution_plan)
    # 旧运行报告没有 plan_objective_metrics；若 plan.json 仍在，直接补出来，
    # 结果卡/对比表就能显示当时计划的目标、暴露量与 P，无需重跑。
    if isinstance(plan_doc, dict) and not report.get('plan_objective_metrics'):
        metrics = plan_doc.get('objective_metrics') or {}
        if metrics:
            report['plan_objective_metrics'] = metrics
            report['plan_objective'] = plan_doc.get('objective')
    if 'execution_exposure' not in report:
        exec_x, exec_p = execution_exposure(replay, (formation or {}).get('constraints'))
        report['execution_exposure'] = round(exec_x, 3)
        report['execution_detection_probability'] = round(exec_p, 4)
    from interop.agent_tasks import ARTIFACT_NAMES, build_agent_tasks, render_agent_tasks
    agent_tasks = (build_agent_tasks(plan_doc, (formation.get('formation') or {}).get('units') or [])
                   if isinstance(plan_doc, dict) else None)
    if agent_tasks is not None and execution_plan is not None:
        agent_tasks['note'] = execution_plan['note']
    files = [n for n in sorted(ARTIFACTS) if (out / n).is_file()]
    if agent_tasks is not None:
        priority = list(ARTIFACT_NAMES) + [n for n in ('execution_plan.json', 'planning_history.json') if n in files]
        files = priority + [n for n in files if n not in priority]
    chain_summary = (read_json(out / 'chain_summary.json')
                     if (out / 'chain_summary.json').is_file() else None)
    return dict(id=run_id, scenario=scenario, report=report, trace=trace, replay=replay,
                manifest=read_json(out / 'manifest.json') if (out / 'manifest.json').exists() else {},
                obstacles=obstacles, geometry_note=geometry_note, scene_map=backdrop,
                threats=threats,
                roads=roads, landmarks=landmarks, fleet_state=fleet_state, plan=plan_payload,
                reference_plan=reference_plan, execution_plan=execution_plan,
                agent_tasks=agent_tasks,
                agent_tasks_text=render_agent_tasks(agent_tasks) if agent_tasks is not None else '本轮未保存计划，无法还原单平台子任务及约束。',
                chain_summary=chain_summary,
                files=files)


DESKTOP_TASK_LABELS = {
    'blockade': 'T-SEC 区域封控',
    'patrol': 'T-PTL 巡逻警戒',
    'recon': 'T-RCN 协同侦察',
    'assault': 'T-ASL 机动突击',
    'hold': 'T-HLD 要点坚守',
    'relay': '任务接力',
}


def _desktop_sample(samples, at_s):
    """Return the last sample at or before at_s, without assuming sorted input."""
    best = None
    for sample in samples or []:
        try:
            t = float(sample.get('t'))
        except (TypeError, ValueError):
            continue
        if t <= at_s + 1e-9 and (best is None or t >= float(best.get('t', 0))):
            best = sample
    return best or {}


def _desktop_platform_sample(worker, at_s):
    """Pose at the cursor, with sparse telemetry held from past feedback only."""
    samples = worker.get('samples') or []
    selected = dict(_desktop_sample(samples, at_s))
    for field, initial in (('battery', worker.get('initial_battery')), ('progress', None)):
        value, when = initial, float('-inf')
        for sample in samples:
            t = float(sample.get('t', 0))
            if t <= at_s + 1e-9 and t >= when and sample.get(field) is not None:
                value, when = sample[field], t
        selected[field] = value
    return selected


def _desktop_status_at(events, job_id, at_s):
    """Derive a task status from recorded events so a replay scrubber can move backward."""
    status = 'pending'
    for event in events or []:
        if event.get('job_id') != job_id or float(event.get('sim_s') or 0) > at_s + 1e-9:
            continue
        kind = event.get('kind')
        if kind in ('job_dispatched', 'job_retry', 'replan'):
            status = 'running'
        elif kind in ('job_succeeded', 'job_completed'):
            status = 'succeeded'
        elif kind in ('job_failed', 'job_cancelled'):
            status = 'failed'
        elif kind == 'job_timeout':
            status = 'timeout'
    return status


def desktop_run(run_id, at_s=None):
    """Compact, native-shell friendly view of one recorded run.

    Full geometry and replay samples stay in /api/runs/<id>; this endpoint only
    returns what the desktop panels need, optionally at a playback time.
    """
    doc = load_run(run_id)
    replay, report = doc.get('replay') or {}, doc.get('report') or {}
    events = replay.get('events') or []
    end = float(replay.get('end') or report.get('simulated_until_s') or 0)
    if at_s is None:
        at_s = end
    at_s = max(0.0, min(float(at_s), end))

    pids_by_job = {}
    for event in events:
        if event.get('kind') == 'job_dispatched' and event.get('job_id'):
            pids_by_job.setdefault(event['job_id'], list(event.get('pids') or []))

    tasks = []
    for job in report.get('jobs') or []:
        job_id = job.get('job_id')
        jtype = job.get('jtype') or ''
        tasks.append(dict(
            id=job_id,
            type=jtype,
            label=DESKTOP_TASK_LABELS.get(jtype, jtype or job_id or '任务'),
            status=job.get('status') or 'unknown',
            status_at=_desktop_status_at(events, job_id, at_s),
            assigned=pids_by_job.get(job_id, []),
            position=job.get('pos'),
            window=job.get('window'),
            crew=job.get('crew'),
            progress=round(float(job.get('progress') or 0), 3),
            work=job.get('work'),
            started_at=job.get('started_at'),
            planned_end=job.get('planned_end'),
            attempts=job.get('attempts'),
        ))

    workers = {w.get('pid'): w for w in replay.get('workers') or []}
    participants = {pid for e in events if e.get('kind') == 'job_dispatched'
                    for pid in e.get('pids') or []}
    platforms = []
    for platform in report.get('platforms') or []:
        pid = platform.get('pid')
        worker = workers.get(pid) or {}
        sample = _desktop_platform_sample(worker, at_s)
        start = worker.get('start') or platform.get('pos') or [0, 0]
        battery = sample.get('battery')
        if battery is None and not worker.get('samples') and pid not in participants:
            battery = platform.get('battery')
        job = sample.get('job')
        task_status = _desktop_status_at(events, job, at_s) if job else None
        status = sample.get('status') or 'idle'
        if task_status in ('succeeded', 'failed', 'timeout'):
            status, job = task_status, None
        losses = [e for e in events if e.get('kind') == 'member_lost'
                  and (e.get('pid') == pid or pid in (e.get('pids') or []))]
        alive = not any(float(e.get('sim_s') or 0) <= at_s + 1e-9 for e in losses)
        if not losses and at_s >= end:
            alive = platform.get('alive', True)
        if not alive:
            status, job = 'lost', None
        platforms.append(dict(
            id=pid,
            participates=pid in participants or any(s.get('job') for s in worker.get('samples') or []),
            kind=platform.get('kind') or worker.get('kind'),
            robot_no=platform.get('robot_no') or worker.get('no'),
            position=[sample.get('x', start[0]), sample.get('y', start[1])],
            z=sample.get('z', worker.get('start_z', 0.0)),
            yaw=sample.get('yaw', 0.0),
            battery=battery,
            alive=alive,
            job=job,
            phase=sample.get('phase'),
            status=status,
            progress=sample.get('progress', 0.0),
            home=platform.get('home'),
            return_status=platform.get('return_status'),
        ))

    visible_events = []
    for event in events:
        if float(event.get('sim_s') or 0) > at_s + 1e-9:
            continue
        visible_events.append({
            key: event.get(key) for key in
            ('kind', 'sim_s', 'job_id', 'label', 'pids', 'attempt',
             'planned_start', 'planned_end', 'detail', 'phase')
            if key in event
        })

    manifest = doc.get('manifest') or {}
    config = manifest.get('workbench_config') or {}
    return dict(
        id=run_id,
        at_s=round(at_s, 3),
        end=round(end, 3),
        run=dict(
            id=run_id,
            scenario=config.get('scenario') or manifest.get('scenario') or '',
            objective=report.get('objective'),
            mode=report.get('mode'),
            motion=report.get('motion'),
            avoid=report.get('avoid'),
            behavior=report.get('behavior'),
            status='已完成' if report.get('settled') else '未完成',
            done=report.get('done'),
            total=report.get('done', 0) + sum(
                1 for j in report.get('jobs') or [] if j.get('status') != 'succeeded'),
            settled=report.get('settled'),
            all_succeeded=report.get('all_succeeded'),
            backend=manifest.get('backend') or 'local',
            protocol=manifest.get('protocol') or '',
            limit_reached=report.get('limit_reached'),
        ),
        tasks=tasks,
        platforms=platforms,
        events=visible_events[-400:],
        scope=report.get('scope'),
        limits=report.get('limitation') or report.get('scope') or '',
        files=doc.get('files') or [],
    )


from workbench_sessions import SessionWorkbench


class Workbench(SessionWorkbench):
    def __init__(self):
        self.lock = threading.RLock()
        self.live_lock = threading.Lock()
        self.live = False
        self.stop_requested = False
        self.pending_replan = None
        self.process_error = None
        self.process = None
        self.current = None

    def start(self, data, desktop_input=None):
        if not isinstance(data, dict):
            raise ValueError('运行参数必须为对象')
        data = dict(data)
        if 'replay_edit' in data:
            if desktop_input is not None or 'edit' in data:
                raise ValueError('续算与新建输入不能同时提交')
            return self.start_replay(data)
        edit = data.pop('edit', None)
        config = validate_config(data)
        if edit is not None:
            if desktop_input is not None:
                raise ValueError('不能同时提供两种输入快照')
            from workbench_browser import edited_draft
            desktop_input = edited_draft(sys.modules[__name__], edit, config)
            config = desktop_input['request']
        if desktop_input is not None:
            from desktop_workflow import validate_draft
            desktop_input, _ = validate_draft(sys.modules[__name__], desktop_input)
            if desktop_input["request"] != config:
                raise ValueError("运行参数与输入快照不一致")
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError('已有仿真正在运行，请等待完成')
            run_id = datetime.now().strftime('workbench_%Y%m%d_%H%M%S_%f')
            out = OUTPUTS / run_id
            out.mkdir(parents=True, exist_ok=False)
            (out / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            if desktop_input is not None:
                (out / 'desktop_input.json').write_text(json.dumps(desktop_input, ensure_ascii=False, indent=2), encoding='utf-8')
            with (out / 'worker.log').open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
                                                 '--worker', str(out)], stdout=log, stderr=log,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.current = run_id
            self.live = bool(config.get('live'))
            self.stop_requested = False
            self.process_error = None
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
        for out in sorted((entry for root in run_roots() for entry in root.iterdir()), key=lambda p: p.name, reverse=True):
            if not out.is_dir() or not (out / 'report.json').is_file():
                continue
            if not (out / 'trace.jsonl').is_file():
                continue
            if out.name.startswith('workbench_') and not (out / 'report.json').is_file():
                continue
            # Do not expose a partial run before the subprocess finishes exporting.
            if self.process and out.name == self.current and self.process.poll() is None:
                continue
            try:
                r = read_json(out / 'report.json')
                if self._scenario_label(out) not in ALL_SCENARIOS or r.get('motion') != 'real':
                    continue
                metrics = r.get('plan_objective_metrics') or plan_objective_metrics(out)
                runs.append(dict(id=out.name, done=r['done'], total=len(r['jobs']),
                                 scenario=self._scenario_label(out),
                                 mode=r.get('mode', 'normal'), motion=r.get('motion', 'real'),
                                 avoid=r.get('avoid', False), behavior=r.get('behavior', False),
                                 behavior_details=r.get('behavior_details', False),
                                 objective=r.get('objective'),
                                 plan_objective=r.get('plan_objective'),
                                 plan_metrics_source=r.get('plan_metrics_source', 'legacy_static_unbound'),
                                 comparison_complete=r.get('comparison_complete'),
                                 comparison_scope=r.get('comparison_scope'),
                                 makespan=metrics.get('makespan_s'),
                                 plan_energy=metrics.get('total_energy'),
                                 exposure=metrics.get('total_exposure'),
                                 execution_exposure=r.get('execution_exposure'),
                                 execution_detection_probability=r.get(
                                     'execution_detection_probability'),
                                 detection_probability=metrics.get('detection_probability'),
                                 planner=r.get('planner', 'base_v2'),
                                 end=r.get('simulated_until_s'), energy=r.get('used_energy'),
                                 settled=r.get('settled'), retries=r.get('retries', 0),
                                 timeouts=r.get('timeouts', 0)))
            except (OSError, ValueError, KeyError):
                continue
        # Prefer a current multi-task relay run, otherwise the latest current run.
        default_run = next((r['id'] for r in runs if int(r.get('total') or 0) >= 2), None)
        default_run = default_run or (runs[0]['id'] if runs else None)
        return dict(service='planning-middle-workbench/v1',
                    app_root=str(ROOT.resolve()), outputs_root=str(OUTPUTS.resolve()),
                    version=WORKBENCH_VERSION,
                    features=dict(planner=True,
                                  containment=True,
                                  hold=True,
                                  interop_scenario='interop_containment',
                                  plan_schema='0.3',
                                  desktop_bridge=True, desktop_scene_navigation=True,
                                  static_task_editor_v2=True, dynamic_task_editor=True, replay_resume=True,
                                  live_stop=True, process_status=True,
                                  desktop_workflow=True,
                                  desktop_workflow_version=17,
                                  task_boundary_validation=True,
                                  urban_benchmark_scenarios=True,
                                  map_selection=True,
                                  randomized_task_points=True),
                    default_run=default_run,
                    scenarios=ALL_SCENARIOS,
                    maps=__import__(
                        'workbench_maps', fromlist=['map_catalog']
                    ).map_catalog(),
                    templates=__import__('workbench_browser', fromlist=['templates']).templates(sys.modules[__name__]),
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
                if path == '/api/process':
                    return self.send(dict(process=app.status()))
                if path.startswith('/api/live/'):
                    parts = path.split('/')
                    query = parse_qs(urlparse(self.path).query)
                    if len(parts) == 5 and parts[4] == 'view':
                        return self.send(app.live_view(parts[3], query.get('cursor',[None])[0]))
                    if len(parts) == 4:
                        return self.send(app.live_state(parts[3]))
                    raise ValueError('实时接口不存在')
                if path == '/api/editor' or path.startswith('/api/editor/'):
                    from workbench_browser import configuration
                    query = parse_qs(urlparse(self.path).query)
                    run_id = path[len('/api/editor/'):] if path.startswith('/api/editor/') else None
                    if run_id and 'at_s' in query:
                        from workbench_replay_editor import playback_config
                        return self.send(playback_config(run_path(run_id), query['at_s'][0]))
                    return self.send(configuration(sys.modules[__name__],
                        query.get('preset', ['interop_containment'])[0], run_id,
                        query.get('map_id', [None])[0]))
                if path == '/api/maps':
                    from workbench_maps import map_catalog
                    return self.send(map_catalog())
                if path.startswith('/api/maps/'):
                    from workbench_maps import map_document
                    return self.send(map_document(path[len('/api/maps/'):]))
                if path == '/api/desktop/storage':
                    from desktop_workflow import storage_info
                    return self.send(storage_info(sys.modules[__name__]))
                if path == '/api/desktop/demo':
                    from desktop_workflow import find_demo
                    query = parse_qs(urlparse(self.path).query)
                    return self.send(find_demo(sys.modules[__name__], query.get('scenario', ['interop_containment'])[0]))
                if path == '/api/desktop/config':
                    from desktop_workflow import get_config
                    query = parse_qs(urlparse(self.path).query)
                    return self.send(get_config(sys.modules[__name__], query.get('scenario', ['interop_containment'])[0], query.get('run', [None])[0]))
                if path.startswith('/api/desktop/events/'):
                    document = load_run(path.split('/')[-1])
                    return self.send(dict(id=document['id'], events=(document.get('replay') or {}).get('events') or []))
                if path.startswith('/api/desktop/details/'):
                    from desktop_workflow import run_details
                    return self.send(run_details(sys.modules[__name__], path.split('/')[-1]))
                if path.startswith('/api/desktop/run/'):
                    query = parse_qs(urlparse(self.path).query)
                    at_s = None
                    if query.get('t'):
                        try:
                            at_s = float(query['t'][0])
                        except (TypeError, ValueError):
                            at_s = None
                    return self.send(desktop_run(path.split('/')[-1], at_s))
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
                    # Historical plans get a derived export without rewriting their evidence.
                    if not file.is_file() and parts[3] in ('agent_tasks.md', 'agent_tasks.csv', 'agent_tasks.json'):
                        from interop.agent_tasks import agent_artifact
                        data = load_run(parts[2]).get('agent_tasks')
                        if data is None:
                            raise FileNotFoundError()
                        return self.send(agent_artifact(data, parts[3]), content_type='text/plain; charset=utf-8')
                elif path == '/demos/behavior':
                    file = OUTPUTS / 'behavior_20261028_verify' / 'behavior_demo.html'
                    if not file.is_file():
                        file = OUTPUTS / 'behavior_demo' / 'behavior_demo.html'
                elif path == '/demos/schematic':
                    file = ROOT.parent / 'outputs' / '任务动态示意_20261027' / 'index.html'
                elif path in ('/', '/index.html', '/app.js', '/containment.js',
                              '/hold.js', '/task_details.js', '/styles.css',
                              '/workbench_ui.js', '/workbench_ui.css', '/map_import.js',
                              '/desktop_bridge.js', '/scene_navigation.js', '/replay_pose.js', '/config_editor.js', '/live_map_adapter.js', '/browser_integration.js', '/favicon.svg'):
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
            if not self.path.startswith('/api/live/') and self.path not in ('/api/editor/task-preview', '/api/runs', '/api/compare', '/api/desktop/validate',
                                 '/api/desktop/editor-metadata',
                                 '/api/desktop/editor-targets',
                                 '/api/desktop/editor-preview',
                                 '/api/desktop/runs', '/api/desktop/refresh-preset',
                                 '/api/desktop/delete', '/api/desktop/restore'):
                return self.send({'error': '接口不存在'}, code=404)
            try:
                limit = (1 << 20) if self.path.startswith(('/api/desktop/', '/api/editor/', '/api/live/')) or self.path == '/api/runs' else 4096
                if length < 1 or length > limit:
                    raise ValueError('请求大小无效')
                data = json.loads(body)
                if self.path.startswith('/api/live/'):
                    return self.send(app.live_command(self.path.split('/')[3], data))
                if self.path == '/api/editor/task-preview':
                    from desktop_workflow import preview_task
                    return self.send(preview_task(data))
                if self.path == '/api/desktop/editor-metadata':
                    from desktop_workflow import editor_metadata
                    if not isinstance(data, dict) or set(data) != {'message'}:
                        raise ValueError('编辑元数据请求必须只包含 message')
                    return self.send(editor_metadata(data.get('message')))
                if self.path == '/api/desktop/editor-targets':
                    from desktop_workflow import apply_editor_targets
                    if not isinstance(data, dict) or set(data) != {
                            'message', 'targets'}:
                        raise ValueError('目标写回请求必须只包含 message 和 targets')
                    return self.send(apply_editor_targets(
                        data.get('message'), data.get('targets')))
                if self.path == '/api/desktop/editor-preview':
                    from desktop_workflow import preview_task
                    return self.send(preview_task(data))
                if self.path == '/api/desktop/refresh-preset':
                    from desktop_workflow import refresh_legacy_preset
                    return self.send(refresh_legacy_preset(sys.modules[__name__], data))
                if self.path in ('/api/desktop/delete', '/api/desktop/restore'):
                    from desktop_workflow import move_record
                    return self.send(move_record(sys.modules[__name__], app, data, restore=self.path.endswith('/restore')))
                if self.path in ('/api/desktop/validate', '/api/desktop/runs'):
                    from desktop_workflow import validate_draft
                    draft, summary = validate_draft(sys.modules[__name__], data)
                    if self.path.endswith('/validate'):
                        return self.send(dict(valid=True, draft=draft, summary=summary))
                    return self.send(app.start(draft['request'], desktop_input=draft), code=202)
                if self.path == '/api/compare':
                    scenario = data.get('scenario')
                    if not isinstance(scenario, str):
                        raise ValueError('缺少场景')
                    return self.send(compare_objectives(scenario))
                self.send(app.start(data), code=202)
            except FileNotFoundError as exc:
                self.send({'error': str(exc)}, code=404)
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
    ports = [args.port] if args.port == 0 else [args.port + i for i in range(32)]
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
