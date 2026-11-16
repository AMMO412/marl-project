"""Airborne station keeping is shared across task types and recorded as motion."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from behavior_runtime import BehaviorRunner
from behaviors import AreaReconBehavior, Behavior
from city_nav import NavMap
from contracts_v2 import PROTOCOL_V2
from mock_fleet import MockFleet
from motion import AirLoiter, Pose
from trajectory_v2 import build_replay_data


def wire(kind='PLANE', task_type='recon', work=80):
    air = kind in ('PLANE', 'WING')
    return dict(protocol=PROTOCOL_V2, run_id='test', plan_id=1, command=dict(
        command_id='cmd', worker_id='unit', job_id='J', attempt=1,
        issued_sim_s=0, start_sim_s=0, expected_end_sim_s=200, action='start',
        delivery=dict(pos=[0, 0], battery=1000, ammo=0, can_climb=air,
                      speed=4, move_cost=.1, work_rate=1, work_cost=.1, kind=kind),
        task=dict(position=[8, 0], altitude=6 if air else 0,
                  goal=dict(x=8, y=0, z=6 if air else 0), work=work, jtype=task_type)))


class StationBehavior(Behavior):
    def step(self, poses, t, dt):
        self.t = t
        self.done = t >= 50 and self.occupy(poses, [self.site] * len(self.pids))
        return dict(targets={pid: self.site for pid in self.pids}, done=self.done,
                    phase='station')


class AirStationKeepingTests(unittest.TestCase):
    def test_air_heading_and_speed_are_rate_limited(self):
        class IdleBehavior(Behavior):
            def step(self, poses, t, dt):
                return dict(targets={}, phase='idle', done=False)

        nav = NavMap((-200, -200, 200, 200), [])
        behavior = IdleBehavior(dict(job_id='J', pos=[0, 0]), nav, ['air'])
        runner = BehaviorRunner(
            nav, behavior, {'air': (0, 0, math.pi / 2)},
            speeds={'air': 30},
            caps={'air': dict(can_climb=True, kind='WING', start_z=25)})
        agent = runner.agents['air']
        agent.path = [[0, 0], [80, 0], [80, 80]]
        agent.follow = runner._follower_for('air').reset()
        previous_yaw = agent.yaw
        previous_speed = agent.air_v
        largest_yaw_step = 0.0
        largest_speed_step = 0.0
        for _ in range(80):
            x, y = agent.x, agent.y
            runner._advance_air(agent)
            moved = math.hypot(agent.x - x, agent.y - y)
            if moved > 1e-9:
                self.assertAlmostEqual(
                    math.atan2(agent.y - y, agent.x - x),
                    agent.yaw, places=9)
            largest_yaw_step = max(
                largest_yaw_step,
                abs(math.atan2(math.sin(agent.yaw - previous_yaw),
                               math.cos(agent.yaw - previous_yaw))))
            largest_speed_step = max(
                largest_speed_step, abs(agent.air_v - previous_speed))
            previous_yaw, previous_speed = agent.yaw, agent.air_v
        self.assertLessEqual(largest_yaw_step, 0.4 * .1 + 1e-9)
        self.assertLessEqual(largest_speed_step, 2.0 * .1 + 1e-9)
        self.assertGreater(abs(agent.yaw - math.pi / 2), 1e-3)

    def test_stopped_tracked_target_requests_an_air_orbit(self):
        nav = NavMap((-100, -100, 100, 100), [])
        behavior = AreaReconBehavior(
            dict(job_id='J', pos=[0, 0]), nav, ['air'],
            params=dict(
                area=[[-50, -50], [50, -50], [50, 50], [-50, 50]],
                cell=10, coverage_target=.99,
                search_starts={'air': [0, 0]},
                sensor_radius_m={'ground': 5, 'air': 10},
                tracking_target=dict(
                    target_id='TRACK', start=[0, 0], goal=[60, 0],
                    move_after_s=0, speed_mps=10,
                    track_outside_s=100, stop_orbit_s=2),
                air_orbit_radius_m=3, search_limit_s=100))
        behavior.set_platform_caps({
            'air': dict(can_climb=True, kind='WING', speed=30)})
        behavior.detected_at = 0
        behavior.track_pid = 'air'
        behavior.target_entered_area = True
        behavior.coverage_reached = True
        behavior.t = 6.0
        point = behavior._track_target({'air': (60, 0, 0)}, .1)
        self.assertEqual(point, [60, 0])
        self.assertEqual(behavior.target_sample['status'], 'orbiting')
        self.assertEqual(behavior.target_sample['follow_point'], [60, 0])
        self.assertEqual(behavior.target_sample['orbit_radius'], 3.0)

    def test_stationary_orbit_is_not_restarted_each_control_step(self):
        nav = NavMap((-200, -200, 200, 200), [])
        behavior = StationBehavior(dict(job_id='J', pos=[0, 0]), nav, ['air'])
        runner = BehaviorRunner(nav, behavior, {'air': (0, 0)},
            speeds={'air': 4},
            caps={'air': dict(can_climb=True, kind='WING', start_z=25)})
        runner.step()
        orbit = runner.agents['air'].loiter
        self.assertIsNotNone(orbit)
        for _ in range(20):
            runner.step()
            self.assertIs(runner.agents['air'].loiter, orbit)

    def test_automatic_air_orbit_never_collapses_to_the_safety_floor(self):
        """A zero radius means automatic, not a 0.5 m fixed-wing pivot."""
        nav = NavMap((-200, -200, 200, 200), [])
        behavior = StationBehavior(
            dict(job_id='J', pos=[0, 0]), nav, ['air'],
            params=dict(air_orbit_radius_m=0, air_orbit_speed_mps=6,
                        air_bank_deg=15))
        runner = BehaviorRunner(
            nav, behavior, {'air': (-11, 0)},
            speeds={'air': 30},
            caps={'air': dict(can_climb=True, kind='WING', start_z=25)})

        runner.step()

        agent = runner.agents['air']
        self.assertIsNotNone(agent.loiter)
        self.assertGreaterEqual(agent.loiter.radius, 10.0)
        before = (agent.x, agent.y)
        for _ in range(10):
            runner.step()
        self.assertGreater(math.dist(before, (agent.x, agent.y)), 1.0)

    def test_moving_waypoint_does_not_trigger_a_second_orbit(self):
        for continuous in (False, True):
            with self.subTest(continuous=continuous):
                self._check_moving_waypoint(continuous)

    def _check_moving_waypoint(self, continuous):
        class MovingBehavior(Behavior):
            def step(self, poses, t, dt):
                angle = .07 * t
                return dict(targets={'air': [30 * math.cos(angle),
                                              30 * math.sin(angle)]},
                            done=False, phase='moving')

        nav = NavMap((-200, -200, 200, 200), [])
        behavior = MovingBehavior(dict(job_id='J', pos=[0, 0]), nav, ['air'])
        behavior.continuous = continuous
        runner = BehaviorRunner(nav, behavior, {'air': (30, 0)},
            speeds={'air': 30},
            caps={'air': dict(can_climb=True, kind='WING', start_z=25)})
        points = []
        for _ in range(60):
            runner.step()
            agent = runner.agents['air']
            points.append((agent.x, agent.y))
            if runner.time > 1:
                self.assertIsNone(agent.loiter)
        # Once motion is established, no large reversal between adjacent
        # one-second displacement vectors is permitted on this gentle arc.
        vectors = [(b[0]-a[0], b[1]-a[1]) for a,b in zip(points, points[1:])]
        for a, b in zip(vectors[2:], vectors[3:]):
            self.assertGreater(a[0]*b[0] + a[1]*b[1], 0)

    def test_circle_is_bounded_continuous_and_never_stalls(self):
        for speed in (.5, 4, 30):
            with self.subTest(speed=speed):
                orbit = AirLoiter((-5, 9), speed)
                pose = Pose(-5 + orbit.radius, 9, 25,
                            yaw=math.pi / 2 - orbit.max_yaw_rate * .05)
                previous_yaw = pose.yaw
                for _ in range(1200):
                    new, distance = orbit.step(pose, .1)
                    self.assertGreater(distance, 0)
                    self.assertLessEqual(distance, speed * .1 + 1e-8)
                    yaw_step = abs(math.atan2(
                        math.sin(new.yaw - previous_yaw),
                        math.cos(new.yaw - previous_yaw)))
                    self.assertLessEqual(yaw_step,
                                         orbit.max_yaw_rate * .1 + 1e-9)
                    if distance > 1e-9:
                        self.assertAlmostEqual(
                            math.atan2(new.y - pose.y, new.x - pose.x),
                            new.yaw, places=9)
                    self.assertEqual(new.z, 25)
                    previous_yaw = new.yaw
                    pose = new
                radius = math.hypot(pose.x + 5, pose.y - 9)
                self.assertAlmostEqual(
                    radius, orbit.radius,
                    delta=max(.5, orbit.radius * .03))

    def test_orbit_entry_does_not_reverse_the_aircraft_instantaneously(self):
        orbit = AirLoiter((0, 0), 30, radius=3)
        pose = Pose(3, 0, 10, yaw=0)
        previous_yaw = pose.yaw
        for _ in range(300):
            new, moved = orbit.step(pose, .1)
            self.assertGreater(moved, 0)
            yaw_step = abs(math.atan2(
                math.sin(new.yaw - previous_yaw),
                math.cos(new.yaw - previous_yaw)))
            self.assertLessEqual(yaw_step,
                                 orbit.max_yaw_rate * .1 + 1e-9)
            self.assertAlmostEqual(
                math.atan2(new.y - pose.y, new.x - pose.x),
                new.yaw, places=9)
            previous_yaw = new.yaw
            pose = new

    def test_real_task_feedback_moves_both_air_types_for_every_task_label(self):
        for kind in ('PLANE', 'WING'):
            for task_type in ('patrol', 'recon', 'blockade', 'hold', 'assault'):
                with self.subTest(kind=kind, task_type=task_type):
                    fleet = MockFleet(motion='real')
                    fleet.submit([wire(kind, task_type)], 0)
                    samples = [event for now in range(1, 25) for event in fleet.poll(now)
                               if event.get('phase') == 'work']
                    self.assertGreater(len(samples), 10)
                    self.assertTrue(all(a['pos'] != b['pos'] for a, b in zip(samples, samples[1:])))
                    self.assertTrue(all(row['z'] == 6 for row in samples))
                    self.assertEqual(samples[-1]['progress'] - samples[0]['progress'], len(samples) - 1)

    def test_ground_task_still_stays_at_its_station(self):
        fleet = MockFleet(motion='real')
        fleet.submit([wire('UGV')], 0)
        samples = [event['pos'] for now in range(1, 25) for event in fleet.poll(now)
                   if event.get('phase') == 'work']
        self.assertGreater(len(samples), 5)
        self.assertEqual(len(set(map(tuple, samples))), 1)

    def test_shared_behavior_runner_keeps_station_and_retargets_from_real_pose(self):
        nav = NavMap((-200, -200, 200, 200), [])
        for task_type in ('patrol', 'recon', 'blockade', 'hold', 'assault'):
            with self.subTest(task_type=task_type):
                behavior = StationBehavior(dict(job_id='J', pos=[0, 0]), nav, ['air', 'ground'])
                behavior.kind = task_type
                runner = BehaviorRunner(nav, behavior, {'air': (-8, 0), 'ground': (0, 0)},
                    speeds={'air': 4, 'ground': 1},
                    caps={'air': dict(can_climb=True, kind='WING', start_z=25)})
                points = []
                for _ in range(60):
                    done = runner.step()
                    points.append((runner.agents['air'].x, runner.agents['air'].y))
                    if done:
                        break
                self.assertTrue(done)
                self.assertTrue(all(math.dist(a, b) > 1e-6 for a, b in zip(points, points[1:])))
                self.assertEqual(runner.agents['ground'].odometer, 0)
                agent = runner.agents['air']
                self.assertTrue(runner._station_holds('air', [0, 0]))
                self.assertGreater(agent.odometer, 50)
                current = [agent.x, agent.y]
                runner._set_target(agent, [40, 0])
                self.assertIsNone(agent.loiter)
                self.assertEqual(agent.path[0], current)
                self.assertFalse(runner._station_holds('air', [0, 0]))

    def test_waiting_and_returning_aircraft_keep_moving_until_touchdown(self):
        fleet = MockFleet(motion='real', nav=NavMap((-200, -200, 200, 200), []),
                          home={'unit': (30, 0)})
        fleet.platforms['unit'] = dict(pos=(0, 0), z=6, yaw=0, battery=100,
            active=False, dead=False,
            return_profile=dict(can_climb=True, speed=4, move_cost=.1))
        for now in range(10):
            fleet.step_returns(now, {'unit'})
        waits = fleet.drain_behavior_events()
        self.assertEqual(len(waits), 10)
        self.assertTrue(all(a['pos'] != b['pos'] for a, b in zip(waits, waits[1:])))
        for now in range(10, 100):
            fleet.step_returns(now, set())
        returns = [r for r in fleet.drain_behavior_events() if r['kind'] == 'return_sample']
        self.assertTrue(all(a['pos'] != b['pos'] for a, b in zip(returns, returns[1:])
                            if a['z'] > 0 and b['z'] > 0))
        self.assertEqual(fleet.return_state['unit']['status'], 'returned')
        self.assertEqual(fleet.platforms['unit']['pos'], (30, 0))
        self.assertEqual(fleet.platforms['unit']['z'], 0)
        replay = build_replay_data(dict(platforms=[dict(robot_no=31, pid='unit', pos=[0, 0])], jobs=[]),
                                  dict(platforms=[], simulated_until_s=9),
                                  [dict(kind='behavior_event', sim_s=r['recorded_at_sim_s'], event=r) for r in waits])
        self.assertEqual(len(replay['workers'][0]['samples']), 10)
        self.assertEqual(replay['workers'][0]['samples'][-1]['phase'], 'loiter')

    def test_fixed_wing_return_captures_the_descent_orbit(self):
        fleet = MockFleet(motion='real', nav=NavMap((-200, -200, 200, 200), []),
                          home={'unit': (0, 0)})
        speed, yaw_rate = 30, .45
        radius = speed / (2 * math.sin(yaw_rate / 2))
        fleet.platforms['unit'] = dict(pos=(radius, 0), z=60,
            yaw=math.pi / 2 - yaw_rate / 2, battery=100, active=False, dead=False,
            return_profile=dict(can_climb=True, kind='PLANE', speed=speed, move_cost=.1))
        for now in range(100):
            fleet.step_returns(now, set())
        self.assertEqual(fleet.return_state['unit']['status'], 'returned')
        self.assertEqual(fleet.platforms['unit']['pos'], (0, 0))
        self.assertEqual(fleet.platforms['unit']['z'], 0)


if __name__ == '__main__':
    unittest.main()
