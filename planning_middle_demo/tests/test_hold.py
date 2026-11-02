# -*- coding: utf-8 -*-
"""要点坚守（T-HLD）测试：几何、分解、执行语义、回放载荷与样例一致性。

覆盖的结论边界（与任务书 §9.2/§9.6 对齐）：
  * 测的是"本地行为状态机 + 4.1 输入"的规则一致性，不是真实平台或
    Gazebo/ROS 联调；
  * 效果类条目只验证"走 assessment.Adjudicator 桩判定且 verified=false"，
    不验证任何毁伤/战果数值；
  * 判定项数值来自本层状态机记录，桩判定口径见 docs/要点坚守任务_20261102.md。
"""

import json
import unittest
from pathlib import Path

import containment_geom as geom
from behaviors import KeepBehavior
from interop.errors import PlanningError
from interop.message import parse_message
from interop.runtime import nav_from_scenario, to_v2_dict
from interop.scheduler import Planner
from interop.templates import (as_point, decompose, hld_key_point,
                               hld_positions, hld_stations)
from contracts_v2 import check_scenario_v2
import trajectory_v2
from trajectory_v2 import BEHAVIOR_EVENT_NAME, HOLD_EVENTS, _hold_replay

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "interop" / "scenarios"
HOLD_MESSAGE = SCENARIO_DIR / "key_point_hold.message.json"
HOLD_FORMATION = SCENARIO_DIR / "key_point_hold.formation.json"

KEY = [0.0, 40.0]
POSITIONS = [dict(id="P1", point=[0.0, 72.0], facing_deg=0.0, min_units=1),
             dict(id="P2", point=[40.0, 40.0], facing_deg=90.0, min_units=1),
             dict(id="P3", point=[22.0, 14.0], facing_deg=150.0, min_units=1)]
THREATS = [dict(id="N", bearing_deg=0.0, width_deg=70.0),
           dict(id="E", bearing_deg=90.0, width_deg=60.0)]


class _Nav:
    """最小可通行地图替身：不做绕障，只提供行为层必需的两个接口。"""

    bounds = (-500.0, -500.0, 500.0, 500.0)
    radius = 1.0

    def nearest_free(self, point, max_radius=4.0):
        return [float(point[0]), float(point[1])], 0.0

    def free(self, point, radius=None):
        return True


def _formation(units=4):
    base = json.loads(HOLD_FORMATION.read_text(encoding="utf-8"))
    base["formation"]["units"] = base["formation"]["units"][:units]
    return base


def _message(params, target=None, min_units=3, max_units=4,
             capabilities=None):
    task = {
        "task_id": "T1", "task_type": "T-HLD", "priority": 1,
        "target": target or {"key_point": KEY},
        "window": {"start_s": 0, "end_s": 300},
        "required_capabilities": capabilities or {"HLD": 2},
        "min_units": min_units, "max_units": max_units,
        "params": params,
    }
    return {"schema_version": "0.3", "message_id": "MSG-TEST-HLD",
            "issued_at": "2026-11-02T00:00:00Z", "source": "UPPER",
            "tasks": [task]}


def _base_params(**overrides):
    params = dict(
        hold_duration_s=60,
        threat_directions=[dict(t) for t in THREATS],
        positions=[dict(p) for p in POSITIONS],
        roles={"post": 3, "reserve": 1},
        min_on_post=2,
        sensor_radius_m=45,
        observation_ring_m=24,
        observation_gap_max_s=8,
        relief=dict(interval_s=60, handover_tol_m=3,
                    swap_requires_arrival=True, relief_cycles=1),
        reinforce=dict(trigger="position_lost", enemy_ratio=1.5,
                       arrive_within_s=60),
        withdraw=dict(allowed=True, route=[KEY, [-40.0, -10.0]],
                      deadline_s=40),
        assembly_point=[-90, -16],
        enemy_events=[],
        counter_attack=dict(authorized=False, max_range_m=0),
        effect=dict(kinds=["damage", "suppress"], adjudicator="stub",
                    required_duration=5),
        stations=dict(reserve=[-21.2, 18.8], support=[], relay=list(KEY)),
    )
    params.update(overrides)
    return params


DEFAULT_ROLES = {"U1": "post:P1", "U2": "post:P2", "U3": "post:P3",
                 "U4": "reserve:standby"}


def _behavior(pid_roles=None, pids=None, caps=None, **overrides):
    params = _base_params(**overrides)
    params["roles"] = dict(pid_roles or DEFAULT_ROLES)
    job = dict(job_id="T1", type="hold", pos=list(KEY))
    behavior = KeepBehavior(job, _Nav(), list(pids or ["U1", "U2", "U3", "U4"]),
                            params)
    if caps:
        behavior.set_platform_caps(caps)
    return behavior


