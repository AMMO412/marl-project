import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_workflow
import workbench_server as backend


class DesktopSceneInputs(unittest.TestCase):
    def setUp(self):
        original = backend.validate_config
        patcher = patch.object(backend, 'validate_config',
            lambda payload: original(dict(payload or {}, randomize_tasks=False)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_patrol_and_recon_start_at_original_fifty_platform_formation(self):
        original = backend.read_json(backend.ROOT / 'scenarios/sdf_initial_state.json')
        expected = {r['no']: r['start'] for r in original['robots']}
        for key in ('interop_patrol', 'interop_recon', 'interop_asl'):
            draft = desktop_workflow.get_config(backend, key)['draft']
            units = draft['formation']['formation']['units']
            self.assertEqual(len(units), 50)
            self.assertEqual({u['robot_id'] for u in units}, set(expected))
            for unit in units:
                self.assertEqual([unit['position']['x'], unit['position']['y']], expected[unit['robot_id']])
            self.assertTrue(any(c['type'] == 'threat' for c in draft['formation']['constraints']))

    def test_recon_area_and_search_starts_use_building_crossroad(self):
        draft = desktop_workflow.get_config(backend, 'interop_recon')['draft']
        task = draft['message']['tasks'][0]
        area = task['target']['area']
        self.assertEqual([sum(p[i] for p in area)/len(area) for i in (0, 1)], [-95, -145])
        for point in task['params']['search_starts'].values():
            self.assertTrue(-126 <= point[0] <= -64 and -176 <= point[1] <= -114)

    def test_demo_selection_rejects_outdated_inputs_and_short_runs(self):
        template = desktop_workflow.get_config(backend, 'interop_patrol')['draft']
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'OUTPUTS', Path(directory)):
            out = Path(directory) / 'workbench_fixture'
            out.mkdir()
            (out / 'report.json').write_text('{}')
            def save(draft):
                (out / 'manifest.json').write_text(json.dumps({'workbench_config': draft['request']}))
                (out / 'desktop_input.json').write_text(json.dumps(draft))
            old = json.loads(json.dumps(template))
            old['formation']['formation']['units'][0]['position']['x'] = -140
            save(old)
            self.assertIsNone(desktop_workflow.find_demo(backend, 'interop_patrol')['id'])
            old = json.loads(json.dumps(template)); old['request']['max_ticks'] = 10
            save(old)
            self.assertIsNone(desktop_workflow.find_demo(backend, 'interop_patrol')['id'])
            save(template)
            self.assertEqual(desktop_workflow.find_demo(backend, 'interop_patrol')['id'], out.name)
            self.assertEqual(backend.read_json(out / 'desktop_input.json'), template)
