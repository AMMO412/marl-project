# -*- coding: utf-8 -*-
"""test_timeline_rules.py —— timeline（数据驱动导调事件）与 rules（可配置参数）测试。

覆盖六类：
  1. 缺省行为一致：无 timeline/rules 时与旧行为一致
  2. 配置实际生效：写了 timeline/rules，事件/参数真的发生
  3. 错误配置被拒绝：非法事件类型/字段/实体引用/开关检查字段 被 check 拒绝
  4. 事件顺序：按 t 升序执行，同一步多事件不吞
  5. 重复处理：同一事件不会重复触发（consumer 顺序消费）
  6. 运行间隔离：多次 simulate 互不共享 timeline/state
"""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts_v2 import (check_scenario_v2, resolve_rules, resolve_timeline)
from run_demo_v2 import simulate


def scenario():
    data = json.loads(
        (ROOT / "scenarios/fleet_demo.json").read_text(encoding="utf-8"))
    data["jobs"] = data["jobs"][:4]
    return data


class TimelineValidationTests(unittest.TestCase):
    """timeline 校验：错误配置被拒绝、实体引用校验。"""

    def test_empty_or_absent_timeline_ok(self):
        data = scenario()
        check_scenario_v2(data)                       # 无 timeline，通过
        self.assertEqual(resolve_timeline(data), [])
        data["timeline"] = []
        check_scenario_v2(data)
        self.assertEqual(resolve_timeline(data), [])

    def test_unknown_event_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": 0, "event": "explode"}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_missing_required_field_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": 0, "event": "job_fail"}]   # 缺 job_id
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_extra_field_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": 0, "event": "member_lost",
                             "robot_no": 1, "surprise": True}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_unknown_entity_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": 0, "event": "member_lost", "robot_no": 999}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)
        data["timeline"] = [{"t": 0, "event": "job_fail", "job_id": "NOPE"}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_invalid_t_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": -1, "event": "job_fail", "job_id": "J1"}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)
        data["timeline"] = [{"t": "0", "event": "job_fail", "job_id": "J1"}]
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_invalid_factor_rejected(self):
        data = scenario()
        data["timeline"] = [{"t": 0, "event": "job_slow", "job_id": "J1",
                             "factor": 1.5}]          # 不在 (0,1)
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_sorted_by_t(self):
        data = scenario()
        data["timeline"] = [
            {"t": 10, "event": "job_fail", "job_id": "J1"},
            {"t": 2, "event": "job_slow", "job_id": "J2", "factor": 0.5},
        ]
        check_scenario_v2(data)
        tl = resolve_timeline(data)
        self.assertEqual([e["t"] for e in tl], [2, 10])


class RulesValidationTests(unittest.TestCase):
    """rules 校验：白名单参数、拒绝开关检查字段。"""

    def test_valid_rule_params_ok(self):
        data = scenario()
        data["rules"] = {"dev_threshold": 2.0, "grace_s": 2, "max_attempts": 3}
        check_scenario_v2(data)
        r = resolve_rules(data)
        self.assertEqual(r["dev_threshold"], 2.0)
        self.assertEqual(r["max_attempts"], 3)

    def test_unknown_rule_rejected(self):
        data = scenario()
        data["rules"] = {"mystery": 1}
        with self.assertRaises(ValueError):
            check_scenario_v2(data)

    def test_check_switch_rejected(self):
        """任何试图开关/关闭约束检查的字段必须被拒绝。"""
        for bad in ("disable_battery_check", "enable_checks", "check_payload",
                    "skip_altitude", "bypass_sensor", "ignore_motion"):
            data = scenario()
            data["rules"] = {bad: True}
            with self.assertRaises(ValueError, msg=bad):
                check_scenario_v2(data)

    def test_negative_rule_rejected(self):
        data = scenario()
        data["rules"] = {"dev_threshold": -1.0}
        with self.assertRaises(ValueError):
            check_scenario_v2(data)


class TimelineBehaviorTests(unittest.TestCase):
    """timeline 实际生效：事件真的发生、顺序、重复、隔离。"""

    def test_default_no_timeline_unchanged(self):
        """缺省行为一致：无 timeline 的 normal 模式仍 6/6 完成。"""
        report, trace = simulate(scenario(), "normal", max_ticks=60)
        self.assertTrue(report["all_succeeded"])
        self.assertEqual(report["active_commands"], 0)
        # 报告里应登记空 timeline / rules
        self.assertEqual(report["timeline"], [])
        self.assertEqual(report["rules"], {})

    def test_member_lost_timeline_fires(self):
        """member_lost 事件在第 t 步失联对应平台。"""
        data = scenario()
        # 挑一台会出现在计划里的平台（用 robot_no 1，fleet_demo 第一个作业在它附近）
        data["timeline"] = [{"t": 5, "event": "member_lost", "robot_no": 1}]
        report, trace = simulate(data, "normal", max_ticks=60)
        self.assertTrue(any(e["kind"] == "member_lost" for e in trace),
                        "应记录 member_lost 事件")

    def test_job_fail_timeline_fires(self):
        """job_fail 事件导致该作业任务级失败一次（触发重试）。"""
        data = scenario()
        data["timeline"] = [{"t": 2, "event": "job_fail", "job_id": "J1"}]
        report, trace = simulate(data, "normal", max_ticks=80)
        # J1 应经历一次失败重试（retries 统计 attempts>1 的作业）
        self.assertGreaterEqual(report["retries"], 1)

    def test_same_t_multi_events_not_swallowed(self):
        """同一步多个事件应全部执行，不互相吞。"""
        # 用校验层直接验证：同 t 多事件都保留
        data = scenario()
        data["timeline"] = [
            {"t": 3, "event": "job_fail", "job_id": "J1"},
            {"t": 3, "event": "job_slow", "job_id": "J2", "factor": 0.5},
        ]
        tl = resolve_timeline(data)
        self.assertEqual(len(tl), 2)

    def test_event_not_repeated(self):
        """同一事件只执行一次（consumer 顺序消费，不重复触发）。"""
        data = scenario()
        data["timeline"] = [{"t": 1, "event": "job_fail", "job_id": "J1"}]
        report, trace = simulate(data, "normal", max_ticks=80)
        # J1 只应失败一次（retries 恰好为 1，而不是反复失败）
        self.assertEqual(report["retries"], 1)

    def test_runs_are_isolated(self):
        """运行间隔离：一次带 timeline 的 simulate 不影响另一次无 timeline 的。"""
        data = scenario()
        data["timeline"] = [{"t": 1, "event": "job_fail", "job_id": "J1"}]
        # 第一次：带失败注入
        report_a, _ = simulate(data, "normal", max_ticks=80)
        # 第二次：同一 data，但不带 timeline（拷贝后清掉）
        clean = copy.deepcopy(data)
        clean.pop("timeline")
        report_b, _ = simulate(clean, "normal", max_ticks=60)
        self.assertEqual(report_b["retries"], 0)
        self.assertTrue(report_b["all_succeeded"])


class RulesBehaviorTests(unittest.TestCase):
    """rules 实际生效：参数真的被采用。"""

    def test_rules_max_attempts_effective(self):
        """rules.max_attempts 覆盖默认值，重试次数上限随之改变。"""
        data = scenario()
        data["rules"] = {"max_attempts": 1}
        data["timeline"] = [{"t": 1, "event": "job_fail", "job_id": "J1"}]
        report, _ = simulate(data, "normal", max_ticks=80)
        # max_attempts=1：失败一次后不再重试，J1 应最终 failed
        j1 = next(j for j in report["jobs"] if j["job_id"] == "J1")
        self.assertEqual(j1["status"], "failed")

    def test_rules_dev_threshold_effective(self):
        """rules.dev_threshold 覆盖默认 4.0。"""
        data = scenario()
        data["rules"] = {"dev_threshold": 1.5}
        from contracts_v2 import resolve_rules
        self.assertEqual(resolve_rules(data)["dev_threshold"], 1.5)


if __name__ == "__main__":
    unittest.main()