def _run(behavior, steps=120, hold=None, start=None):
    """平台按行为层给出的目标"瞬移到位"，把决策与运动解耦便于断言。

    ``hold`` 中的平台保持不动（用于测"接替者未到位不得撤""增援超时"）；
    ``start`` 覆盖初位。多次调用时时钟从 behavior.t 继续，不回到 T+0。
    """
    hold = set(hold or ())
    poses = {}
    for pid in behavior.pids:
        if start and pid in start:
            poses[pid] = (float(start[pid][0]), float(start[pid][1]), 0.0)
        else:
            point = behavior._station_of(pid)
            poses[pid] = (float(point[0]), float(point[1]), 0.0)
    begin = int(round(behavior.t)) + 1 if behavior.t else 0
    for offset in range(steps):
        t = float(begin + offset)
        out = behavior.step(poses, t, 1.0)
        for pid, target in out["targets"].items():
            if pid in hold:
                continue
            poses[pid] = (float(target[0]), float(target[1]), 0.0)
        if out["done"]:
            break
    return behavior


def _kinds(behavior):
    return [event["kind"] for event in behavior.history]


def _result(behavior):
    for event in behavior.history:
        if event["kind"] == "hold_result":
            return event
    return None


# ----------------------------------------------------------------------
# 1. 几何（与封控共用 containment_geom）
# ----------------------------------------------------------------------
class HoldGeometryTests(unittest.TestCase):
    def test_compass_bearing_convention(self):
        north = geom.compass_vector(0)
        east = geom.compass_vector(90)
        self.assertAlmostEqual(north[0], 0.0, places=6)
        self.assertAlmostEqual(north[1], 1.0, places=6)
        self.assertAlmostEqual(east[0], 1.0, places=6)
        self.assertAlmostEqual(east[1], 0.0, places=6)
        self.assertAlmostEqual(geom.bearing_deg(KEY, [0, 100]), 0.0, places=4)
        self.assertAlmostEqual(geom.bearing_deg(KEY, [100, 40]), 90.0, places=4)
        self.assertAlmostEqual(geom.angle_gap_deg(350, 10), 20.0, places=4)

    def test_threat_sector_contains_direction(self):
        polygon = geom.threat_sector(KEY, 0.0, 60.0, 50.0)
        self.assertGreaterEqual(len(polygon), 4)
        self.assertTrue(geom.in_sector(KEY, 0.0, 60.0, 50.0, [0.0, 80.0]))
        self.assertFalse(geom.in_sector(KEY, 0.0, 60.0, 50.0, [60.0, 40.0]))
        self.assertFalse(geom.in_sector(KEY, 0.0, 60.0, 50.0, [0.0, 120.0]))

    def test_observation_ring_and_approach(self):
        ring = geom.observation_ring(KEY, 20.0, 8)
        self.assertEqual(len(ring), 9)          # 圆心 + 8 个环点
        for sample in ring:
            radius = ((sample["point"][0] - KEY[0]) ** 2
                      + (sample["point"][1] - KEY[1]) ** 2) ** 0.5
            self.assertLessEqual(radius, 20.0 + 1e-6)
        points = geom.approach_points(KEY, THREATS, 20.0, 2)
        self.assertEqual(len(points), 4)
        self.assertTrue(geom.in_sector(KEY, 0.0, 70.0, 25.0,
                                       points[0]["point"]))

    def test_threat_posts_and_facing(self):
        posts = geom.threat_posts(KEY, [0.0, 90.0], 30.0)
        self.assertAlmostEqual(posts[0][0], KEY[0], places=3)
        self.assertAlmostEqual(posts[0][1], KEY[1] + 30.0, places=3)
        self.assertAlmostEqual(posts[1][0], KEY[0] + 30.0, places=3)
        self.assertAlmostEqual(geom.facing_of(posts[0], KEY), 0.0, places=1)


