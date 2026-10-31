import json
import sys
import tempfile
import time

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
import workbench_server as wb

for motion in ('real', 'teleport'):
    tmp = tempfile.mkdtemp(prefix='wb_motion_')
    out = wb.Path(tmp)
    request = dict(scenario='interop_neutral', mode='normal', motion=motion,
                   avoid=False, max_ticks=260, objective='makespan',
                   behavior=False, effect_kind='damage', planner='interop')
    (out / 'request.json').write_text(json.dumps(request), encoding='utf-8')
    started = time.perf_counter()
    wb.run_worker(out)
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    print(motion, 'elapsed', round(time.perf_counter() - started, 1),
          {k: report[k] for k in ('done', 'makespan', 'settled')})
