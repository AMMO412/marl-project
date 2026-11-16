"""Dynamic edits preserve runtime state, identity and trace provenance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import workbench_server as server
from chain_trace import verify_chain
from interop.message import parse_message
from interop.runtime import to_v2_dict
from motion import MOTION_MODEL
from workbench_replay_editor import SEED_FILE, playback_config, prepare_branch
from tests.test_interop import message, formation, point_task


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')


def seed_bundle(live=False):
    task=point_task(task_id='A',task_type='T-RCN',target={'target_list':[[30,0]]},
        min_units=1,max_units=1,required_capabilities={},params={'duration_s':8},
        window={'start_s':0,'end_s':180})
    msg=message(tasks=[task]);frm=formation(constraints=[])
    frm['formation']['units']=frm['formation']['units'][:1]
    frm['formation']['units'][0].update(speed_mps=4,position={'x':0,'y':0})
    scene=parse_message(msg,frm)
    config=server.validate_config(dict(scenario='interop_recon',planner='interop',
        max_ticks=150,avoid=False,behavior=False,randomize_tasks=False,task_seed=1,
        reseed_on_run=False,live=live))
    return dict(scenario=to_v2_dict(scene,msg,frm),config=config,history=[],motion_model=MOTION_MODEL)


class DynamicResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.patch=patch.object(server,'OUTPUTS',self.root)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.original=self.root/'original';self.original.mkdir()
        seed=seed_bundle()
        write(self.original/SEED_FILE,seed);write(self.original/'request.json',seed['config'])
        server.run_worker(self.original)

    def payload(self,tick=3):
        c=playback_config(self.original,tick)
        return dict(source_run='original',sim_s=c['sim_s'],snapshot_token=c['snapshot_token'],
            tasks=deepcopy(c['message']['tasks']),units=deepcopy(c['formation']['formation']['units']),
            targets=c['targets'],exclude_tasks=[],delete_tasks=[])

    def prefix(self,tick=3):
        trace=[json.loads(line) for line in (self.original/'trace.jsonl').read_text('utf8').splitlines()]
        return [row for row in trace if row['sim_s']<=tick and row['kind']=='feedback_applied']

    def wait(self,app):
        app.process.wait(timeout=60)
        for _ in range(50):
            result=app.status()
            if not result.get('replacing'):return result
            time.sleep(.02)
        self.fail('Continuation not published')

    def test_capture_preserves_motion_and_does_not_write_source(self):
        before={p.name:p.read_bytes() for p in self.original.iterdir() if p.is_file()}
        c=playback_config(self.original,3.9)
        self.assertEqual(c['sim_s'],3)
        self.assertGreater(c['formation']['formation']['units'][0]['position']['x'],0)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.original.iterdir() if p.is_file()})

    def test_same_id_successive_continuations_keep_prefix_and_backups(self):
        prefix=self.prefix();app=server.Workbench();edit=self.payload()
        edit['tasks'][0]['target']={'target_list':[[20,10]]}
        result=app.start({'replay_edit':edit})
        self.assertEqual(result['id'],'original');self.assertEqual(self.wait(app)['state'],'complete')
        self.assertEqual(self.prefix(),prefix);self.assertTrue(verify_chain(self.original)['passed'])
        manifest=server.read_json(self.original/'manifest.json')
        self.assertTrue(Path(manifest['continuation']['previous_revision']).is_dir())
        scene=server.read_json(self.original/'scenario.json')
        self.assertEqual(scene['platforms'][0]['pos'],[0.0,0.0])
        edit=self.payload(5);edit['tasks'][0]['target']={'target_list':[[12,8]]}
        app.start({'replay_edit':edit});self.assertEqual(self.wait(app)['state'],'complete')
        self.assertEqual([e['at_s'] for e in server.read_json(self.original/SEED_FILE)['history']],[3,5])
        self.assertEqual(self.prefix(),prefix)

    def test_stale_token_or_invalid_edit_changes_no_files(self):
        edit=self.payload();before=(self.original/'manifest.json').read_bytes()
        edit['snapshot_token']='stale'
        with self.assertRaises(ValueError):prepare_branch(self.original,edit)
        self.assertEqual((self.original/'manifest.json').read_bytes(),before)
        edit=self.payload();edit['tasks'][0]['window']['end_s']=1
        with self.assertRaises(ValueError):prepare_branch(self.original,edit)
        self.assertEqual((self.original/'manifest.json').read_bytes(),before)

    def test_excluding_and_deleting_remaining_tasks_settle(self):
        edit=self.payload();edit['exclude_tasks']=['A'];app=server.Workbench()
        app.start({'replay_edit':edit});self.assertEqual(self.wait(app)['state'],'complete')
        report=server.read_json(self.original/'report.json');self.assertTrue(report['settled'])
        self.assertEqual(report['jobs'][0]['status'],'excluded')
        edit=self.payload(3);edit['tasks']=[];edit['targets']=[];edit['exclude_tasks']=[];edit['delete_tasks']=['A']
        app.start({'replay_edit':edit});self.assertEqual(self.wait(app)['state'],'complete')
        self.assertEqual(server.read_json(self.original/'report.json')['jobs'],[])

    def test_live_pause_apply_resume_and_saved_history(self):
        app=server.Workbench();seed=seed_bundle(live=True)
        # Start with an authoritative saved seed, without re-randomizing it.
        directory=self.root/'live';directory.mkdir();write(directory/SEED_FILE,seed)
        # An initial seed is replayed fast, so use a normal worker with explicit inputs.
        directory.joinpath(SEED_FILE).unlink()
        write(directory/'request.json',seed['config'])
        write(directory/'desktop_input.json',dict(request=seed['config'],
            message=seed['scenario']['_meta']['interop']['message'],
            formation=seed['scenario']['_meta']['interop']['formation']))
        import subprocess,sys
        app.process=subprocess.Popen([sys.executable,'-X','utf8',server.__file__,'--worker',str(directory)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        app.current='live';app.live=True
        self.addCleanup(lambda:app.process.kill() if app.process.poll() is None else None)
        for _ in range(200):
            if (directory/'.live_state.json').is_file():break
            if app.process.poll() is not None:self.fail('Live worker exited before snapshot')
            time.sleep(.05)
        snap=app.live_command('live',{'action':'pause'})
        self.assertTrue(snap['paused']);paused=snap['config']['sim_s'];time.sleep(.35)
        self.assertEqual(app.live_state('live')['state']['config']['sim_s'],paused)
        with self.assertRaises(ValueError):app.live_command('live',{'action':'apply','revision':-1,'sim_s':paused,'tasks':[],'units':[]})
        c=snap['config'];tasks=deepcopy(c['message']['tasks']);tasks[0]['params']['duration_s']=4
        result=app.live_command('live',dict(action='apply',revision=snap['revision'],sim_s=paused,
            tasks=tasks,units=c['formation']['formation']['units'],targets=c['targets'],delete_tasks=[],exclude_tasks=[]))
        self.assertFalse(result['paused']);self.assertEqual(result['revision'],1)
        self.assertEqual(self.wait(app)['state'],'complete')
        self.assertEqual(len(server.read_json(directory/SEED_FILE)['history']),1)
        self.assertTrue(verify_chain(directory)['passed'])

    def test_completed_task_is_locked(self):
        report=server.read_json(self.original/'report.json')
        tick=min(report['simulated_until_s']-1,report['makespan']+1)
        edit=self.payload(tick);edit['tasks'][0]['params']['duration_s']=90
        seed=prepare_branch(self.original,edit)
        self.assertTrue(seed['history'])
        directory=self.root/'locked';directory.mkdir()
        write(directory/SEED_FILE,seed);write(directory/'request.json',seed['config'])
        server.run_worker(directory)
        final=server.read_json(directory/'final_config.json')
        self.assertEqual(final['message']['tasks'][0]['params']['duration_s'],8)
        self.assertEqual(server.read_json(directory/'report.json')['jobs'][0]['attempts'],1)

    def test_failed_worker_keeps_original_bytes(self):
        before={p.name:p.read_bytes() for p in self.original.iterdir() if p.is_file()}
        def failed(*args,**kwargs):
            kwargs['stdout'].write('forced failure\n');kwargs['stdout'].flush()
            return SimpleNamespace(poll=lambda:1,wait=lambda **kw:1)
        app=server.Workbench()
        with patch('workbench_sessions.subprocess.Popen',side_effect=failed):
            app.start({'replay_edit':self.payload()})
            result=self.wait(app)
        self.assertEqual(result['state'],'error')
        self.assertIn('forced failure',result['error'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.original.iterdir() if p.is_file()})

    def test_platform_addition_and_disable_reassigns_unfinished_task(self):
        edit=self.payload();unit=deepcopy(edit['units'][0])
        unit.update(unit_id='NEW',robot_id=9,position={'x':0,'y':5},status='READY')
        edit['units'][0]['status']='OFFLINE';edit['units'].append(unit)
        app=server.Workbench();app.start({'replay_edit':edit})
        result=self.wait(app);self.assertEqual(result['state'],'complete',result)
        self.assertTrue(verify_chain(self.original)['passed'])
        raw=server.read_json(self.original/'chain_raw.json')
        self.assertTrue(any(c['worker_id']=='rover_09' and c['action']=='start' for c in raw['commands']))
        self.assertTrue(any(event['added']==[9] for event in raw['config_events']))

if __name__=='__main__':unittest.main()
