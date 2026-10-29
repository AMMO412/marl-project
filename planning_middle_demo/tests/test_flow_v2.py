# -*- coding: utf-8 -*-
"""test_flow_v2.py —— 规划能力版（v2）测试。

两层覆盖：
  1. 消息骨架纪律（沿用 v1，逐条核对）
  2. 规划器不变量（六步规则，含已踩坑修复回归）
"""
import ast
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts_v2 import check_scenario_v2
from coordinator_v2 import CoordinatorV2
from mock_fleet import MockFleet
import planner_v2
from planner_v2 import Assignment, Plan
import fleet
from contracts_v2 import Job, Platform


def scenario():
    """复用 fleet_demo.json 的前 4 个作业，保证作业点靠近对应能力的平台。"""
    data = json.loads(
        (ROOT / "scenarios/fleet_demo.json").read_text(encoding="utf-8"))
    data["jobs"] = data["jobs"][:4]
    return data


class FeedbackTests(unittest.TestCase):
    def _first_command(self, core, fleet, until=40):
        """推进直到中间层发出第一条指令，返回 (now, 指令消息列表)。"""
        for now in range(until):
            for event in fleet.poll(now):
                core.receive(event, now)
            cmds = core.step(now)
            for event in fleet.submit(cmds, now):
                core.receive(event, now)
            if cmds and any(c["command"]["action"] == "start" for c in cmds):
                return now, cmds
        raise AssertionError("推进 %d 步仍无指令下发" % until)

    def test_peer_cannot_mutate_core_without_feedback(self):
        core, fleet = CoordinatorV2(scenario()), MockFleet()
        now, messages = self._first_command(core, fleet)
        fleet.submit(messages, now)
        events = fleet.poll(now + 20)
        self.assertNotEqual(core.jobs["J1"].status, "succeeded")
        for event in events:
            core.receive(event, now + 20)

    def test_duplicate_result_does_not_double_apply(self):
        core, fleet = CoordinatorV2(scenario()), MockFleet()
        now, messages = self._first_command(core, fleet)
        fleet.submit(messages, now)
        result = fleet.poll(now + 30)[0]
        core.receive(result, now + 30)
        self.assertFalse(core.receive(result, now + 30))

    def test_identity_mismatch_and_incomplete_success_rejected(self):
        for field, value in (("run_id", "other"), ("worker_id", "rover_99"),
                             ("attempt", 99), ("progress", -1)):
            core, fleet = CoordinatorV2(scenario()), MockFleet()
            now, messages = self._first_command(core, fleet)
            event = fleet.submit(messages, now)[0]
            event[field] = value
            self.assertFalse(core.receive(event, now), field)
        core, fleet = CoordinatorV2(scenario()), MockFleet()
        now, messages = self._first_command(core, fleet)
        event = fleet.submit(messages, now)[0]
        event.update(status="succeeded", progress=1)
        self.assertFalse(core.receive(event, now))
        self.assertNotEqual(core.jobs["J1"].status, "succeeded")

    def test_malformed_feedback_does_not_crash(self):
        core, fleet = CoordinatorV2(scenario()), MockFleet()
        now, messages = self._first_command(core, fleet)
        accepted = fleet.submit(messages, now)[0]
        before = copy.deepcopy(core.report())
        for event in ([], None, dict(accepted, command_id=[])):
            self.assertFalse(core.receive(event, now))
        self.assertEqual(core.report(), before)

    def test_member_lost_releases_inflight_without_waiting(self):
        core, fleet = CoordinatorV2(scenario()), MockFleet()
        now, _messages = self._first_command(core, fleet)
        pid = None
        for a in (core.plan.assignments if core.plan else []):
            if a.pids:
                pid = a.pids[0]
                break
        self.assertIsNotNone(pid)
        self.assertTrue(core.notify_member_lost(pid, now + 1))
        self.assertFalse(core.platforms[pid].alive)
        self.assertNotIn(pid, core.platform_cmd)


