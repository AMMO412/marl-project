# -*- coding: utf-8 -*-
"""behavior_demo.py —— 规划下发 → 避障机动 → 到位执行行为的端到端演示。

流程（与真实对接的形状一致）：
  1. 用 planner_v2 生成指派（谁去哪个作业点），与 run_demo_v2 同一套规划器；
  2. 每台平台按 city_nav 的 A* 路径绕开真实建筑轮廓机动到位；
  3. 到位后由 behaviors.py 的对应状态机接管：巡逻环路 / 封控拦截 /
     协同侦察 / 突击四阶段 / 坚守轮换；
  4. 产出 behavior_trace.json 与自包含 behavior_demo.html（可离线打开）。

作业按计划开工顺序**串行**重放：这样同一台平台跨作业的先后关系看得清，
也不会出现两台平台同时被派给两个作业。计划里的 start/end 原样保留在
产物里，便于对照"计划时刻 vs 行为实际耗时"。

用法：
  py -3.14 behavior_demo.py
  py -3.14 behavior_demo.py --scenario scenarios/simple_city.json --out outputs/behavior_demo
"""
import argparse
from datetime import datetime
import hashlib
import json
import sys
from pathlib import Path

from behaviors import make_behavior
from behavior_runtime import BehaviorRunner
from city_nav import build_nav
from contracts_v2 import build_jobs, build_platforms
import planner_v2

ROOT = Path(__file__).resolve().parent

TYPE_COLOR = {'patrol': '#2563eb', 'blockade': '#dc2626', 'recon': '#7c3aed',
              'assault': '#ea580c', 'hold': '#15803d'}
TYPE_LABEL = {'patrol': '巡逻警戒', 'blockade': '区域封控', 'recon': '协同侦察',
              'assault': '机动突击', 'hold': '要点坚守'}


