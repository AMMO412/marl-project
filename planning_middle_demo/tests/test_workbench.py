"""Exercise workbench input boundaries and HTTP output, without changing old runs."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench_server import LocalServer, Workbench, load_run, make_handler, validate_config

# 这两条用例校验"历史混合任务录制"（J1–J6、含累计换班）的读取口径。
# 默认运行会随最新实验变化，因此固定在录制的 run 上，缺失时跳过。
MIXED_RUN = 'workbench_20261028_213551_310530'


class ConfigTests(unittest.TestCase):
    def test_defaults_match_local_city_motion(self):
        c = validate_config({})
        self.assertEqual((c['scenario'], c['motion'], c['avoid']),
                         ('simple_city', 'real', True))

    def test_invalid_requests_never_reach_runner(self):
        for request in [[], {'scenario': '../secret'}, {'mode': 'shell'},
                        {'max_ticks': True}, {'max_ticks': 701},
                        {'motion': 'teleport'}, {'scenario': 'fleet_demo'},
                        {'objective': 'unsupported'}, {'avoid': 'false'},
                        {'command': 'arbitrary command'}]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate_config(request)

    def test_fleet_fast_demo(self):
        c = validate_config(dict(scenario='fleet_demo', motion='teleport', avoid=False,
                                 mode='failure', max_ticks=60))
        self.assertEqual(c['mode'], 'failure')

    def test_behavior_record_is_preferred_and_loads_actions(self):
        catalog = Workbench().catalog()
        # 默认运行规则：优先最新融合层运行，其次最新 asl_city 行为运行，
        # 再退回任意最新行为运行。
        interop = [r for r in catalog['runs'] if r.get('planner') == 'interop']
        asl = [r for r in catalog['runs']
               if r['behavior_details'] and r.get('scenario') == 'asl_city']
        detailed = [r for r in catalog['runs'] if r['behavior_details']]
        expected = (interop or asl or detailed)[0]['id'] if (interop or asl or detailed) \
            else 'workbench_behavior_20261028'
        self.assertEqual(catalog['default_run'], expected)
        if not (Path(__file__).resolve().parents[1] / 'outputs' / MIXED_RUN).is_dir():
            self.skipTest('缺少历史混合录制 %s' % MIXED_RUN)
        data = load_run(MIXED_RUN)
        self.assertTrue(data['report']['behavior'])
        # 行为记录只覆盖真正下发过的作业；历史录制里有的作业一直 pending，
        # 按报告里非 pending 的作业数比对，而不是写死条数。
        started = [j for j in data['report']['jobs'] if j['status'] != 'pending']
        self.assertEqual(len(data['replay']['behaviors']), len(started))
        phases = {s['phase'] for w in data['replay']['workers'] for s in w['samples']}
        self.assertTrue({'巡逻', '接替', '结果确认'}.issubset(phases))
        self.assertTrue(all('sim_s' in b for b in data['replay']['behaviors']))

    def test_detailed_record_has_global_route_times_and_changing_roles(self):
        catalog = Workbench().catalog()
        if not any(r['behavior_details'] for r in catalog['runs']):
            self.skipTest('No detailed workbench recording available')
        if not (Path(__file__).resolve().parents[1] / 'outputs' / MIXED_RUN).is_dir():
            self.skipTest('缺少历史混合录制 %s' % MIXED_RUN)
        data = load_run(MIXED_RUN)
        snapshots = [e for e in data['trace'] if e.get('event', {}).get('kind')
                     == 'behavior_detail']
        routes = [(e, r) for e in snapshots for r in e['event']['routes']]
        self.assertTrue(routes)
        for event, route in routes:
            self.assertEqual(route['recorded_at_sim_s'], event['sim_s'])
            self.assertGreaterEqual(event['sim_s'], route['t'])
            self.assertGreaterEqual(len(route['path']), 2)
        hold = [e['event']['debug'] for e in snapshots
                if e['event']['job_id'] == 'J5']
        self.assertGreater(len({s['primary'] for s in hold}), 1)
        self.assertEqual(hold[0]['handovers'], 0)
        self.assertEqual(hold[-1]['handovers'], 2)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer(('127.0.0.1', 0), make_handler(Workbench()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, url, body=None, headers=None):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, url, body=body, headers=headers or {})
        r = conn.getresponse()
        result = (r.status, r.read())
        conn.close()
        return result

    def test_catalog_and_static(self):
        code, body = self.request('GET', '/api/catalog')
        self.assertEqual(code, 200)
        self.assertIn('runs', json.loads(body))
        code, body = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn('动作回放', body.decode())
        self.assertNotIn('id="page-original"', body.decode())

    def test_bad_body_and_external_origin_are_rejected(self):
        self.assertEqual(self.request('POST', '/api/runs', '[]')[0], 400)
        self.assertEqual(self.request('POST', '/api/runs', '{}',
                                     {'Origin': 'https://example.com'})[0], 403)

    def test_files_cannot_escape_allowlist(self):
        for path in ['/artifacts/avoid_run/../../workbench_server.py',
                     '/api/runs/..', '/api/source/unknown', '/workbench_server.py']:
            self.assertIn(self.request('GET', path)[0], (400, 404))

    def test_second_server_cannot_reuse_same_port(self):
        with self.assertRaises(OSError):
            LocalServer(('127.0.0.1', self.server.server_port), make_handler(Workbench()))


if __name__ == '__main__':
    unittest.main()
