# -*- coding: utf-8 -*-
"""端到端：规划指派 → 避障机动 → 到位行为；以及 MockFleet 的避障开关。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from behavior_demo import build_demo
from run_demo_v2 import simulate


def scenario():
    return json.loads((ROOT / 'scenarios/simple_city.json')
                      .read_text(encoding='utf-8'))


class BehaviorDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.stats = build_demo(scenario())

    def test_all_five_behaviors_complete(self):
        self.assertTrue(self.stats['all_done'])
        self.assertEqual({j['type'] for j in self.data['jobs']},
                         {'patrol', 'blockade', 'recon', 'assault', 'hold'})
        for job in self.data['jobs']:
            self.assertEqual(job['phase'], '完成', job['job_id'])

    def test_approach_paths_detour_around_buildings(self):
        self.assertGreater(self.data['stats']['approach_blocked'], 0)
        j6 = next(j for j in self.data['jobs'] if j['job_id'] == 'J6')
        self.assertEqual(j6['approach_blocked'], 1)
        self.assertGreater(j6['approach_length'], j6['approach_straight'] * 1.4)

    def test_behavior_specific_events_are_recorded(self):
        by_type = {j['type']: j for j in self.data['jobs']}
        kinds = {t: {e['kind'] for e in j['events']}
                 for t, j in by_type.items()}
        self.assertIn('cycle_completed', kinds['patrol'])
        self.assertIn('intercepted', kinds['blockade'])
        self.assertIn('report_sent', kinds['recon'])
        self.assertIn('confirmed', kinds['assault'])
        self.assertIn('handover_complete', kinds['hold'])


class MockFleetAvoidanceTests(unittest.TestCase):
    def test_real_motion_with_avoid_completes(self):
        report, trace = simulate(scenario(), 'normal', max_ticks=200,
                                 motion='real', avoid=True)
        self.assertTrue(report['all_succeeded'], report['jobs'])
        self.assertTrue(report['avoid'])
        self.assertEqual(report['active_commands'], 0)

    def test_avoid_flag_requires_opt_in(self):
        report, _ = simulate(scenario(), 'normal', max_ticks=200,
                             motion='real')
        self.assertFalse(report['avoid'])

    def test_simple_city_behavior_run_completes(self):
        """回归：行为模式下 simple_city 六作业必须全部收尾。

        rover_01 的出生点落在建筑膨胀圈内。行为层改为从原始位姿直接
        起跑（替身 approach 路线已删）后，若无出发点吸附，J6 巡逻会
        start_in_obstacle 后永久 0 进度，rover_01 一直占着不放，连带
        J5 每轮都因"成员忙"派不出去（2026-10-29 实际发生过）。
        """
        report, trace = simulate(scenario(), 'normal', max_ticks=350,
                                 motion='real', avoid=True, behavior=True)
        self.assertTrue(report['all_succeeded'],
                        [(j['job_id'], j['status']) for j in report['jobs']])
        self.assertTrue(report['settled'])
        stranded = [e['event'] for e in trace
                    if e['kind'] == 'behavior_event'
                    and e['event'].get('kind') == 'route_failed'
                    and e['event'].get('reason') == 'start_in_obstacle']
        self.assertEqual(stranded, [], '出生点在膨胀圈内未吸附，作业被搁浅')

    def test_assault_maneuver_is_not_teleported(self):
        """回归：行为层必须从下发时刻接管机动，不能等全员到位才起表。

        旧实现里替身先把平台开到集结位才建行为 runner，于是 `all_staged`
        落在行为时钟 t=0（工作台显示"机动集结 0 s / 全员到位 0 s"）。
        这里同时校验两件事：
          * `all_staged` 与受领时刻之间有真实的机动耗时；
          * 轨迹每步位移不超过平台速度，不存在瞬移。
        """
        report, trace = simulate(scenario(), 'normal', max_ticks=200,
                                 motion='real', avoid=True, behavior=True)
        events, poses, snaps = {}, {}, {}
        for line in trace:
            kind = line.get('kind')
            if kind == 'behavior_event':
                ev = line['event']
                if ev.get('kind') and ev['kind'] != 'behavior_detail':
                    events.setdefault(ev.get('job_id'), []).append(ev)
                    if ev['kind'] == 'start_snapped':
                        # 出发点吸附是显式记录的有界位置修正（出生点在
                        # 膨胀圈内）：吸附当步允许位移 = 吸附距离 + 正常行进
                        snaps.setdefault(ev['pid'], {})[line['sim_s']] = ev['offset']
            elif kind == 'feedback_applied':
                ev = line['event']
                poses.setdefault(ev['worker_id'], []).append(
                    (line['sim_s'], ev['pos']))
        assault = [j for j in report['jobs'] if j['jtype'] == 'assault']
        self.assertTrue(assault)
        for job in assault:
            jid = job['job_id']
            kinds = {e['kind']: e for e in events.get(jid, [])}
            self.assertIn('all_staged', kinds, jid)
            self.assertIn('command_received', kinds, jid)
            maneuver = kinds['all_staged']['t'] - kinds['command_received']['t']
            self.assertGreater(maneuver, 5.0, '%s 机动只用了 %.1f s' % (jid, maneuver))
        # 逐拍位移检查：反馈里相邻两步的位姿差不超过平台速度，没有瞬移
        # （出发点吸附当步的限值 = 速度 + 显式记录的吸附距离）
        worst, worst_pid, worst_raw = 0.0, None, 0.0   # worst = 最大超限量
        for pid, rows in poses.items():
            prev = None
            for sim_s, pos in rows:
                if prev is not None and sim_s > prev[0]:
                    gap = sim_s - prev[0]
                    step_len = ((pos[0] - prev[1][0]) ** 2
                                + (pos[1] - prev[1][1]) ** 2) ** 0.5
                    limit = 1.2
                    for snap_s, offset in snaps.get(pid, {}).items():
                        if prev[0] <= snap_s <= sim_s:
                            # 该步内发生出发点吸附：扣除显式记录的吸附距离
                            limit += offset
                    excess = step_len / gap - limit
                    if excess > worst:
                        worst, worst_pid, worst_raw = excess, pid, step_len / gap
                prev = (sim_s, pos)
        self.assertLessEqual(
            worst, 0.0,
            '%s 出现超速位移 %.2f m/s（超限 %.2f）' % (worst_pid, worst_raw, worst))


class EnduranceGateTests(unittest.TestCase):
    """续航闸门：行为段的集结/区内机动/撤离里程必须进入规划估算。

    之前规划期只算"到作业点"的直线距离，而行为层按实际行程记电，于是
    本场景 16 台中有 15 台跑到一半电量归零（t≈318–364 s），轨迹里全是
    battery=0 却仍在突进。下面三条分别校验：里程口径、闸门拒绝、闸门放行。
    """

    def setUp(self):
        import planner_v2
        from contracts_v2 import build_jobs, build_platforms
        self.pl = planner_v2
        self.scene = json.loads((ROOT / 'scenarios/asl_city.json')
                                .read_text(encoding='utf-8'))
        self.plats = build_platforms(self.scene)
        self.job = build_jobs(self.scene)[0]
        self.pl.BEHAVIOR_MODE = True

    def tearDown(self):
        self.pl.BEHAVIOR_MODE = False

    def test_mileage_includes_staging_and_withdraw(self):
        """全程里程必须大于"到作业点"的直线距离，且含撤离返程。"""
        p = self.plats[0]
        miles = self.pl._behavior_mileage(p, self.job)
        direct = ((p.pos[0] - self.job.pos[0]) ** 2
                  + (p.pos[1] - self.job.pos[1]) ** 2) ** 0.5
        self.assertGreater(miles, direct)
        # 去掉撤离段应当正好少了"目标→撤离点 + 撤离环"那一段
        no_retreat = dict(self.job.behavior, withdraw=False)
        self.job.behavior = no_retreat
        self.assertLess(self.pl._behavior_mileage(p, self.job),
                        miles - 20.0, '撤离返程未计入全程里程')

    def test_far_staging_is_rejected_by_gate(self):
        """旧几何（集结在办公楼东侧、撤离返程 90 m）必须被续航闸门拒收。"""
        self.job.behavior = dict(self.job.behavior,
                                 staging_center=[-5.0, -145.0],
                                 withdraw_point=[-15.0, -100.0],
                                 withdraw_ring=6.0)
        p = self.plats[0]
        ok, reason = self.pl.feasible(p, self.job)
        self.assertFalse(ok, '全程 300 m 超过 250 m 续航，闸门却放行了')
        self.assertIn('全程', reason)

    def test_asl_city_all_platforms_pass(self):
        """当前几何下 16 台都应在续航包线内，否则 crew=16 会组不起来。"""
        need = [self.pl._energy_need(p, self.job) for p in self.plats]
        self.assertLess(max(need), self.plats[0].battery,
                        '最远一台需电 %.1f > 电池 %.0f'
                        % (max(need), self.plats[0].battery))
        for p in self.plats:
            ok, reason = self.pl.feasible(p, self.job)
            self.assertTrue(ok, '%s 被拒：%s' % (p.pid, reason))


if __name__ == '__main__':
    unittest.main()
