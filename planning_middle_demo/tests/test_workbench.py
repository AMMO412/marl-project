"""Exercise workbench input boundaries and HTTP output, without changing old runs."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench_server import (LocalServer, Workbench, load_run, make_handler,
                              run_worker, validate_config)

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

    def test_objective_exposure_and_legacy_dispersion(self):
        c = validate_config({'scenario': 'simple_city', 'objective': 'exposure'})
        self.assertEqual(c['objective'], 'exposure')
        # 2026-11：旧名 dispersion 归一为 exposure，旧请求仍可复跑。
        c = validate_config({'scenario': 'simple_city', 'objective': 'dispersion'})
        self.assertEqual(c['objective'], 'exposure')

    def test_balanced_is_a_fourth_objective(self):
        c = validate_config({'scenario': 'simple_city', 'objective': 'balanced'})
        self.assertEqual(c['objective'], 'balanced')

    def test_run_no_longer_emits_standalone_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            request = dict(scenario='simple_city', mode='normal', motion='teleport',
                           avoid=False, behavior=False, max_ticks=12,
                           objective='makespan', planner='base')
            (out / 'request.json').write_text(json.dumps(request), encoding='utf-8')
            run_worker(out)
            self.assertTrue((out / 'report.json').is_file())
            self.assertTrue((out / 'summary.txt').is_file())
            self.assertFalse((out / 'report.html').exists())
            self.assertFalse((out / 'trajectory.html').exists())

    def test_fleet_fast_demo(self):
        c = validate_config(dict(scenario='fleet_demo', motion='teleport', avoid=False,
                                 mode='failure', max_ticks=60))
        self.assertEqual(c['mode'], 'failure')

    def test_behavior_record_is_preferred_and_loads_actions(self):
        catalog = Workbench().catalog()
        # 默认运行规则：优先多任务融合层运行，其次其它融合层运行，再其次
        # asl_city / 任意行为运行。单任务的区域封控运行不抢占首页——它自己的
        # 控制画面从该运行的地图工具条"区域封控视图"进入。
        interop_multi = [r for r in catalog['runs']
                         if r.get('planner') == 'interop'
                         and int(r.get('total') or 0) >= 2]
        interop = [r for r in catalog['runs'] if r.get('planner') == 'interop']
        asl = [r for r in catalog['runs']
               if r['behavior_details'] and r.get('scenario') == 'asl_city']
        detailed = [r for r in catalog['runs'] if r['behavior_details']]
        pool = interop_multi or interop or asl or detailed
        expected = pool[0]['id'] if pool else 'workbench_behavior_20261028'
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
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
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
        html = body.decode()
        self.assertIn('动作回放', html)
        self.assertIn('value="balanced"', html)
        self.assertIn('id="compare-panel"', html)
        self.assertIn('id="report-objective"', html)
        self.assertIn('id="run-compare-card"', html)
        self.assertIn('id="show-threats"', html)
        self.assertNotIn('id="overview-tabs"', html)
        self.assertNotIn('id="page-original"', html)

    def test_bad_body_and_external_origin_are_rejected(self):
        self.assertEqual(self.request('POST', '/api/runs', '[]')[0], 400)
        self.assertEqual(self.request('POST', '/api/runs', '{}',
                                     {'Origin': 'https://example.com'})[0], 403)

    def test_objective_compare_endpoint(self):
        body = json.dumps({'scenario': 'interop_patrol'})
        code, payload = self.request('POST', '/api/compare', body)
        self.assertEqual(code, 200)
        data = json.loads(payload)
        self.assertEqual([x['objective'] for x in data['results']],
                         ['timeliness', 'energy', 'balanced', 'exposure'])
        self.assertTrue(data['threats'])
        self.assertEqual(self.request('POST', '/api/compare',
                                      json.dumps({'scenario': 'asl_city'}))[0], 400)

    def test_files_cannot_escape_allowlist(self):
        for path in ['/artifacts/avoid_run/../../workbench_server.py',
                     '/api/runs/..', '/api/source/unknown', '/workbench_server.py']:
            self.assertIn(self.request('GET', path)[0], (400, 404))

    def test_second_server_cannot_reuse_same_port(self):
        with self.assertRaises(OSError):
            LocalServer(('127.0.0.1', self.server.server_port), make_handler(Workbench()))


if __name__ == '__main__':
    unittest.main()
