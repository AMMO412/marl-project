# -*- coding: utf-8 -*-
"""Contract tests for the desktop shell's compact workbench API."""
import unittest
from pathlib import Path

import workbench_server


class DesktopBridgeTests(unittest.TestCase):
    def test_catalog_advertises_desktop_bridge(self):
        catalog = workbench_server.Workbench().catalog()
        self.assertIs(catalog['features'].get('desktop_bridge'), True)
        self.assertEqual(catalog['service'], 'planning-middle-workbench/v1')

    def test_recording_projects_to_desktop_run(self):
        fixture = (Path(workbench_server.ROOT) / 'outputs' /
                   'behavior_20261028_verify' / 'behavior_trace.json')
        if not fixture.is_file():
            self.skipTest('历史专项记录夹具缺失')
        run = workbench_server.desktop_run('behavior_20261028_verify', 120)
        self.assertEqual(run['id'], 'behavior_20261028_verify')
        self.assertGreaterEqual(len(run['tasks']), 1)
        self.assertGreater(run['end'], 0)
        self.assertEqual(run['at_s'], 120)
        for task in run['tasks']:
            for key in ('id', 'label', 'status', 'assigned', 'progress'):
                self.assertIn(key, task)
        for event in run['events']:
            self.assertIn('kind', event)
            self.assertIn('sim_s', event)


if __name__ == '__main__':
    unittest.main()