class PlannerInvariantTests(unittest.TestCase):
    def _plats(self):
        from contracts_v2 import build_platforms
        return build_platforms(scenario())

    def _jobs(self):
        from contracts_v2 import build_jobs
        return build_jobs(scenario())

    def test_serial_no_overlap(self):
        pl, _ = planner_v2.plan(self._plats(), self._jobs(), 0, H=20)
        by_pid = {}
        for a in pl.assignments:
            for pid in a.pids:
                by_pid.setdefault(pid, []).append((a.start, a.end))
        for pid, spans in by_pid.items():
            spans.sort()
            for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
                self.assertLessEqual(e0, s1, "平台 %s 串行被破坏" % pid)

    def test_altitude_requires_air_platform(self):
        plats, jobs = self._plats(), self._jobs()
        # 造一个带高度、crew=1 的作业，只允许 PLANE/WING 接
        j = Job(job_id="ALT", jtype="recon", pos=(50, 50), work=10.0,
                window=(0, 60), crew=1, need_payload=0.0,
                need_sensor="sar", altitude=30)
        pl, events = planner_v2.plan(plats, [j], 0, H=20)
        for a in pl.assignments:
            for pid in a.pids:
                self.assertTrue(plats[[p.pid for p in plats].index(pid)].can_climb)

    def test_crew_short_is_reported(self):
        plats, jobs = self._plats(), self._jobs()
        # crew=8 超过任何可用平台数，必须上报结构性不足
        j = Job(job_id="BIG", jtype="assault", pos=(50, 50), work=20.0,
                window=(0, 90), crew=8, need_payload=4.0,
                need_sensor=None, altitude=0)
        pl, events = planner_v2.plan(plats, [j], 0, H=20)
        self.assertEqual(pl.assignments, [])
        self.assertTrue(any(e.get("need_report") for e in events))

    def test_optimal_not_worse_than_greedy(self):
        plats, jobs = self._plats(), self._jobs()
        single = [j for j in jobs if j.crew == 1]
        pl, events = planner_v2.plan(plats, single, 0, H=20)
        solves = [e for e in events if e["kind"] == "assign_solve"]
        if solves:
            s = solves[0]
            self.assertLessEqual(s["optimal"], s["greedy"] + 1e-6)

    def test_plan_rejects_over_window(self):
        plats, jobs = self._plats(), self._jobs()
        # 窗口极窄、距离极远：必超窗，须 reject 或 defer
        j = Job(job_id="FAR", jtype="patrol", pos=(99, 99), work=12.0,
                window=(0, 5), crew=1, need_payload=0.0,
                need_sensor="eo", altitude=0)
        pl, events = planner_v2.plan(plats, [j], 0, H=20)
        self.assertNotIn("FAR", [a.job_id for a in pl.assignments])


class ScenarioTests(unittest.TestCase):
    def test_scenario_rejects_private_capability_override(self):
        data = scenario()
        data["platforms"][0]["speed"] = 99.0
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_scenario_rejects_unknown_job_field(self):
        data = scenario()
        data["jobs"][0]["secret"] = True
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_python38_syntax_and_no_legacy_dependency(self):
        for path in ROOT.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            ast.parse(text, feature_version=(3, 8))
            self.assertNotIn("import rclpy", text)
            self.assertNotIn("from planning ", text)
            self.assertNotIn("import planning", text)

    def test_fleet_facts(self):
        self.assertEqual(fleet.FLEET_SIZE, 50)
        self.assertEqual(fleet.kind_of(1), "UGV")
        self.assertEqual(fleet.kind_of(31), "PLANE")
        self.assertEqual(fleet.kind_of(41), "WING")
        self.assertEqual(fleet.topic_of(7), "/rover_07/cmd_vel")
        self.assertTrue(fleet.PLANNING_PARAMS["PLANE"]["can_climb"])
        self.assertFalse(fleet.PLANNING_PARAMS["UGV"]["can_climb"])


class EndToEndTests(unittest.TestCase):
    def test_normal_mode_completes(self):
        from run_demo_v2 import simulate
        report, trace = simulate(scenario(), "normal", max_ticks=60)
        self.assertTrue(report["all_succeeded"], report["jobs"])
        self.assertEqual(report["active_commands"], 0)

    def test_failure_mode_retries_once(self):
        from run_demo_v2 import simulate
        report, _ = simulate(scenario(), "failure", max_ticks=80)
        self.assertTrue(report["all_succeeded"])
        self.assertEqual(report["retries"], 1)

    def test_kill_mode_handles_member_loss(self):
        from run_demo_v2 import simulate
        report, trace = simulate(scenario(), "kill", max_ticks=80)
        self.assertTrue(any(e["kind"] == "member_lost" for e in trace))


