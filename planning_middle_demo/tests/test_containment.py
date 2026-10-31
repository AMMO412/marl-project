# -*- coding: utf-8 -*-
"""区域封控（T-SEC）测试：几何、分解、执行语义与回放载荷。

覆盖的结论边界：
  * 测的是"本地行为状态机 + 4.1 输入"的规则一致性，不是真实平台或
    Gazebo/ROS 联调；
  * 判定项的数值来自本层状态机记录，桩判定口径见 docs/区域封控任务.md。
"""

import json
import math
import unittest

import containment_geom as geom
from behaviors import ContainmentBehavior
from interop.model import Platform, Scenario, Task
from interop.templates import decompose
import trajectory_v2

RECT = [[0, 0], [100, 0], [100, 100], [0, 100]]


class _Nav:
    """最小可通行地图替身：不做绕障，只提供行为层必需的两个接口。"""

    bounds = (-500.0, -500.0, 500.0, 500.0)
    radius = 1.0

    def nearest_free(self, point, max_radius=4.0):
        return [float(point[0]), float(point[1])], 0.0

    def free(self, point, radius=None):
        return True


def _params(**overrides):
    base = dict(
        area=RECT,
        gates=[dict(gate_id="G1", point=[50, 0], width=10, direction=[0, 1])],
        roles={"boundary": 1, "gate": 1, "intercept": 1},
        standoff_m=10.0,
        gate_standoff_m=6.0,
        sensor_radius_m=45.0,
        control_level="block",
        engagement_authority="on_order",
        control_objective="deny_entry",
        duration_s=40.0,
        max_leak_rate=0.0,
        max_steps=200,
        intruders=[],
    )
    base.update(overrides)
    return base


def _intruder(**overrides):
    spec = dict(target_id="IN-1", start=[50, -40], goal=[50, 50],
                speed_mps=2.0, t_start_s=0, authorized=False, compliance=False)
    spec.update(overrides)
    return spec


def _run(behavior, steps=80):
    """平台按行为层给出的目标点"瞬移到位"，把决策与运动解耦便于断言。"""
    poses = {pid: (behavior.posts[pid][0], behavior.posts[pid][1], 0.0)
             for pid in behavior.pids}
    for t in range(steps):
        out = behavior.step(poses, float(t), 1.0)
        for pid, target in out["targets"].items():
            poses[pid] = (float(target[0]), float(target[1]), 0.0)
        if out["done"]:
            break
    return behavior


def _kinds(behavior):
    return [event["kind"] for event in behavior.history]


class GeometryTests(unittest.TestCase):
    def test_perimeter_and_equal_sectors(self):
        self.assertAlmostEqual(geom.perimeter(geom.as_polygon(RECT)), 400.0)
        sectors = geom.split_sectors(RECT, 2)
        self.assertAlmostEqual(sectors[0][1] - sectors[0][0], 200.0)
        self.assertAlmostEqual(sectors[1][1] - sectors[1][0], 200.0)

    def test_posts_sit_inside_the_responsible_sector(self):
        posts = geom.sector_posts(RECT, 2, standoff=10.0)
        self.assertEqual(len(posts), 2)
        for post in posts:
            self.assertTrue(geom.inside(RECT, post["post"]))
            distance = geom.arc_of_point(RECT, post["post"])["distance"]
            self.assertAlmostEqual(distance, 10.0, places=3)
        # 段中点落在顶点时沿弧长挪开，不会把阵地摆在相邻边上
        for post in posts:
            self.assertNotIn(post["mid"], [[0, 0], [100, 0], [100, 100], [0, 100]])

    def test_coverage_ratio_counts_observers_only(self):
        samples = geom.boundary_samples(RECT, 10.0)
        self.assertEqual(geom.coverage_ratio(samples, [], 30.0), 0.0)
        self.assertAlmostEqual(
            geom.coverage_ratio(samples, [(50.0, 50.0)], 30.0), 0.0)
        full = geom.coverage_ratio(samples, [(50.0, 50.0), (0.0, 50.0),
                                             (100.0, 50.0), (50.0, 0.0),
                                            (50.0, 100.0)], 60.0)
        self.assertAlmostEqual(full, 1.0)

    def test_gate_channel_is_perpendicular_to_direction(self):
        line = geom.gate_channel((50, 0), (0, 1), 10)
        self.assertAlmostEqual(line[0][1], 0.0)
        self.assertAlmostEqual(line[1][1], 0.0)
        self.assertAlmostEqual(abs(line[1][0] - line[0][0]), 10.0)