# ----------------------------------------------------------------------
# 2. 分解（角色 / 兵力裁剪 / 旧样例兼容）
# ----------------------------------------------------------------------
class HoldDecompositionTests(unittest.TestCase):
    def test_roles_and_targets(self):
        scenario = parse_message(_message(_base_params()), _formation())
        subtasks = decompose(scenario)
        self.assertEqual([s.role for s in subtasks],
                         ["post:P1", "post:P2", "post:P3",
                          "reserve:standby"])
        # 4.2 契约：目标仍只写 {"point": [x, y]}
        for subtask in subtasks:
            self.assertEqual(list(subtask.target), ["point"])
            self.assertEqual(len(subtask.target["point"]), 2)

    def test_crop_keeps_posts_last(self):
        params = _base_params(roles={"post": 3, "reserve": 1,
                                     "support": 1, "relay": 1})
        scenario = parse_message(_message(params, min_units=2, max_units=2),
                                 _formation())
        subtasks = decompose(scenario)
        self.assertEqual(len(subtasks), 2)
        self.assertTrue(all(s.role.startswith("post:") for s in subtasks))

    def test_crop_order_support_relay_reserve(self):
        params = _base_params(roles={"post": 1, "reserve": 1,
                                     "support": 1, "relay": 1})
        scenario = parse_message(_message(params, min_units=3, max_units=3),
                                 _formation())
        roles = [s.role for s in decompose(scenario)]
        self.assertEqual(roles, ["post:P1", "reserve:standby",
                                 "relay:standby"])

    def test_legacy_defense_positions_unchanged(self):
        params = {"hold_duration_s": 60,
                  "defense_positions": [[-5, 0], [5, 0]]}
        scenario = parse_message(_message(params, target={"key_point": [0, 0]},
                                          min_units=2, max_units=2),
                                 _formation())
        subtasks = decompose(scenario)
        self.assertEqual(len(subtasks), 2)
        self.assertEqual([s.role for s in subtasks], ["post:P1", "post:P2"])

    def test_positions_derived_from_threats(self):
        params = {"hold_duration_s": 60, "post_radius_m": 30,
                  "threat_directions": [dict(id="N", bearing_deg=0,
                                             width_deg=60),
                                        dict(id="E", bearing_deg=90,
                                             width_deg=60)]}
        scenario = parse_message(_message(params), _formation())
        positions = hld_positions(scenario.tasks[0])
        self.assertEqual([p["id"] for p in positions], ["P1", "P2"])
        self.assertAlmostEqual(positions[0]["point"][1], KEY[1] + 30.0,
                               places=3)
        self.assertAlmostEqual(positions[1]["point"][0], KEY[0] + 30.0,
                               places=3)
        self.assertEqual(positions[0]["facing_deg"], 0.0)
        self.assertEqual(positions[1]["facing_deg"], 90.0)

    def test_key_point_from_defense_area(self):
        area = [[0, 0], [100, 0], [100, 100], [0, 100]]
        scenario = parse_message(_message({"hold_duration_s": 60},
                                          target={"defense_area": area},
                                          min_units=1, max_units=1),
                                 _formation())
        key = hld_key_point(scenario.tasks[0])
        self.assertAlmostEqual(key[0], 50.0, places=3)
        self.assertAlmostEqual(key[1], 50.0, places=3)
        self.assertEqual(len(hld_positions(scenario.tasks[0])), 1)

    def test_stations_shared_with_runtime(self):
        scenario = parse_message(_message(_base_params()), _formation())
        stations = hld_stations(scenario.tasks[0])
        self.assertEqual(set(stations), {"reserve", "support", "relay"})
        self.assertEqual(len(stations["reserve"]), 2)
        self.assertEqual(stations["relay"], [0.0, 40.0])

    def test_missing_target_raises(self):
        params = _base_params()
        params.pop("positions")
        params.pop("threat_directions")
        scenario = parse_message(_message(params), _formation())
        scenario.tasks[0].target = {}
        with self.assertRaises(PlanningError):
            decompose(scenario)

    def test_unknown_role_rejected(self):
        params = _base_params(roles={"post": 3, "artillery": 1})
        scenario = parse_message(_message(params), _formation())
        with self.assertRaises(PlanningError):
            decompose(scenario)


