"""Browser edits keep immutable snapshots and the existing planner semantics."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workbench_server as backend
from workbench_browser import configuration, edited_draft
from interop.message import parse_message
from interop.runtime import InteropPlanner, nav_from_scenario, to_v2_dict
from interop.templates import decompose
from run_demo_v2 import simulate


class BrowserIntegrationTests(unittest.TestCase):
    def test_position_recommendation_uses_current_city_map(self):
        from desktop_workflow import preview_task
        config = configuration(backend, 'interop_patrol', map_id='residential')
        result = preview_task(dict(message=config['message'], formation=config['formation'],
            task_id=config['message']['tasks'][0]['task_id'], targets=config['targets'],
            recommend=True, now=0, objective='makespan', max_ticks=600))
        self.assertEqual(result['error'], '')
        self.assertEqual(len(result['slots']), 4)
        self.assertTrue(all(slot['unit_id'] for slot in result['slots']))
        self.assertTrue(any(target['slot'] == 'observation' for target in result['targets']))

    def test_limited_timing_and_export_use_the_same_profile(self):
        from tests.test_interop import message, formation, point_task
        from interop.scheduler import Planner
        units = formation(constraints=[])
        units['formation']['units'] = units['formation']['units'][:1]
        units['formation']['units'][0]['speed_mps'] = 8
        task = point_task(target={'point': [80, 0]})
        original = Planner(parse_message(message(tasks=[task]), units)).plan()
        units['meta']['motion_model'] = 'acceleration_limited'
        limited = Planner(parse_message(message(tasks=[task]), units)).plan()
        self.assertEqual(len(limited.assignments), 1)
        self.assertGreater(limited.assignments[0].travel_s, original.assignments[0].travel_s)
        transit = sum(command.duration_s for command in limited.commands
                      if command.phase == 'TRANSIT')
        self.assertAlmostEqual(transit, limited.assignments[0].travel_s, places=5)

    def test_imported_cases_preserve_source_and_current_matching(self):
        for key, tasks, slots in [('interop_integrated', 5, 19),
                                  ('interop_campus_motion20', 9, 30)]:
            message, formation = backend.interop_inputs_for(key)
            scene = parse_message(message, formation)
            self.assertEqual(len(scene.tasks), tasks)
            self.assertEqual(len(scene.platforms), 20)
            self.assertEqual(len(decompose(scene)), slots)
            self.assertIn('sensor', formation['formation']['units'][0]['_source_profile'])
            self.assertEqual(backend.validate_config({'scenario': key})['map_id'], 'source')

    def test_template_edit_uses_selected_map_and_starts_at_zero(self):
        config = configuration(backend, 'interop_patrol', map_id='mixed')
        self.assertEqual(config['request']['map_id'], 'mixed')
        self.assertEqual(config['sim_s'], 0)
        self.assertEqual(config['completed'], [])
        self.assertEqual(config['edit_mode'], 'new_run')
        self.assertTrue(any(c.get('source') == 'urban_map:mixed'
                            for c in config['formation']['constraints']))

    def test_browser_save_preserves_edited_geometry(self):
        config = configuration(backend, 'interop_patrol', map_id='residential')
        edit = dict(source_run=None, tasks=deepcopy(config['message']['tasks']),
                    units=deepcopy(config['formation']['formation']['units']),
                    targets=config['targets'])
        before = deepcopy(edit)
        draft = edited_draft(backend, edit, config['request'])
        self.assertEqual(edit, before)
        self.assertFalse(draft['request']['randomize_tasks'])
        self.assertEqual(draft['message']['tasks'][0]['target'], edit['tasks'][0]['target'])

    def test_malformed_dynamic_request_is_rejected_before_creating_run(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(backend, 'OUTPUTS', Path(temp)):
            app = backend.Workbench()
            for payload in ({'live': 'yes'}, {'replay_edit': {}}):
                with self.assertRaises(ValueError):
                    app.start(payload)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_generic_slots_execute_their_own_destinations(self):
        from tests.test_interop import message, formation, point_task
        task = point_task()
        task.update(task_type='T-RCN', target={'target_list': [[8, 0], [50, 0]]},
                    min_units=2, max_units=2, window={'start_s': 0, 'end_s': 180},
                    params={'duration_s': 60})
        units = formation()
        units['formation']['units'] = units['formation']['units'][:2]
        for unit in units['formation']['units']:
            unit.update(position={'x': 0, 'y': 0}, speed_mps=2)
        scene = parse_message(message(tasks=[task]), units)
        data = to_v2_dict(scene)
        report, trace = simulate(data, 'normal', motion='real', avoid=True,
            behavior=False, max_ticks=180, planner=InteropPlanner(scene, data=data),
            nav=nav_from_scenario(scene))
        self.assertTrue(report['all_succeeded'])
        self.assertEqual(report['timeouts'], 0)
        self.assertEqual(report['jobs'][0]['attempts'], 1)
        ends = [row['event']['pos'] for row in trace
                if row['kind'] == 'feedback_applied' and row['event']['status'] == 'succeeded']
        for x in (8, 50):
            self.assertTrue(any(abs(pos[0] - x) < 0.6 for pos in ends), ends)