class DecomposeTests(unittest.TestCase):
    def _scenario(self, params):
        platforms = [
            Platform(unit_id="U%d" % i, robot_id=i, platform_class="UGV",
                    position=(0.0, 0.0), speed_mps=8.0, endurance_s=1e9,
                    capabilities={"HLD": 2})
            for i in (1, 2, 3)]
        task = Task(task_id="T1", task_type="T-SEC", priority=1,
                    target={"defense_area": RECT}, window_start_s=0.0,
                    window_end_s=600.0, required_capabilities={"HLD": 1},
                    min_units=3, max_units=3, params=params)
        return Scenario(formation_id="F-TEST", platforms=platforms, tasks=[task])

    def test_roles_split_into_boundary_gate_and_intercept(self):
        params = dict(params=_params())
        params.update(**params.pop("params"))
        subtasks = decompose(self._scenario(params))
        roles = [s.role for s in subtasks]
        self.assertEqual(len(subtasks), 3)
        self.assertIn("boundary:1/1", roles)
        self.assertIn("gate:G1", roles)
        self.assertIn("intercept:standby", roles)
        for subtask in subtasks:
            self.assertEqual(list(subtask.target.keys()), ["point"])

    def test_role_count_is_capped_by_max_units(self):
        params = _params()
        params["roles"] = {"boundary": 3, "gate": 2, "intercept": 1}
        scenario = self._scenario(params)
        scenario.tasks[0].max_units = 4
        subtasks = decompose(scenario)
        self.assertEqual(len(subtasks), 4)
        # 兵力上限先砍预备队/边界段：两个通道口各留一个哨位，机动组保留
        roles = [s.role for s in subtasks]
        self.assertEqual(sum(r.startswith("boundary") for r in roles), 1)
        self.assertEqual(sum(r.startswith("gate") for r in roles), 2)
        self.assertEqual(sum(r.startswith("intercept") for r in roles), 1)

    def test_legacy_entry_points_still_supported(self):
        scenario = self._scenario({"entry_points": [[10, 0], [90, 0]],
                                   "hold_duration_s": 60})
        subtasks = decompose(scenario)
        self.assertEqual([s.target for s in subtasks],
                         [{"point": [10.0, 0.0]}, {"point": [90.0, 0.0]}])
        self.assertTrue(all(s.role == "" for s in subtasks))


