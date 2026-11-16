"""Run with the extracted package's isolated embedded Python, not system Python."""
import json
import sys
import time
import threading
from pathlib import Path
from urllib.request import Request, urlopen

package, evidence = (Path(p).resolve() for p in sys.argv[1:3])
evidence.mkdir(parents=True, exist_ok=True)
assert Path(sys.executable).is_relative_to(package)
assert sys.flags.isolated and sys.flags.no_site
assert all(Path(p).is_relative_to(package) for p in sys.path)
import workbench_server as backend
import desktop_workflow

assert backend.ROOT.resolve() == package / 'app' / 'planning_middle_demo'
backend.OUTPUTS = package / 'data' / 'runs'
templates = {}
for scenario in backend.INTEROP_PAIRS:
    document = desktop_workflow.get_config(backend, scenario)
    draft, summary = desktop_workflow.validate_draft(backend, document['draft'])
    templates[scenario] = summary
samples = []
for record in json.loads((package / 'SAMPLES.json').read_text(encoding='utf-8-sig')):
    data = backend.load_run(record['id'])
    assert data['replay']['workers'] and data['replay']['end'] > 0
    assert not (data.get('scene_map') or {}).get('error'), data.get('scene_map')
    assert data['agent_tasks'] is not None
    samples.append(dict(id=record['id'], scenario=record['scenario'], duration=data['replay']['end']))
app = backend.Workbench()
server = backend.LocalServer(('127.0.0.1', 0), backend.make_handler(app))
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = 'http://127.0.0.1:%d' % server.server_port

def call(path, value=None):
    payload = None if value is None else json.dumps(value).encode()
    request = Request(base + path, data=payload, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)

try:
    catalog = call('/api/catalog')
    assert Path(catalog['app_root']).resolve() == backend.ROOT.resolve()
    assert Path(catalog['outputs_root']).resolve() == backend.OUTPUTS.resolve()
    draft = call('/api/desktop/config?scenario=interop_containment')['draft']
    draft['request']['max_ticks'] = 10
    draft['message']['message_id'] = 'PORTABLE-PACKAGE-SMOKE'
    result = app.start(draft['request'], desktop_input=draft)
    created = result['id']
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        report = backend.OUTPUTS / created / 'report.json'
        if report.is_file():
            break
        if app.status().get('state') == 'error':
            raise AssertionError(app.status())
        time.sleep(.25)
    else:
        raise TimeoutError('Portable worker did not finish')
    document = backend.load_run(created)
    assert document['manifest']['workbench_config']['max_ticks'] == 10
    assert (backend.OUTPUTS / created / 'ros2_plan_node.py').is_file()
    assert (backend.OUTPUTS / created / 'chain_viewer.html').is_file()
    assert not (backend.OUTPUTS / created / 'report.md').exists()
    assert not (backend.OUTPUTS / created / 'ros2_commands.txt').exists()
    print('Portable backend/worker verified:', created)
    result = dict(python=sys.version, executable=sys.executable,
                  isolated=True, no_user_site=True, module_root=str(backend.ROOT),
                  outputs_root=str(backend.OUTPUTS), templates=templates,
                  samples=samples, worker_run=created,
                  worker_created_in_package=True, http=True, gazebo_export=True,
                  chain_export=True, retired_files_absent=True)
    (evidence / 'portable-backend-verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