class RealMotionTests(unittest.TestCase):
    """真实运动语义（motion="real"）：GoalController 闭环、带高度爬升、
    转向耗时、travel 与运动层同源。"""

    def test_real_motion_completes(self):
        from run_demo_v2 import simulate
        report, trace = simulate(scenario(), "normal", max_ticks=200,
                                 motion="real")
        self.assertTrue(report["all_succeeded"], report["jobs"])

    def test_real_motion_travel_accounts_turn(self):
        """真实运动下 travel 估算要考虑平台当前朝向（先转后走）。"""
        import motion
        # 同一起点，朝向相反：转向耗时不同，travel 应不同
        straight = motion.estimate_arrival_steps(
            (0, 0, 0, 0.0), (20, 0, 0, 0.0), max_linear=1.0, can_climb=False)
        turned = motion.estimate_arrival_steps(
            (0, 0, 0, 3.0), (20, 0, 0, 0.0), max_linear=1.0, can_climb=False)
        self.assertGreaterEqual(turned, straight)

    def test_real_motion_travel_accounts_climb(self):
        """带高度作业的真实 travel 应大于纯水平距离（爬升耗时）。"""
        import motion
        flat = motion.estimate_arrival_steps(
            (0, 0, 0, 0.0), (10, 0, 0, 0.0), max_linear=2.0, can_climb=True)
        climb = motion.estimate_arrival_steps(
            (0, 0, 0, 0.0), (10, 0, 30, 0.0), max_linear=2.0, can_climb=True)
        self.assertGreater(climb, flat)

    def test_real_motion_invalid_mode_rejected(self):
        from run_demo_v2 import simulate
        with self.assertRaises(ValueError):
            simulate(scenario(), "normal", motion="flying")


class RealSceneTests(unittest.TestCase):
    """真实城市场景（simple_city.json，源自 OSRF citysim）：
    _ 前缀元数据透传、H/K 从场景读取、真实坐标跑通。"""

    def _load(self):
        return json.loads(
            (ROOT / "scenarios/simple_city.json").read_text(encoding="utf-8"))

    def test_scene_meta_fields_transparent(self):
        """_ 前缀元数据字段（来源坐标/地标）应通过校验，不参与规划。"""
        data = self._load()
        check_scenario_v2(data)  # 不应抛错
        # 平台和作业的 _src_xy_m 元数据保留，但不进入 Platform/Job 对象
        from contracts_v2 import build_platforms, build_jobs
        plats = build_platforms(data)
        jobs = build_jobs(data)
        self.assertEqual(len(plats), 10)
        self.assertEqual(len(jobs), 6)
        # Platform/Job 对象不应携带 _src 元数据（仅场景文件追溯用）
        self.assertFalse(hasattr(plats[0], "_src_xy_m"))

    def test_scene_H_K_read_from_file(self):
        """场景文件声明的 H/K 应被 simulate 采用（而非默认 20/5）。"""
        from run_demo_v2 import simulate
        data = self._load()
        report, _ = simulate(data, "normal", max_ticks=60)
        self.assertEqual(report["H"], data["H"])
        self.assertEqual(report["K"], data["K"])

    def test_real_scene_normal_completes(self):
        """真实城市场景在瞬移语义下应 6/6 完成。"""
        from run_demo_v2 import simulate
        report, _ = simulate(self._load(), "normal", max_ticks=80)
        self.assertTrue(report["all_succeeded"], report["jobs"])

    def test_real_scene_real_motion_completes(self):
        """真实城市场景在真实运动语义下应 6/6 完成。"""
        from run_demo_v2 import simulate
        report, _ = simulate(self._load(), "normal", max_ticks=200,
                             motion="real")
        self.assertTrue(report["all_succeeded"], report["jobs"])


if __name__ == "__main__":
    unittest.main()
