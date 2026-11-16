import copy
import unittest

import workbench_server as backend
from execution_evidence import bind_execution
from run_demo_v2 import simulate
from tests.test_flow_v2 import scenario


class ExecutionEvidenceTests(unittest.TestCase):
    def test_selected_version_and_attempt_exclude_unused_platforms(self):
        def a(robot,risk):
            return dict(robot_id=robot,unit_id='U'+str(robot),subtask_id='T1-S1',
                parent_task_id='T1',energy=2,risk=risk)
        history=[dict(runtime_plan_id=0,plan=dict(assignments=[a(1,99)])),
                 dict(runtime_plan_id=1,plan=dict(assignments=[a(2,3)]))]
        audit=[dict(kind='job_dispatched',plan_id=1,sim_s=5,job_id='T1',attempt=2,
            pids=['rover_02'],planned_start=5,planned_end=15,
            commands=[dict(worker_id='rover_02',command_id='cmd2')]),
            dict(kind='feedback_applied',event=dict(command_id='cmd2',status='succeeded')),
            dict(kind='attempt_finished',command_id='cmd2',sim_s=14)]
        result=bind_execution(history,audit,30,'balanced')
        self.assertEqual(result['assignments'][0]['robot_id'],2)
        self.assertEqual(result['assignments'][0]['runtime_plan_id'],1)
        self.assertEqual(result['assignments'][0]['attempt'],2)
        self.assertEqual(result['metrics']['total_exposure'],3)
        self.assertEqual(result['intervals']['rover_02'][0]['end_s'],14)
        self.assertTrue(result['comparison_complete'])
        self.assertNotIn('attempt',history[1]['plan']['assignments'][0])
        broken=copy.deepcopy(audit);broken[0]['pids']=['rover_01']
        with self.assertRaises(ValueError):bind_execution(history,broken,30,'balanced')

    def test_task_exposure_excludes_return_and_clips_command_window(self):
        constraints=[dict(type='threat',intensity=1,applies_to='ground',
            area=dict(polygon=[[-10,-10],[10,-10],[10,10],[-10,10]]))]
        replay=dict(workers=[dict(pid='rover_01',kind='UGV',samples=[
            dict(t=0,x=0,y=0,command='cmd'),dict(t=10,x=0,y=0,command='cmd'),
            dict(t=20,x=0,y=0,command='return:rover_01')])])
        full,_=backend.execution_exposure(replay,constraints)
        scoped,_=backend.execution_exposure(replay,constraints,
            dict(rover_01=[dict(command_id='cmd',start_s=2,end_s=8)]))
        self.assertAlmostEqual(full,20*.64)
        self.assertAlmostEqual(scoped,6*.64)

    def test_unfinished_attempt_is_not_marked_complete(self):
        self.assertFalse(bind_execution([],[],10,'makespan')['comparison_complete'])

    def test_lost_command_window_ends_at_abandonment(self):
        history=[dict(runtime_plan_id=0,plan=dict(assignments=[dict(
            robot_id=1,subtask_id='S1',parent_task_id='T1',energy=1,risk=1)]))]
        trace=[dict(kind='job_dispatched',plan_id=0,sim_s=0,job_id='T1',attempt=1,
            pids=['rover_01'],planned_start=0,planned_end=20,
            commands=[dict(worker_id='rover_01',command_id='c')]),
            dict(kind='command_abandoned',command_id='c',sim_s=8,reason='member_lost')]
        result=bind_execution(history,trace,100,'makespan')
        self.assertEqual(result['intervals']['rover_01'][0]['end_s'],8)
        self.assertFalse(result['comparison_complete'])


class DemoModesTests(unittest.TestCase):
    def test_mode_policy_is_visible_and_normalization_is_consistent(self):
        for mode in ('normal','failure','timeout','kill','deviation'):
            with self.subTest(mode=mode):
                result=backend.validate_config(dict(mode=mode,behavior=True))
                self.assertEqual(result['behavior'],mode not in ('timeout','deviation'))

    def test_real_timeout_stalls_then_cancels_and_retries(self):
        report,trace=simulate(scenario(),'timeout',max_ticks=250,motion='real',behavior=True)
        self.assertFalse(report['behavior'])
        self.assertGreater(report['timeouts'],0)
        self.assertTrue(any(e['kind']=='job_dispatched' and e['attempt']==2 for e in trace))

    def test_member_loss_is_injected_only_once_across_replans(self):
        report,trace=simulate(scenario(),'kill',max_ticks=200,motion='real')
        self.assertEqual(sum(e['kind']=='member_lost' for e in trace),1)

    def test_deviation_has_actual_deviation_events(self):
        from tests.test_interop import message, formation, point_task
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, to_v2_dict
        source=parse_message(message(tasks=[point_task()]),formation())
        data=to_v2_dict(source)
        report,trace=simulate(data,'deviation',max_ticks=200,motion='real',behavior=True,
                              planner=InteropPlanner(source,data=data))
        self.assertFalse(report['behavior'])
        self.assertTrue(any(e['kind']=='deviation' for e in trace))


if __name__=='__main__':unittest.main()
