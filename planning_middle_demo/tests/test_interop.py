# -*- coding: utf-8 -*-
"""interop 统一层的单元与集成测试。

运行（在 planning_middle_demo 目录）：
    python -m unittest tests.test_interop -v
"""

import json
import contextlib
import io
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from interop.assignment import hungarian
from interop.compare import audit
from interop.cost import CostModel
from interop.errors import UnsupportedFeature, WireError
from interop.geometry import (
    path_enters_polygon,
    point_in_polygon,
    segment_polygon_distance,
    segment_polygon_overlap_length,
)
from interop.message import parse_message
from interop.model import Plan
from interop.output import write_outputs
from interop.routing import NoRouteError, Router
from interop.scheduler import Planner


def formation(**overrides):
    data = {
        "formation": {
            "formation_id": "TEST-FORMATION",
            "units": [
                dict(unit_id="U1", platform_class="UGV", robot_id=1,
                     position=[0, 0], speed_mps=5.0, endurance_s=1000.0,
                     capabilities={"PTL": 2, "RCN": 2}),
                dict(unit_id="U2", platform_class="WING", robot_id=41,
                     position=[0, 10], speed_mps=10.0, endurance_s=1000.0,
                     capabilities={"PTL": 2, "RCN": 2}),
            ],
        },
        "constraints": [
            {"constraint_id": "BLOCK", "type": "no_go",
             "area": {"polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]}},
        ],
        "meta": {"cell_size_m": 1, "grid_cell_m": 2, "grid_margin_m": 1.0,
                 "plan_id": "PLAN-TEST"},
    }
    data.update(overrides)
    return data


def point_task(**overrides):
    task = {
        "task_id": "T1", "task_type": "T-PTL", "priority": 1,
        "target": {"point": [30, 0]},
        "window": {"start_s": 0, "end_s": 200},
        "required_capabilities": {"PTL": 2},
        "min_units": 1, "max_units": 1,
        "params": {"duration_s": 20},
    }
    task.update(overrides)
    return task


def message(tasks=None, **overrides):
    data = {
        "schema_version": "0.3",
        "message_id": "MSG-TEST",
        "issued_at": "2026-10-30T00:00:00Z",
        "source": "UPPER",
        "tasks": tasks or [{
            "task_id": "T1", "task_type": "T-PTL", "priority": 1,
            "target": {"route": [[-10, 0], [5, 12], [30, 0]]},
            "window": {"start_s": 0, "end_s": 200},
            "required_capabilities": {"PTL": 2},
            "min_units": 1, "max_units": 2,
            "params": {"duration_s": 20,
                       "coordination": ["simultaneous_arrival"]},
        }],
    }
    data.update(overrides)
    return data


class MessageTests(unittest.TestCase):
    def test_rejects_old_schema_versions(self):
        for version in ("0.1", "0.2"):
            data = message(schema_version=version)
            with self.assertRaises(WireError) as ctx:
                parse_message(data, formation())
            self.assertIn("0.3", str(ctx.exception))
            self.assertIn("拒绝", str(ctx.exception))

    def test_parses_asl(self):
        tasks = [dict(message()["tasks"][0], task_type="T-ASL",
                      target={"point": [0, 0]}, min_units=4, max_units=4,
                      params={"effect": "毁伤"})]
        scenario = parse_message(message(tasks=tasks), formation())
        task = scenario.tasks[0]
        self.assertEqual(task.task_type, "T-ASL")
        self.assertEqual(task.params["effect"], "damage")
        self.assertEqual(task.params["assault_units"], 2)
        self.assertEqual(task.params["required_level"], 6.0)

    def test_asl_needs_assault_slot(self):
        tasks = [dict(message()["tasks"][0], task_type="T-ASL",
                      target={"point": [0, 0]}, min_units=2, max_units=2,
                      params={})]
        with self.assertRaises(WireError):
            parse_message(message(tasks=tasks), formation())

    def test_source_aliases(self):
        for raw, canonical in (("上级", "UPPER"), ("调整", "ADJUST"),
                               ("自主", "AUTONOMOUS")):
            scenario = parse_message(message(source=raw), formation())
            self.assertEqual(scenario.message["source"], canonical)

    def test_missing_field(self):
        tasks = [dict(message()["tasks"][0])]
        del tasks[0]["window"]
        with self.assertRaises(WireError):
            parse_message(message(tasks=tasks), formation())

    def test_dependency_cycle(self):
        base = message()["tasks"][0]
        tasks = [dict(base, task_id="T1", depends_on=["T2"], target={"point": [0, 0]}),
                 dict(base, task_id="T2", depends_on=["T1"], target={"point": [5, 5]})]
        with self.assertRaises(WireError):
            parse_message(message(tasks=tasks), formation())

    def test_target_needs_exactly_one_kind(self):
        tasks = [dict(message()["tasks"][0],
                      target={"point": [0, 0], "route": [[0, 0], [1, 1]]})]
        with self.assertRaises(WireError):
            parse_message(message(tasks=tasks), formation())

    def test_robot_id_range(self):
        data = formation()
        data["formation"]["units"][0]["robot_id"] = 41
        with self.assertRaises(WireError):
            parse_message(message(), data)

    def test_missing_robot_id_is_allocated(self):
        data = formation()
        del data["formation"]["units"][0]["robot_id"]
        scenario = parse_message(message(), data)
        self.assertEqual(scenario.platforms[0].robot_id, 1)

    def test_capability_level_range(self):
        data = formation()
        data["formation"]["units"][0]["capabilities"] = {"PTL": 9}
        with self.assertRaises(WireError):
            parse_message(message(), data)

    def test_non_finite_number_rejected(self):
        data = formation()
        data["formation"]["units"][0]["speed_mps"] = float("nan")
        with self.assertRaises(WireError):
            parse_message(message(), data)

    def test_accepts_air_threat_and_nested_constraints(self):
        threat = {
            "constraint_id": "AIR-ONLY", "type": "threat",
            "applies_to": "air", "intensity": 0.6,
            "area": {"polygon": [[0, 0], [5, 0], [5, 5], [0, 5]]},
        }
        data = formation(constraints=None)
        data["formation"]["constraints"] = [threat]
        scenario = parse_message(message(), data)
        self.assertEqual(len(scenario.constraints), 1)
        self.assertEqual(scenario.constraints[0]["applies_to"], "air")


class DecomposeTests(unittest.TestCase):
    def test_area_split_honours_max_units(self):
        tasks = [{
            "task_id": "T1", "task_type": "T-RCN", "priority": 1,
            "target": {"area": [[0, 0], [100, 0], [100, 40], [0, 40]]},
            "window": {"start_s": 0, "end_s": 300},
            "required_capabilities": {"RCN": 2},
            "min_units": 1, "max_units": 1,
            "params": {"duration_s": 30},
        }]
        scenario = parse_message(message(tasks=tasks), formation())
        subtasks = Planner(scenario, assignment_mode="greedy").subtasks
        self.assertEqual(len(subtasks), 1)

    def test_hld_defense_positions(self):
        tasks = [{
            "task_id": "T1", "task_type": "T-HLD", "priority": 1,
            "target": {"key_point": [0, 0]},
            "window": {"start_s": 0, "end_s": 300},
            "required_capabilities": {"PTL": 2},
            "min_units": 2, "max_units": 2,
            "params": {"hold_duration_s": 60,
                       "defense_positions": [[-5, 0], [5, 0]]},
        }]
        scenario = parse_message(message(tasks=tasks), formation())
        subtasks = Planner(scenario, assignment_mode="greedy").subtasks
        self.assertEqual(len(subtasks), 2)


class PlatformDiversityTests(unittest.TestCase):
    def test_patrol_uses_all_four_available_platform_classes(self):
        root = os.path.join(BASE_DIR, "interop", "scenarios")
        with open(os.path.join(root, "area_patrol.message.json"),
                  encoding="utf-8-sig") as fh:
            raw_message = json.load(fh)
        with open(os.path.join(root, "area_patrol.formation.json"),
                  encoding="utf-8-sig") as fh:
            raw_formation = json.load(fh)
        scenario = parse_message(raw_message, raw_formation)
        plan = Planner(scenario, objective="timeliness").plan()
        platform_map = scenario.platform_map
        patrol_classes = {
            platform_map[item.unit_id].platform_class
            for item in plan.assignments
            if item.parent_task_id == "T1"
        }
        self.assertEqual(
            patrol_classes, {"UGV", "TANK", "PLANE", "WING"})


class HungarianTests(unittest.TestCase):
    def test_optimal_pairing(self):
        matrix = [[1.0, 2.0], [2.0, 1.0]]
        pairs = sorted(hungarian(matrix))
        self.assertEqual(pairs, [(0, 0), (1, 1)])

    def test_more_platforms_than_slots(self):
        matrix = [[3.0, 1.0, 2.0]]
        pairs = hungarian(matrix)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][1], 1)


