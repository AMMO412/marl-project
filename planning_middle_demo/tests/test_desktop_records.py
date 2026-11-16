import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import desktop_workflow as workflow
import workbench_server as backend

class DesktopRecordTests(unittest.TestCase):
    def setUp(self):
        original = backend.validate_config
        patcher = patch.object(backend, 'validate_config',
            lambda payload: original(dict(payload or {}, randomize_tasks=False)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_delete_restore_preserves_exact_bytes_and_excludes_catalog(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend,'OUTPUTS',Path(directory)):
            root=Path(directory);run=root/'workbench_test';run.mkdir()
            content=b'{"original":true}';(run/'manifest.json').write_bytes(content)
            app=backend.Workbench()
            result=workflow.move_record(backend,app,{'id':run.name})
            self.assertFalse(run.exists())
            self.assertEqual((Path(result['directory'])/'manifest.json').read_bytes(),content)
            self.assertNotIn(run.name,[p.parent.name for p in root.glob('*/manifest.json')])
            workflow.move_record(backend,app,{'token':result['token']},restore=True)
            self.assertEqual((run/'manifest.json').read_bytes(),content)

    def test_running_record_and_traversal_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(backend,'OUTPUTS',Path(directory)):
            run=Path(directory)/'workbench_running';run.mkdir()
            app=backend.Workbench();app.current=run.name
            class Running:
                def poll(self):return None
            app.process=Running()
            with self.assertRaises(RuntimeError):workflow.move_record(backend,app,{'id':run.name})
            self.assertTrue(run.exists())
            for operation,payload in [(False,{'id':'../escape'}),(True,{'token':'../escape'})]:
                with self.assertRaises(ValueError):workflow.move_record(backend,app,payload,restore=operation)

    def test_restore_cannot_overwrite_another_record(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(backend,'OUTPUTS',Path(directory)):
            run=Path(directory)/'workbench_test';run.mkdir();app=backend.Workbench()
            result=workflow.move_record(backend,app,{'id':run.name});run.mkdir()
            with self.assertRaises(ValueError):workflow.move_record(backend,app,{'token':result['token']},restore=True)
            self.assertTrue(Path(result['directory']).exists())

    def test_only_exact_old_recon_preset_is_refreshed_and_objective_survives(self):
        # Reconstruct the known shipped preset independently of current templates.
        current=workflow.get_config(backend,'interop_recon')['draft']
        old=json.loads(json.dumps(current))
        _, old['formation'] = backend.interop_inputs_for('interop_recon')
        old['request']['objective']='exposure'
        task=old['message']['tasks'][0]
        def back(p):return [p[0]+95,p[1]+153]
        task['target']['area']=[back(p) for p in task['target']['area']]
        task['params']['search_starts']={k:back(p) for k,p in task['params']['search_starts'].items()}
        for k in ('start','goal'):task['params']['tracking_target'][k]=back(task['params']['tracking_target'][k])
        task['description']='四台空地平台从路口北侧分头扫描。发现目标后上报位置，随后由一台平台跟踪驶离目标，完成区外跟踪及 99% 覆盖后回传。'
        positions={1:(6,64),2:(12,64),41:(15,69),42:(6,70)}
        for u in old['formation']['formation']['units']:
            if u['robot_id'] in positions:
                x,y=positions[u['robot_id']];u['position']={'x':x,'y':y}
        before=json.dumps(old,sort_keys=True)
        refreshed=workflow.refresh_legacy_preset(backend,old)
        self.assertTrue(refreshed['refreshed'])
        self.assertEqual(refreshed['draft']['message'],current['message'])
        self.assertEqual(refreshed['draft']['request']['objective'],'exposure')
        self.assertEqual(json.dumps(old,sort_keys=True),before)
        old['message']['message_id']='USER-CUSTOM-AREA'
        custom=workflow.refresh_legacy_preset(backend,old)
        self.assertFalse(custom['refreshed'])
        self.assertEqual(custom['draft']['message'],old['message'])
