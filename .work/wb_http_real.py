import json
import sys
import threading
import time
from http.client import HTTPConnection

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
from workbench_server import LocalServer, Workbench, make_handler

server = LocalServer(('127.0.0.1', 0), make_handler(Workbench()))
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_port


def request(method, url, body=None):
    conn = HTTPConnection('127.0.0.1', port, timeout=60)
    conn.request(method, url, body=body,
                 headers={'Content-Type': 'application/json'})
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, json.loads(payload.decode('utf-8')) if payload else None


config = dict(scenario='interop_neutral', mode='normal', motion='real',
              avoid=False, max_ticks=260, objective='makespan',
              behavior=False, planner='interop')
code, body = request('POST', '/api/runs', json.dumps(config))
print('post', code, body)
run_id = body['id']
deadline = time.time() + 240
state = body['state']
while time.time() < deadline:
    time.sleep(2)
    code, catalog = request('GET', '/api/catalog')
    state = (catalog.get('process') or {}).get('state')
    if state in ('complete', 'error'):
        break
print('state', state)
code, run = request('GET', '/api/runs/' + run_id)
print('run', code, run['report'].get('planner'), run['report'].get('done'),
      run['report'].get('makespan'), run['manifest'].get('plan_files'))
print('files', run['files'])
server.shutdown()
server.server_close()