class RoutingTests(unittest.TestCase):
    def _scenario(self):
        return parse_message(message(), formation())

    def test_ground_route_avoids_polygon(self):
        scenario = self._scenario()
        router = Router(scenario, [])
        route = router.route((-10.0, 0.0), (30.0, 0.0), is_air=False)
        self.assertGreater(len(route.path), 2)
        polygon = [(10, -5), (20, -5), (20, 5), (10, 5)]
        self.assertFalse(path_enters_polygon(route.path, polygon))

    def test_air_route_is_straight(self):
        scenario = self._scenario()
        router = Router(scenario, [])
        route = router.route((-10.0, 0.0), (30.0, 0.0), is_air=True)
        self.assertEqual(len(route.path), 2)

    def test_risk_weight_keeps_straight_when_no_threat_on_line(self):
        # 只有 risk_weight>0、但直线不穿威胁区时，不应为了“风险”改走栅格 A*：
        # 栅格路径会略长，等于凭空增加时效成本（2026-11 暴露度目标踩过）。
        scenario = self._scenario()
        router = Router(scenario, [], risk_weight=1.0)
        route = router.route((0.0, 0.0), (0.0, 20.0), is_air=False)
        self.assertEqual(len(route.path), 2)

    def test_air_only_threat_does_not_reroute_ground(self):
        data = formation(constraints=[{
            "constraint_id": "AIR-ONLY", "type": "threat",
            "applies_to": "air", "intensity": 1.0,
            "area": {"polygon": [[10, 15], [20, 15], [20, 25], [10, 25]]},
        }])
        scenario = parse_message(message(), data)
        router = Router(scenario, [], risk_weight=50.0)
        ground = router.route((0.0, 20.0), (30.0, 20.0), is_air=False)
        air = router.route((0.0, 20.0), (30.0, 20.0), is_air=True)
        self.assertEqual(len(ground.path), 2)
        self.assertGreater(len(air.path), 2)

    def test_aircraft_overflies_height_limited_building(self):
        data = formation(constraints=[{
            "constraint_id": "BUILDING", "type": "no_go",
            "applies_to": "all", "height_m": 9.0,
            "area": {"polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]},
        }])
        scenario = parse_message(message(), data)
        router = Router(scenario, [])

        above = router.route(
            (-10.0, 0.0), (30.0, 0.0),
            is_air=True, altitude_m=60.0)
        below = router.route(
            (-10.0, 0.0), (30.0, 0.0),
            is_air=True, altitude_m=5.0)

        self.assertEqual(len(above.path), 2)
        self.assertGreater(len(below.path), 2)
        self.assertFalse(path_enters_polygon(
            below.path, [(10, -5), (20, -5), (20, 5), (10, 5)]))

    def test_airspace_no_go_applies_at_every_altitude(self):
        data = formation(constraints=[{
            "constraint_id": "AIRSPACE", "type": "no_go",
            "applies_to": "air", "height_m": 9.0,
            "area": {"polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]},
        }])
        scenario = parse_message(message(), data)
        route = Router(scenario, []).route(
            (-10.0, 0.0), (30.0, 0.0),
            is_air=True, altitude_m=60.0)
        self.assertGreater(len(route.path), 2)
        self.assertFalse(path_enters_polygon(
            route.path, [(10, -5), (20, -5), (20, 5), (10, 5)]))

    def test_air_threat_still_reroutes_above_building_height(self):
        data = formation(constraints=[
            {
                "constraint_id": "BUILDING", "type": "no_go",
                "applies_to": "all", "height_m": 9.0,
                "area": {
                    "polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]},
            },
            {
                "constraint_id": "AIR-THREAT", "type": "threat",
                "applies_to": "all", "intensity": 1.0,
                "area": {
                    "polygon": [[10, -15], [20, -15], [20, 15], [10, 15]]},
            },
        ])
        scenario = parse_message(message(), data)
        route = Router(scenario, [], risk_weight=50.0).route(
            (-10.0, 0.0), (30.0, 0.0),
            is_air=True, altitude_m=60.0)
        self.assertGreater(len(route.path), 2)
        for first, second in zip(route.path, route.path[1:]):
            self.assertGreater(
                segment_polygon_distance(
                    first, second,
                    [(10, -15), (20, -15), (20, 15), (10, 15)]),
                0.0)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.scenario = parse_message(message(), formation())

    def _single_unit(self, index, task=None):
        data = formation()
        data["formation"]["units"] = [data["formation"]["units"][index]]
        return parse_message(message(tasks=[task or point_task()]), data)

    def test_assignments_and_commands(self):
        plan = Planner(self.scenario).plan()
        self.assertEqual(plan.metrics.assigned_subtasks, 2)
        self.assertEqual(plan.metrics.unassigned_subtasks, 0)
        starts = [a.start_s for a in plan.assignments]
        self.assertLess(max(starts) - min(starts), 1e-6,
                        "协同组没有对齐开始时刻")
        self.assertTrue(plan.commands)
        for command in plan.commands:
            self.assertLessEqual(command.duration_s, 120.0 + 1e-9)
            self.assertIn(command.phase, ("TRANSIT", "HOLD", "STOP"))
        stops = [c for c in plan.commands if c.phase == "STOP"]
        self.assertTrue(stops)
        for stop in stops:
            self.assertEqual((stop.linear_x, stop.linear_z, stop.angular_z),
                             (0.0, 0.0, 0.0))

    def test_ground_path_avoids_obstacle(self):
        plan = Planner(self._single_unit(0)).plan()
        self.assertEqual(len(plan.assignments), 1)
        ground = plan.assignments[0]
        self.assertGreater(len(ground.path), 2)
        self.assertFalse(path_enters_polygon(
            ground.path, [(10, -5), (20, -5), (20, 5), (10, 5)]))

    def test_air_path_is_straight(self):
        plan = Planner(self._single_unit(1)).plan()
        self.assertEqual(len(plan.assignments[0].path), 2)

    def test_planner_passes_cruise_altitude_to_air_router(self):
        data = formation(constraints=[{
            "constraint_id": "BUILDING", "type": "no_go",
            "applies_to": "all", "height_m": 9.0,
            "area": {"polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]},
        }])
        data["formation"]["units"] = [
            dict(data["formation"]["units"][1],
                 position=[0, 0], altitude_m=60.0),
        ]
        scenario = parse_message(message(tasks=[point_task()]), data)
        plan = Planner(scenario).plan()
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(len(plan.assignments[0].path), 2)

    def test_no_go_target_rejected(self):
        scenario = self._single_unit(0, point_task(target={"point": [15, 0]}))
        plan = Planner(scenario).plan()
        self.assertEqual(plan.metrics.unassigned_subtasks, 1)
        self.assertEqual(plan.unassigned[0]["reason"], "NO_GO")

    def test_area_can_contain_obstacles_when_concrete_points_are_clear(self):
        task = point_task()
        task["target"] = {"area": [[-10, -10], [30, -10],
                                  [30, 10], [-10, 10]]}
        task["allow_split"] = False
        data = formation()
        data["formation"]["units"] = [data["formation"]["units"][0]]
        data["constraints"].append({
            "constraint_id": "BUILDING", "type": "no_go",
            "applies_to": "ground",
            "area": {"polygon": [[10, -5], [20, -5],
                                 [20, 5], [10, 5]]},
        })
        scenario = parse_message(message(tasks=[task]), data)
        plan = Planner(scenario).plan()
        self.assertEqual(plan.metrics.assigned_subtasks, 1)

    def test_deterministic(self):
        first = Planner(self.scenario).plan().to_dict()
        second = Planner(self.scenario).plan().to_dict()
        for data in (first, second):
            data.pop("generated_at", None)
            data["metrics"].pop("plan_latency_ms", None)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_window_rejection_is_reported(self):
        tasks = [dict(message()["tasks"][0],
                      window={"start_s": 0, "end_s": 5})]
        scenario = parse_message(message(tasks=tasks), formation())
        plan = Planner(scenario).plan()
        self.assertEqual(plan.metrics.unassigned_subtasks, 2)
        reasons = {item["reason"] for item in plan.unassigned}
        self.assertIn("WINDOW", reasons)

    def test_capability_rejection_is_reported(self):
        tasks = [dict(message()["tasks"][0],
                      required_capabilities={"RCN": 3})]
        scenario = parse_message(message(tasks=tasks), formation())
        plan = Planner(scenario).plan()
        # 没有平台满足 RCN3 时，可拆分段数退化为 1，未分配 1 个槽位
        self.assertEqual(plan.metrics.unassigned_subtasks, 1)
        reasons = {item["reason"] for item in plan.unassigned}
        self.assertIn("NO_CAPABILITY", reasons)

    def test_objective_switch_is_recorded(self):
        plan = Planner(self.scenario, objective="risk").plan()
        self.assertEqual(plan.objective, "risk")

    def _exposure_scenario(self):
        """单台地面平台、去程必经一个威胁区：用来区分时效与暴露度。"""
        data = formation(constraints=[{
            "constraint_id": "THREAT", "type": "threat",
            "applies_to": "ground", "intensity": 1.0,
            "area": {"polygon": [[10, -5], [20, -5], [20, 5], [10, 5]]},
        }])
        data["formation"]["units"] = [data["formation"]["units"][0]]
        return parse_message(message(tasks=[point_task()]), data)

    def test_exposure_objective_avoids_threat(self):
        scenario = self._exposure_scenario()
        fast = Planner(scenario, objective="timeliness").plan()
        safe = Planner(scenario, objective="exposure").plan()
        self.assertEqual(safe.objective, "exposure")
        # 时效目标走直线穿威胁区；暴露度目标绕行，暴露量必须更低。
        self.assertGreater(fast.objective_metrics["total_exposure"], 0.0)
        self.assertLess(safe.objective_metrics["total_exposure"],
                        fast.objective_metrics["total_exposure"])
        self.assertGreaterEqual(
            safe.objective_metrics["detection_probability"], 0.0)
        self.assertLessEqual(
            safe.objective_metrics["detection_probability"], 1.0)

    def test_dispersion_alias_maps_to_exposure(self):
        plan = Planner(self._exposure_scenario(), objective="dispersion").plan()
        self.assertEqual(plan.objective, "exposure")


class ThreatScopeCostTests(unittest.TestCase):
    def test_short_corner_crossing_has_exact_positive_overlap(self):
        polygon = [[-55, -85], [-20, -85], [-20, -45], [-55, -45]]
        start = (-20.0, -22.5)
        goal = (-56.9, -48.8)
        self.assertGreater(
            segment_polygon_overlap_length(start, goal, polygon), 1.0)

    def test_air_only_threat_is_ignored_for_ground_cost(self):
        data = formation(constraints=[{
            "constraint_id": "AIR-ONLY", "type": "threat",
            "applies_to": "air", "intensity": 1.0,
            "area": {"polygon": [[0, 5], [20, 5], [20, 15], [0, 15]]},
        }])
        scenario = parse_message(message(), data)
        model = CostModel(scenario, objective="exposure")
        ground = scenario.platform_map["U1"]
        air = scenario.platform_map["U2"]
        route = [(0.0, 10.0), (20.0, 10.0)]
        self.assertEqual(model.path_risk(ground, route, 5.0, 10.0,
                                         (20.0, 10.0)), 0.0)
        self.assertGreater(model.path_risk(air, route, 10.0, 10.0,
                                           (20.0, 10.0)), 0.0)

    def test_asl_exposure_plan_has_no_threat_segment_overlap(self):
        message_path = os.path.join(BASE_DIR, "interop", "scenarios",
                                    "asl_junction.message.json")
        formation_path = os.path.join(BASE_DIR, "interop", "scenarios",
                                      "asl_junction.formation.json")
        with open(message_path, encoding="utf-8-sig") as stream:
            raw_message = json.load(stream)
        with open(formation_path, encoding="utf-8-sig") as stream:
            raw_formation = json.load(stream)
        scenario = parse_message(raw_message, raw_formation)
        threats = [
            item for item in scenario.constraints
            if item.get("type") == "threat"
            and item.get("applies_to") in ("ground", "air", "all")
        ]
        plan = Planner(scenario, objective="exposure").plan()
        self.assertEqual(plan.objective_metrics["total_exposure"], 0.0)
        from interop.routing import DEFAULT_THREAT_CLEARANCE_M
        for assignment in plan.assignments:
            items = threats
            platform = scenario.platform_map[assignment.unit_id]
            if platform.is_air:
                items = [
                    item for item in threats
                    if item.get("applies_to") in ("air", "all")
                ]
            else:
                items = [
                    item for item in threats
                    if item.get("applies_to") in ("ground", "all")
                ]
            for first, second in zip(assignment.path, assignment.path[1:]):
                for item in items:
                    overlap = segment_polygon_overlap_length(
                        first, second, item["area"]["polygon"])
                    self.assertLessEqual(
                        overlap, 1e-9,
                        "%s crosses %s" %
                        (assignment.unit_id, item.get("constraint_id")))
                    clearance = segment_polygon_distance(
                        first, second, item["area"]["polygon"])
                    self.assertGreaterEqual(
                        clearance, DEFAULT_THREAT_CLEARANCE_M - 1e-6,
                        "%s only has %.3f m clearance to %s" %
                        (assignment.unit_id, clearance,
                         item.get("constraint_id")))


class OutputTests(unittest.TestCase):
    def test_write_outputs_and_validate(self):
        scenario = parse_message(message(), formation())
        plan = Planner(scenario).plan()
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_outputs(plan, scenario, tmp)
            for key in ("plan_json", "assignments_csv", "commands_csv",
                        "report_md", "manifest_json"):
                self.assertTrue(os.path.exists(paths[key]), key)
            with open(paths["plan_json"], encoding="utf-8") as stream:
                data = json.load(stream)
            for key in ("plan_id", "assignments", "commands", "schema_version",
                        "unassigned", "conflicts", "metrics"):
                self.assertIn(key, data)
            self.assertEqual(data["schema_version"], "0.3")
            with open(paths["manifest_json"], encoding="utf-8") as stream:
                manifest = json.load(stream)
            self.assertEqual(manifest["backend"], "unified")
            self.assertTrue(manifest["outputs"]["plan_json"]["sha256"])
            self.assertIn("ros2_commands", manifest["outputs"])
            with open(paths["ros2_commands"], encoding="utf-8") as stream:
                ros2_text = stream.read()
            self.assertIn("ros2 topic pub -r 20 /container_00/robot_", ros2_text)
            self.assertIn("angular: {x:", ros2_text)
            self.assertIn("geometry_msgs/msg/Twist", ros2_text)
            self.assertNotIn(" Z:", ros2_text)
            for line in ros2_text.splitlines():
                if line.startswith("ros2 topic pub"):
                    self.assertIn("/container_00/robot_", line)
                    self.assertIn("geometry_msgs/msg/Twist", line)
                    self.assertNotIn(" Z:", line)

    def test_result_status_is_not_execution_evidence(self):
        scenario = parse_message(message(), formation())
        plan = Planner(scenario).plan()
        self.assertEqual(plan.result_status, "PLAN_ONLY")
        self.assertEqual(plan.evidence_source, "NO_EXECUTION_EVIDENCE")


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.scenario = parse_message(message(), formation())

    def test_detects_window_overrun(self):
        rows = [dict(unit_id="U1", robot_id=1, parent_task_id="T1",
                     subtask_id="T1-S1", start_s=190.0, end_s=210.0,
                     travel_s=5.0, path_length_m=10.0, path=[],
                     window_start_s=0.0, window_end_s=200.0)]
        result = audit(self.scenario, rows, "test", "timeliness", 1.0)
        self.assertEqual(result["violation_count"], 1)
        self.assertEqual(result["violations"][0]["type"], "WINDOW")

    def test_detects_path_through_obstacle(self):
        rows = [dict(unit_id="U1", robot_id=1, parent_task_id="T1",
                     subtask_id="T1-S1", start_s=10.0, end_s=20.0,
                     travel_s=5.0, path_length_m=40.0,
                     path=[(-10, 0), (30, 0)],
                     window_start_s=0.0, window_end_s=200.0)]
        result = audit(self.scenario, rows, "test", "timeliness", 1.0)
        self.assertIn("PATH_NO_GO",
                      {item["type"] for item in result["violations"]})

    def test_detects_force_limit(self):
        tasks = [dict(message()["tasks"][0], max_units=1)]
        scenario = parse_message(message(tasks=tasks), formation())
        rows = []
        for index, unit in enumerate(("U1", "U2")):
            rows.append(dict(unit_id=unit, robot_id=index + 1,
                             parent_task_id="T1",
                             subtask_id="T1-S%d" % (index + 1),
                             start_s=0.0, end_s=10.0, travel_s=1.0,
                             path_length_m=5.0, path=[],
                             window_start_s=0.0, window_end_s=200.0))
        result = audit(scenario, rows, "test", "timeliness", 1.0)
        self.assertIn("FORCE_LIMIT",
                      {item["type"] for item in result["violations"]})


class CliSmokeTests(unittest.TestCase):
    def test_plan_and_validate(self):
        from interop.cli import main
        scenario_dir = os.path.join(BASE_DIR, "tests", "fixtures", "interop_legacy")
        message_path = os.path.join(scenario_dir, "area_recon.message.json")
        formation_path = os.path.join(scenario_dir, "area_recon.formation.json")
        if not os.path.exists(message_path):
            self.skipTest("缺少历史接口测试夹具")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan")
            code = main(["plan", "--message", message_path,
                         "--formation", formation_path, "--out", out])
            self.assertEqual(code, 0)
            self.assertEqual(main(["validate", "--plan",
                                   os.path.join(out, "plan.json")]), 0)

    def test_to_v2_rejects_lossy_conversion_without_writing(self):
        from interop.cli import main
        scenario_dir = os.path.join(BASE_DIR, "tests", "fixtures", "interop_legacy")
        message_path = os.path.join(scenario_dir, "area_recon.message.json")
        formation_path = os.path.join(scenario_dir, "area_recon.formation.json")
        if not os.path.exists(message_path):
            self.skipTest("样例未生成")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "scenario.json")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["to-v2", "--message", message_path,
                             "--formation", formation_path, "--out", out])
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(out))
            self.assertIn("TASK_GEOMETRY", stderr.getvalue())
            self.assertIn("PLATFORM_PROFILE", stderr.getvalue())
            self.assertIn("WORLD_CONSTRAINTS", stderr.getvalue())


class RuntimeIntegrationTests(unittest.TestCase):
    def test_execution_navigation_keeps_threats_soft_and_scoped(self):
        from interop.runtime import nav_from_scenario
        data = formation(constraints=[
            {"constraint_id": "AIR", "type": "threat", "applies_to": "air",
             "intensity": 1.0,
             "area": {"polygon": [[10, -2], [20, -2],
                                  [20, 2], [10, 2]]}},
            {"constraint_id": "GROUND", "type": "threat",
             "applies_to": "ground", "intensity": 1.0,
             "area": {"polygon": [[30, -2], [40, -2],
                                  [40, 2], [30, 2]]}},
        ])
        scenario = parse_message(message(), data)
        nav = nav_from_scenario(scenario, avoid_threats=True)
        self.assertTrue(nav.free((15.0, 0.0)))
        self.assertTrue(nav.free((35.0, 0.0)))
        self.assertIsNotNone(nav.ground_threat_map)
        self.assertTrue(nav.ground_threat_map.free((15.0, 0.0)))
        self.assertFalse(nav.ground_threat_map.free((35.0, 0.0)))
        self.assertIsNotNone(nav.air_threat_map)
        self.assertFalse(nav.air_threat_map.free((15.0, 0.0)))
        self.assertTrue(nav.air_threat_map.free((35.0, 0.0)))

    def test_threat_over_initial_position_is_plannable(self):
        """威胁区覆盖出生点时必须保留真实起点，不能陷入无限重规划。"""
        from interop.runtime import nav_from_scenario
        data = formation(
            constraints=[{
                "constraint_id": "START-THREAT", "type": "threat",
                "applies_to": "all", "intensity": 0.7,
                "area": {"polygon": [[-5, -5], [5, -5],
                                     [5, 5], [-5, 5]]},
            }])
        scenario = parse_message(message(tasks=[point_task()]), data)
        nav = nav_from_scenario(scenario, avoid_threats=True)
        start = (0.0, 0.0)
        self.assertTrue(nav.free(start))
        self.assertFalse(nav.ground_threat_map.free(start))
        self.assertFalse(nav.air_threat_map.free(start))
        route = nav.plan(start, (30.0, 0.0))
        self.assertEqual(route['path'][0], [0.0, 0.0])
        self.assertEqual(route['path'][-1], [30.0, 0.0])

    def test_bundle_scene_passes_base_validator(self):
        import contracts_v2
        from interop.runtime import to_v2_dict
        scenario = parse_message(message(), formation())
        data = to_v2_dict(scenario, message(), formation())
        contracts_v2.check_scenario_v2(data)
        self.assertIn("interop", data["_meta"])
        self.assertEqual(data["_meta"]["interop"]["message"]["message_id"],
                         "MSG-TEST")
        self.assertFalse(data["_meta"]["interop"]["authoritative"])

    def test_runtime_planner_end_to_end(self):
        from interop.runtime import InteropPlanner, to_v2_dict
        from run_demo_v2 import simulate
        tasks = [point_task()]
        scenario = parse_message(message(tasks=tasks), formation())
        v2 = to_v2_dict(scenario, message(tasks=tasks), formation())
        engine = InteropPlanner(scenario, objective="timeliness", data=v2)
        report, audit = simulate(v2, mode="normal", max_ticks=80,
                                 motion="teleport", planner=engine)
        self.assertEqual(report["planner"], "interop")
        self.assertTrue(report["all_succeeded"], report.get("need_report"))
        self.assertGreaterEqual(report["makespan"], 20)
        self.assertTrue(any(e["kind"] == "job_succeeded" for e in audit))

    def test_planner_from_v2_maps_assault(self):
        from interop.runtime import planner_from_v2
        scenario_path = os.path.join(BASE_DIR, "scenarios", "fleet_demo.json")
        if not os.path.exists(scenario_path):
            self.skipTest("缺少 fleet_demo 场景")
        with open(scenario_path, encoding="utf-8-sig") as stream:
            data = json.load(stream)
        planner = planner_from_v2(data)
        asl = [t for t in planner.scenario.tasks if t.task_type == "T-ASL"]
        self.assertEqual(len(asl), 1)
        self.assertEqual(asl[0].task_id, "J6")

    def test_workbench_accepts_current_scene_and_rejects_retired_inputs(self):
        import workbench_server
        config = workbench_server.validate_config(dict(
            scenario="interop_recon", planner="interop", motion="real",
            avoid=False, behavior=False, max_ticks=260, objective="makespan"))
        self.assertEqual(config["planner"], "interop")
        self.assertEqual(config["max_ticks"], 260)
        with self.assertRaises(ValueError):
            workbench_server.validate_config(dict(
                scenario="asl_city", planner="interop", motion="real",
                avoid=True, behavior=False, max_ticks=620))


class AslIntegrationTests(unittest.TestCase):
    """T-ASL：五类任务里的行为型任务，规划槽位与运行视图。"""

    @staticmethod
    def scenario():
        from interop.message import load_scenario
        root = os.path.join(BASE_DIR, "interop", "scenarios")
        return load_scenario(
            os.path.join(root, "asl_junction.message.json"),
            os.path.join(root, "asl_junction.formation.json"))

    def test_plan_has_three_roles(self):
        plan = Planner(self.scenario()).plan()
        self.assertEqual(len(plan.assignments), 6)
        self.assertFalse(plan.unassigned)
        roles = {item.role for item in plan.assignments}
        self.assertEqual(roles, {"scout", "assault", "assessor"})
        scout = [item for item in plan.assignments if item.role == "scout"][0]
        self.assertEqual(scout.unit_id, "UAV-31")
        assessor = [item for item in plan.assignments if item.role == "assessor"][0]
        self.assertEqual(assessor.unit_id, "UAV-41")
        assault = [item for item in plan.assignments if item.role == "assault"]
        self.assertEqual(len(assault), 4)
        for item in assault:
            self.assertGreaterEqual(item.end_s, item.start_s)

    def test_to_v2_assault_job(self):
        from contracts_v2 import check_scenario_v2
        from interop.runtime import to_v2_dict
        v2 = to_v2_dict(self.scenario())
        check_scenario_v2(v2)
        job = v2["jobs"][0]
        self.assertEqual(job["type"], "assault")
        self.assertEqual(job["crew"], 6)
        behavior = job["_behavior"]
        self.assertEqual(behavior["effect_kind"], "damage")
        self.assertEqual(behavior["required_level"], 6.0)
        self.assertEqual(behavior["scout_pid"], "rover_31")
        self.assertEqual(behavior["assessor_pid"], "rover_41")
        self.assertEqual(behavior["target_id"], "JUNCTION-CROSS-01")
        self.assertIn("sdf", v2["_meta"])

    def test_runtime_assault_end_to_end(self):
        from interop.runtime import InteropPlanner, to_v2_dict
        from run_demo_v2 import simulate
        scenario = self.scenario()
        v2 = to_v2_dict(scenario)
        engine = InteropPlanner(scenario, objective="timeliness", data=v2)
        report, audit = simulate(v2, mode="normal", max_ticks=320,
                                 motion="real", avoid=True, behavior=True,
                                 planner=engine)
        self.assertTrue(report["all_succeeded"], report.get("need_report"))
        results = [event.get("event") for event in audit
                   if event.get("kind") == "behavior_event"
                   and (event.get("event") or {}).get("kind") == "behavior_result"]
        self.assertTrue(results)
        items = {item["id"]: item["status"]
                 for item in results[-1]["items"] if item.get("required")}
        self.assertEqual(items.get("effect"), "achieved")
        self.assertEqual(items.get("confirmation"), "achieved")

    def test_workbench_config_interop_asl(self):
        import workbench_server
        config = workbench_server.validate_config(dict(
            scenario="interop_asl", planner="interop", motion="real",
            avoid=True, behavior=True, max_ticks=700))
        self.assertEqual(config["planner"], "interop")
        self.assertTrue(config["behavior"])
        self.assertTrue(config["avoid"])
        with self.assertRaises(ValueError):
            workbench_server.validate_config(dict(
                scenario="interop_asl", planner="base", motion="teleport",
                avoid=False, behavior=False, max_ticks=700))


if __name__ == "__main__":
    unittest.main()
