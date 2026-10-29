import hashlib, json, time, urllib.request
from pathlib import Path
root=Path('planning_middle_demo')
old=root/'outputs'/'avoid_run'
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in old.iterdir() if p.is_file()}
base='http://127.0.0.1:8766'
def get(path):
    with urllib.request.urlopen(base+path, timeout=20) as r:return json.load(r)
def run(config):
    req=urllib.request.Request(base+'/api/runs',data=json.dumps(config).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:job=json.load(r)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        catalog=get('/api/catalog')
        status=catalog['process']
        if status['state']!='running':
            assert status['state']=='complete',status
            data=get('/api/runs/'+job['id'])
            r=data['report']
            result={k:r[k] for k in ['mode','motion','done','settled','retries','timeouts','triggers','simulated_until_s']}
            result['id']=job['id'];result['road_count']=len(data['replay']['background']['roads']);result['obstacle_count']=len(data['obstacles'])
            print(json.dumps(result,ensure_ascii=False),flush=True)
            return result
        time.sleep(.35)
    raise TimeoutError(job)
results=[]
# Existing UI QA already exercised failure; verify all original presets independently.
for mode in ['normal','timeout','kill','deviation']:
    results.append(run(dict(scenario='fleet_demo',mode=mode,motion='teleport',avoid=False,max_ticks=60,objective='makespan')))
results.append(run(dict(scenario='simple_city',mode='normal',motion='real',avoid=True,max_ticks=200,objective='makespan')))
after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in old.iterdir() if p.is_file()}
assert before==after,'old run mutated'
assert results[-1]['done']==6 and results[-1]['road_count']==11 and results[-1]['obstacle_count']==7
assert results[1]['timeouts']>=1 and results[1]['retries']>=1
assert results[2]['done']==5 and not results[2]['settled']
assert results[3]['triggers']['deviation']>=1
Path('.work/workbench_qa/integration.json').write_text(json.dumps(dict(results=results,original_hashes=before,original_unchanged=True),ensure_ascii=False,indent=2),encoding='utf-8')
