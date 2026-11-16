"""Red targets are edited in a dedicated panel and stored in 4.1 params."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_workflow
import workbench_server as server
from interop.message import parse_message
from workbench_target_editor import (apply_targets, editor_target_slots,
                                     editor_targets)


def read_pair(preset):
    return server.interop_inputs_for(preset)


class TargetEditorTests(unittest.TestCase):
    def test_extracts_slots_from_current_scenarios(self):
        recon, _ = read_pair('interop_recon')
        tracking = editor_targets(recon)
        self.assertEqual(
            [(item['slot'], item['task_id']) for item in tracking],
            [('tracking', 'T1')])
        self.assertEqual(tracking[0]['target_id'], 'RCN-OBS-1')
        self.assertEqual(tracking[0]['move_after_s'], 6)

        asl, _ = read_pair('interop_asl')
        assault = editor_targets(asl)
        self.assertEqual(
            [(item['slot'], item['kind']) for item in assault],
            [('assault', 'point')])
        self.assertEqual(assault[0]['target_id'], 'JUNCTION-CROSS-01')
        self.assertEqual(assault[0]['point'], [-95.0, -145.0])

        patrol, _ = read_pair('interop_patrol')
        self.assertEqual(
            [item['slot'] for item in editor_targets(patrol)],
            ['observation'])
        containment, _ = read_pair('interop_containment')
        intruders = editor_targets(containment)
        self.assertEqual(
            [item['target_id'] for item in intruders], ['IN-1', 'IN-2', 'AU-1'])
        self.assertEqual({item['slot'] for item in intruders}, {'intruder'})
        hold, _ = read_pair('interop_hold')
        self.assertEqual(editor_targets(hold), [])

    def test_slot_catalog_exposes_widgets_and_defaults(self):
        slots = editor_target_slots()
        self.assertEqual(
            list(slots),
            ['tracking', 'observation', 'relay', 'intruder', 'assault'])
        self.assertEqual(slots['tracking']['task_types'], ['T-RCN'])
        self.assertEqual(slots['intruder']['task_types'], ['T-SEC'])
        self.assertTrue(slots['intruder']['multi'])
        self.assertFalse(slots['assault']['deletable'])
        self.assertIn(
            'point', [field['key'] for field in slots['assault']['fields']])
        self.assertEqual(slots['tracking']['defaults']['speed_mps'], 3)

    def test_all_six_templates_round_trip_without_change(self):
        for preset in server.INTEROP_PAIRS:
            with self.subTest(preset=preset):
                message, formation = read_pair(preset)
                tasks = apply_targets(
                    message['tasks'], editor_targets(message))
                self.assertEqual(tasks, message['tasks'])
                parse_message(dict(message, tasks=tasks), formation)

    def test_edit_each_editable_target_kind(self):
        recon, formation = read_pair('interop_recon')
        targets = editor_targets(recon)
        targets[0].update(goal=[130, 5], speed_mps=4.5,
                          track_outside_s=30)
        tasks = apply_targets(recon['tasks'], targets)
        params = tasks[0]['params']['tracking_target']
        self.assertEqual(params['goal'], [130.0, 5.0])
        self.assertEqual(params['speed_mps'], 4.5)
        self.assertEqual(params['track_outside_s'], 30.0)
        parse_message(dict(recon, tasks=tasks), formation)

        patrol, formation = read_pair('interop_patrol')
        targets = editor_targets(patrol)
        targets[0].update(goal=[12, 18])
        tasks = apply_targets(patrol['tasks'], targets)
        self.assertEqual(
            tasks[0]['params']['observation_target']['goal'], [12.0, 18.0])
        parse_message(dict(patrol, tasks=tasks), formation)

        containment, formation = read_pair('interop_containment')
        targets = editor_targets(containment)
        targets[0].update(compliance=False, t_start_s=8)
        tasks = apply_targets(containment['tasks'], targets)
        self.assertFalse(tasks[0]['params']['intruders'][0]['compliance'])
        self.assertEqual(tasks[0]['params']['intruders'][0]['t_start_s'], 8.0)
        parse_message(dict(containment, tasks=tasks), formation)

        asl, formation = read_pair('interop_asl')
        targets = editor_targets(asl)
        targets[0].update(point=[10, -20], target_id='RED-9',
                          object_label='新目标')
        tasks = apply_targets(asl['tasks'], targets)
        self.assertEqual(tasks[0]['target'], {'point': [10.0, -20.0]})
        self.assertEqual(tasks[0]['params']['target_id'], 'RED-9')
        self.assertEqual(tasks[0]['params']['object_label'], '新目标')
        parse_message(dict(asl, tasks=tasks), formation)

    def test_remove_non_mandatory_targets_and_keep_assault(self):
        recon, _ = read_pair('interop_recon')
        tasks = apply_targets(recon['tasks'], [])
        self.assertNotIn('tracking_target', tasks[0]['params'])
        containment, _ = read_pair('interop_containment')
        tasks = apply_targets(containment['tasks'], [])
        self.assertNotIn('intruders', tasks[0]['params'])
        asl, _ = read_pair('interop_asl')
        assault = editor_targets(asl)
        self.assertFalse(editor_target_slots()['assault']['deletable'])
        unchanged = apply_targets(asl['tasks'], assault)
        self.assertIn('point', unchanged[0]['target'])

    def test_unknown_extension_fields_survive_target_edit(self):
        message, _ = read_pair('interop_recon')
        message['tasks'][0]['params']['future_planner_hint'] = {
            'keep': [1, 2, 3]}
        targets = editor_targets(message)
        tasks = apply_targets(message['tasks'], targets)
        self.assertEqual(
            tasks[0]['params']['future_planner_hint'], {'keep': [1, 2, 3]})

    def test_skip_completed_tasks_and_reject_invalid_targets(self):
        recon, _ = read_pair('interop_recon')
        tasks = apply_targets(
            recon['tasks'], [], skip_task_ids={'T1'})
        self.assertIn('tracking_target', tasks[0]['params'])
        cases = [
            [dict(slot='tracking', task_id='NOPE')],
            [dict(slot='intruder', task_id='T1')],
            [dict(slot='tracking', task_id='T1', target_id='',
                  start=[0, 0], goal=[1, 1], speed_mps=1,
                  move_after_s=0, track_outside_s=1)],
            [dict(slot='tracking', task_id='T1', target_id='X',
                  start=[0, 0], goal=[1, 1], speed_mps=-1,
                  move_after_s=0, track_outside_s=1)],
        ]
        for targets in cases:
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                apply_targets(recon['tasks'], targets)
        duplicated = editor_targets(recon) + editor_targets(recon)
        with self.assertRaisesRegex(ValueError, '只能有一个'):
            apply_targets(recon['tasks'], duplicated)

    def test_validate_draft_applies_targets(self):
        draft = desktop_workflow.get_config(
            server, 'interop_recon')['draft']
        targets = editor_targets(draft['message'])
        targets[0]['speed_mps'] = 5
        draft['targets'] = targets
        normalized, _ = desktop_workflow.validate_draft(server, draft)
        self.assertEqual(
            normalized['message']['tasks'][0]['params'][
                'tracking_target']['speed_mps'], 5.0)
        self.assertNotIn('targets', normalized)

    def test_http_metadata_and_target_endpoints(self):
        app = server.Workbench()
        httpd = server.LocalServer(
            ('127.0.0.1', 0), server.make_handler(app))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%s' % httpd.server_port

        def call(path, value):
            request = Request(
                base + path, data=json.dumps(value).encode(),
                headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=10) as response:
                return json.load(response)

        try:
            message, _ = read_pair('interop_recon')
            metadata = call(
                '/api/desktop/editor-metadata', {'message': message})
            self.assertEqual(metadata['task_count'], 1)
            self.assertTrue(metadata['targets'])
            targets = metadata['targets']
            targets[0]['goal'] = [77, 88]
            edited = call('/api/desktop/editor-targets', {
                'message': message, 'targets': targets})
            self.assertEqual(
                edited['message']['tasks'][0]['params'][
                    'tracking_target']['goal'], [77.0, 88.0])
            self.assertEqual(edited['editor']['targets'][0]['goal'],
                             [77.0, 88.0])
            invalid = Request(
                base + '/api/desktop/editor-targets',
                data=json.dumps({'message': message}).encode(),
                headers={'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(invalid, timeout=10)
            caught.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
