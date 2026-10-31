# -*- coding: utf-8 -*-
"""T-ASL 效果判定与逐项结算验收（规范 2026-10-29 §8）。

用"瞬移执行"驱动 AssaultBehavior 的效果引擎，逐条覆盖：
  1 毁伤成功 / 2 弹药耗尽终止 / 3 执行超时终止 / 4 确认超时
  5 压制成功与中断重计 / 6 夺占与移交后坚守分别结算
  7 部分达成不冒充 / 8 评估组在场与桩标注
  9/10 由全量回归与 test_workbench 默认运行用例覆盖。
"""
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
    poses = {pid: (p[0], p[1], 0.0) for pid, p in starts.items()}
    for t in range(max_steps):
        out = behavior.step(poses, float(t), 1.0)
        for pid, target in (out['targets'] or {}).items():
            poses[pid] = (target[0], target[1], 0.0)
        if out['done']:
            return True
    return False


def assault_job(**behavior_params):
    """J4 作业 + 可覆盖的行为参数；攻击窗默认给足。"""
    scene = scenario()
    job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
    bh = dict(behavior_params)
    bh.setdefault('staging_center', job['pos'])
    bh.setdefault('staging_radius', 3.0)
    bh.setdefault('objective_radius', 2.0)
    bh.setdefault('attack_window', [0, 600])
    bh.setdefault('timeout_s', 300.0)
    return dict(job, _behavior=bh)


def make(nav, job, pids=('rover_21', 'rover_22')):
    behavior = make_behavior(job, nav, list(pids))
    starts = {pid: behavior.staging[i % len(behavior.staging)]
              for i, pid in enumerate(pids)}
    return behavior, starts


class DamageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav, _ = build_nav(scenario())

    def _damage_behavior(self, **params):
        base = dict(effect_kind='damage', required_level=2.0,
                    damage_per_hit=1.0, fire_interval=1.0,
                    rounds_per_salvo=1, ammo_per_platform=2,
                    assessment_delay=1.0, confirmation_deadline=20.0,
                    execute_deadline=60.0)
        base.update(params)
        return make(self.nav, assault_job(**base))

    def test_1_damage_success_all_items_achieved(self):
        behavior, starts = self._damage_behavior()
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        self.assertEqual(result['effect_kind'], 'damage')
        for item in result['items']:
            if item['required']:
                self.assertEqual(item['status'], 'achieved', item)
        self.assertIn('salvo_fired', {e['kind'] for e in behavior.history})

    def test_2_ammo_exhausted_terminates_failed(self):
        behavior, starts = self._damage_behavior(
            required_level=5.0, ammo_per_platform=1)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'failed')
        self.assertEqual(result['termination'], 'ammo_exhausted')
        effect = next(x for x in result['items'] if x['id'] == 'effect')
        self.assertEqual(effect['status'], 'failed')
        self.assertIn('ammo_exhausted',
                      {e['kind'] for e in behavior.history})
        self.assertGreaterEqual(
            sum(1 for e in behavior.history if e['kind'] == 'ammo_depleted'),
            2)   # 两台平台各打空一次

    def test_3_execute_deadline_exceeded_terminates_failed(self):
        behavior, starts = self._damage_behavior(
            required_level=50.0, ammo_per_platform=50,
            execute_deadline=4.0)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'failed')
        self.assertEqual(result['termination'], 'deadline_exceeded')
        self.assertIn('deadline_exceeded',
                      {e['kind'] for e in behavior.history})

    def test_4_confirmation_timeout_fails_confirmation_item(self):
        behavior, starts = self._damage_behavior(
            assessment_delay=50.0, confirmation_deadline=5.0)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertNotEqual(result['overall'], 'succeeded')
        self.assertEqual(result['termination'], 'confirmation_timeout')
        confirm = next(x for x in result['items']
                       if x['id'] == 'confirmation')
        self.assertEqual(confirm['status'], 'failed')
        self.assertIn('confirmation_timeout',
                      {e['kind'] for e in behavior.history})


class SuppressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav, _ = build_nav(scenario())

    def test_5a_continuous_coverage_succeeds(self):
        job = assault_job(effect_kind='suppress', required_duration=5.0,
                          recovery_gap=3.0, fire_interval=1.0,
                          rounds_per_salvo=1, ammo_per_platform=10,
                          assessment_delay=1.0, confirmation_deadline=20.0,
                          execute_deadline=60.0)
        behavior, starts = make(self.nav, job)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        metric = next(x for x in result['items']
                      if x['id'] == 'effect_metric')['metric']
        self.assertGreaterEqual(metric['longest_suppression_s'], 5.0)

    def test_5b_gap_resets_continuous_clock(self):
        # fire_interval > recovery_gap：每轮齐射间隔太长，覆盖断开重计，
        # 连续时长永远达不到要求 → 执行截止终止，且断开次数 ≥ 2。
        job = assault_job(effect_kind='suppress', required_duration=5.0,
                          recovery_gap=3.0, fire_interval=8.0,
                          rounds_per_salvo=1, ammo_per_platform=20,
                          execute_deadline=30.0)
        behavior, starts = make(self.nav, job)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'failed')
        self.assertEqual(result['termination'], 'deadline_exceeded')
        gaps = [e for e in behavior.history if e['kind'] == 'suppression_gap']
        self.assertGreaterEqual(len(gaps), 2)
        self.assertLess(behavior.longest_suppression_s, 5.0)
        evidence_gaps = behavior._evidence()['coverage_intervals']
        self.assertGreaterEqual(len(evidence_gaps), 2)   # 覆盖时段被断开


class SeizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav, _ = build_nav(scenario())

    def _seize_behavior(self, **params):
        base = dict(effect_kind='seize', required_control_s=3.0,
                    min_occupants=2, hold_required_s=60.0,
                    assessment_delay=1.0, confirmation_deadline=20.0,
                    execute_deadline=60.0)
        base.update(params)
        return make(self.nav, assault_job(**base))

    def test_6_seize_and_hold_settled_separately(self):
        # 夺占达成（控制 3s）但坚守要求 60s、总时限 40s：
        # 夺占 achieved + 坚守 failed → overall 非 succeeded。
        behavior, starts = self._seize_behavior(timeout_s=40.0)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertNotEqual(result['overall'], 'succeeded')
        effect = next(x for x in result['items'] if x['id'] == 'effect')
        hold = next(x for x in result['items']
                    if x['id'] == 'hold_after_handover')
        self.assertEqual(effect['status'], 'achieved')
        self.assertEqual(hold['status'], 'failed')
        self.assertIn('handover', {e['kind'] for e in behavior.history})

    def test_6b_seize_success_includes_hold(self):
        behavior, starts = self._seize_behavior(hold_required_s=5.0,
                                                timeout_s=120.0)
        self.assertTrue(run(behavior, starts, max_steps=120))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'succeeded')
        for item in result['items']:
            if item['required']:
                self.assertEqual(item['status'], 'achieved', item)


class ItemStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nav, _ = build_nav(scenario())

    def test_7_effect_achieved_but_window_missed_is_failed(self):
        # 压制连续 12s 达标（效果 achieved），但达成时刻超出 [0,10] 时间窗
        # → 时间窗项 failed，overall failed：部分达成不冒充全部成功。
        job = assault_job(effect_kind='suppress', required_duration=12.0,
                          recovery_gap=3.0, fire_interval=1.0,
                          rounds_per_salvo=1, ammo_per_platform=30,
                          attack_window=[0, 10],
                          assessment_delay=1.0, confirmation_deadline=30.0,
                          execute_deadline=60.0)
        behavior, starts = make(self.nav, job)
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['overall'], 'failed')
        effect = next(x for x in result['items'] if x['id'] == 'effect')
        window = next(x for x in result['items'] if x['id'] == 'window')
        self.assertEqual(effect['status'], 'achieved')
        self.assertEqual(window['status'], 'failed')

    def test_8_assessor_owns_assessment_and_stub_is_unverified(self):
        job = assault_job(effect_kind='damage', required_level=2.0,
                          fire_interval=1.0, rounds_per_salvo=1,
                          ammo_per_platform=2, assessment_delay=1.0,
                          confirmation_deadline=20.0, execute_deadline=60.0,
                          scout_pid='rover_21', observe_radius=12.0,
                          observe_angle=0.0, assessor_pid='rover_04')
        pids = ('rover_21', 'rover_22', 'rover_04')
        behavior, starts = make(self.nav, job, pids)
        self.assertEqual(behavior.roles['rover_04'], '评估组')
        self.assertTrue(run(behavior, starts, max_steps=80))
        result = behavior.metrics['result']
        self.assertEqual(result['adjudicator'], 'constructed_assessment_stub')
        self.assertFalse(result['verified'])
        requested = [e for e in behavior.history
                     if e['kind'] == 'assessment_requested']
        self.assertEqual(requested[0]['by'], 'rover_04')
        received = [e for e in behavior.history
                    if e['kind'] == 'assessment_received']
        self.assertTrue(received)
        self.assertFalse(received[0]['verified'])
        self.assertEqual(received[0]['source'], 'constructed_assessment_stub')

    def test_asl_city_scenario_carries_effect_config(self):
        data = json.loads((ROOT / 'scenarios/asl_city.json')
                          .read_text(encoding='utf-8'))
        job = next(j for j in data['jobs'] if j['type'] == 'assault')
        bh = job['_behavior']
        self.assertEqual(bh['effect_kind'], 'damage')
        # 多类型兵力包：固定翼侦察、飞翼评估，其余为地面突击组
        self.assertEqual(bh['scout_pid'], 'rover_31')
        self.assertEqual(bh['assessor_pid'], 'rover_41')
        self.assertIn('assessment_post', bh)
        self.assertEqual(bh['role_payload'], {'assault': 4.0, 'support': 0.5})
        self.assertEqual(bh['air_altitude']['rover_31'], 30.0)
        self.assertEqual(job['crew'], 6)
        self.assertEqual(len(data['platforms']), 6)
        kinds = {p['robot_no']: None for p in data['platforms']}
        self.assertEqual(set(kinds), {1, 11, 21, 22, 31, 41})


class EffectKindConfigTests(unittest.TestCase):
    def test_effect_kind_normalization(self):
        from assessment import normalize_effect_kind
        from workbench_server import validate_config
        self.assertEqual(normalize_effect_kind('压制'), 'suppress')
        self.assertEqual(normalize_effect_kind('seize'), 'seize')
        self.assertEqual(normalize_effect_kind(None), 'damage')
        self.assertEqual(normalize_effect_kind('未知'), 'damage')
        config = validate_config(dict(scenario='asl_city',
                                      effect_kind='夺占'))
        self.assertEqual(config['effect_kind'], 'seize')
        with self.assertRaises(ValueError):
            validate_config(dict(effect_kind=123))


if __name__ == '__main__':
    unittest.main()
