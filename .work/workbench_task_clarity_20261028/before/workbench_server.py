"""Local workbench for the existing v2 planner. Python standard library only."""
import argparse
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'workbench'
OUTPUTS = ROOT / 'outputs'
SCENARIOS = {'simple_city': '城市道路场景', 'fleet_demo': '基础编成场景'}
MODES = {'normal': '正常执行', 'failure': '失败重试', 'timeout': '超时恢复',
         'kill': '成员失联', 'deviation': '进度偏差'}
ARTIFACTS = {'manifest.json', 'scenario.json', 'report.json', 'trace.jsonl',
             'summary.txt', 'report.html', 'trajectory.html', 'request.json', 'worker.log'}
SOURCES = {'readme': ROOT / 'README_v2.md', 'planner': ROOT / 'planner_v2.py',
           'coordinator': ROOT / 'coordinator_v2.py', 'fleet': ROOT / 'mock_fleet.py',
           'contracts': ROOT / 'contracts_v2.py'}


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('参数必须是 JSON 对象')
    allowed = {'scenario', 'mode', 'motion', 'avoid', 'max_ticks', 'objective',
               'behavior'}
    if set(data) - allowed:
        raise ValueError('存在不支持的参数')
    result = dict(scenario='simple_city', mode='normal', motion='real',
                  avoid=True, max_ticks=200, objective='makespan',
                  behavior=True)
    result.update(data)
    for key, choices in [('scenario', SCENARIOS), ('mode', MODES),
                         ('motion', ('real', 'teleport')),
                         ('objective', ('makespan', 'energy', 'dispersion'))]:
        if not isinstance(result[key], str) or result[key] not in choices:
            raise ValueError('无效参数：' + key)
    if type(result['max_ticks']) is not int or not 10 <= result['max_ticks'] <= 500:
        raise ValueError('仿真上限应为 10–500 步')
    if type(result['avoid']) is not bool:
        raise ValueError('avoid 必须是布尔值')
    if type(result['behavior']) is not bool:
        raise ValueError('behavior 必须是布尔值')
    if result['avoid'] and (result['motion'] != 'real' or result['scenario'] != 'simple_city'):
        raise ValueError('建筑绕障只适用于城市场景的逐步运动模式')
    # 到位行为依赖真实运动 + 建筑绕障：不满足时自动降级（与 simulate 内部
    # 逻辑一致），而非报错——teleport 快进检查规划时不必为行为层报错。
    if result['behavior'] and not (result['motion'] == 'real' and result['avoid']):
        result['behavior'] = False
    return result


def run_worker(out):
    """Reuse the planner and its exporters; retain every run in a fresh directory."""
    from run_demo_v2 import simulate
    from reporting_v2 import render_html, render_text
    from trajectory_v2 import render
    config = validate_config(read_json(out / 'request.json'))
    source = ROOT / 'scenarios' / (config['scenario'] + '.json')
    scenario = read_json(source)
    scenario['objective'] = config['objective']
    content = json.dumps(scenario, ensure_ascii=False, indent=2)
    report, audit = simulate(scenario, mode=config['mode'], motion=config['motion'],
                             avoid=config['avoid'], max_ticks=config['max_ticks'],
                             behavior=config['behavior'])
    manifest = dict(protocol=report['protocol'], python=sys.version,
                    scenario=str(source), scenario_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source_scenario_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    generated_at=datetime.now().astimezone().isoformat(),
                    backend='mock_only', external_integration_verified=False,
                    workbench_config=config, **{k: report[k] for k in
                    ('mode', 'motion', 'avoid', 'behavior', 'max_ticks', 'H', 'K', 'dev_threshold')})
    (out / 'scenario.json').write_text(content, encoding='utf-8')
    for name, value in [('report.json', report), ('manifest.json', manifest)]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'trace.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n'
                                           for e in audit), encoding='utf-8')
    (out / 'summary.txt').write_text(render_text(scenario, report, audit), encoding='utf-8')
    (out / 'report.html').write_text(render_html(scenario, report, audit), encoding='utf-8')
    render(out)


