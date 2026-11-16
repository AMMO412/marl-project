import copy
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import desktop_workflow
import workbench_server as backend


class DesktopWorkflowTests(unittest.TestCase):
    def draft(self):
        return desktop_workflow.get_config(backend, 'interop_recon')['draft']

    def test_round_trip_and_template_is_unchanged(self):
        path = backend.ROOT / 'interop/scenarios/crossroad_recon.message.json'
        before = path.read_bytes()
        draft = self.draft()
        draft['message']['message_id'] = 'DESKTOP-ROUNDTRIP'
        normalized, summary = desktop_workflow.validate_draft(backend, draft)
        self.assertEqual(summary['tasks'], len(draft['message']['tasks']))
        self.assertEqual(normalized['message']['message_id'], 'DESKTOP-ROUNDTRIP')
        self.assertEqual(path.read_bytes(), before)

    def test_rejects_invalid_contract_and_unknown_fields(self):
        draft = self.draft()
        draft['message']['schema_version'] = '0.1'
        with self.assertRaises(ValueError):
            desktop_workflow.validate_draft(backend, draft)
        draft = self.draft()
        draft['execute'] = 'anything'
        with self.assertRaises(ValueError):
            desktop_workflow.validate_draft(backend, draft)

    def test_threat_over_initial_fleet_is_warning_not_validation_error(self):
        draft = self.draft()
        # Exercise a deliberately fixed overlap; random placement moves threats away.
        draft['request'].update(randomize_tasks=False, reseed_on_run=False)
        draft['formation']['constraints'] = [{
            'constraint_id': 'INITIAL-OVERLAP',
            'type': 'threat',
            'applies_to': 'all',
            'intensity': 0.7,
            'area': {'polygon': [[-30, 30], [20, 30],
                                 [20, -35], [-30, -35]]},
        }]
        normalized, summary = desktop_workflow.validate_draft(backend, draft)
        overlap = summary['initial_threat_overlap']
        self.assertTrue(overlap['allowed'])
        self.assertEqual(overlap['total'], 50)
        self.assertGreater(overlap['ground'], 0)
        self.assertGreater(overlap['air'], 0)
        self.assertIn('配置允许运行', overlap['warning'])
        self.assertEqual(normalized['formation']['constraints'][0]['constraint_id'],
                         'INITIAL-OVERLAP')

    def test_threat_over_initial_fleet_still_settles_instead_of_planning_forever(self):
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, nav_from_scenario, to_v2_dict
        from run_demo_v2 import simulate

        draft = self.draft()
        draft['formation']['constraints'] = [{
            'constraint_id': 'INITIAL-OVERLAP',
            'type': 'threat',
            'applies_to': 'all',
            'intensity': 0.7,
            'area': {'polygon': [[-30, 30], [20, 30],
                                 [20, -35], [-30, -35]]},
        }]
        scenario = parse_message(draft['message'], draft['formation'])
        data = to_v2_dict(scenario, draft['message'], draft['formation'])
        data['objective'] = 'exposure'
        nav = nav_from_scenario(scenario, avoid_threats=True)
        report, trace = simulate(
            data, 'normal', max_ticks=220, motion='real', avoid=True,
            behavior=True,
            planner=InteropPlanner(scenario, objective='exposure', data=data),
            nav=nav)
        self.assertTrue(report['all_succeeded'], report.get('jobs'))
        self.assertTrue(report['settled'])
        failures = [
            row for row in trace
            if row.get('kind') == 'behavior_event'
            and row.get('event', {}).get('kind') == 'route_failed'
            and row.get('event', {}).get('reason') == 'start_in_obstacle'
        ]
        self.assertEqual(failures, [])

    def test_historical_scene_does_not_silently_ignore_custom_input(self):
        draft = self.draft()
        draft['request'].update(scenario='simple_city', planner='base')
        with self.assertRaises(ValueError):
            desktop_workflow.validate_draft(backend, draft)

    def test_failed_validation_does_not_create_run(self):
        draft = self.draft()
        draft['formation'] = None
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'OUTPUTS', Path(directory)):
            with self.assertRaises(ValueError):
                backend.Workbench().start(draft['request'], desktop_input=draft)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_saved_input_has_priority_over_current_template(self):
        draft = self.draft()
        draft['message']['message_id'] = 'ORIGINAL-SNAPSHOT'
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'OUTPUTS', Path(directory)):
            run = Path(directory) / 'workbench_snapshot'
            run.mkdir()
            (run / 'manifest.json').write_text(json.dumps({'workbench_config': draft['request']}))
            (run / 'desktop_input.json').write_text(json.dumps(draft))
            loaded = desktop_workflow.get_config(backend, run_id=run.name)
            self.assertEqual(loaded['input_source'], 'run_snapshot')
            self.assertEqual(loaded['draft']['message']['message_id'], 'ORIGINAL-SNAPSHOT')

    def test_http_native_run_exports_exact_custom_input_and_artifacts(self):
        template = backend.ROOT / 'interop/scenarios/crossroad_recon.message.json'
        before = hashlib.sha256(template.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'OUTPUTS', Path(directory)):
            app = backend.Workbench()
            server = backend.LocalServer(('127.0.0.1', 0), backend.make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:%s' % server.server_port

            def call(path, value=None, origin=None):
                headers = {'Content-Type': 'application/json'}
                if origin:
                    headers['Origin'] = origin
                data = None if value is None else json.dumps(value).encode()
                with urlopen(Request(base + path, data=data, headers=headers), timeout=40) as response:
                    return json.load(response)

            try:
                draft = call('/api/desktop/config?scenario=interop_recon')['draft']
                draft['request']['max_ticks'] = 10
                draft['message']['message_id'] = 'DESKTOP-HTTP-SMOKE'
                targets = call(
                    '/api/desktop/editor-metadata',
                    {'message': draft['message']})['targets']
                targets[0]['speed_mps'] = 4.5
                draft['targets'] = targets
                checked = call('/api/desktop/validate', draft)
                self.assertTrue(checked['valid'])
                self.assertEqual(
                    checked['draft']['message']['tasks'][0]['params'][
                        'tracking_target']['speed_mps'],
                    4.5)
                self.assertNotIn('targets', checked['draft'])
                with self.assertRaises(HTTPError) as caught:
                    call('/api/desktop/runs', draft, origin='https://untrusted.invalid')
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()
                self.assertIsNone(app.process)
                started = call('/api/desktop/runs', draft)
                app.process.wait(timeout=45)
                out = Path(directory) / started['id']
                self.assertEqual(
                    app.process.returncode,
                    0,
                    (out / 'worker.log').read_text(
                        encoding='utf-8', errors='replace'
                    ),
                )
                saved = json.loads((out / 'input_message.json').read_text(encoding='utf-8'))
                self.assertEqual(saved, checked['draft']['message'])
                desktop_input = json.loads(
                    (out / 'desktop_input.json').read_text(encoding='utf-8'))
                self.assertEqual(desktop_input, checked['draft'])
                self.assertNotIn('targets', desktop_input)
                manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['inputs']['message_sha256'], hashlib.sha256((out / 'input_message.json').read_bytes()).hexdigest())
                self.assertIn('input_message.json', call('/api/desktop/details/' + started['id'])['files'])
                details = call('/api/desktop/details/' + started['id'])
                self.assertEqual(details['files'][:3], ['agent_tasks.md', 'agent_tasks.csv', 'agent_tasks.json'])
                self.assertTrue(details['chain_summary']['passed'])
                for name in ('chain_viewer.html', 'chain_summary.json',
                             'chain_verification.json', 'chain_raw.json',
                             'initial_config.json', 'final_config.json',
                             'ros2_plan_node.py'):
                    self.assertIn(name, details['files'])
                for name in details['files'][:3]:
                    self.assertTrue((out / name).is_file(), name)
                self.assertIn('execution_plan.json',details['files'])
                self.assertIn('planning_history.json',details['files'])
                self.assertEqual(details['report']['plan_metrics_source'],'runtime_dispatch')
                bindings=details['execution_plan']['bindings']
                self.assertGreater(len(bindings),0)
                self.assertEqual({a['command_id'] for a in details['execution_plan']['assignments']},
                    {c['command_id'] for b in bindings for c in b['commands']})
                self.assertEqual(call('/artifacts/' + started['id'] + '/agent_tasks.json')['plan_id'],
                                 details['plan']['plan_id'])
                self.assertTrue(call('/artifacts/' + started['id']
                                     + '/chain_summary.json')['passed'])
                with urlopen(base + '/artifacts/' + started['id']
                             + '/chain_viewer.html', timeout=10) as response:
                    self.assertIn('全链路追溯',
                                  response.read().decode('utf-8'))
                all_events = call('/api/desktop/events/' + started['id'])
                self.assertEqual(all_events['id'], started['id'])
                self.assertGreater(len(all_events['events']), 0)
                self.assertEqual(call('/api/desktop/config?run=' + started['id'])['draft']['message'], saved)
                with self.assertRaises(HTTPError) as missing:
                    call('/artifacts/' + started['id'] + '/not-allowed.json')
                missing.exception.close()
            finally:
                if app.process and app.process.poll() is None:
                    app.process.terminate()
                    app.process.wait(timeout=10)
                server.shutdown()
                server.server_close()
        self.assertEqual(hashlib.sha256(template.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