# ----------------------------------------------------------------------
# 3. 运行视图（白名单透传 / 4.2 契约）
# ----------------------------------------------------------------------
class HoldRuntimeTests(unittest.TestCase):
    def test_behavior_params_whitelist(self):
        scenario = parse_message(_message(_base_params()), _formation())
        job = to_v2_dict(scenario)["jobs"][0]
        behavior = job["_behavior"]
        for key in ("key_point", "positions", "stations", "threats",
                    "min_on_post", "relief", "reinforce", "withdraw",
                    "enemy_events", "counter_attack", "effect", "duration_s"):
            self.assertIn(key, behavior)
        scenario.tasks[0].params["secret_field"] = 1
        self.assertNotIn("secret_field",
                         to_v2_dict(scenario)["jobs"][0]["_behavior"])

    def test_v2_view_passes_contract(self):
        scenario = parse_message(_message(_base_params()), _formation())
        check_scenario_v2(to_v2_dict(scenario))

    def test_plan_roles_and_command_phases(self):
        scenario = parse_message(_message(_base_params()), _formation())
        plan = Planner(scenario).plan()
        self.assertEqual(sorted(item.role for item in plan.assignments),
                         ["post:P1", "post:P2", "post:P3",
                          "reserve:standby"])
        phases = {command.phase for command in plan.commands}
        self.assertTrue(phases <= {"TRANSIT", "HOLD", "STOP"})
        for command in plan.commands:
            if command.phase != "STOP":
                continue
            for value in (command.linear_x, command.linear_y, command.linear_z,
                          command.angular_x, command.angular_y,
                          command.angular_z):
                self.assertEqual(value, 0.0)

    def test_nav_includes_positions(self):
        scenario = parse_message(_message(_base_params()), _formation())
        nav = nav_from_scenario(scenario)
        for position in POSITIONS:
            point = position["point"]
            self.assertGreaterEqual(point[0], nav.bounds[0])
            self.assertLessEqual(point[1], nav.bounds[3])


