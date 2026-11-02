# -*- coding: utf-8 -*-
"""检查 T-HLD 样例里每一段实际会走的机动是否会被跟车器卡住。

踩过的坑（任务书 §6.6）：高速平台沿 A* 生成的细密折线走时，可能在窄缝里
原地打转且不再恢复。样例几何必须保证每段"阵地↔阵地/预备队/撤离点"都能走通，
否则时间线上会出现"接替超时"这类假故障。
"""
import json
import math
import sys

sys.path.insert(0, 'planning_middle_demo')

import city_nav
from interop.message import parse_message
from interop.runtime import nav_from_scenario


def _sim(nav, start, goal, max_ticks=4000):
    plan = nav.plan(start, goal)
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
                return dict(ok=False, reason='replan_failed',
                            at=[round(x, 1), round(y, 1)])
            continue
        yaw += w * 0.1
        x += v * math.cos(yaw) * 0.1
        y += v * math.sin(yaw) * 0.1
    return dict(ok=False, reason='stuck', at=[round(x, 1), round(y, 1)])


def main():
    message = json.load(open('planning_middle_demo/interop/scenarios/'
                             'key_point_hold.message.json', encoding='utf-8'))
    formation = json.load(open('planning_middle_demo/interop/scenarios/'
                               'key_point_hold.formation.json',
                               encoding='utf-8'))
    scenario = parse_message(message, formation)
    nav = nav_from_scenario(scenario)
    params = scenario.tasks[0].params
    from interop.templates import hld_stations
    stations = hld_stations(scenario.tasks[0])
    posts = [(p['id'], tuple(p['point'])) for p in params['positions']]
    reserve = tuple(stations['reserve'])
    withdraw = tuple(params['withdraw']['route'][-1])
    starts = [(u['unit_id'], (u['position']['x'], u['position']['y']))
              for u in formation['formation']['units']]

    legs = []
    for unit, start in starts:
        legs.append(('进场 %s→P1' % unit, start, posts[0][1]))
    for name, point in posts:
        legs.append(('预备队→%s' % name, reserve, point))
        legs.append(('%s→预备队' % name, point, reserve))
        legs.append(('%s→撤离点' % name, point, withdraw))
        legs.append(('要点→%s' % name, tuple(params.get('key_point') or
                                            (0, 40)), point))

    bad = 0
    for name, start, goal in legs:
        result = _sim(nav, start, goal)
        flag = 'OK ' if result['ok'] else 'BAD'
        if not result['ok']:
            bad += 1
        print('%-4s %-22s %s -> %s  %s' % (flag, name, start, goal, result))
    print('bad legs:', bad, '/', len(legs))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
