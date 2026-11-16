"""A live run must release the workbench after normal or requested termination."""
import json
from http.client import HTTPConnection
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import workbench_server as server
from tests.test_dynamic_resume import seed_bundle,write
from chain_trace import verify_chain
from run_demo_v2 import simulate


class LiveLifecycleTests(unittest.TestCase):
    def test_failed_full_progress_attempt_is_replanned_instead_of_left_pending(self):
        from tests.test_subtask_reassignment import _message,_formation,_ugv
        from interop.message import parse_message
        from interop.runtime import InteropPlanner,to_v2_dict
        msg=_message(duration=12);frm=_formation([_ugv(i) for i in range(1,5)])
        parsed=parse_message(msg,frm);data=to_v2_dict(parsed,msg,frm)
        def inject(core,fleet,now):
            if now!=5:return
            old=fleet.jobs.pop('T1')
            events=[]
            for member in old['members'].values():
                pid=member['wire']['command']['worker_id'];fleet.platforms[pid]['active']=False
                event=fleet._event(member['wire'],now,'failed',core.jobs['T1'].work,note='coverage complete, verdict failed')
                event['terminal']=True;events.append(event)
            for event in events:core.receive(event,now)
        report,audit=simulate(data,planner=InteropPlanner(parsed,data=data),max_ticks=80,before_tick=inject)
        self.assertEqual(report['jobs'][0]['attempts'],2)
        self.assertTrue(report['all_succeeded'])
        self.assertFalse(any(row['kind']=='subtask_reassigned' for row in audit))

    def test_manual_termination_keeps_unfinished_work_distinct_from_success(self):
        seed=seed_bundle()
        report,audit=simulate(seed['scenario'],max_ticks=100,
            after_tick=lambda core,fleet,tick:False if tick==2 else None)
        self.assertTrue(report['manual_stopped'])
        self.assertEqual(report['termination_reason'],'user_stopped')
        self.assertEqual(report['simulated_until_s'],2)
        self.assertFalse(report['all_succeeded'])
        self.assertFalse(report['limit_reached'])
        self.assertEqual(sum(row['kind']=='run_stopped' for row in audit),1)

    def test_paused_run_can_end_save_and_accept_another_run(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'OUTPUTS',Path(temp)):
            seed=seed_bundle(live=True);directory=Path(temp)/'first';directory.mkdir()
            write(directory/'request.json',seed['config'])
            inputs=dict(request=seed['config'],message=seed['scenario']['_meta']['interop']['message'],
                        formation=seed['scenario']['_meta']['interop']['formation'])
            write(directory/'desktop_input.json',inputs)
            app=server.Workbench()
            app.process=subprocess.Popen([sys.executable,'-X','utf8',server.__file__,'--worker',str(directory)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            app.current='first';app.live=True
            try:
                for _ in range(200):
                    if (directory/'.live_state.json').is_file():break
                    if app.process.poll() is not None:self.fail('Worker exited without live state')
                    time.sleep(.03)
                paused=app.live_command('first',{'action':'pause'})
                self.assertTrue(paused['paused'])
                reply=app.live_command('first',{'action':'stop'})
                self.assertTrue(reply['stopping'])
                app.process.wait(timeout=30)
                self.assertEqual(app.status()['state'],'complete')
                self.assertFalse(app.status()['stopping'])
                report=server.read_json(directory/'report.json')
                self.assertTrue(report['manual_stopped'])
                self.assertTrue(server.read_json(directory/'archive/report.json')['manual_stopped'])
                self.assertFalse(report['all_succeeded'])
                self.assertTrue(verify_chain(directory)['passed'])
                next_run=app.start(seed['config'],desktop_input=inputs)
                self.assertNotEqual(next_run['id'],'first')
                self.assertEqual(next_run['state'],'running')
                self.assertFalse(next_run['stopping'])
                app.live_command(next_run['id'],{'action':'stop'})
                app.process.wait(timeout=30)
                self.assertEqual(app.status()['state'],'complete')
            finally:
                if app.process.poll() is None:app.process.kill();app.process.wait()

    def test_process_poll_does_not_rebuild_the_catalog(self):
        app=server.Workbench();app.process=type('Worker',(),{'poll':lambda self:None})()
        app.current='active';app.live=True
        http=server.LocalServer(('127.0.0.1',0),server.make_handler(app))
        threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            with patch.object(app,'catalog',side_effect=AssertionError('Heavy catalog should not be polled')):
                connection=HTTPConnection('127.0.0.1',http.server_port)
                connection.request('GET','/api/process');response=connection.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(json.loads(response.read())['process']['state'],'running')
                connection.close()
        finally:http.shutdown();http.server_close()


if __name__=='__main__':unittest.main()
