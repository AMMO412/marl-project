# -*- coding: utf-8 -*-

import math
import tempfile
import unittest
from pathlib import Path

from interop.benchmark_scenarios import build_suite, run_suite
from interop.gate import target_inside_no_go
from interop.message import parse_message
from interop.scheduler import Planner
from interop.templates import decompose
from interop.urban_maps import scene_geometry


class BenchmarkScenarioTests(unittest.TestCase):
    def test_suite_uses_existing_formation_and_five_task_types(self):
        suite = build_suite()
        self.assertEqual(
            set(suite),
            {
                "interop_bench_multitask",
                "interop_bench_deadlines",
                "interop_bench_threats",
                "interop_bench_chokepoint",
            },
        )
        for bundle in suite.values():
            scenario = parse_message(bundle.message, bundle.formation)
            self.assertEqual(len(scenario.platforms), 50)
            self.assertEqual(len(scenario.tasks), 5)
            self.assertEqual(
                {task.task_type for task in scenario.tasks},
                {"T-RCN", "T-SEC", "T-PTL", "T-HLD", "T-ASL"},
            )

    def test_suite_uses_packaged_maps_for_planner_and_display(self):
        expected = {
            "interop_bench_multitask": "residential",
            "interop_bench_deadlines": "downtown",
            "interop_bench_threats": "mixed",
            "interop_bench_chokepoint": "downtown",
        }
        for name, bundle in build_suite().items():
            meta = bundle.formation["meta"]
            self.assertEqual(meta["map_id"], expected[name])
            self.assertEqual(
                meta["map_geometry_authority"], "planning_and_display"
            )
            self.assertGreater(meta["map_constraint_count"], 0)
            urban_constraints = [
                item for item in bundle.formation["constraints"]
                if str(item.get("constraint_id", "")).startswith("URBAN-")
            ]
            self.assertEqual(
                len(urban_constraints), meta["map_constraint_count"]
            )
            display = scene_geometry(meta)
            self.assertEqual(display["map_id"], meta["map_id"])
            self.assertTrue(display["roads"])
            self.assertTrue(display["buildings"])
            self.assertEqual(
                len(display["buildings"]), len(
                    [
                        item for item in urban_constraints
                        if "BUILDING-" in item["constraint_id"]
                    ]
                ),
            )

    def test_threat_objective_reduces_exposure(self):
        bundle = build_suite()["interop_bench_threats"]
        scenario = parse_message(bundle.message, bundle.formation)
        urgency = Planner(scenario, objective="timeliness").plan()
        exposure = Planner(scenario, objective="exposure").plan()
        self.assertGreater(
            urgency.objective_metrics["total_exposure"],
            exposure.objective_metrics["total_exposure"],
        )
        self.assertLessEqual(
            exposure.objective_metrics["total_exposure"], 1e-9
        )
        self.assertEqual(
            urgency.metrics.assigned_subtasks
            + urgency.metrics.unassigned_subtasks,
            26,
        )
        self.assertEqual(
            exposure.metrics.assigned_subtasks
            + exposure.metrics.unassigned_subtasks,
            26,
        )

    def test_showcase_resources_are_fully_assignable(self):
        bundle = build_suite()["interop_bench_multitask"]
        scenario = parse_message(bundle.message, bundle.formation)
        plan = Planner(scenario, objective="balanced").plan()
        self.assertEqual(plan.metrics.assigned_subtasks, 26)
        self.assertEqual(plan.metrics.unassigned_subtasks, 0)
        self.assertEqual(plan.metrics.tasks_fully_assigned, 5)
        self.assertLess(plan.metrics.makespan_s, 700)

    def test_benchmark_slots_do_not_start_inside_urban_buildings(self):
        for name, bundle in build_suite().items():
            scenario = parse_message(bundle.message, bundle.formation)
            blocked = [
                subtask.subtask_id
                for subtask in decompose(scenario)
                if target_inside_no_go(subtask.target, scenario.constraints)
            ]
            self.assertEqual(blocked, [], name)

    def test_chokepoint_has_a_map_valid_long_range_task(self):
        bundle = build_suite()["interop_bench_chokepoint"]
        patrol = next(
            task for task in bundle.message["tasks"]
            if task["task_id"] == "BENCH-PTL"
        )
        area = patrol["target"]["patrol_area"]
        center = [
            sum(point[0] for point in area) / len(area),
            sum(point[1] for point in area) / len(area),
        ]
        units = bundle.formation["formation"]["units"]
        origin = [
            sum(unit["position"]["x"] for unit in units) / len(units),
            sum(unit["position"]["y"] for unit in units) / len(units),
        ]
        distance_m = math.hypot(
            center[0] - origin[0], center[1] - origin[1]
        )
        self.assertGreaterEqual(distance_m, 350.0)
        self.assertGreaterEqual(
            max(
                math.hypot(point[0] - origin[0], point[1] - origin[1])
                for point in area
            ),
            400.0,
        )
        bounds = bundle.formation["meta"]["map_scene_bounds"]
        for point in area + [
            patrol["params"]["observation_target"]["start"],
            patrol["params"]["observation_target"]["goal"],
        ]:
            self.assertGreaterEqual(point[0], bounds[0])
            self.assertLessEqual(point[0], bounds[2])
            self.assertGreaterEqual(point[1], bounds[1])
            self.assertLessEqual(point[1], bounds[3])

    def test_deadline_scenario_exercises_partial_assignment(self):
        bundle = build_suite()["interop_bench_deadlines"]
        scenario = parse_message(bundle.message, bundle.formation)
        plan = Planner(scenario, objective="timeliness").plan()
        self.assertGreater(plan.metrics.unassigned_subtasks, 0)
        self.assertTrue(plan.unassigned)
        self.assertTrue(
            any(item.get("reason") == "WINDOW" for item in plan.unassigned)
        )

    def test_suite_materializes_scene_and_plan_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_suite(
                Path(tmp), objectives=("timeliness", "exposure")
            )
            self.assertEqual(payload["scenario_count"], 4)
            for scenario in payload["scenarios"]:
                self.assertEqual(len(scenario["results"]), 2)
                root = Path(tmp) / scenario["name"]
                self.assertTrue((root / "message.json").is_file())
                self.assertTrue((root / "formation.json").is_file())
                self.assertTrue((root / "plan-timeliness.json").is_file())
                self.assertTrue((root / "plan-exposure.json").is_file())

    def test_workbench_exposes_benchmarks_without_adding_demo_scenes(self):
        import workbench_server
        from desktop_workflow import get_config

        self.assertEqual(len(workbench_server.SCENARIOS), 5)
        self.assertEqual(len(workbench_server.BENCHMARK_SCENARIOS), 4)
        self.assertEqual(len(workbench_server.CASE_SCENARIOS), 2)
        self.assertEqual(len(workbench_server.ALL_SCENARIOS), 11)
        config = workbench_server.validate_config(
            {
                "scenario": "interop_bench_multitask",
                "mode": "normal",
                "motion": "real",
                "objective": "balanced",
                "avoid": True,
                "behavior": True,
                "max_ticks": 700,
                "planner": "interop",
            }
        )
        self.assertEqual(config["scenario"], "interop_bench_multitask")
        message, formation = workbench_server.interop_inputs_for(
            "interop_bench_multitask"
        )
        self.assertEqual(len(message["tasks"]), 5)
        self.assertEqual(len(formation["formation"]["units"]), 50)
        draft = get_config(workbench_server, "interop_bench_multitask")
        self.assertTrue(draft["editable"])
        self.assertEqual(draft["summary"]["tasks"], 5)
        self.assertEqual(draft["summary"]["platforms"], 50)


if __name__ == "__main__":
    unittest.main()