class ContainmentBehaviorTests(unittest.TestCase):
    def test_control_established_and_boundary_coverage_recorded(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(),
            ["p1", "p2", "p3"], _params(duration_s=10.0)))
        kinds = _kinds(behavior)
        self.assertIn("control_established", kinds)
        metrics = behavior.metrics
        self.assertGreater(metrics["boundary_coverage"], 0.0)
        self.assertGreater(metrics["occupancy_ratio"], 0.9)
        self.assertEqual(metrics["control_established_at_s"], 0.0)

    def test_unauthorized_target_is_warned_then_intercepted(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(intruders=[_intruder()], duration_s=40.0)))
        kinds = _kinds(behavior)
        for kind in ("target_detected", "target_unauthorized",
                     "warning_issued", "intercept_assigned", "intercepted"):
            self.assertIn(kind, kinds, kinds)
        metrics = behavior.metrics
        self.assertEqual(metrics["unauthorized_entries"], 0)
        self.assertEqual(metrics["leak_rate"], 0.0)
        self.assertEqual(metrics["intercepted"], 1)
        self.assertEqual(behavior.verdict["verdict"], "succeeded")

    def test_warning_only_level_records_leak(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(intruders=[_intruder()], control_level="warn",
                    duration_s=60.0)))
        kinds = _kinds(behavior)
        self.assertIn("warning_issued", kinds)
        self.assertNotIn("intercepted", kinds)
        self.assertIn("breach", kinds)
        metrics = behavior.metrics
        self.assertEqual(metrics["unauthorized_entries"], 1)
        self.assertEqual(metrics["leak_rate"], 1.0)
        self.assertEqual(behavior.verdict["verdict"], "failed")

    def test_authorized_target_passes_without_warning(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(intruders=[_intruder(target_id="AU-1", authorized=True)],
                    duration_s=40.0)))
        kinds = _kinds(behavior)
        self.assertIn("authorized_pass", kinds)
        self.assertNotIn("warning_issued", kinds)
        self.assertNotIn("intercepted", kinds)
        self.assertEqual(behavior.metrics["authorized_passes"], 1)
        self.assertEqual(behavior.metrics["false_intercepts"], 0)

    def test_no_targets_yields_pending_verdict(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(intruders=[], duration_s=10.0)))
        self.assertEqual(behavior.verdict["verdict"], "pending")
        self.assertIn("状态维持", behavior.verdict["reason"])

    def test_embargo_authority_blocks_interception(self):
        behavior = _run(ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(intruders=[_intruder()], engagement_authority="none",
                    duration_s=60.0)))
        kinds = _kinds(behavior)
        self.assertIn("intercept_denied", kinds)
        self.assertNotIn("intercepted", kinds)

    def test_boundary_posts_patrol_within_their_sector(self):
        """在岗不等于钉在原地：沿负责的段巡视，但始终在自己的段内。"""
        behavior = ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(duration_s=120.0))
        poses = {pid: (behavior.posts[pid][0], behavior.posts[pid][1], 0.0)
                 for pid in behavior.pids}
        boundary = next(pid for pid in behavior.pids
                        if behavior.roles[pid].startswith("boundary"))
        seen = set()
        out = None
        for t in range(60):
            out = behavior.step(poses, float(t), 1.0)
            for pid, target in out["targets"].items():
                poses[pid] = (float(target[0]), float(target[1]), 0.0)
            if t >= 3:
                seen.add((round(poses[boundary][0], 1),
                          round(poses[boundary][1], 1)))
            self.assertTrue(behavior._is_on_post(boundary, poses[boundary]))
        self.assertGreater(len(seen), 8)
        self.assertIn("speed_scale", out)
        self.assertLess(out["speed_scale"][boundary], 1.0)

    def test_air_watch_orbits_and_carries_altitude(self):
        roles = {"p1": "boundary:1/1", "p2": "gate:G1",
                 "p3": "intercept:standby", "p4": "air:watch"}
        behavior = ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(),
            ["p1", "p2", "p3", "p4"],
            _params(roles=roles, duration_s=30.0,
                    air_altitude_m=60, air_orbit_radius_m=40))
        self.assertEqual(behavior.air_pids, ["p4"])
        self.assertEqual(behavior.params["air_altitude"]["p4"], 60)
        self.assertTrue(behavior.roles["p4"].startswith("air"))
        orbit = behavior._patrol_target("p4", 0.0)
        self.assertAlmostEqual(
            math.hypot(orbit[0] - behavior.center[0],
                       orbit[1] - behavior.center[1]), 40.0, places=2)
        # 空中监视也算观察者：封控区上方盘旋即提供覆盖
        poses = {pid: (behavior.posts[pid][0], behavior.posts[pid][1], 0.0)
                 for pid in behavior.pids}
        poses["p4"] = (orbit[0], orbit[1], 0.0)
        behavior.step(poses, 0.0, 1.0)
        self.assertGreater(behavior._last_coverage, 0.0)
        self.assertEqual(behavior.metrics.get("air_units"), 1)

    def test_losing_a_post_records_control_interruption(self):
        behavior = ContainmentBehavior(
            dict(job_id="T1", pos=[50, 50]), _Nav(), ["p1", "p2", "p3"],
            _params(duration_s=30.0))
        poses = {pid: (behavior.posts[pid][0], behavior.posts[pid][1], 0.0)
                 for pid in behavior.pids}
        behavior.step(poses, 0.0, 1.0)
        behavior.report_loss("p1", 1.0)
        for t in range(1, 12):
            behavior.step(poses, float(t), 1.0)
        self.assertIn("member_lost", _kinds(behavior))
        self.assertGreaterEqual(behavior.metrics.get("our_losses", 0), 1)


