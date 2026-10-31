import json
import time
import urllib.request

BASE = 'http://127.0.0.1:8766'


def request(method, path, body=None):
    data = body.encode('utf-8') if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.status, json.loads(response.read().decode('utf-8'))


config = dict(scenario='interop_neutral', mode='normal', motion='real',
              avoid=False, max_ticks=260, objective='makespan',
              behavior=False, planner='interop')
code, body = request('POST', '/api/runs', json.dumps(config))
print('post', code, body)
run_id = body['id']
for _ in range(120):
    time.sleep(2)
    _, catalog = request('GET', '/api/catalog')
    state = (catalog.get('process') or {}).get('state')
    if state in ('complete', 'error'):
        break
print('state', state)
_, run = request('GET', '/api/runs/' + run_id)
print('planner', run['report'].get('planner'), 'done', run['report'].get('done'),
      'makespan', run['report'].get('makespan'))
print('plan_files', run['manifest'].get('plan_files'))
print('topics', sorted({p['topic'] for p in run['report']['platforms']})[:3])
