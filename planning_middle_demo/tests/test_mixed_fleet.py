# -*- coding: utf-8 -*-
"""多类型兵力包与 SDF 初始状态测试（2026-10-29 新增能力）。

覆盖四件事：
  1. SDF 提取出的初始位姿/三维尺寸与场景起点一致（规划初始状态可追溯）；
  2. 角色级载荷校核：支援组（侦察/评估）不被任务级 4.0 载荷挡在门外，
     突击组仍按 4.0 卡；
  3. 空地面分流：空中平台越障直飞并爬升到巡航高度，地面平台走 A*；
  4. 辅助指标逐项可核验：毁伤（命中率/弹药/二次打击/我方损失）、
     夺占（控制时长/敌方反击/移交），不只报一个"成功"。
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import planner_v2
import sdf_state
from behavior_runtime import BehaviorRunner
from behaviors import make_behavior
from city_nav import build_nav
from contracts_v2 import build_jobs, build_platforms


def load(name):
    return json.loads((ROOT / 'scenarios' / name).read_text(encoding='utf-8'))


def run_teleport(behavior, starts, max_steps=200):
    """行为层单测：每步把平台瞬移到目标点，只验状态机与指标。"""
    poses = {pid: (p[0], p[1], 0.0) for pid, p in starts.items()}
    done = False
    for t in range(max_steps):
        out = behavior.step(poses, float(t), 1.0)
        for pid, target in (out['targets'] or {}).items():
            poses[pid] = (target[0], target[1], 0.0)
        if out['done']:
            done = True
            break
    return done


class SdfStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = sdf_state.read_state()

    def test_fifty_platforms_four_kinds(self):
        self.assertEqual(self.state['counts']['robots'], 50)
        kinds = {k: v['count'] for k, v in self.state['fleet'].items()}
        self.assertEqual(kinds, {'UGV': 20, 'TANK': 10, 'PLANE': 10, 'WING': 10})
        self.assertEqual(len(self.state['robots']), 50)

    def test_dimensions_come_from_collision_geometry(self):
        ugv = next(r for r in self.state['robots'] if r['no'] == 1)
        self.assertEqual(ugv['envelope_size'], [2.011, 1.85, 0.875])
        self.assertAlmostEqual(ugv['envelope_radius'], 1.366, places=3)
        self.assertEqual(ugv['wheel_radius'], 0.3)
        self.assertEqual(ugv['wheel_separation'], 1.25)
        plane = next(r for r in self.state['robots'] if r['no'] == 31)
        self.assertEqual(plane['envelope_size'], [1.0, 2.0, 0.2])
        self.assertTrue(plane['can_climb'])
        self.assertFalse(ugv['can_climb'])

    def test_city_cluster_is_resolved_not_invented(self):
        buildings = [o for o in self.state['obstacles']
                     if o['id'].startswith('env_city_')]
        self.assertEqual(len(buildings), 6)
        office = next(o for o in buildings if 'office_01' in o['id'])
        self.assertAlmostEqual(office['size'][0], 17.697, places=2)
        self.assertEqual(len(self.state['roads']), 5)
        # 外部模型（湿地/山体）没有本地几何时必须列 missing，不臆造
        missing = {m['name'] for m in self.state['missing']}
        self.assertIn('env_yosemite', missing)

    def test_scenario_starts_match_sdf(self):
        scene = load('asl_city.json')
        by_no = {r['no']: r for r in self.state['robots']}
        for item in scene['platforms']:
            self.assertEqual(item['pos'], by_no[item['robot_no']]['start'],
                             '场景起点必须来自 SDF 初始位姿')


class RolePayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = load('asl_city.json')
        cls.plats = {p.pid: p for p in build_platforms(cls.scene)}
        cls.job = build_jobs(cls.scene)[0]
        planner_v2.BEHAVIOR_MODE = True

    @classmethod
    def tearDownClass(cls):
        planner_v2.BEHAVIOR_MODE = False

    def test_support_role_relaxes_payload_only_for_support_pids(self):
        wing = self.plats['rover_41']
        self.assertLess(wing.payload, 4.0)
        ok, _ = planner_v2.feasible(wing, self.job)
        self.assertTrue(ok, '支援组只带传感器，不应被突击载荷 4.0 挡下')
        # 把支援位换成别人后，飞翼按突击组 4.0 校核，必须被拒
        self.job.behavior = dict(self.job.behavior, scout_pid='rover_01',
                                 assessor_pid='rover_02')
        ok, reason = planner_v2.feasible(wing, self.job)
        self.assertFalse(ok)
        self.assertIn('载荷不足', reason)
        self.assertIn('突击组', reason)

    def test_assault_group_still_requires_battle_payload(self):
        from contracts_v2 import Platform
        light = Platform(pid='rover_99', robot_no=9, kind='UGV', pos=(0.0, 0.0),
                         speed=0.8, work_rate=1.0, battery=100.0, payload=1.0,
                         sensor='eo', can_climb=False, move_cost=0.3,
                         work_cost=1.0, ammo=0, pos_topic='/x')
        ok, reason = planner_v2.feasible(light, self.job)
        self.assertFalse(ok)
        self.assertIn('突击组需4.0', reason)


class AirGroundRunnerTests(unittest.TestCase):
    def test_air_direct_ground_astar_and_altitude(self):
        scene = load('asl_city.json')
        nav, _ = build_nav(scene)
        job = scene['jobs'][0]
        pids = ['rover_01', 'rover_31']
        behavior = make_behavior(job, nav, pids)
        starts = {'rover_01': (0.0, -22.5, 0.0), 'rover_31': (-15.0, -22.5, 0.0)}
        caps = {'rover_01': dict(kind='UGV', can_climb=False, start_z=0.0,
                                 payload=6.0),
                'rover_31': dict(kind='PLANE', can_climb=True, start_z=6.0,
                                 payload=2.0)}
        runner = BehaviorRunner(nav, behavior, starts,
                                speeds={'rover_01': 0.8, 'rover_31': 2.0},
                                caps=caps)
        for _ in range(40):
            runner.step()
            if behavior.done:
                break
        modes = {(r['pid'], r['mode']) for r in runner.routes}
        self.assertIn(('rover_31', 'air_direct'), modes)
        self.assertIn(('rover_01', 'ground_astar'), modes)
        air = runner.agents['rover_31']
        self.assertGreater(air.z, 6.0)
        self.assertLessEqual(air.z, 30.0 + 1e-6)
        self.assertEqual(runner.agents['rover_01'].z, 0.0)

    def test_role_gate_blocks_unqualified_assault_member(self):
        scene = load('asl_city.json')
        nav, _ = build_nav(scene)
        job = scene['jobs'][0]
        behavior = make_behavior(job, nav, ['rover_01'])
        behavior.set_platform_caps({'rover_01': dict(kind='UGV',
                                                     can_climb=False, payload=1.0)})
        poses = {'rover_01': (0.0, -22.5, 0.0)}
        behavior.step(poses, 0.0, 1.0)
        self.assertTrue(behavior.done)
        self.assertEqual(behavior.status, '失败')
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'failed')
        self.assertEqual(result['termination'], 'role_infeasible')
        self.assertFalse(result['role_check']['ok'])


class AuxiliaryMetricTests(unittest.TestCase):
    def setUp(self):
        self.scene = load('asl_city.json')
        self.nav, _ = build_nav(self.scene)

    def _job(self, **behavior):
        params = dict(self.scene['jobs'][0]['_behavior'])
        params.update(behavior)
        return dict(job_id='T-AUX', type='assault', pos=[-95.0, -145.0],
                    _behavior=params)

    def test_damage_auxiliary_metrics_are_settled(self):
        behavior = make_behavior(
            self._job(effect_kind='damage', required_level=2.0,
                      damage_per_hit=1.0, fire_interval=1.0,
                      ammo_per_platform=2, scout_pid=None, assessor_pid=None,
                      withdraw=False, assessment_delay=1.0,
                      confirmation_deadline=30.0), self.nav,
            ['rover_01', 'rover_11'])
        starts = {pid: behavior.staging[i]
                  for i, pid in enumerate(behavior.pids)}
        self.assertTrue(run_teleport(behavior, starts, max_steps=80))
        rows = {r['key']: r for r in behavior.metrics['auxiliary']}
        self.assertIn('hit_rate', rows)
        self.assertEqual(rows['ammo_used']['value'], behavior.shots_fired)
        self.assertIn('restrikes', rows)
        self.assertEqual(rows['our_losses']['value'], 0)
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        self.assertTrue(result['auxiliary'])

    def test_losses_are_counted_when_member_reported_lost(self):
        behavior = make_behavior(
            self._job(effect_kind='damage', required_level=4.0,
                      fire_interval=2.0, scout_pid=None, assessor_pid=None,
                      confirmation_deadline=10.0), self.nav,
            ['rover_01', 'rover_11'])
        starts = {pid: behavior.staging[i]
                  for i, pid in enumerate(behavior.pids)}
        poses = {pid: (p[0], p[1], 0.0) for pid, p in starts.items()}
        behavior.step(poses, 0.0, 1.0)
        behavior.report_loss('rover_11', 1.0)
        behavior._fill_info_items()
        rows = {r['key']: r for r in behavior.metrics['auxiliary']}
        self.assertEqual(rows['our_losses']['value'], 1)
        self.assertEqual(rows['our_losses']['verdict'], '有损失')

    def test_seize_counts_counterattacks_and_handover(self):
        behavior = make_behavior(
            self._job(effect_kind='seize', required_control_s=6.0,
                      min_occupants=2, hold_required_s=4.0,
                      counterattack_interval=3.0, counterattack_break_s=0.0,
                      scout_pid=None, assessor_pid=None, assessment_delay=1.0,
                      confirmation_deadline=30.0), self.nav,
            ['rover_01', 'rover_11'])
        starts = {pid: behavior.staging[i]
                  for i, pid in enumerate(behavior.pids)}
        self.assertTrue(run_teleport(behavior, starts, max_steps=80))
        self.assertGreaterEqual(len(behavior.counterattacks), 1)
        self.assertIsNotNone(behavior.handover_t)
        rows = {r['key']: r for r in behavior.metrics['auxiliary']}
        self.assertEqual(rows['counterattacks']['value'],
                         len(behavior.counterattacks))
        self.assertEqual(rows['handover_t']['verdict'], '已移交')
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        self.assertIn('hold_after_handover',
                      {x['id'] for x in result['items']})


if __name__ == '__main__':
    unittest.main()
