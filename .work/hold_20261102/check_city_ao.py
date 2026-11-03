# -*- coding: utf-8 -*-
"""把 T-SEC / T-HLD 样例搬到"十字路口建筑区"前的可行性检查。

检查项（都是真踩过的坑）：
  1. 任务点/阵位/门哨/集结地是否落在禁入区或建筑里；
  2. 每台平台从集结地到各自位置能否规划出路径；
  3. 用跟车器真跑一遍这些腿，确认不会在建筑缝隙里原地打转。
"""
import json
import math
import sys

sys.path.insert(0, 'planning_middle_demo')

import city_nav
from interop.message import parse_message
from interop.runtime import nav_from_scenario

SCEN = 'planning_middle_demo/interop/scenarios/'


def load(name):
    return (json.load(open(SCEN + name + '.message.json', encoding='utf-8')),
            json.load(open(SCEN + name + '.formation.json', encoding='utf-8')))


def _sim(nav, start, goal, max_ticks=5000):
    try:
        plan = nav.plan(start, goal)
    except Exception as exc:                       # noqa: BLE001
        return dict(ok=False, reason='plan:%s' % exc)
    follower = city_nav.PathFollower(max_linear=8.0, lookahead=2.4,
                                     waypoint_tol=1.28)
    state = follower.reset()
    x, y, yaw = float(start[0]), float(start[1]), 0.0
    for k in range(max_ticks):
        v, w, state = follower.step((x, y, yaw), plan['path'], state, nav)
        if state.done:
            return dict(ok=True, ticks=k, length=round(plan['length'], 1))
        if state.replan:
            state.replan = False
            yaw += w * 0.1
            try:
                plan = nav.plan((x, y), plan['path'][-1])
                state = follower.reset()
            except Exception:                      # noqa: BLE001
                return dict(ok=False, reason='replan', at=[round(x, 1), round(y, 1)])
            continue
        yaw += w * 0.1
        x += v * math.cos(yaw) * 0.1
        y += v * math.sin(yaw) * 0.1
    return dict(ok=False, reason='stuck', at=[round(x, 1), round(y, 1)])


def _free(nav, point, radius=1.6):
    return bool(nav.free((float(point[0]), float(point[1])), radius))


def check_sec(area, gates, assembly, unit_starts):
    msg, form = load('area_containment')
    task = msg['tasks'][0]
    task['target'] = {'defense_area': area}
    task['params']['gates'] = gates
    task['params']['assembly_point'] = assembly
    for unit in form['formation']['units']:
        uid = unit['unit_id']
        if uid in unit_starts:
            unit['position'] = {'x': unit_starts[uid][0], 'y': unit_starts[uid][1]}
    scenario = parse_message(msg, form)
    nav = nav_from_scenario(scenario)
    points = [('gates.' + g['gate_id'], g['point']) for g in gates]
    points += [('area.' + str(i), p) for i, p in enumerate(area)]
    bad = [(name, p) for name, p in points if not _free(nav, p)]
    print('[SEC] free check:', 'OK' if not bad else bad)
    # 用规划出来的占位点（行为层几何）检查可达性
    from behaviors import ContainmentBehavior
    job = dict(job_id='T1', type='blockade', pos=area[0])
    params = dict(task['params'])
    params['area'] = area
    params['duration_s'] = 60
    behavior = ContainmentBehavior(job, nav, ['rover_1', 'rover_2', 'rover_21',
                                              'rover_22', 'rover_31', 'rover_41'],
                                   params)
    legs = []
    for pid, post in behavior.posts.items():
        start = unit_starts.get('U' + str(list(behavior.posts).index(pid) + 1))
        if start:
            legs.append(('进场→%s' % behavior.roles.get(pid), start, post))
    bad_legs = 0
    for name, start, goal in legs:
        result = _sim(nav, start, goal)
        if not result['ok']:
            bad_legs += 1
        print('  %-4s %-16s %s -> (%.1f, %.1f) %s'
              % ('OK' if result['ok'] else 'BAD', name, start, goal[0], goal[1],
                 result))
    return bad_legs


def check_hld(key, positions, assembly, unit_starts, withdraw):
    msg, form = load('key_point_hold')
    task = msg['tasks'][0]
    task['target'] = {'key_point': key}
    task['params']['positions'] = positions
    task['params']['assembly_point'] = assembly
    task['params']['withdraw']['route'] = [key, withdraw]
    for unit in form['formation']['units']:
        uid = unit['unit_id']
        if uid in unit_starts:
            unit['position'] = {'x': unit_starts[uid][0], 'y': unit_starts[uid][1]}
    scenario = parse_message(msg, form)
    nav = nav_from_scenario(scenario)
    pts = [('key', key)] + [('pos.' + p['id'], p['point']) for p in positions]
    bad = [(name, p) for name, p in pts if not _free(nav, p)]
    print('[HLD] free check:', 'OK' if not bad else bad)
    legs = []
    for index, position in enumerate(positions):
        uid = 'U%d' % (index + 1)
        start = unit_starts.get(uid)
        if start:
            legs.append(('进场%s→%s' % (uid, position['id']), start, position['point']))
        legs.append(('%s→撤离' % position['id'], position['point'], withdraw))
    legs.append(('预备队→P1', assembly, positions[0]['point']))
    bad_legs = 0
    for name, start, goal in legs:
        result = _sim(nav, start, goal)
        if not result['ok']:
            bad_legs += 1
        print('  %-4s %-18s %s -> %s %s'
              % ('OK' if result['ok'] else 'BAD', name, start, goal, result))
    return bad_legs


if __name__ == '__main__':
    # ---- 候选：小十字路口建筑区（asl_city 的 (-95,-145) 一带）----
    sec_area = [[-125, -115], [-65, -115], [-65, -175], [-125, -175]]
    sec_gates = [
        dict(gate_id='G-A', point=[-95, -115], width=14, direction=[0, -1]),
        dict(gate_id='G-B', point=[-65, -145], width=14, direction=[-1, 0]),
    ]
    sec_starts = {'U1': (-95, -60), 'U2': (-88, -62), 'U3': (-102, -62),
                  'U4': (-95, -55), 'U5': (-86, -56), 'U6': (-104, -56)}
    bad = check_sec(sec_area, sec_gates, [-95, -60], sec_starts)

    hld_key = [-95, -145]
    hld_positions = [
        dict(id='P1', point=[-95, -113], facing_deg=0, min_units=1),
        dict(id='P2', point=[-55, -145], facing_deg=90, min_units=1),
        dict(id='P3', point=[-95, -177], facing_deg=180, min_units=1),
        dict(id='P4', point=[-135, -145], facing_deg=270, min_units=1),
    ]
    hld_starts = {'U1': (-95, -60), 'U2': (-88, -62), 'U3': (-102, -62),
                  'U4': (-95, -55), 'U5': (-86, -56), 'U6': (-104, -56)}
    bad += check_hld(hld_key, hld_positions, [-95, -60], hld_starts, [-60, -80])
    print('bad legs total:', bad)
    raise SystemExit(0 if bad == 0 else 1)