# ----------------------------------------------------------------------
# 4. 执行语义（KeepBehavior）
# ----------------------------------------------------------------------
class HoldBehaviorTests(unittest.TestCase):
    def test_control_established_at_min_on_post(self):
        behavior = _behavior()
        poses = {pid: (200.0, 200.0, 0.0) for pid in behavior.pids}
        poses["U1"] = (0.0, 72.0, 0.0)
        poses["U4"] = (-21.2, 18.8, 0.0)
        behavior.step(poses, 0.0, 1.0)
        self.assertIsNone(behavior.control_established_at)
        poses["U2"] = (40.0, 40.0, 0.0)
        behavior.step(poses, 1.0, 1.0)
        self.assertEqual(behavior.control_established_at, 1.0)
        self.assertIn("control_established", _kinds(behavior))

    def test_handover_requires_arrival(self):
        behavior = _behavior(hold_duration_s=200)
        _run(behavior, steps=80, hold={"U4"})
        self.assertIn("handover_start", _kinds(behavior))
        self.assertNotIn("handover_complete", _kinds(behavior))
        # 未到位前，原占位者的目标仍是自己的阵位（不得先撤）
        self.assertEqual(behavior._targets_for()["U1"],
                         behavior.post_point["P1"])
        _run(behavior, steps=20, start={"U4": [0.0, 0.0]})
        self.assertIn("handover_complete", _kinds(behavior))
        row = behavior.handover_list[0]
        self.assertTrue(row["arrival_before_departure"])
        self.assertEqual(row["post_id"], "P1")

    def test_early_release_counts_as_interruption(self):
        behavior = _behavior(
            hold_duration_s=200, control_lost_after_s=999, min_on_post=3,
            relief=dict(interval_s=20, handover_tol_m=3,
                        swap_requires_arrival=False, relief_cycles=1))
        _run(behavior, steps=40, hold={"U4"})
        kinds = _kinds(behavior)
        self.assertIn("handover_start", kinds)
        self.assertIn("control_interrupted", kinds)
        _run(behavior, steps=20, start={"U4": [0.0, 0.0]})
        row = behavior.handover_list[-1]
        self.assertFalse(row["arrival_before_departure"])

    def test_relief_skipped_without_reserve(self):
        roles = dict(DEFAULT_ROLES)
        roles["U4"] = "support:S1"
        behavior = _behavior(pid_roles=roles, hold_duration_s=200)
        _run(behavior, steps=70)
        self.assertIn("relief_skipped", _kinds(behavior))
        self.assertEqual(behavior.relief_skipped, 1)

    def test_reinforce_triggered_by_enemy_ratio(self):
        behavior = _behavior(enemy_events=[
            dict(t_s=5, kind="assault", direction="N", ratio=1.6)])
        _run(behavior, steps=40)
        kinds = _kinds(behavior)
        self.assertIn("reinforce_triggered", kinds)
        self.assertIn("reinforce_arrived", kinds)
        row = behavior.reinforce_list[0]
        self.assertEqual(row["post_id"], "P1")
        self.assertTrue(row["on_time"])

    def test_reinforce_timeout_recorded(self):
        behavior = _behavior(
            hold_duration_s=200, control_lost_after_s=999,
            reinforce=dict(trigger="position_lost", enemy_ratio=1.5,
                           arrive_within_s=2),
            enemy_events=[dict(t_s=1, kind="assault", direction="N",
                               ratio=1.6)])
        _run(behavior, steps=10, hold={"U4"})
        self.assertIn("reinforce_timeout", _kinds(behavior))
        late = [row for row in behavior.reinforce_list if not row["on_time"]]
        self.assertTrue(late or behavior.reinforce is not None)

    def test_position_lost_marks_breach(self):
        behavior = _behavior(min_on_post=2, enemy_events=[
            dict(t_s=1, kind="assault", direction="N", ratio=1.0)])
        poses = {pid: (behavior._station_of(pid)[0],
                       behavior._station_of(pid)[1], 0.0)
                 for pid in behavior.pids}
        poses["U1"] = (-200.0, -200.0, 0.0)     # P1 无人
        for t in range(5):
            behavior.step(poses, float(t), 1.0)
        kinds = _kinds(behavior)
        self.assertIn("post_lost", kinds)
        self.assertEqual(behavior.counts["breaches"], 1)

    def test_observation_gap_detected(self):
        behavior = _behavior(
            positions=[dict(id="P1", point=[0.0, 340.0], facing_deg=0.0),
                       dict(id="P2", point=[40.0, 340.0], facing_deg=90.0)],
            pid_roles={"U1": "post:P1", "U2": "post:P2", "U3": "post:P1",
                       "U4": "post:P2"},
            min_on_post=1, sensor_radius_m=20, observation_gap_max_s=3)
        _run(behavior, steps=10)
        self.assertIn("observation_gap", _kinds(behavior))
        self.assertGreater(behavior.gap_run, 3.0)

    def test_counter_attack_uses_stub_adjudicator(self):
        behavior = _behavior(
            counter_attack=dict(authorized=True, max_range_m=80),
            enemy_events=[dict(t_s=2, kind="probe", direction="N")])
        _run(behavior, steps=100)
        kinds = _kinds(behavior)
        self.assertIn("counter_attack", kinds)
        self.assertIn("effect_adjudicated", kinds)
        self.assertFalse(behavior.effects[0]["verified"])
        self.assertEqual(behavior.effects[0]["adjudicator"],
                         "constructed_assessment_stub")
        item = next(it for it in _result(behavior)["items"]
                    if it["id"] == "effect_verified")
        self.assertFalse(item["required"])
        self.assertIn("桩判定", item["note"])

    def test_counter_attack_denied_without_authority(self):
        behavior = _behavior(
            counter_attack=dict(authorized=False),
            enemy_events=[dict(t_s=2, kind="probe", direction="N")])
        _run(behavior, steps=100)
        self.assertIn("counter_attack_denied", _kinds(behavior))
        self.assertEqual(behavior.effects, [])

    def test_verdict_pending_without_enemy_events(self):
        behavior = _behavior(enemy_events=[])
        _run(behavior, steps=100)
        result = _result(behavior)
        self.assertEqual(result["verdict"], "pending")
        self.assertIn("未出现敌方进攻", result["reason"])

    def test_verdict_failed_on_control_lost(self):
        behavior = _behavior(min_on_post=2, control_lost_after_s=3,
                             withdraw=dict(allowed=False))
        _run(behavior, steps=10)
        for pid in list(behavior.post_owner.values()):
            behavior.report_loss(pid, 10.0)
        _run(behavior, steps=15)
        self.assertIn("control_lost", _kinds(behavior))
        self.assertEqual(_result(behavior)["verdict"], "failed")

    def test_withdraw_after_hold_period(self):
        behavior = _behavior(
            hold_duration_s=5,
            counter_attack=dict(authorized=True, max_range_m=80),
            enemy_events=[dict(t_s=1, kind="probe", direction="N")])
        _run(behavior, steps=60)
        kinds = _kinds(behavior)
        self.assertIn("withdraw_started", kinds)
        self.assertIn("withdrawn", kinds)
        item = next(i for i in _result(behavior)["items"]
                    if i["id"] == "withdraw_compliance")
        self.assertTrue(item["ok"])

    def test_hold_result_payload(self):
        behavior = _behavior(enemy_events=[
            dict(t_s=2, kind="probe", direction="N")])
        _run(behavior, steps=100)
        result = _result(behavior)
        self.assertIsNotNone(result)
        self.assertIn("桩判定", result["scope"])
        for key in ("positions", "timeline", "effects", "handovers",
                    "reinforcements"):
            self.assertIn(key, result)
        self.assertEqual(len(result["positions"]), 3)
        for position in result["positions"]:
            self.assertIn("occupants", position)
        metrics = result["metrics"]
        for key in ("control_hold_ratio", "control_interruption_s",
                    "observation_gap_max_s", "enemy_attacks",
                    "enemy_breaches", "relief_count", "our_losses",
                    "patrol_radius_m"):
            self.assertIn(key, metrics)

    def test_on_post_patrol_moves_but_stays_manned(self):
        """到点后要游走，但游走不能被记成离岗。"""
        behavior = _behavior(hold_duration_s=40, patrol_radius_m=4.0,
                             patrol_speed_mps=2.0)
        poses = {}
        for pid in behavior.pids:
            point = behavior._station_of(pid)
            poses[pid] = (float(point[0]), float(point[1]), 0.0)
        seen_offset = {}
        for t in range(40):
            out = behavior.step(poses, float(t), 1.0)
            for pid, target in out["targets"].items():
                post_id = behavior.post_of_pid.get(pid)
                if post_id:
                    offset = ((target[0] - behavior.post_point[post_id][0]) ** 2
                              + (target[1] - behavior.post_point[post_id][1]) ** 2) ** 0.5
                    seen_offset[pid] = max(seen_offset.get(pid, 0.0), offset)
                poses[pid] = (float(target[0]), float(target[1]), 0.0)
        # 游走确实发生了（目标点离阵位超过 1 m）
        self.assertTrue(any(v > 1.0 for v in seen_offset.values()))
        # 而且在位判定没被游走打穿
        self.assertNotIn("control_interrupted", _kinds(behavior))
        self.assertGreater(behavior.control_time, 30.0)

    def test_patrol_disabled_posts_are_static(self):
        behavior = _behavior(patrol_enabled=False)
        poses = {pid: (0.0, 0.0, 0.0) for pid in behavior.pids}
        for pid, post_id in behavior.post_of_pid.items():
            poses[pid] = (float(behavior.post_point[post_id][0]),
                          float(behavior.post_point[post_id][1]), 0.0)
        out = behavior.step(poses, 5.0, 1.0)
        for pid in behavior.pids:
            post_id = behavior.post_of_pid.get(pid)
            if not post_id:
                continue
            self.assertEqual(out["targets"][pid], behavior.post_point[post_id])
        self.assertEqual(out["speed_scale"], {})

    def test_patrol_speed_scale_on_post(self):
        behavior = _behavior(patrol_radius_m=4.0, patrol_speed_mps=2.0)
        behavior.speeds = {pid: 8.0 for pid in behavior.pids}
        poses = {pid: (0.0, 0.0, 0.0) for pid in behavior.pids}
        for pid, post_id in behavior.post_of_pid.items():
            poses[pid] = (float(behavior.post_point[post_id][0]),
                          float(behavior.post_point[post_id][1]), 0.0)
        out = behavior.step(poses, 0.0, 1.0)
        self.assertTrue(out["speed_scale"])
        for value in out["speed_scale"].values():
            self.assertAlmostEqual(value, 2.0 / 8.0, places=3)

    def test_handover_aborted_when_withdraw_starts(self):
        """撤离优先：在途接替要中止并留痕，不能拖成"接替超时"。"""
        behavior = _behavior(
            hold_duration_s=25, control_lost_after_s=999,
            relief=dict(interval_s=15, handover_tol_m=3,
                        swap_requires_arrival=True, relief_cycles=1))
        _run(behavior, steps=40, hold={"U4"})     # 预备队卡住 → 接替一直不完成
        kinds = _kinds(behavior)
        self.assertIn("handover_start", kinds)
        self.assertIn("withdraw_started", kinds)
        self.assertIn("handover_aborted", kinds)
        self.assertNotIn("handover_timeout", kinds)

    def test_air_seat_orbits_and_reports_alive(self):
        """空中观察席：绕要点定高盘旋，并计入在位率。"""
        roles = dict(DEFAULT_ROLES)
        roles["U5"] = "air:watch"
        behavior = _behavior(pid_roles=roles, pids=["U1", "U2", "U3", "U4", "U5"],
                             hold_duration_s=30, air_altitude_m=60,
                             air_orbit_radius_m=40)
        poses = {pid: (0.0, 0.0, 0.0) for pid in behavior.pids}
        for pid, post_id in behavior.post_of_pid.items():
            poses[pid] = (float(behavior.post_point[post_id][0]),
                          float(behavior.post_point[post_id][1]), 0.0)
        out = behavior.step(poses, 10.0, 1.0)
        target = out["targets"]["U5"]
        radius = ((target[0] - KEY[0]) ** 2 + (target[1] - KEY[1]) ** 2) ** 0.5
        self.assertAlmostEqual(radius, 40.0, delta=0.5)
        self.assertIn("U5", behavior.params["air_altitude"])
        self.assertEqual(len(behavior.air_pids), 1)
        self.assertGreater(behavior.air_watch_s, 0.0)

    def test_air_seat_reassigned_when_platform_cannot_climb(self):
        roles = dict(DEFAULT_ROLES)
        roles["U5"] = "air:watch"
        behavior = _behavior(pid_roles=roles, pids=["U1", "U2", "U3", "U4", "U5"])
        caps = {pid: dict(can_climb=False) for pid in behavior.pids}
        caps["U5"] = dict(can_climb=False)          # 地面平台误占空中席位
        behavior.set_platform_caps(caps)
        self.assertEqual(behavior.air_pids, [])
        self.assertEqual(behavior.role["U5"], "reserve:standby")
        self.assertIn("air_seat_reassigned", _kinds(behavior))

    def test_coverage_gap_detected_and_judged(self):
        """只用一侧阵位时，要点全向覆盖出现缺口，判据应判失败。"""
        behavior = _behavior(
            positions=[dict(id="P1", point=[0.0, 80.0], facing_deg=0.0),
                       dict(id="P2", point=[20.0, 80.0], facing_deg=45.0)],
            pid_roles={"U1": "post:P1", "U2": "post:P2", "U3": "post:P1",
                       "U4": "post:P2"},
            min_on_post=1, sensor_radius_m=20, observation_ring_m=24,
            min_key_point_coverage=0.95, hold_duration_s=20)
        _run(behavior, steps=40)
        metrics = _result(behavior)["metrics"]
        self.assertGreater(metrics["coverage_gap_count"], 0)
        item = next(it for it in _result(behavior)["items"]
                    if it["id"] == "key_point_coverage")
        self.assertTrue(item["required"])
        self.assertFalse(item["ok"])


