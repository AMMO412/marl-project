import csv
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

import workbench_server as backend
from interop.agent_tasks import build_agent_tasks, agent_artifact, render_agent_tasks
from interop.output import write_outputs
from interop.scheduler import Planner
from interop.message import parse_message
from tests.test_interop import message, formation


class AgentTasksTests(unittest.TestCase):
    def test_platform_sequence_windows_and_cross_platform_constraints_survive_export(self):
        def task(unit, sub, start, dep, coord):
            return dict(unit_id=unit, robot_id=int(unit[1:]), subtask_id=sub,
                        parent_task_id='T1', task_type='T-PTL', role='patrol',
                        start_s=start, end_s=start+10, travel_s=2,
                        window=dict(start_s=0, end_s=100), depends_on=dep,
                        coordination=coord, status='ASSIGNED')
        plan = dict(plan_id='TEST', assignments=[
            task('U10','T1-S3',40,['T1-S1'],[]),
            task('U2','T1-S2',10,[],['simultaneous_arrival']),
            task('U10','T1-S1',10,[],['simultaneous_arrival'])],
            unassigned=[dict(subtask_id='T2-S1', reason='WINDOW')])
        data=build_agent_tasks(plan, [dict(unit_id=u) for u in ['U11','U3','U10','U2']])
        self.assertEqual([p['unit_id'] for p in data['agents']], ['U2','U10','U3','U11'])
        agent=data['agents'][1]
        self.assertEqual(agent['platform_id'],'rover_10')
        self.assertEqual([t['subtask_id'] for t in agent['tasks']],['T1-S1','T1-S3'])
        self.assertEqual(agent['tasks'][1]['depends_on'],['T1-S1'])
        self.assertEqual(agent['tasks'][1]['sequence'],2)
        self.assertEqual(agent['tasks'][0]['transit_start_s'],8)
        self.assertEqual(agent['tasks'][0]['coordination_peers'],[dict(unit_id='U2',subtask_id='T1-S2')])
        exported=json.loads(agent_artifact(data,'agent_tasks.json'))
        self.assertEqual(exported['unassigned'],plan['unassigned'])
        rows=list(csv.DictReader(io.StringIO(agent_artifact(data,'agent_tasks.csv').decode('utf-8-sig'))))
        self.assertEqual(rows[2]['window_end_s'],'100')
        self.assertEqual(rows[-1]['status'],'NO_ASSIGNMENT')

    def test_historical_missing_fields_are_not_reported_as_no_constraints(self):
        data=build_agent_tasks(dict(assignments=[dict(unit_id='U1',subtask_id='S1')]))
        text=render_agent_tasks(data)
        self.assertIn('未记录',text)
        self.assertNotIn('无显式条目',text)
        self.assertIn('不是实际执行时序',text)

    def test_outputs_prioritize_agent_report_and_hash_every_new_file(self):
        scenario=parse_message(message(),formation())
        plan=Planner(scenario).plan()
        with tempfile.TemporaryDirectory() as directory:
            paths=write_outputs(plan,scenario,directory)
            report=Path(paths['report_md']).read_text(encoding='utf-8')
            self.assertLess(report.index('单平台智能体任务'),report.index('## 1 指标'))
            manifest=json.loads(Path(paths['manifest_json']).read_text(encoding='utf-8'))
            from interop.output import sha256_file
            for name in ['agent_tasks_md','agent_tasks_csv','agent_tasks_json']:
                self.assertEqual(manifest['outputs'][name]['sha256'],sha256_file(paths[name]))

    def test_desktop_projection_preserves_subtasks_and_recognizes_future_participant(self):
        assignment=dict(unit_id='U9', robot_id=9, subtask_id='S1',parent_task_id='T1',
                        window=dict(start_s=12,end_s=90),depends_on=['S0'],coordination=['handover'])
        compact=backend.compact_plan(dict(assignments=[assignment]))
        for key in ['subtask_id','parent_task_id','window','depends_on','coordination']:
            self.assertEqual(compact['assignments'][0][key],assignment[key])
        doc=dict(replay=dict(end=100,workers=[],events=[dict(kind='job_dispatched',sim_s=50,job_id='T1',pids=['rover_09'])]),
                 report=dict(platforms=[dict(pid='rover_09',pos=[0,0]),dict(pid='rover_01',pos=[0,0])]),
                 agent_tasks=dict(agents=[dict(platform_id='rover_01',participates=True)]))
        with patch.object(backend,'load_run',return_value=doc):
            view=backend.desktop_run('history',0)
        self.assertTrue(view['platforms'][0]['participates'])
        self.assertFalse(view['platforms'][1]['participates'])
        self.assertEqual(view['events'],[])

    def test_historical_export_uses_saved_plan_without_rewriting_run(self):
        data=build_agent_tasks(dict(plan_id='SAVED',assignments=[]))
        with tempfile.TemporaryDirectory() as directory, patch.object(backend,'OUTPUTS',Path(directory)):
            run=Path(directory)/'history';run.mkdir()
            server=backend.LocalServer(('127.0.0.1',0),backend.make_handler(backend.Workbench()))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                with patch.object(backend,'load_run',return_value=dict(agent_tasks=data)):
                    with urlopen('http://127.0.0.1:%s/artifacts/history/agent_tasks.json'%server.server_port) as response:
                        self.assertEqual(json.load(response)['plan_id'],'SAVED')
                self.assertEqual(list(run.iterdir()),[])
            finally:
                server.shutdown();server.server_close();worker.join(timeout=5)


if __name__=='__main__':
    unittest.main()