def run_path(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('无效运行编号')
    path = OUTPUTS / run_id
    if not path.is_dir():
        raise FileNotFoundError('运行不存在')
    return path


def load_run(run_id):
    from trajectory_v2 import build_replay_data
    out = run_path(run_id)
    scenario, report = read_json(out / 'scenario.json'), read_json(out / 'report.json')
    trace = [json.loads(line) for line in (out / 'trace.jsonl').read_text(encoding='utf-8').splitlines()
             if line.strip()]
    replay = build_replay_data(scenario, report, trace)
    obstacles, geometry_note = [], ''
    if 'simple_city.world' in str(scenario.get('_meta', {}).get('source', '')):
        try:
            from city_nav import bounds_from_scenario, load_obstacles
            geometry = load_obstacles(transform=scenario['_meta'],
                                      bounds=bounds_from_scenario(scenario))
            obstacles = geometry['obstacles']
            geometry_note = geometry['provenance']['rule']
        except (OSError, ValueError, KeyError) as exc:
            geometry_note = str(exc)
    return dict(id=run_id, scenario=scenario, report=report, trace=trace, replay=replay,
                manifest=read_json(out / 'manifest.json') if (out / 'manifest.json').exists() else {},
                obstacles=obstacles, geometry_note=geometry_note,
                files=[n for n in sorted(ARTIFACTS) if (out / n).is_file()])


class Workbench:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.current = None

    def status(self):
        if self.process is None:
            return None
        code = self.process.poll()
        return dict(id=self.current, state='running' if code is None else
                    ('complete' if code == 0 else 'error'), exit_code=code)

    def start(self, data):
        config = validate_config(data)
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError('已有仿真正在运行，请等待完成')
            run_id = datetime.now().strftime('workbench_%Y%m%d_%H%M%S_%f')
            out = OUTPUTS / run_id
            out.mkdir(parents=True, exist_ok=False)
            (out / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            with (out / 'worker.log').open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                                 '--worker', str(out)], stdout=log, stderr=log,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.current = run_id
            return self.status()

    def catalog(self):
        runs = []
        for out in sorted(OUTPUTS.iterdir(), reverse=True):
            if not out.is_dir() or not (out / 'report.json').is_file():
                continue
            if not (out / 'trace.jsonl').is_file():
                continue
            if out.name.startswith('workbench_') and not (out / 'trajectory.html').is_file():
                continue
            # Do not expose a partial run before the subprocess finishes exporting.
            if self.process and out.name == self.current and self.process.poll() is None:
                continue
            try:
                r = read_json(out / 'report.json')
                runs.append(dict(id=out.name, done=r['done'], total=len(r['jobs']),
                                 mode=r.get('mode', 'normal'), motion=r.get('motion', 'teleport'),
                                 avoid=r.get('avoid', False), behavior=r.get('behavior', False),
                                 behavior_details=r.get('behavior_details', False),
                                 objective=r.get('objective'),
                                 end=r.get('simulated_until_s'), energy=r.get('used_energy'),
                                 settled=r.get('settled'), retries=r.get('retries', 0),
                                 timeouts=r.get('timeouts', 0)))
            except (OSError, ValueError, KeyError):
                continue
        default_run = next((r['id'] for r in runs if r['behavior_details']), None)
        default_run = default_run or next((r['id'] for r in runs if r['id'] == 'workbench_behavior_20261028'), None)
        default_run = default_run or next((r['id'] for r in runs if r['behavior']), None)
        default_run = default_run or next((r['id'] for r in runs if r['id'] == 'avoid_run'), None)
        return dict(service='planning-middle-workbench/v1', default_run=default_run,
                    scenarios=SCENARIOS,
                    modes=MODES, runs=runs, process=self.status())


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, body, content_type='application/json; charset=utf-8', code=200):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == '/api/catalog':
                    return self.send(app.catalog())
                if path.startswith('/api/runs/'):
                    return self.send(load_run(path.split('/')[-1]))
                if path.startswith('/api/source/'):
                    source = SOURCES.get(path.split('/')[-1])
                    if source is None:
                        raise FileNotFoundError()
                    return self.send(dict(name=source.name, text=source.read_text(encoding='utf-8')))
                if path.startswith('/artifacts/'):
                    parts = path.split('/')
                    if len(parts) != 4 or parts[3] not in ARTIFACTS:
                        raise FileNotFoundError()
                    file = run_path(parts[2]) / parts[3]
                elif path == '/demos/behavior':
                    file = OUTPUTS / 'behavior_20261028_verify' / 'behavior_demo.html'
                    if not file.is_file():
                        file = OUTPUTS / 'behavior_demo' / 'behavior_demo.html'
                elif path == '/demos/schematic':
                    file = ROOT.parent / 'outputs' / '任务动态示意_20261027' / 'index.html'
                elif path in ('/', '/index.html', '/app.js', '/styles.css', '/favicon.svg'):
                    file = STATIC / ('index.html' if path == '/' else path[1:])
                else:
                    raise FileNotFoundError()
                body = file.read_bytes()
                mime = mimetypes.guess_type(file.name)[0] or 'text/plain'
                return self.send(body, mime + '; charset=utf-8')
            except FileNotFoundError:
                self.send({'error': '文件或运行不存在'}, code=404)
            except (ValueError, KeyError, TypeError) as exc:
                self.send({'error': str(exc)}, code=400)

        def do_POST(self):
            # A local-only API: reject browser requests from any other origin.
            origin = self.headers.get('Origin')
            expected = 'http://' + self.headers.get('Host', '')
            if origin and origin != expected:
                return self.send({'error': '仅允许工作台本身发起运行'}, code=403)
            if self.path != '/api/runs':
                return self.send({'error': '接口不存在'}, code=404)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 4096:
                    raise ValueError('请求大小无效')
                data = json.loads(self.rfile.read(length))
                self.send(app.start(data), code=202)
            except RuntimeError as exc:
                self.send({'error': str(exc)}, code=409)
            except (ValueError, TypeError) as exc:
                self.send({'error': str(exc)}, code=400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run_worker(args.worker)
        return
    OUTPUTS.mkdir(exist_ok=True)
    try:
        server = LocalServer(('127.0.0.1', args.port), make_handler(Workbench()))
    except OSError:
        if args.open:
            url = 'http://127.0.0.1:%d' % args.port
            try:
                with urlopen(url + '/api/catalog', timeout=2) as response:
                    existing = json.load(response)
                if existing.get('service') == 'planning-middle-workbench/v1':
                    webbrowser.open(url)
                    return
            except (OSError, ValueError):
                pass
        parser.exit(2, '端口 %d 已被占用；请使用 --port 指定其他端口。\n' % args.port)
    url = 'http://127.0.0.1:%d' % server.server_port
    print('MARL workbench: ' + url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
