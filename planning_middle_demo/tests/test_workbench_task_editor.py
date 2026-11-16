"""Structured task forms use the current 4.1 message and validator."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_workflow
import workbench_server as server
from workbench_task_editor import (EDITOR_TASK_GEOMETRY, TASK_DEFAULTS,
                                   TASK_PARAM_CATALOG, editor_task_types)


RED_TARGET_KEYS = {
    'tracking_target', 'observation_target', 'relay_target', 'intruders',
    'target_id', 'object_label',
}
KINDS = {
    'number', 'text', 'bool', 'point', 'point_list', 'string_list',
    'object', 'object_list',
}
PRESETS = {
    'T-RCN': 'interop_recon',
    'T-SEC': 'interop_containment',
    'T-PTL': 'interop_patrol',
    'T-HLD': 'interop_hold',
    'T-ASL': 'interop_asl',
}


def message_path(scenario):
    return server.ROOT / 'interop' / 'scenarios' / server.INTEROP_PAIRS[
        scenario][0]


def new_task(task_type, task_id='NEW-1'):
    defaults = TASK_DEFAULTS[task_type]
    return {
        'task_id': task_id,
        'task_type': task_type,
        'priority': defaults['priority'],
        'target': deepcopy(EDITOR_TASK_GEOMETRY[task_type]),
        'window': {'start_s': 0, 'end_s': 300},
        'required_capabilities': {},
        'min_units': defaults['min_units'],
        'max_units': defaults['max_units'],
        'params': deepcopy(defaults['params']),
    }


class TaskCatalogTests(unittest.TestCase):
    def test_five_task_type_templates(self):
        types = editor_task_types()
        self.assertEqual(
            list(types), ['T-RCN', 'T-SEC', 'T-PTL', 'T-HLD', 'T-ASL'])
        self.assertEqual(
            {key: value['label'] for key, value in types.items()},
            {
                'T-RCN': '协同侦察',
                'T-SEC': '区域封控',
                'T-PTL': '巡逻警戒',
                'T-HLD': '要点坚守',
                'T-ASL': '机动突击',
            })
        for key, value in types.items():
            self.assertEqual(value['target'], EDITOR_TASK_GEOMETRY[key])
            self.assertEqual(value['defaults'], TASK_DEFAULTS[key])
            self.assertTrue(value['params'])

    def test_catalog_entries_are_well_formed(self):
        for task_type, value in editor_task_types().items():
            with self.subTest(task_type=task_type):
                keys = [entry['key'] for entry in value['params']]
                self.assertEqual(len(keys), len(set(keys)), '参数键不能重复')
                for entry in value['params']:
                    self.assertIn(entry['kind'], KINDS, entry['key'])
                    if entry['kind'] == 'object_list':
                        self.assertIsInstance(entry.get('item'), dict,
                                              entry['key'])
                    self.assertTrue(entry.get('label'), entry['key'])

    def test_catalog_covers_every_template_parameter(self):
        for task_type, preset in PRESETS.items():
            message = server.read_json(message_path(preset))
            known = {
                entry['key'] for entry in TASK_PARAM_CATALOG[task_type]
            }
            for task in message['tasks']:
                if task['task_type'] != task_type:
                    continue
                missing = set(task['params']) - known - RED_TARGET_KEYS
                self.assertFalse(
                    missing, '%s 缺少参数目录: %s' % (task_type, missing))

    def test_new_task_defaults_validate_for_every_type(self):
        base = desktop_workflow.get_config(
            server, 'interop_recon')['draft']
        for task_type in PRESETS:
            with self.subTest(task_type=task_type):
                payload = deepcopy(base)
                payload['message']['message_id'] = (
                    'EDITOR-NEW-' + task_type.replace('-', ''))
                payload['message']['tasks'] = [new_task(task_type)]
                targets = []
                if task_type == 'T-ASL':
                    targets.append({
                        'slot': 'assault',
                        'task_id': 'NEW-1',
                        'kind': 'point',
                        'target_id': 'RED-ASL-1',
                        'object_label': '新突击目标',
                        'point': [0, 0],
                    })
                payload['targets'] = targets
                normalized, summary = desktop_workflow.validate_draft(
                    server, payload)
                self.assertEqual(summary['tasks'], 1)
                self.assertEqual(normalized['message']['tasks'][0]['task_type'],
                                 task_type)
                if task_type == 'T-ASL':
                    saved = normalized['message']['tasks'][0]
                    self.assertEqual(saved['min_units'], 3)
                    self.assertEqual(saved['params']['target_id'],
                                     'RED-ASL-1')

    def test_editor_metadata_is_json_serializable_and_non_mutating(self):
        message = server.read_json(message_path('interop_recon'))
        before = deepcopy(message)
        editor = desktop_workflow.editor_metadata(message)
        self.assertEqual(message, before)
        self.assertEqual(editor['task_count'], len(message['tasks']))
        self.assertEqual(list(editor['task_types']),
                         ['T-RCN', 'T-SEC', 'T-PTL', 'T-HLD', 'T-ASL'])
        json.dumps(editor, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
