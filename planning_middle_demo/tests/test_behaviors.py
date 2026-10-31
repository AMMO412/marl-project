# -*- coding: utf-8 -*-
"""五类到位行为测试：用"瞬移执行"把决策与运动解耦，只验状态机语义。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from behaviors import make_behavior
from city_nav import build_nav


def scenario():
    return json.loads((ROOT / 'scenarios/simple_city.json')
                      .read_text(encoding='utf-8'))


def run(behavior, starts, max_steps=300):
    """每个仿真步：行为给目标，平台瞬移到目标。用于验证阶段推进。"""
    poses = {pid: (p[0], p[1], 0.0) for pid, p in starts.items()}
    done = False
    for t in range(max_steps):
        out = behavior.step(poses, float(t), 1.0)
        for pid, target in (out['targets'] or {}).items():
            poses[pid] = (target[0], target[1], 0.0)
        if out['done']:
            done = True
            break
    return done, poses


class BehaviorFactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = scenario()
        cls.nav, _ = build_nav(cls.scene)
        cls.jobs = {j['job_id']: j for j in cls.scene['jobs']}

    def test_five_types_dispatch_to_expected_state_machine(self):
        kinds = set()
        for job in self.jobs.values():
            behavior = make_behavior(job, self.nav, ['rover_21'])
            self.assertEqual(behavior.kind, job['type'])
            kinds.add(behavior.kind)
        self.assertEqual(kinds, {'patrol', 'blockade', 'recon',
                                 'assault', 'hold'})

    def test_site_snapped_out_of_building(self):
        behavior = make_behavior(self.jobs['J4'], self.nav, ['rover_21'])
        self.assertTrue(self.nav.free(behavior.site))
        self.assertGreater(behavior.site_snap, 0)


class PatrolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = scenario()
        cls.nav, _ = build_nav(cls.scene)
        job = next(j for j in cls.scene['jobs'] if j['job_id'] == 'J6')
        cls.behavior = make_behavior(job, cls.nav, ['rover_01'])
        cls.done, _ = run(cls.behavior, {'rover_01': cls.behavior.loop[0]})

    def test_closed_loop_and_checkpoints(self):
        self.assertTrue(self.done)
        self.assertGreaterEqual(len(self.behavior.loop), 3)
        self.assertGreaterEqual(self.behavior.metrics['checkpoints'], 3)

    def test_revisit_interval_recorded(self):
        self.assertGreater(self.behavior.metrics.get('revisit_s', 0), 0)
        self.assertEqual(self.behavior.cycles['rover_01'], 3)
        visited = [e for e in self.behavior.visits['rover_01']]
        self.assertGreaterEqual(len(visited), 3 * len(self.behavior.loop) - 1)


class BlockadeTests(unittest.TestCase):
    def test_intruder_detected_and_intercepted(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J2')
        behavior = make_behavior(job, nav, ['rover_21', 'rover_22', 'rover_04'])
        starts = {pid: behavior.posts[i] for i, pid in enumerate(behavior.pids)}
        done, _ = run(behavior, starts, max_steps=120)
        self.assertTrue(done)
        self.assertTrue(behavior.triggered)
        self.assertTrue(behavior.intercepted)
        self.assertIn('intercept_t', behavior.metrics)
        kinds = {e['kind'] for e in behavior.history}
        self.assertIn('intrusion_detected', kinds)
        self.assertIn('intercepted', kinds)


class ReconTests(unittest.TestCase):
    def test_shared_map_reaches_coverage_target(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J3')
        behavior = make_behavior(job, nav, ['rover_41', 'rover_32'])
        done, _ = run(behavior, {'rover_41': (43.4, 40.07),
                                 'rover_32': (47.95, 49.7)}, max_steps=300)
        self.assertTrue(done)
        coverage = behavior.metrics.get('coverage', 0)
        self.assertGreaterEqual(coverage, 0.8)
        kinds = {e['kind'] for e in behavior.history}
        self.assertIn('map_shared', kinds)
        self.assertIn('report_sent', kinds)


class AssaultTests(unittest.TestCase):
    def test_phase_order_and_confirmation(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
        pids = ['rover_21', 'rover_22', 'rover_04', 'rover_02']
        behavior = make_behavior(job, nav, pids)
        starts = {pid: behavior.staging[i] for i, pid in enumerate(pids)}
        done, _ = run(behavior, starts, max_steps=120)
        self.assertTrue(done)
        phases = [p['phase'] for p in behavior.metrics.get('phases', [])]
        self.assertEqual(phases, ['机动', '到位', '执行', '结果确认'])
        kinds = {e['kind'] for e in behavior.history}
        self.assertIn('all_staged', kinds)
        self.assertIn('effect_applied', kinds)
        self.assertIn('confirmed', kinds)

    def test_tasl_roles_designation_assessment_and_withdraw(self):
        """T-ASL：侦察指示→齐射→效果达成→评估回传→确认→撤离；逐项结算。"""
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
        site = job['pos']
        job = dict(job, _behavior=dict(
            scout_pid='rover_21', observe_radius=12.0, observe_angle=0.0,
            assessor_pid='rover_02',
            staging_center=site, staging_radius=3.0, objective_radius=2.0,
            effect_kind='damage', required_level=2.0, damage_per_hit=1.0,
            fire_interval=1.0, rounds_per_salvo=1, ammo_per_platform=2,
            assessment_delay=1.0, confirmation_deadline=10.0,
            execute_deadline=30.0,
            withdraw=True, withdraw_point=[site[0] - 10.0, site[1]],
            withdraw_ring=2.0, withdraw_deadline=10.0, timeout_s=120.0))
        pids = ['rover_21', 'rover_22', 'rover_04', 'rover_02']
        behavior = make_behavior(job, nav, pids)
        self.assertEqual(behavior.roles['rover_21'], '侦察指示组')
        self.assertEqual(behavior.roles['rover_02'], '评估组')
        self.assertNotIn('rover_21', behavior.assault_pids)
        self.assertNotIn('rover_02', behavior.assault_pids)
        starts = {pid: behavior.staging[i % len(behavior.staging)]
                  for i, pid in enumerate(pids)}
        done, _ = run(behavior, starts, max_steps=60)
        self.assertTrue(done)
        kinds = [e['kind'] for e in behavior.history]
        order = ['command_received', 'target_designated', 'all_staged',
                 'assault_started', 'all_in_position', 'effect_started',
                 'salvo_fired', 'effect_achieved', 'effect_applied',
                 'result_pending', 'assessment_requested',
                 'assessment_received', 'confirmed', 'withdraw_started',
                 'withdrawn', 'behavior_complete']
        index = {k: kinds.index(k) for k in order}
        self.assertEqual([index[k] for k in order],
                         sorted(index[k] for k in order))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        self.assertEqual(result['adjudicator'], 'constructed_assessment_stub')
        self.assertFalse(result['verified'])
        required = [x for x in result['items'] if x['required']]
        self.assertTrue(required)
        self.assertTrue(all(x['status'] == 'achieved' for x in required))
        self.assertEqual(behavior.metrics['overall_status'], '成功')
        self.assertTrue(behavior.metrics['withdraw_ok'])
        self.assertEqual([p['phase'] for p in behavior.metrics['phases']],
                         ['机动', '到位', '执行', '结果确认', '撤离'])


class HoldTests(unittest.TestCase):
    def test_handover_keeps_continuous_presence(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J5')
        behavior = make_behavior(job, nav, ['rover_01', 'rover_31'])
        starts = {'rover_01': behavior.posts[0], 'rover_31': behavior.standbys[0]}
        done, _ = run(behavior, starts, max_steps=120)
        self.assertTrue(done)
        self.assertEqual(behavior.handovers, 2)
        self.assertEqual(behavior.gap_s, 0.0)
        self.assertGreaterEqual(behavior.min_present, 1)
        kinds = [e['kind'] for e in behavior.history]
        self.assertIn('handover_complete', kinds)
        self.assertGreaterEqual(kinds.count('relief'), 2)


if __name__ == '__main__':
    unittest.main()
