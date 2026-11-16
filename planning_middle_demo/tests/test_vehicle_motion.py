# -*- coding: utf-8 -*-
"""运动学限幅、路径圆角与 4.2 指令平滑的回归测试。"""
import math
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from city_nav import PathFollower
from behavior_runtime import BehaviorRunner
from interop.limited_motion import coalesce, simulate_path
from motion import DriveGains, GoalController, Pose
from path_smoothing import sharp_corners, smooth_corners
from vehicle_kinematics import limits_for, turn_radius_for


def platform(kind, speed):
    return SimpleNamespace(platform_class=kind, speed_mps=speed)


class KinematicsTests(unittest.TestCase):
    def test_ground_can_pivot_and_air_cannot(self):
        self.assertTrue(limits_for('UGV', 0.8).can_pivot)
        self.assertTrue(limits_for('TANK', 1.0).can_pivot)
        self.assertFalse(limits_for('PLANE', 2.0).can_pivot)
        self.assertFalse(limits_for('WING', 1.6).can_pivot)

    def test_faster_platform_has_larger_turn_radius(self):
        slow = limits_for('UGV', 0.8)
        fast = limits_for('UGV', 8.0)
        self.assertEqual(fast.max_yaw_rate, slow.max_yaw_rate)
        self.assertGreater(turn_radius_for('UGV', 8.0), turn_radius_for('UGV', 0.8))
        self.assertGreater(limits_for('PLANE', 2.0).min_turn_radius, 2.0)


class SmoothingTests(unittest.TestCase):
    def test_right_angle_gets_rounded_and_keeps_endpoints(self):
        path = [[0, 0], [10, 0], [10, 10]]
        result = smooth_corners(path, 2.0)
        self.assertEqual(tuple(result[0]), (0.0, 0.0))
        self.assertEqual(tuple(result[-1]), (10.0, 10.0))
        self.assertFalse(sharp_corners(result, 25.0),
                         '圆角后不应再有大于 25° 的单点转角')

    def test_blocked_curve_falls_back_to_sharp_corner(self):
        path = [[0, 0], [10, 0], [10, 10]]
        result = smooth_corners(path, 2.0, free_point=lambda p: False)
        self.assertEqual(result, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])


class ControllerTests(unittest.TestCase):
    def test_goal_controller_ramps_angular_velocity(self):
        gains = DriveGains(max_linear=0.8, max_angular=0.7,
                           max_angular_accel=1.4, max_lateral_accel=0.8)
        ctl = GoalController(gains)
        pose = Pose(0, 0, 0, 0)
        goal = Pose(0, -10, 0, 0)       # 目标在正后方
        dt = 1.0 / 20
        first = ctl.update(pose, goal, dt=dt)
        self.assertLessEqual(abs(first.angular_z), 1.4 * dt + 1e-9)
        previous = first.angular_z
        for _ in range(40):
            tw = ctl.update(pose, goal, dt=dt)
            self.assertLessEqual(abs(tw.angular_z - previous), 1.4 * dt + 1e-9)
            previous = tw.angular_z

    def test_path_follower_turns_and_reaches_goal(self):
        limits = limits_for('UGV', 0.8)
        follower = PathFollower(max_linear=0.8, max_angular=limits.max_yaw_rate,
                                max_angular_accel=limits.max_yaw_accel,
                                max_lateral_accel=limits.max_lateral_accel,
                                lookahead=1.0, waypoint_tol=0.6)
        path = smooth_corners([[0, 0], [6, 0], [6, 6]], 1.2)
        state = follower.reset()
        x, y, yaw = 0.0, 0.0, 0.0
        previous_w = 0.0
        for _ in range(2000):
            v, w, state = follower.step((x, y, yaw), path, state, None, 0.1)
            self.assertLessEqual(abs(w), limits.max_yaw_rate + 1e-9)
            self.assertLessEqual(abs(w - previous_w),
                                 limits.max_yaw_accel * 0.1 + 1e-9)
            previous_w = w
            if state.done:
                break
            yaw += w * 0.1
            x += v * math.cos(yaw) * 0.1
            y += v * math.sin(yaw) * 0.1
        self.assertTrue(state.done)
        self.assertLess(math.hypot(x - 6, y - 6), 0.8)

    def test_trailing_ground_agent_yields_instead_of_stacking(self):
        behavior = SimpleNamespace(
            params={}, pids=['rover_09', 'rover_10'],
            job_id='TEST-CONVOY', site=[0.0, 0.0])
        nav = SimpleNamespace(radius=1.0)
        runner = BehaviorRunner(
            nav, behavior,
            {'rover_09': (0.0, 0.0), 'rover_10': (-1.0, 0.0)},
            speeds={'rover_09': 8.0, 'rover_10': 8.0})
        runner.agents['rover_09'].target = [10.0, 0.0]
        runner.agents['rover_10'].target = [10.0, 0.0]
        self.assertEqual(
            runner._ground_separation_scale(runner.agents['rover_09']), 1.0)
        self.assertEqual(
            runner._ground_separation_scale(runner.agents['rover_10']), 0.0)
        runner.agents['rover_10'].x = -4.0
        self.assertEqual(
            runner._ground_separation_scale(runner.agents['rover_10']), 1.0)

    def test_ground_agent_yields_to_cross_job_peer(self):
        behavior = SimpleNamespace(
            params={}, pids=['rover_10'],
            job_id='TEST-CROSS-JOB', site=[0.0, 0.0])
        runner = BehaviorRunner(
            SimpleNamespace(radius=1.0), behavior,
            {'rover_10': (0.0, 0.0)}, speeds={'rover_10': 8.0})
        agent = runner.agents['rover_10']
        agent.target = [10.0, 0.0]
        runner.peer_ground_positions = {'rover_09': (0.5, 0.0)}
        self.assertEqual(runner._ground_separation_scale(agent), 0.0)
        runner.peer_ground_positions = {'rover_09': (5.0, 0.0)}
        self.assertEqual(runner._ground_separation_scale(agent), 1.0)


class CommandProfileTests(unittest.TestCase):
    def test_ground_command_profile_has_no_step_changes(self):
        ugv = platform('UGV', 0.8)
        limits = limits_for(ugv)
        plan = simulate_path([[0, 0], [8, 0], [8, 8]], ugv, 0.0, 0.8)
        samples = coalesce(plan.samples)
        self.assertTrue(samples)
        self.assertLess(plan.duration_s, 100.0)
        for sample in samples:
            self.assertLessEqual(abs(sample.vx), 0.8 + 1e-6)
            self.assertLessEqual(abs(sample.wz), limits.max_yaw_rate + 1e-6)
        for a, b in zip(samples, samples[1:]):
            self.assertLessEqual(abs(b.vx - a.vx),
                                 limits.max_decel * 0.2 + 1e-6)
            self.assertLessEqual(abs(b.wz - a.wz),
                                 limits.max_yaw_accel * 0.2 + 1e-6)

    def test_air_initial_reverse_turn_is_ramped(self):
        plane = platform('PLANE', 2.0)
        limits = limits_for(plane)
        plan = simulate_path([[0, 0], [12, 0]], plane, math.pi, 2.0)
        samples = coalesce(plan.samples)
        self.assertTrue(samples)
        for sample in samples:
            self.assertLessEqual(abs(sample.wz), limits.max_yaw_rate + 1e-6)
        for a, b in zip(samples, samples[1:]):
            self.assertLessEqual(abs(b.wz - a.wz),
                                 limits.max_yaw_accel * 0.2 + 1e-6)


if __name__ == '__main__':
    unittest.main()