def build_demo(scenario, max_steps=200, H=200, scenario_path=None):
    """返回 (data, stats)；data 直接喂给可视化模板。"""
    H = int(scenario.get('H', H))
    nav, loaded = build_nav(scenario)
    platforms = build_platforms(scenario)
    jobs = build_jobs(scenario)
    plan, plan_events = planner_v2.plan(platforms, jobs, now=0, H=H)
    by_id = {j['job_id']: j for j in scenario['jobs']}
    pos = {}
    for p in scenario['platforms']:
        pid = 'rover_%02d' % p['robot_no']
        point, offset = nav.nearest_free(p['pos'])
        pos[pid] = [point[0], point[1], 0.0]
        if offset:
            loaded.setdefault('snapped', []).append(
                dict(pid=pid, raw=p['pos'], snapped=[round(v, 2) for v in point],
                     offset=round(offset, 2)))

    results, cursor = [], 0.0
    assignments = sorted(plan.assignments, key=lambda a: (a.start, a.job_id))
    for a in assignments:
        job = by_id[a.job_id]
        behavior = make_behavior(job, nav, a.pids)
        starts = {pid: list(pos[pid]) for pid in a.pids}
        speeds = {p.pid: p.speed for p in platforms}
        runner = BehaviorRunner(nav, behavior, starts,
                                speeds={pid: speeds[pid] for pid in a.pids
                                        if pid in speeds})
        result = runner.run(max_steps=max_steps)
        for sample in result['samples']:
            sample['t'] = round(sample['t'] + cursor, 2)
        for event in result['events']:
            event['t'] = round(event['t'] + cursor, 2)
        for pid, agent in runner.agents.items():
            pos[pid] = [agent.x, agent.y, agent.yaw]
        distance_travelled = sum(r['length'] for r in result['routes'])
        straight_total = sum(r['straight'] for r in result['routes'])
        # 每条平台的第一段路径 = "从当前位到作业区的接近路径"，单独统计，
        # 避免把行为内部的微调路径混进绕行率里。
        seen, approach = set(), []
        for route in result['routes']:
            if route['pid'] not in seen:
                seen.add(route['pid'])
                approach.append(route)
        result.update(
            job_id=a.job_id, type=job['type'],
            label=TYPE_LABEL.get(job['type'], job['type']),
            color=TYPE_COLOR.get(job['type'], '#64748b'),
            pids=list(a.pids), plan_start=a.start, plan_end=a.end,
            t0=round(cursor, 2),
            t1=round(cursor + result['duration'], 2),
            distance=round(distance_travelled, 2),
            straight_distance=round(straight_total, 2),
            detour_ratio=round(distance_travelled / max(straight_total, 1e-6), 3),
            routes_blocked=sum(1 for r in result['routes']
                               if not r['straight_line_ok']),
            approach=approach,
            approach_blocked=sum(1 for r in approach
                                 if not r['straight_line_ok']),
            approach_length=round(sum(r['length'] for r in approach), 2),
            approach_straight=round(sum(r['straight'] for r in approach), 2))
        cursor += result['duration'] + 1.0
        results.append(result)

    stats = dict(
        jobs=len(results),
        all_done=all(r['phase'] == '完成' for r in results),
        blocked_routes=sum(r['routes_blocked'] for r in results),
        routes=sum(len(r['routes']) for r in results),
        approach=sum(len(r['approach']) for r in results),
        approach_blocked=sum(r['approach_blocked'] for r in results),
        obstacles=len(nav.obstacles),
        models=len({o['source_model'] for o in nav.obstacles}),
        missing_geometry=len(loaded['missing']),
        nominal_plan_end=max((a.end for a in plan.assignments), default=0),
        behavior_total_s=round(cursor, 1),
        snapped_spawns=len(loaded.get('snapped', [])),
    )
    scenario_rel = (str(Path(scenario_path).resolve().relative_to(ROOT))
                    if scenario_path else 'scenarios/simple_city.json')
    source_file = Path(scenario_path) if scenario_path else ROOT / 'scenarios/simple_city.json'
    sdf_mode = bool(scenario.get('_meta', {}).get('sdf'))
    limitation = [
        '障碍来自 %s：%d 个盒体、%d 个模型；静态盒体以外的地面/道路顶面'
        '（≤0.2m）不计为障碍。'
        % (loaded['provenance']['world'], len(nav.obstacles),
           len({o['source_model'] for o in nav.obstacles})),
        '这是已知静态地图上的避障（膨胀栅格 A* + 路径跟随 + 前向安全投影），'
        '不是 SLAM，也不是动态避障；动态障碍只会触发局部重规划。',
        '规划速度取自 fleet.PLANNING_PARAMS（开发方暂定示例值），与 SDF 声明的'
        '0.5 m/s 限速未对齐；时间是场景步，不是实测秒。',
        '作业按计划开工顺序串行重放，t0/t1 是重放时刻，非并行仿真时刻。',
        'planner 的 plan_start/plan_end 只按行驶与工作量估算，不含集结等待、'
        '评估时延和撤离；时序以行为 t0/t1 与阶段记录为准。',
    ]
    if sdf_mode:
        limitation.insert(1,
                          '9 处外部引用（4 住宅、2 办公楼、2 湿地、1 山地）缺几何，'
                          '未纳入；本图不能作为完整环境无碰撞证明。')
        limitation.append('机动突击的效果由演示用外部评估桩判定，'
                          '不是真实战损评估接口。')
    data = dict(
        title='五类任务到位行为 · 带避障的代码级演示',
        generated_at=datetime.now().astimezone().isoformat(),
        source=dict(scenario=scenario_rel,
                    scenario_sha256=hashlib.sha256(
                        source_file.read_bytes()).hexdigest(),
                    world=loaded['provenance']['world'],
                    transform=loaded['provenance']['transform']),
        bounds=nav.bounds, obstacles=nav.obstacles,
        missing=loaded['missing'], snapped=loaded.get('snapped', []),
        radius=nav.radius, resolution=nav.resolution,
        jobs=results, total=round(cursor, 2), stats=stats,
        plan_events=[dict(e) for e in plan_events],
        limitation=limitation)
    return data, stats


def render(data, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False,
                         allow_nan=False).replace('<', '\\u003c')
    (out_dir / 'behavior_trace.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    template = (ROOT / 'behavior_demo.html').read_text(encoding='utf-8')
    page = template.replace('__DATA__', payload)
    (out_dir / 'behavior_demo.html').write_text(page, encoding='utf-8')
    return out_dir / 'behavior_demo.html'


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path,
                        default=ROOT / 'scenarios/simple_city.json')
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'outputs' / datetime.now().strftime(
                            'behavior_%Y%m%d_%H%M%S'))
    parser.add_argument('--max-steps', type=int, default=None)
    args = parser.parse_args(argv)
    scenario = json.loads(args.scenario.read_text(encoding='utf-8-sig'))
    max_steps = (args.max_steps
                 or int(scenario.get('_meta', {}).get('demo_max_steps', 200)))
    data, stats = build_demo(scenario, max_steps=max_steps,
                             scenario_path=args.scenario)
    page = render(data, args.out)
    print('作业 %d 个，全部完成 %s；绕行路径 %d/%d 条直线被建筑阻挡；'
          '障碍 %d 个；行为总时长 %.0f s'
          % (stats['jobs'], stats['all_done'], stats['blocked_routes'],
             stats['routes'], stats['obstacles'], stats['behavior_total_s']))
    print('产物：%s' % page.resolve())
    return 0 if stats['all_done'] else 2


if __name__ == '__main__':
    sys.exit(main())