class ContainmentReplayTests(unittest.TestCase):
    def _trace(self):
        structure = dict(kind="behavior_structure", type="blockade",
                         job_id="T1", area=RECT, posts=[[50.0, 10.0]],
                         post_plan=[], gates=[], roles={}, sim_s=0)
        result = dict(kind="containment_result", verdict="succeeded",
                      reason="ok", items=[], metrics={}, targets=[],
                      timeline=[])
        return [
            dict(kind="behavior_event", sim_s=0, event=structure),
            dict(kind="behavior_event", sim_s=5,
                 event=dict(kind="control_established", t=5.0)),
            dict(kind="behavior_event", sim_s=9,
                 event=result),
        ]

    def test_replay_extracts_structure_result_and_events(self):
        payload = trajectory_v2._containment_replay(self._trace())
        self.assertIsNotNone(payload)
        self.assertEqual(payload["job_id"], "T1")
        self.assertEqual(payload["result"]["verdict"], "succeeded")
        self.assertEqual([e["kind"] for e in payload["events"]],
                         ["control_established"])

    def test_no_structure_means_no_containment_page_data(self):
        self.assertIsNone(trajectory_v2._containment_replay(
            [dict(kind="behavior_event", sim_s=0,
                  event=dict(kind="phase", phase="机动"))]))

    def test_event_names_cover_every_recorded_kind(self):
        for kind in trajectory_v2.CONTAINMENT_EVENTS:
            self.assertIn(kind, trajectory_v2.BEHAVIOR_EVENT_NAME)


class ScenarioSampleTests(unittest.TestCase):
    """4.1 样例必须能直接解析、分解并跑到判定，避免样例与实现漂移。"""

    MESSAGE = ("interop/scenarios/area_containment.message.json",
               "interop/scenarios/area_containment.formation.json")

    def test_sample_decomposes_to_five_roles(self):
        from interop.message import load_scenario
        scenario = load_scenario(self.MESSAGE[0], self.MESSAGE[1])
        subtasks = decompose(scenario)
        roles = sorted(s.role for s in subtasks)
        self.assertEqual(len(subtasks), 6)
        self.assertEqual(sum(r.startswith("boundary") for r in roles), 2)
        self.assertEqual(sum(r.startswith("gate") for r in roles), 2)
        self.assertEqual(sum(r.startswith("intercept") for r in roles), 1)
        self.assertEqual(sum(r.startswith("air") for r in roles), 1)

    def test_sample_to_v2_carries_behavior_params(self):
        from interop.message import load_scenario
        from interop.runtime import to_v2_dict
        scenario = load_scenario(self.MESSAGE[0], self.MESSAGE[1])
        data = to_v2_dict(scenario)
        job = data["jobs"][0]
        self.assertEqual(job["_task_type"], "T-SEC")
        behavior = job["_behavior"]
        self.assertEqual(len(behavior["area"]), 4)
        self.assertEqual(behavior["control_level"], "block")
        self.assertEqual(len(behavior["intruders"]), 3)
        # 空中监视的高度层与盘旋参数要随运行视图下发
        self.assertEqual(behavior["air_altitude_m"], 60)
        self.assertEqual(behavior["air_unit"], "U6")
        # 场景要能通过 v2 契约校验（否则工作台运行会在构造阶段就被拒绝）
        from contracts_v2 import check_scenario_v2
        check_scenario_v2(json.loads(json.dumps(data)))


if __name__ == "__main__":
    unittest.main()
