import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import desktop_workflow
import workbench_server
from interop.geometry import point_in_polygon
from interop.urban_maps import scene_geometry
from interop.random_tasks import (_collect_polygon_vertices, _valid_placement,
                                 task_boundary_points, validate_task_bounds)


class MapRandomTaskTests(unittest.TestCase):
    def test_nested_target_dictionary_vertices_are_checked(self):
        task = dict(task_id='edge', task_type='T-RCN', target={
            'area': {'polygon': [[10, 10], [30, 10], [30, 105], [10, 105]]}})
        self.assertEqual(len(list(_collect_polygon_vertices(task['target']))), 4)
        self.assertFalse(_valid_placement([task], [], [0, 0, 100, 100]))

    def test_inside_region_with_outside_orbit_is_rejected(self):
        task = dict(task_id='edge', task_type='T-SEC', target={
            'defense_area': [[30, 30], [50, 30], [50, 50], [30, 50]]},
            params=dict(air_orbit_radius_m=55))
        self.assertFalse(_valid_placement([task], [], [0, 0, 100, 100]))

    def test_patrol_vertices_must_be_clear_platform_destinations(self):
        task = dict(task_id='patrol', task_type='T-PTL', target={
            'patrol_area': [[10, 10], [30, 10], [30, 40], [10, 40]]})
        obstacle = [[20, 5], [25, 5], [25, 15], [20, 15]]
        # The first two vertices are clear and the other two are outside the
        # building.  Moving this polygon four metres up puts a checkpoint in
        # the building, even though its centroid remains on a clear road.
        task['target']['patrol_area'] = [
            [10, 10], [21, 10], [30, 40], [10, 40]]
        self.assertFalse(_valid_placement([task], [obstacle], [0, 0, 100, 100]))

    def test_screenshot_patrol_seed_produces_clear_checkpoints(self):
        checked, _ = desktop_workflow.validate_draft(
            workbench_server,
            self.draft('interop_patrol', 'mixed', 856948801),
        )
        geometry = scene_geometry(checked['formation']['meta'])
        obstacles = [
            item['polygon'] for item in geometry['obstacles']
        ]
        polygon = checked['message']['tasks'][0]['target']['patrol_area']
        self.assertTrue(polygon)
        for point in polygon:
            self.assertFalse(
                any(point_in_polygon(point, item) for item in obstacles),
                point,
            )

    def test_screenshot_seed_has_all_geometry_and_orbit_inside_map(self):
        checked, _ = desktop_workflow.validate_draft(workbench_server,
            self.draft('interop_containment', 'residential', 1703134165))
        validate_task_bounds(checked['message'], 'residential')
        for point in task_boundary_points(checked['message']['tasks'][0]):
            self.assertGreaterEqual(point[1], -255)

    def test_manual_out_of_map_area_is_rejected_before_run_creation(self):
        draft = self.draft('interop_containment')
        draft['request'].update(randomize_tasks=False, reseed_on_run=False)
        draft['message']['tasks'][0]['target']['defense_area'] = [
            [-215, -205], [-155, -205], [-155, -265], [-215, -265]]
        with tempfile.TemporaryDirectory() as directory, patch.object(
                workbench_server, 'OUTPUTS', Path(directory)):
            with self.assertRaisesRegex(ValueError, '超出地图边界'):
                workbench_server.Workbench().start(draft['request'], desktop_input=draft)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_old_outside_snapshot_is_read_without_relocation(self):
        draft = self.draft('interop_containment')
        draft['message']['tasks'][0]['target']['defense_area'] = [
            [-215, -205], [-155, -205], [-155, -265], [-215, -265]]
        with tempfile.TemporaryDirectory() as directory, patch.object(
                workbench_server, 'OUTPUTS', Path(directory)):
            run = Path(directory) / 'workbench_old_bounds'
            run.mkdir()
            (run / 'manifest.json').write_text(json.dumps(
                {'workbench_config': draft['request']}), encoding='utf-8')
            (run / 'desktop_input.json').write_text(json.dumps(draft), encoding='utf-8')
            loaded = desktop_workflow.get_config(workbench_server, run_id=run.name)['draft']
            self.assertEqual(loaded['message'], draft['message'])
            self.assertEqual(loaded['formation'], draft['formation'])

    def draft(self, scenario="interop_recon", map_id="residential", seed=12345):
        draft = desktop_workflow.get_config(
            workbench_server, scenario
        )["draft"]
        draft["request"].update(
            map_id=map_id,
            randomize_tasks=True,
            task_seed=seed,
            reseed_on_run=False,
        )
        return draft

    def test_same_seed_is_reproducible_across_task_types(self):
        for scenario in (
            "interop_containment",
            "interop_patrol",
            "interop_recon",
            "interop_hold",
            "interop_asl",
        ):
            with self.subTest(scenario=scenario):
                draft = self.draft(scenario)
                first, _ = desktop_workflow.validate_draft(
                    workbench_server, copy.deepcopy(draft)
                )
                second, _ = desktop_workflow.validate_draft(
                    workbench_server, copy.deepcopy(draft)
                )
                self.assertEqual(first["message"], second["message"])
                self.assertEqual(first["formation"], second["formation"])

    def test_different_seed_changes_task_points(self):
        first = self.draft(seed=12345)
        second = self.draft(seed=98765)
        checked_first, _ = desktop_workflow.validate_draft(
            workbench_server, first
        )
        checked_second, _ = desktop_workflow.validate_draft(
            workbench_server, second
        )
        first_points = checked_first["message"]["_meta"][
            "task_placement"
        ]["placements"]
        second_points = checked_second["message"]["_meta"][
            "task_placement"
        ]["placements"]
        self.assertNotEqual(first_points, second_points)

    def test_generated_anchors_are_clear_on_each_map(self):
        for map_id in ("residential", "downtown", "mixed"):
            with self.subTest(map_id=map_id):
                checked, summary = desktop_workflow.validate_draft(
                    workbench_server, self.draft(map_id=map_id)
                )
                geometry = scene_geometry(
                    checked["formation"]["meta"]
                )
                obstacles = [
                    item["polygon"] for item in geometry["obstacles"]
                ]
                placements = summary["task_randomization"]["placement"][
                    "placements"
                ]
                self.assertTrue(placements)
                for placement in placements:
                    point = placement["anchor"]
                    self.assertFalse(
                        any(point_in_polygon(point, item) for item in obstacles),
                        (map_id, point),
                    )

    def test_map_override_replaces_previous_map_constraints(self):
        draft = self.draft(map_id="residential")
        first, _ = desktop_workflow.validate_draft(
            workbench_server, draft
        )
        first["request"].update(
            map_id="mixed", task_seed=22222, reseed_on_run=False
        )
        second, summary = desktop_workflow.validate_draft(
            workbench_server, first
        )
        sources = {
            item.get("source")
            for item in second["formation"]["constraints"]
            if str(item.get("source") or "").startswith("urban_map:")
        }
        self.assertEqual(sources, {"urban_map:mixed"})
        self.assertEqual(summary["map"]["id"], "mixed")
        self.assertEqual(second["formation"]["meta"]["map_id"], "mixed")

    def test_randomization_can_be_disabled_without_changing_task_points(self):
        draft = self.draft()
        draft["request"].update(
            randomize_tasks=False, task_seed=0, reseed_on_run=False
        )
        before = copy.deepcopy(draft["message"]["tasks"])
        checked, summary = desktop_workflow.validate_draft(
            workbench_server, draft
        )
        self.assertEqual(checked["message"]["tasks"], before)
        self.assertFalse(summary["task_randomization"]["enabled"])

    def test_each_run_refresh_reseeds_tasks_on_selected_map(self):
        draft = self.draft(map_id="mixed", seed=11111)
        draft["request"].update(
            randomize_tasks=True,
            reseed_on_run=True,
        )
        with patch(
            "interop.random_tasks.new_task_seed",
            side_effect=(24681357, 97531864),
        ):
            first = desktop_workflow.refresh_legacy_preset(
                workbench_server, copy.deepcopy(draft)
            )
            second = desktop_workflow.refresh_legacy_preset(
                workbench_server, copy.deepcopy(draft)
            )

        self.assertTrue(first["task_randomized"])
        self.assertTrue(second["task_randomized"])
        self.assertEqual(first["draft"]["request"]["task_seed"], 24681357)
        self.assertEqual(second["draft"]["request"]["task_seed"], 97531864)
        first_placement = first["draft"]["message"]["_meta"][
            "task_placement"
        ]
        second_placement = second["draft"]["message"]["_meta"][
            "task_placement"
        ]
        self.assertEqual(first_placement["map_id"], "mixed")
        self.assertEqual(second_placement["map_id"], "mixed")
        self.assertNotEqual(
            first_placement["placements"],
            second_placement["placements"],
        )


if __name__ == "__main__":
    unittest.main()
