import json
import sys
import tempfile
import time

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
import workbench_server as wb

tmp = tempfile.mkdtemp(prefix='wb_interop_')
out = wb.Path(tmp)
request = dict(scenario='interop_neutral', mode='normal', motion='teleport',
               avoid=False, max_ticks=260, objective='makespan',
               behavior=False, effect_kind='damage', planner='interop')
(out / 'request.json').write_text(json.dumps(request), encoding='utf-8')
started = time.perf_counter()
wb.run_worker(out)
print('elapsed', round(time.perf_counter() - started, 1))
report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
print({k: report[k] for k in ('planner', 'done', 'makespan', 'settled')})
for job in report['jobs']:
    print(job['job_id'], job['status'], job['started_at'], job['planned_end'],
          round(job['progress'], 1), round(job['work'], 1))
manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
print(manifest['planner'], sorted(manifest['inputs']))
print('outdir', tmp)
