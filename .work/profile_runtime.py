import cProfile
import pstats
import io
import json
import sys

sys.path.insert(0, r'D:\Desktop\MARL项目\planning_middle_demo')
from interop.message import parse_message
from interop.runtime import InteropPlanner, to_v2_dict
from run_demo_v2 import simulate

raw_message = json.load(open(r'D:\Desktop\MARL项目\planning_middle_demo\interop\scenarios\mixed_inspection.message.json', encoding='utf-8'))
raw_formation = json.load(open(r'D:\Desktop\MARL项目\planning_middle_demo\interop\scenarios\mixed_inspection.formation.json', encoding='utf-8'))
scenario = parse_message(raw_message, raw_formation)
v2 = to_v2_dict(scenario, raw_message, raw_formation)
engine = InteropPlanner(scenario, objective='timeliness', data=v2)

pr = cProfile.Profile()
pr.enable()
report, audit = simulate(v2, mode='normal', max_ticks=6, motion='teleport', planner=engine)
pr.disable()
out = io.StringIO()
pstats.Stats(pr, stream=out).sort_stats('cumulative').print_stats(25)
print(out.getvalue())
print('report', report['done'], report['plans'], report['makespan'])
