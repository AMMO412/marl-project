# -*- coding: utf-8 -*-
"""五类到位行为测试：用"瞬移执行"把决策与运动解耦，只验状态机语义。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from behavior_runtime import BehaviorRunner
from behaviors import AreaReconBehavior, Behavior, make_behavior
from city_nav import NavMap, build_nav


def scenario():
    return json.loads((ROOT / 'tests/fixtures/base_scenarios/simple_city.json')
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

    def test_large_blocked_site_falls_back_to_map_wide_search(self):
        nav = NavMap(
            [0.0, 0.0, 20.0, 20.0],
            [dict(id='LARGE-BLOCK',
                  polygon=[[2.0, 2.0], [14.0, 2.0],
                           [14.0, 14.0], [2.0, 14.0]])],
            radius=0.4, resolution=0.5)
        behavior = Behavior(
            dict(job_id='J-RECON', pos=[8.0, 8.0]), nav, ['rover_01'])
        self.assertTrue(nav.free(behavior.site))
        self.assertGreater(behavior.site_snap, 4.0)


class PatrolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = scenario()
        cls.nav, _ = build_nav(cls.scene)
        job = next(j for j in cls.scene['jobs'] if j['job_id'] == 'J6')
        cls.job = job
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

    def test_fixed_wing_follows_densified_boundary_route(self):
        behavior = make_behavior(
            self.job,
            self.nav,
            ['wing'],
            params=dict(
                waypoints=[[0.0, 0.0], [60.0, 0.0],
                           [60.0, 60.0], [0.0, 60.0]],
                cycles=2,
                roles={'wing': 'patrol:1'},
                air_pass_tolerance_m=2.5,
            ),
        )
        behavior.set_platform_caps({
            'wing': dict(kind='WING', can_climb=True, start_z=25.0),
        })
        behavior.speeds = {'wing': 6.0}
        route = behavior.air_routes['wing']
        self.assertGreater(len(route), 4)
        first_target = route[1]
        poses = {'wing': (first_target[0], first_target[1], 0.0)}
        behavior.step(poses, 1.0, 1.0)
        self.assertTrue(behavior.visits['wing'])
        self.assertEqual(behavior.metrics['air_patrol']['mode'],
                         'boundary_follow')
        self.assertTrue(all(0.0 <= x <= 60.0 and 0.0 <= y <= 60.0
                            for x, y in route))

    def test_target_waits_for_patrol_and_is_reported(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J6')
        loop = make_behavior(job, nav, ['rover_01']).loop
        behavior = make_behavior(
            job, nav, ['rover_01'],
            params=dict(
                waypoints=loop,
                cycles=1,
                sensor_radius_m={'ground': 1000},
                observation_target=dict(
                    target_id='TARGET-1',
                    start=list(loop[0]),
                    goal=[0.0, 0.0],
                    speed_mps=1.0,
                    start_after_patrol_s=5,
                ),
            ),
        )
        behavior.set_platform_caps({
            'rover_01': dict(can_climb=False),
        })
        starts = {'rover_01': behavior.loop[0]}
        done, _ = run(behavior, starts, max_steps=300)
        self.assertTrue(done)
        started = next(e for e in behavior.history
                       if e['kind'] == 'patrol_target_started')
        self.assertIsNotNone(behavior.patrol_started_at)
        self.assertGreaterEqual(
            started['t'], behavior.patrol_started_at + 5)
        self.assertGreater(behavior.target_report_count, 0)
        self.assertTrue(behavior.metrics['target_detected'])
        self.assertEqual(behavior.result['overall'], 'succeeded')
        self.assertEqual(behavior.result['reason'],
                         'target_detected_and_reported')

    def test_completed_cycles_without_target_report_are_not_success(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J6')
        loop = make_behavior(job, nav, ['rover_01']).loop
        behavior = make_behavior(
            job, nav, ['rover_01'],
            params=dict(
                waypoints=loop,
                cycles=1,
                sensor_radius_m={'ground': 0.5},
                observation_target=dict(
                    target_id='TARGET-MISSED',
                    start=[-1000.0, -1000.0],
                    goal=[-999.0, -1000.0],
                    speed_mps=1.0,
                    start_after_patrol_s=1,
                ),
            ),
        )
        behavior.set_platform_caps({
            'rover_01': dict(can_climb=False),
        })
        done, _ = run(
            behavior, {'rover_01': behavior.loop[0]}, max_steps=300)
        self.assertTrue(done)
        self.assertEqual(behavior.target_report_count, 0)
        self.assertFalse(behavior.metrics['target_detected'])
        self.assertEqual(behavior.result['overall'], 'failed')
        self.assertEqual(behavior.result['reason'], 'target_not_detected')


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
    def test_recon_releases_a_claim_as_soon_as_the_cell_is_scanned(self):
        nav = NavMap((-40, -40, 40, 40), [])
        behavior = AreaReconBehavior(
            dict(job_id='T2', pos=[0, 0]), nav, ['air'],
            dict(area=[[-20, -20], [20, -20], [20, 20], [-20, 20]],
                 search_starts={'air': [-18, -18]}, search_limit_s=90,
                 cell=4, sensor_radius_m={'ground': 7, 'air': 8},
                 frontier_tol=1.0))
        behavior.set_platform_caps({
            'air': dict(kind='WING', can_climb=True, start_z=20)})
        old_target = behavior.claimed['air']
        behavior._scan('air', old_target)
        self.assertNotIn(old_target, behavior.unknown)

        behavior.step({'air': (old_target[0] + 4, old_target[1], 0.0)},
                      0.0, 0.1)

        self.assertNotEqual(behavior.claimed['air'], old_target)

    def test_recon_prefers_a_forward_cell_for_a_fixed_wing(self):
        nav = NavMap((-40, -40, 40, 40), [])
        behavior = AreaReconBehavior(
            dict(job_id='T2', pos=[0, 0]), nav, ['air'],
            dict(area=[[-20, -20], [20, -20], [20, 20], [-20, 20]],
                 search_starts={'air': [0, 0]}, search_limit_s=90,
                 cell=4))
        behavior.set_platform_caps({
            'air': dict(kind='WING', can_climb=True, start_z=20)})
        behavior.claimed = {'air': None}
        forward = (5.0, 0.5)
        behind = (-5.0, 0.5)
        behavior.unknown = {forward, behind}
        behavior.sector.update({forward: 'air', behind: 'air'})

        selected = behavior._next_cell('air', (0.0, 0.0, 0.0))

        self.assertEqual(selected, forward)

    def test_recon_limits_fixed_wing_speed_to_the_search_area_scale(self):
        nav = NavMap((-40, -40, 40, 40), [])
        behavior = AreaReconBehavior(
            dict(job_id='T2', pos=[0, 0]), nav, ['air'],
            dict(area=[[-20, -20], [20, -20], [20, 20], [-20, 20]],
                 search_starts={'air': [-18, -18]}, search_limit_s=90,
                 cell=4, air_max_yaw_rate=0.35))
        behavior.set_platform_caps({
            'air': dict(kind='WING', can_climb=True, start_z=20)})
        behavior.speeds = {'air': 30.0}

        out = behavior.step({'air': (-18, -18, 0)}, 0.0, 0.1)

        self.assertGreaterEqual(behavior.air_search_speed_effective_mps, 3.5)
        self.assertLessEqual(behavior.air_search_speed_effective_mps, 8.0)
        self.assertLess(out['air_speed_scale']['air'], 0.5)

    def test_air_tracker_circles_the_stopped_target_before_completing(self):
        nav = NavMap((-30, -30, 80, 30), [])
        area = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
        target = dict(target_id='OBS', start=[0, 0], goal=[20, 0], speed_mps=3,
                      move_after_s=1, track_outside_s=2, track_until_stop=True,
                      move_after_contact=True, stop_orbit_s=18)
        behavior = AreaReconBehavior(dict(job_id='T2', pos=[0, 0]), nav, ['air'],
            dict(area=area, search_starts={'air': [0, 0]}, search_limit_s=90,
                 tracking_target=target, air_altitude={'air': 20}))
        caps = {'air': {'kind': 'WING', 'can_climb': True, 'start_z': 20}}
        behavior.set_platform_caps(caps)
        runner = BehaviorRunner(nav, behavior, {'air': [0, 0]}, speeds={'air': 8}, caps=caps)
        orbit = []
        for _ in range(90):
            done = runner.step()
            if behavior.target_sample['status'] == 'orbiting':
                a = runner.agents['air']
                orbit.append((a.x, a.y, a.z))
            if done:
                break
        self.assertTrue(behavior.track_complete)
        self.assertGreaterEqual(len(orbit), 17)
        self.assertEqual(len(set(orbit)), len(orbit))
        self.assertTrue(all(z == 20 for _, _, z in orbit))
        self.assertLess(min(x for x, _, _ in orbit), 18)
        self.assertGreater(max(x for x, _, _ in orbit), 22)

    def test_ground_tracker_reports_before_target_stops(self):
        nav = NavMap((-50, -50, 100, 50), [])
        area = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
        target = dict(target_id='OBS', start=[0, 0], goal=[40, 0], speed_mps=3,
                      move_after_s=2, track_outside_s=4, track_until_stop=True,
                      move_after_contact=True)
        behavior = AreaReconBehavior(dict(job_id='T2', pos=[0, 0]), nav, ['ground'],
            dict(area=area, search_starts={'ground': [-4, 0]}, search_limit_s=60,
                 tracking_target=target))
        behavior.set_platform_caps({'ground': {'kind': 'UGV'}})
        runner = BehaviorRunner(nav, behavior, {'ground': [-12, 0]}, speeds={'ground': 8})
        for _ in range(60):
            if runner.step():
                break
        moving = [e for e in runner.events if e['kind'] == 'recon_track_report' and e['moving']]
        self.assertGreater(len(moving), 5)
        self.assertTrue(all(a['pos'][0] < b['pos'][0] for a, b in zip(moving, moving[1:])))
        result = next(e for e in runner.events if e['kind'] == 'recon_track_completed')
        self.assertEqual(result['pos'], target['goal'])

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
    def test_blocked_withdraw_ring_uses_mapwide_recovery(self):
        nav = NavMap(
            [0.0, 0.0, 80.0, 80.0],
            [dict(id='WITHDRAW-BLOCK',
                  polygon=[[10.0, 10.0], [70.0, 10.0],
                           [70.0, 70.0], [10.0, 70.0]])],
            radius=0.5, resolution=0.5)
        job = dict(
            job_id='ASL-RING', type='assault', pos=[5.0, 5.0],
            _behavior=dict(
                staging_center=[5.0, 5.0], staging_radius=2.0,
                objective_radius=1.0, withdraw=True,
                withdraw_point=[40.0, 40.0], withdraw_ring=4.0,
                withdraw_deadline=30.0, timeout_s=120.0))
        behavior = make_behavior(job, nav, ['ugv-1', 'ugv-2'])
        self.assertEqual(len(behavior.withdraw_targets), 2)
        self.assertTrue(all(nav.free(point) for point in behavior.withdraw_targets))

    def test_air_station_uses_stable_center_and_continuous_orbit(self):
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
        site = job['pos']
        job = dict(job, _behavior=dict(
            scout_pid='wing-1', observe_radius=12.0, observe_angle=0.0,
            staging_center=site, staging_radius=3.0, objective_radius=2.0,
            air_altitude={'wing-1': 20.0}, air_orbit_radius_m=0.0,
            timeout_s=120.0))
        behavior = make_behavior(job, nav, ['wing-1', 'ugv-1'])
        behavior.set_platform_caps({
            'wing-1': dict(kind='WING', can_climb=True, start_z=20.0),
            'ugv-1': dict(kind='UGV', can_climb=False),
        })
        behavior.speeds = {'wing-1': 6.0, 'ugv-1': 0.8}
        behavior.phase = '执行'
        behavior.arrivals['wing-1']['observation'] = 0.0
        targets = {'wing-1': behavior.observation}
        loitered = behavior._apply_station_loiter(targets, 1.0)
        first = behavior._station_loiter_radii(loitered)
        second = behavior._station_loiter_radii(loitered)
        self.assertEqual(loitered['wing-1'], behavior.observation)
        self.assertIn('wing-1', first)
        self.assertEqual(second['wing-1'], first['wing-1'])

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

    def test_assessor_prepositions_without_delaying_assault_staging(self):
        """评估组直接前出观察位，不能阻塞突击组从集结转入执行。"""
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
        site = job['pos']
        job = dict(job, _behavior=dict(
            scout_pid='rover_21', observe_radius=12.0, observe_angle=0.0,
            assessor_pid='rover_02',
            staging_center=site, staging_radius=3.0, objective_radius=2.0,
            assessment_post=[site[0] - 12.0, site[1]],
            assessment_delay=2.0, confirmation_deadline=20.0,
            execute_deadline=30.0, timeout_s=120.0))
        pids = ['rover_21', 'rover_02', 'rover_22', 'rover_04']
        behavior = make_behavior(job, nav, pids)
        poses = {
            'rover_21': (*behavior.observation, 0.0),
            'rover_22': (*behavior.staging[0], 0.0),
            'rover_04': (*behavior.staging[1], 0.0),
            'rover_02': (-100.0, -100.0, 0.0),
        }
        out = behavior.step(poses, 0.0, 1.0)
        self.assertEqual(out['targets']['rover_02'], behavior.assessment_post)
        self.assertIn('all_staged', {e['kind'] for e in behavior.history})
        out = behavior.step(poses, 1.0, 1.0)
        self.assertEqual(out['phase'], '执行')
        self.assertIn('assault_started', {e['kind'] for e in behavior.history})

    def test_confirmation_progress_remains_visible_while_waiting(self):
        """结果确认等待评估时，进度必须从90%继续推进，不能呈粘滞状态。"""
        scene = scenario()
        nav, _ = build_nav(scene)
        job = next(j for j in scene['jobs'] if j['job_id'] == 'J4')
        behavior = make_behavior(job, nav, ['rover_22'])
        behavior.phase = '结果确认'
        behavior.stage_enter_t = 10.0
        behavior.assess_requested = True
        behavior.assessed = False
        behavior.assessment_t = 20.0
        behavior.t = 15.0
        self.assertAlmostEqual(behavior.progress_frac(), 0.925)
        behavior.t = 20.0
        self.assertAlmostEqual(behavior.progress_frac(), 0.95)


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
