"""Supplier increments exercised through the current workbench and archive."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import workbench_server as server
from chain_trace import verify_chain
from interop.ros2_plan_node import PlanSchedule, ZERO
from tests.test_dynamic_resume import seed_bundle, write
from workbench_replay_editor import SEED_FILE, playback_config, prepare_branch


class ColleagueIncrementTests(unittest.TestCase):
    def test_local_replacement_command_is_present_in_verified_archive(self):
        from tests.test_subtask_reassignment import _message, _formation, _ugv
        from interop.message import parse_message
        from interop.runtime import InteropPlanner, to_v2_dict
        from run_demo_v2 import simulate
        from chain_trace import ChainRecorder, export_chain
        message=_message(); formation=_formation([_ugv(n) for n in range(1,5)])
        parsed=parse_message(message,formation); data=to_v2_dict(parsed,message,formation)
        data['timeline']=[dict(t=20,event='member_lost',robot_no=1)]
        planner=InteropPlanner(parsed,data=data)
        recorder=ChainRecorder(message,formation,planner=planner)
        report,audit=simulate(data,planner=planner,max_ticks=120,before_tick=recorder.before_tick)
        replacement,=[row for row in audit if row['kind']=='subtask_reassigned']
        command,=[row for row in recorder.commands if row['action']=='start'
                   and row['worker_id']==replacement['new_pid']]
        self.assertEqual(command['subtask_id'],replacement['subtask_id'])
        self.assertEqual(command['unit_id'],'U3')
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(export_chain(temp,recorder,parsed,message,formation,report,audit,'replacement')['passed'])

    def make_run(self, parent, name='source'):
        directory=parent/name
        directory.mkdir()
        seed=seed_bundle()
        write(directory/SEED_FILE, seed)
        write(directory/'request.json', seed['config'])
        server.run_worker(directory)
        return directory

    def test_actual_motion_is_exported_with_return_and_offline_playback(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=self.make_run(Path(temp))
            data=server.read_json(directory/'motion_commands.json')
            summary=data['summary']
            self.assertEqual(summary['discontinuity_count'],0)
            self.assertEqual(summary['status'],'complete')
            self.assertTrue({'work','hold','return','stop'} <= set(summary['phases']), summary)
            self.assertTrue(any(c['twist']['linear']['x']>0 for c in data['commands']))
            self.assertTrue(all(c['topic'].endswith('/cmd_vel') for c in data['commands']))
            moving=[c for c in data['commands'] if c['source_command_id']]
            self.assertTrue(moving)
            self.assertTrue(all(c['subtask_id']=='A-S1' for c in moving))
            schedule=PlanSchedule(data)
            self.assertTrue(all(v==ZERO for v in schedule.velocities_at(schedule.duration).values()))
            result=subprocess.run([sys.executable,str(directory/'ros2_plan_node.py'),'--dry-run'],
                capture_output=True,encoding='utf-8',check=True)
            self.assertEqual(json.loads(result.stdout.splitlines()[0])['source'],data['format'])
            with patch.object(server,'OUTPUTS',directory.parent):
                self.assertIn('motion_commands.json',server.load_run(directory.name)['files'])
            self.assertTrue(verify_chain(directory)['passed'])

    def test_same_platform_switch_is_confirmed_and_shared_by_archive(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server,'OUTPUTS',Path(temp)):
            directory=self.make_run(Path(temp))
            config=playback_config(directory,3)
            task=deepcopy(config['message']['tasks'][0]);task['task_id']='B'
            task['target']={'target_list':[[18,8]]}
            tasks=[*config['message']['tasks'],task]
            payload=dict(source_run=directory.name,
                sim_s=config['sim_s'],snapshot_token=config['snapshot_token'],
                tasks=tasks,units=config['formation']['formation']['units'],exclude_tasks=['A'],delete_tasks=[])
            seed=prepare_branch(directory,payload)
            branch=Path(temp)/'branch';branch.mkdir()
            write(branch/SEED_FILE,seed);write(branch/'request.json',seed['config'])
            server.run_worker(branch)
            report=server.read_json(branch/'report.json')
            metric=report['timing_resolution']
            self.assertEqual((metric['resolved'],metric['total']),(1,1))
            switch,=metric['switches']
            self.assertEqual((switch['from_subtask_id'],switch['to_subtask_id']),('A-S1','B-S1'))
            self.assertEqual(metric,server.read_json(branch/'archive/report.json')['timing_resolution'])
            self.assertTrue(verify_chain(branch)['passed'])

    def test_air_body_frame_twist_preserves_vertical_and_turn_components(self):
        from types import SimpleNamespace
        from interop.motion_replay import MotionReplay
        p=SimpleNamespace(robot_no=31,topic='/container_00/robot_031/cmd_vel',can_climb=True)
        replay=MotionReplay({'rover_31':p},{'rover_31':'P31'},1.0)
        replay.record('rover_31',0,.1,'travel',(0,0,0,0),(1,.02,.3,.04),None)
        sample=replay.samples['rover_31'][0]
        self.assertEqual(sample['phase'],'takeoff')
        self.assertAlmostEqual(sample['twist']['linear']['z'],3)
        self.assertAlmostEqual(sample['twist']['angular']['z'],.4)


if __name__=='__main__':
    unittest.main()
