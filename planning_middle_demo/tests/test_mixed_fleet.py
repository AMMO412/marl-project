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
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import planner_v2
import sdf_state
from behavior_runtime import BehaviorRunner
from behaviors import make_behavior
from city_nav import NavMap, distance
from city_nav import build_nav
from contracts_v2 import build_jobs, build_platforms
from mock_fleet import MockFleet


def load(name):
    path = ROOT / 'scenarios' / name
    if not path.is_file():
        path = ROOT / 'tests' / 'fixtures' / 'base_scenarios' / name
    return json.loads(path.read_text(encoding='utf-8'))


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

    def test_dispatched_assault_roles_override_stale_template_seats(self):
        nav = NavMap([0.0, 0.0, 10.0, 10.0], [], radius=0.2,
                     resolution=0.5)
        fleet = MockFleet(motion='real', nav=nav, behavior_params={
            'ASL-RANDOM': dict(scout_pid='rover_31',
                               assessor_pid='rover_41'),
        })
        job = {
            'members': {
                'rover_40': {'wire': {'command': {
                    'attempt': 1,
                    'task': {
                        'job_id': 'ASL-RANDOM',
                        'jtype': 'assault',
                        'position': [5.0, 5.0],
                        'roles': {
                            'rover_40': 'scout',
                            'rover_50': 'assessor',
                            'rover_20': 'assault',
                        },
                    },
                }}},
            },
        }
        behavior = fleet._behavior_job_dict(job)['_behavior']
        self.assertEqual(behavior['scout_pid'], 'rover_40')
        self.assertEqual(behavior['assessor_pid'], 'rover_50')


