import json
import sys
import time

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
from interop.message import parse_message
from interop.runtime import InteropPlanner, to_v2_dict
from run_demo_v2 import simulate

base = r'D:\Desktop\MARL项目\planning_middle_demo\interop\scenarios'
raw_message = json.load(open(base + r'\mixed_inspection.message.json', encoding='utf-8'))
raw_formation = json.load(open(base + r'\mixed_inspection.formation.json', encoding='utf-8'))
scenario = parse_message(raw_message, raw_formation)
v2 = to_v2_dict(scenario, raw_message, raw_formation)
engine = InteropPlanner(scenario, objective='timeliness', data=v2)

calls = []


def timed(coord, now):
    started = time.perf_counter()
    plan, events = engine(coord, now)
    calls.append((now, round(time.perf_counter() - started, 2),
                  len(plan.assignments), [j.job_id for j in coord.jobs.values()
                                          if j.status == 'pending']))
    return plan, events


started = time.perf_counter()
report, audit = simulate(v2, mode='normal', max_ticks=20, motion='teleport',
                         planner=timed)
print('elapsed', round(time.perf_counter() - started, 1))
print('plans', report['plans'], 'done', report['done'])
for row in calls[:40]:
    print(row)