# ----------------------------------------------------------------------
# 5. 回放
# ----------------------------------------------------------------------
def _fake_trace():
    structure = dict(kind="behavior_structure", type="hold", job_id="T1",
                     sim_s=0, key_point=KEY, positions=POSITIONS,
                     threats=THREATS, roles={"U1": "post:P1"},
                     min_on_post=2, duration_s=60)
    result = dict(kind="hold_result", verdict="succeeded", reason="ok",
                  items=[], metrics={}, positions=[], timeline=[])
    return [
        dict(kind="behavior_event", sim_s=0, event=structure),
        dict(kind="behavior_event", sim_s=5,
             event=dict(kind="handover_complete", t=5, post_id="P1",
                        incoming="U4", outgoing="U1", arrival_s=3.0)),
        dict(kind="behavior_event", sim_s=60, event=dict(result, t=60)),
        dict(kind="feedback_applied", sim_s=0, event={}),
    ]


class HoldReplayTests(unittest.TestCase):
    def test_replay_extraction(self):
        data = _hold_replay(_fake_trace())
        self.assertEqual(data["job_id"], "T1")
        self.assertEqual(len(data["structure"]["positions"]), 3)
        self.assertEqual(data["result"]["verdict"], "succeeded")
        kinds = [event["kind"] for event in data["events"]]
        self.assertIn("handover_complete", kinds)
        handover = next(e for e in data["events"]
                        if e["kind"] == "handover_complete")
        self.assertEqual(handover["post_id"], "P1")
        self.assertEqual(handover["arrival_s"], 3.0)

    def test_replay_none_without_structure(self):
        self.assertIsNone(_hold_replay([]))
        self.assertIsNone(_hold_replay([
            dict(kind="behavior_event", sim_s=0,
                 event=dict(kind="phase"))]))
        # 区域封控的结构不能被当成要点坚守
        other = [dict(kind="behavior_event", sim_s=0,
                      event=dict(kind="behavior_structure", type="blockade",
                                 job_id="T1", area=[[0, 0], [1, 0], [1, 1]]))]
        self.assertIsNone(_hold_replay(other))

    def test_event_names_complete(self):
        missing = [kind for kind in HOLD_EVENTS
                   if kind not in BEHAVIOR_EVENT_NAME]
        self.assertEqual(missing, [])

    def test_rebuild_replay_data_includes_hold(self):
        scenario = {"platforms": [], "jobs": [], "_meta": {}}
        report = {"platforms": [], "run_id": "t", "motion": "real",
                  "behavior": True, "simulated_until_s": 60}
        data = trajectory_v2.build_replay_data(scenario, report, _fake_trace())
        self.assertIn("hold", data)
        self.assertEqual(data["hold"]["job_id"], "T1")
        self.assertIsNone(data["containment"])