class AirGroundRunnerTests(unittest.TestCase):
    def test_moving_target_replans_at_control_deadline_not_every_tick(self):
        """动态追赶不应每 0.1 s 重做一次整图搜索。"""
        class CountingNav(NavMap):
            def __init__(self):
                super().__init__([-5.0, -5.0, 15.0, 25.0], [],
                                 radius=0.2, resolution=0.5)
                self.plan_calls = 0

            def plan(self, start, goal, **kwargs):
                self.plan_calls += 1
                return super().plan(start, goal, **kwargs)

        class IdleBehavior(object):
            kind = 'recon'
            pids = ['rover_01']
            job_id = 'T-RCN'
            site = [0.0, 20.0]
            continuous = False
            phase = '跟踪'
            params = {}

            def step(self, poses, t, dt):
                return dict(targets={}, phase=self.phase, done=False)

            def drain(self):
                return []

        nav = CountingNav()
        runner = BehaviorRunner(
            nav, IdleBehavior(), {'rover_01': (0.0, 0.0, 0.0)},
            speeds={'rover_01': 2.0},
            caps={'rover_01': dict(kind='UGV', can_climb=False)})
        agent = runner.agents['rover_01']
        runner._set_target(agent, [0.0, 20.0], pursuit=True, now=0.0)
        self.assertEqual(nav.plan_calls, 1)

        for index in range(1, 10):
            runner._set_target(
                agent, [0.1 * index, 20.0], pursuit=True, now=0.1 * index)
        self.assertEqual(
            nav.plan_calls, 1,
            '更新拦截点后一秒内应复用已经验证过的路径')

        runner._set_target(agent, [1.0, 20.0], pursuit=True, now=1.0)
        self.assertEqual(
            nav.plan_calls, 2,
            '到达动态重规划期限后应重新计算一次路径')

    def test_dynamic_behavior_routes_keep_threat_clearance(self):
        """集结/观察等动态航点也必须走带安全间隔的威胁路由器。"""
        from interop.geometry import segment_polygon_distance
        from interop.message import parse_message
        from interop.routing import DEFAULT_THREAT_CLEARANCE_M
        from interop.runtime import nav_from_scenario

        raw_message = json.loads(
            (ROOT / 'interop/scenarios/asl_junction.message.json')
            .read_text(encoding='utf-8-sig'))
        raw_formation = json.loads(
            (ROOT / 'interop/scenarios/asl_junction.formation.json')
            .read_text(encoding='utf-8-sig'))
        for item in raw_formation.get('constraints') or []:
            if item.get('type') == 'threat':
                item['applies_to'] = 'all'
        scenario = parse_message(raw_message, raw_formation)
        nav = nav_from_scenario(scenario, avoid_threats=True)

        class DynamicTargetBehavior(object):
            kind = 'assault'
            pids = ['rover_21', 'rover_31']
            job_id = 'T-ASL'
            site = [-95.0, -145.0]
            continuous = False
            phase = '机动'
            params = {}

            def step(self, poses, t, dt):
                return dict(targets={}, phase=self.phase, done=False)

            def drain(self):
                return []

        starts = {
            'rover_21': (-10.0, -22.5, 0.0),
            'rover_31': (-15.0, -22.5, 0.0),
        }
        caps = {
            'rover_21': dict(kind='TANK', can_climb=False),
            'rover_31': dict(kind='PLANE', can_climb=True, start_z=30.0),
        }
        runner = BehaviorRunner(
            nav, DynamicTargetBehavior(), starts,
            speeds={'rover_21': 1.0, 'rover_31': 2.0}, caps=caps)
        runner._set_target(runner.agents['rover_21'], [-56.0, -124.0])
        runner._set_target(runner.agents['rover_31'], [-70.0, -145.0])

        threat = next(item for item in scenario.constraints
                      if item.get('type') == 'threat')
        polygon = threat['area']['polygon']
        self.assertEqual(
            [route['mode'] for route in runner.routes],
            ['ground_threat_astar', 'air_threat_astar'])
        for route in runner.routes:
            for first, second in zip(route['path'], route['path'][1:]):
                self.assertGreaterEqual(
                    segment_polygon_distance(first, second, polygon),
                    DEFAULT_THREAT_CLEARANCE_M - 1e-6,
                    '%s route cuts into %s clearance' %
                    (route['pid'], threat.get('constraint_id')))

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

    def test_planned_threat_route_bypasses_local_hard_obstacle_projection(self):
        class PlannedRouteBehavior(object):
            kind = 'assault'
            pids = ['rover_23']
            job_id = 'T-ASL'
            site = [10.0, 0.0]
            continuous = False
            phase = '机动'
            params = {}

            def step(self, poses, t, dt):
                path = [[0.0, 0.0], [0.0, 6.0], [10.0, 6.0],
                        [10.0, 0.0]]
                length = sum(distance(a, b) for a, b in zip(path, path[1:]))
                return {
                    'targets': {'rover_23': [10.0, 0.0]},
                    'phase': self.phase,
                    'done': False,
                    'planned_routes': {
                        'rover_23': {
                            'path': path, 'length': length,
                            'straight_length': 10.0,
                            'straight_line_ok': False,
                            'min_clearance': None,
                            'mode': 'planned_threat_route',
                        }
                    },
                }

            def drain(self):
                return []

        # This map deliberately treats the threat footprint as a hard obstacle.
        # The runner must not feed the planner-approved route back through that
        # projection, otherwise vehicles can pivot forever at the polygon corner.
        nav = NavMap(
            [-5.0, -10.0, 20.0, 15.0],
            [dict(id='THREAT', polygon=[[2.0, -5.0], [8.0, -5.0],
                                        [8.0, 5.0], [2.0, 5.0]])],
            radius=0.5, resolution=0.5)
        behavior = PlannedRouteBehavior()
        runner = BehaviorRunner(
            nav, behavior, {'rover_23': (0.0, 0.0, 0.0)},
            speeds={'rover_23': 5.0},
            caps={'rover_23': dict(kind='UGV', can_climb=False)})
        runner.step()
        # 回放要能还原每个 0.1 s 控制拍的真实折线。安全计划航路
        # 直接按折点逐步结算，不经过前瞻跟随器；否则高速平台会以
        # 弧线切掉折点，中心线虽然安全，实际轨迹仍可能擦入威胁区。
        self.assertEqual(len(runner.samples), 10)
        self.assertGreater(distance((runner.agents['rover_23'].x,
                                    runner.agents['rover_23'].y),
                                   (0.0, 0.0)), 1.0)
        self.assertAlmostEqual(runner.agents['rover_23'].x, 0.0, places=2)
        self.assertGreater(runner.agents['rover_23'].y, 1.0)

    def test_air_runner_follows_all_planned_threat_waypoints(self):
        class PlannedAirRouteBehavior(object):
            kind = 'assault'
            pids = ['rover_41']
            job_id = 'T-AIR'
            site = [20.0, 0.0]
            continuous = False
            phase = '机动'
            params = {}

            def step(self, poses, t, dt):
                path = [[0.0, 0.0], [0.0, -10.0], [20.0, -10.0],
                        [20.0, 0.0]]
                length = sum(distance(a, b) for a, b in zip(path, path[1:]))
                return {
                    'targets': {'rover_41': [20.0, 0.0]},
                    'phase': self.phase,
                    'done': False,
                    'planned_routes': {
                        'rover_41': {
                            'path': path, 'length': length,
                            'straight_length': 20.0,
                            'straight_line_ok': False,
                            'min_clearance': None,
                            'mode': 'planned_threat_route',
                        }
                    },
                }

            def drain(self):
                return []

        # 起终点直线穿过威胁区；规划折线从下方绕过。空中执行器必须
        # 依次经过全部航点，不能退化为直接飞向 path[-1]。
        nav = NavMap(
            [-5.0, -15.0, 25.0, 5.0],
            [dict(id='AIR-THREAT', polygon=[[5.0, -2.0], [15.0, -2.0],
                                            [15.0, 2.0], [5.0, 2.0]])],
            radius=0.2, resolution=0.5)
        runner = BehaviorRunner(
            nav, PlannedAirRouteBehavior(), {'rover_41': (0.0, 0.0, 0.0)},
            speeds={'rover_41': 5.0},
            caps={'rover_41': dict(kind='WING', can_climb=True,
                                   start_z=20.0)})
        positions = []
        for _ in range(180):
            runner.step()
            agent = runner.agents['rover_41']
            positions.append((agent.x, agent.y))
            if distance((agent.x, agent.y), (20.0, 0.0)) <= 0.75:
                break
        # A fixed-wing aircraft cannot stop at a zero-radius point.  Once it
        # reaches the route end it enters a bounded orbit around the station.
        self.assertLessEqual(
            distance(positions[-1], (20.0, 0.0)), 3.75)
        through_columns = [y for x, y in positions if 4.5 <= x <= 15.5]
        self.assertTrue(through_columns)
        self.assertLess(max(through_columns), -8.5)

    def test_air_runner_projects_dynamic_goal_out_of_threat(self):
        class OrbitIntoThreatBehavior(object):
            kind = 'blockade'
            pids = ['rover_31']
            job_id = 'T-AIR'
            site = [10.0, 0.0]
            continuous = False
            phase = '封控在位'
            params = {}

            def step(self, poses, t, dt):
                return {
                    'targets': {'rover_31': [10.0, 0.0]},
                    'phase': self.phase,
                    'done': False,
                }

            def drain(self):
                return []

        nav = NavMap(
            [-5.0, -15.0, 25.0, 15.0], [],
            radius=0.2, resolution=0.5)
        nav.air_threat_nav = NavMap(
            [-5.0, -15.0, 25.0, 15.0],
            [dict(id='AIR-THREAT',
                  polygon=[[5.0, -5.0], [15.0, -5.0],
                           [15.0, 5.0], [5.0, 5.0]])],
            radius=0.2, resolution=0.5)
        runner = BehaviorRunner(
            nav, OrbitIntoThreatBehavior(), {'rover_31': (0.0, 0.0, 0.0)},
            speeds={'rover_31': 5.0},
            caps={'rover_31': dict(kind='PLANE', can_climb=True,
                                   start_z=20.0)},
            air_nav=nav.air_threat_nav)
        positions = []
        for _ in range(300):
            runner.step()
            agent = runner.agents['rover_31']
            positions.append((agent.x, agent.y))

        self.assertGreater(max(x for x, _ in positions), 3.0)
        self.assertFalse(any(5.2 < x < 14.8 and -4.8 < y < 4.8
                             for x, y in positions))

    def test_air_patrol_follows_a_bounded_inner_route(self):
        """Fixed-wing patrol must follow the boundary instead of circling at center."""
        nav = NavMap(
            [-20.0, -20.0, 20.0, 20.0], [],
            radius=0.2, resolution=0.5)
        nav.air_threat_nav = NavMap(
            [-20.0, -20.0, 20.0, 20.0],
            [dict(id='AIR-THREAT',
                  polygon=[[-2.0, -2.0], [2.0, -2.0],
                           [2.0, 2.0], [-2.0, 2.0]])],
            radius=0.2, resolution=0.5)
        job = dict(
            job_id='T-PATROL', type='patrol', pos=[0.0, 0.0],
            _behavior=dict(
                waypoints=[[-10.0, -10.0], [0.0, 0.0],
                           [10.0, -10.0], [10.0, 10.0]],
                cycles=1,
                corner_lookahead_m=1.8,
                air_altitude={'rover_41': 25.0},
            ),
        )
        behavior = make_behavior(job, nav, ['rover_41'])
        caps = {'rover_41': dict(kind='WING', can_climb=True,
                                start_z=25.0)}
        behavior.set_platform_caps(caps)
        runner = BehaviorRunner(
            nav, behavior, {'rover_41': (-10.0, -10.0, 0.0)},
            speeds={'rover_41': 5.0},
            caps=caps, air_nav=nav.air_threat_nav)
        positions = []
        for _ in range(240):
            runner.step()
            agent = runner.agents['rover_41']
            positions.append((agent.x, agent.y))
            if behavior.done:
                break

        self.assertTrue(behavior.done)
        self.assertEqual(behavior.cycles['rover_41'], 1)
        self.assertEqual(behavior.metrics['air_patrol']['mode'],
                         'boundary_follow')
        self.assertTrue(all(-10.1 <= x <= 10.1 and -10.1 <= y <= 10.1
                            for x, y in positions))
        self.assertLess(
            min(min(abs(x + 10.0), abs(x - 10.0),
                    abs(y + 10.0), abs(y - 10.0))
                for x, y in positions),
            8.0)
        self.assertFalse(any(-1.7 < x < 1.7 and -1.7 < y < 1.7
                             for x, y in positions))

    def test_air_patrol_follows_inset_boundary_without_leaving_area(self):
        """Several aircraft must stay on boundary routes without swinging out."""
        nav = NavMap(
            [-300.0, -100.0, 100.0, 200.0], [],
            radius=0.2, resolution=0.5)
        pids = ['rover_41', 'rover_42', 'rover_43', 'rover_44']
        corners = [
            [-229.535, 35.449], [-109.535, 35.449],
            [-109.535, 105.449], [-229.535, 105.449],
        ]
        job = dict(
            job_id='T-PATROL-MULTI', type='patrol', pos=[-169.535, 70.449],
            _behavior=dict(
                waypoints=corners, cycles=1,
                roles={pid: 'patrol:%d' % (index + 1)
                       for index, pid in enumerate(pids)},
                air_altitude={pid: 30.0 for pid in pids},
            ),
        )
        behavior = make_behavior(job, nav, pids)
        caps = {
            pid: dict(kind='WING', can_climb=True, start_z=30.0)
            for pid in pids
        }
        behavior.set_platform_caps(caps)
        starts = {
            'rover_41': (-220.0, 45.0, 0.0),
            'rover_42': (-120.0, 45.0, math.pi / 2),
            'rover_43': (-120.0, 95.0, math.pi),
            'rover_44': (-220.0, 95.0, -math.pi / 2),
        }
        runner = BehaviorRunner(
            nav, behavior, starts,
            speeds={pid: 30.0 for pid in pids}, caps=caps)
        outside = {pid: 0.0 for pid in pids}
        for _ in range(600):
            runner.step()
            for pid in pids:
                agent = runner.agents[pid]
                outside[pid] = max(
                    outside[pid],
                    -229.535 - agent.x, agent.x - -109.535,
                    35.449 - agent.y, agent.y - 105.449)
            if behavior.done:
                break

        self.assertTrue(behavior.done)
        self.assertTrue(all(value <= 0.05
                            for value in outside.values()), outside)

    def test_mixed_recon_tracks_after_coverage_without_stall_reassignment(self):
        """Coverage completion must not freeze feedback or replace healthy members."""
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, nav_from_scenario, to_v2_dict
        from run_demo_v2 import simulate

        scenario_dir = ROOT / 'interop' / 'scenarios'
        raw_message = json.loads(
            (scenario_dir / 'crossroad_recon.message.json')
            .read_text(encoding='utf-8-sig'))
        raw_formation = json.loads(
            (scenario_dir / 'crossroad_recon.formation.json')
            .read_text(encoding='utf-8-sig'))
        scenario = parse_message(raw_message, raw_formation)
        data = to_v2_dict(scenario, raw_message, raw_formation)
        planner = InteropPlanner(
            scenario, objective='timeliness', data=data)
        nav = nav_from_scenario(scenario)
        report, audit = simulate(
            data, mode='normal', motion='real', avoid=True,
            max_ticks=220, behavior=True, planner=planner, nav=nav)

        dispatch = next(e for e in audit
                        if e.get('kind') == 'job_dispatched'
                        and e.get('job_id') == 'T1')
        platform_map = scenario.platform_map
        classes = {
            platform_map[next(
                item.unit_id for item in scenario.platforms
                if item.robot_id == int(pid.rsplit('_', 1)[1]))].platform_class
            for pid in dispatch['pids']
        }
        self.assertEqual(classes, {'UGV', 'PLANE', 'WING'})
        self.assertFalse(any(
            row.get('kind') == 'subtask_reassigned'
            for row in audit))
        event_rows = [
            row for row in audit
            if row.get('kind') == 'behavior_event'
            and row.get('event', {}).get('job_id') == 'T1'
        ]
        coverage = next(row for row in event_rows
                        if row['event'].get('kind') == 'coverage_reached')
        tracking = next(row for row in event_rows
                        if row['event'].get('kind') == 'recon_track_completed')
        report_sent = next(row['event'] for row in event_rows
                           if row['event'].get('kind') == 'report_sent')
        returns = [row['sim_s'] for row in audit
                   if row.get('kind') == 'behavior_event'
                   and row.get('event', {}).get('kind') == 'return_started']
        self.assertLess(coverage['sim_s'], tracking['sim_s'])
        self.assertEqual(report_sent['overall'], 'succeeded')
        self.assertTrue(returns)
        self.assertEqual(report['return_complete'], True)

    def test_assault_formup_snaps_out_of_threat_obstacle(self):
        """集结中心落在威胁障碍内时，四台地面平台仍应得到可到达的分散点位。"""
        nav = NavMap(
            [-20.0, -20.0, 20.0, 20.0],
            [dict(id='THREAT-ALL',
                  polygon=[[-4.0, -4.0], [4.0, -4.0],
                           [4.0, 4.0], [-4.0, 4.0]])],
            radius=0.2, resolution=0.5)
        pids = ['rover_21', 'rover_22', 'rover_23', 'rover_24']
        job = dict(
            job_id='T-ASL', type='assault', pos=[10.0, 0.0],
            _behavior=dict(
                staging_center=[0.0, 0.0],
                staging_radius=3.0,
                objective_radius=2.0,
                withdraw=True,
                withdraw_point=[10.0, 0.0],
                withdraw_ring=3.0,
                timeout_s=60.0,
            ),
        )
        behavior = make_behavior(job, nav, pids)

        self.assertTrue(all(nav.free(point) for point in behavior.staging))
        self.assertEqual(
            len({tuple(round(v, 2) for v in point)
                 for point in behavior.staging}), len(pids))
        self.assertEqual(len(behavior.withdraw_targets),
                         len(behavior.assault_pids))
        self.assertTrue(all(len(point) == 2
                            for point in behavior.withdraw_targets))
        starts = [[-12.0, -6.0], [-12.0, -2.0],
                  [-12.0, 2.0], [-12.0, 6.0]]
        for start, target in zip(starts, behavior.staging):
            self.assertTrue(nav.plan(start, target)['path'])

    def test_air_return_uses_air_threat_routes(self):
        ground_nav = NavMap(
            [-5.0, -15.0, 25.0, 5.0], [],
            radius=0.2, resolution=0.5)
        ground_nav.air_threat_nav = NavMap(
            [-5.0, -15.0, 25.0, 5.0],
            [dict(id='AIR-THREAT', polygon=[[5.0, -2.0], [15.0, -2.0],
                                            [15.0, 2.0], [5.0, 2.0]])],
            radius=0.2, resolution=0.5)
        fleet = MockFleet(motion='real', nav=ground_nav,
                          home={'rover_41': [0.0, 0.0]})
        fleet.platforms['rover_41'] = dict(
            pos=(20.0, 0.0), yaw=0.0, z=25.0, battery=100.0,
            active=False, dead=False,
            return_profile=dict(can_climb=True, speed=5.0, move_cost=0.1))
        positions = []
        for now in range(1, 20):
            fleet.step_returns(float(now), set())
            positions.append(fleet.platforms['rover_41']['pos'])
            if fleet.return_state['rover_41']['status'] == 'returned':
                break
        self.assertEqual(fleet.return_state['rover_41']['status'], 'returned')
        self.assertEqual(fleet.platforms['rover_41']['pos'], (0.0, 0.0))
        through_columns = [y for x, y in positions if 4.5 <= x <= 15.5]
        self.assertTrue(through_columns)
        self.assertLess(max(through_columns), -1.5)


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