# ----------------------------------------------------------------------
# 6. 样例一致性与工作台登记
# ----------------------------------------------------------------------
class HoldSampleTests(unittest.TestCase):
    def test_sample_parses_and_decomposes(self):
        message = json.loads(HOLD_MESSAGE.read_text(encoding="utf-8"))
        formation = json.loads(HOLD_FORMATION.read_text(encoding="utf-8"))
        scenario = parse_message(message, formation)
        subtasks = decompose(scenario)
        self.assertEqual(len(subtasks), 6)
        self.assertEqual(sorted(s.role for s in subtasks),
                         ["air:watch", "post:P1", "post:P2", "post:P3",
                          "post:P4", "reserve:standby"])
        check_scenario_v2(to_v2_dict(scenario, message, formation))

    def test_sample_air_slot_pinned_to_air_unit(self):
        message = json.loads(HOLD_MESSAGE.read_text(encoding="utf-8"))
        formation = json.loads(HOLD_FORMATION.read_text(encoding="utf-8"))
        scenario = parse_message(message, formation)
        air = [s for s in decompose(scenario) if s.role == "air:watch"]
        self.assertEqual(len(air), 1)
        self.assertEqual(air[0].pinned_unit, "U6")
        self.assertEqual(air[0].required_capabilities, {"RCN": 2})

    def test_sample_covers_all_threat_directions(self):
        """后方不能空着：每个威胁方向都要有一个正对它的阵位。"""
        message = json.loads(HOLD_MESSAGE.read_text(encoding="utf-8"))
        params = message["tasks"][0]["params"]
        facings = [float(p["facing_deg"]) % 360.0
                   for p in params["positions"]]
        for threat in params["threat_directions"]:
            bearing = float(threat["bearing_deg"]) % 360.0
            gaps = [abs((f - bearing + 180.0) % 360.0 - 180.0) for f in facings]
            self.assertLessEqual(min(gaps), 30.0,
                                 "威胁 %s 没有正对的阵位" % threat["id"])

    def test_sample_positions_inside_scene(self):
        formation = json.loads(HOLD_FORMATION.read_text(encoding="utf-8"))
        bounds = formation["meta"]["scene_bounds"]
        message = json.loads(HOLD_MESSAGE.read_text(encoding="utf-8"))
        for position in message["tasks"][0]["params"]["positions"]:
            point = as_point(position["point"])
            self.assertGreaterEqual(point[0], bounds[0])
            self.assertLessEqual(point[0], bounds[2])
            self.assertGreaterEqual(point[1], bounds[1])
            self.assertLessEqual(point[1], bounds[3])

    def test_scenario_documented_params(self):
        message = json.loads(HOLD_MESSAGE.read_text(encoding="utf-8"))
        params = message["tasks"][0]["params"]
        for key in ("hold_duration_s", "threat_directions", "positions",
                    "roles", "min_on_post", "relief", "reinforce",
                    "withdraw", "enemy_events", "counter_attack", "effect"):
            self.assertIn(key, params)
        self.assertTrue(params["withdraw"]["allowed"])
        self.assertGreaterEqual(params["roles"]["post"],
                                params["min_on_post"])


class HoldWorkbenchTests(unittest.TestCase):
    def test_scenario_registered(self):
        import workbench_server
        self.assertIn("interop_hold", workbench_server.SCENARIOS)
        self.assertIn("interop_hold", workbench_server.INTEROP_SCENARIOS)
        message, formation = workbench_server.INTEROP_PAIRS["interop_hold"]
        self.assertTrue((SCENARIO_DIR / message).is_file())
        self.assertTrue((SCENARIO_DIR / formation).is_file())
        self.assertIn("interop_hold", workbench_server.AVOID_SCENARIOS)

    def test_validate_config_defaults(self):
        import workbench_server
        config = workbench_server.validate_config(
            {"scenario": "interop_hold", "planner": "interop"})
        self.assertEqual(config["motion"], "real")
        self.assertTrue(config["avoid"])
        self.assertTrue(config["behavior"])
        self.assertEqual(config["max_ticks"], 280)

    def test_catalog_exposes_hold_feature(self):
        import workbench_server
        catalog = workbench_server.Workbench().catalog()
        self.assertTrue(catalog["features"]["hold"])
        self.assertIn("interop_hold", catalog["scenarios"])


if __name__ == "__main__":
    unittest.main()
