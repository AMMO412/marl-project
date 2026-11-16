from copy import deepcopy
import unittest
import workbench_server as backend
from workbench_browser import configuration, edited_draft

class ThreatEditorTests(unittest.TestCase):
    def test_manual_threats_preserve_other_constraints_and_are_not_randomized(self):
        config=configuration(backend,'interop_patrol',map_id='residential')
        edit=dict(tasks=config['message']['tasks'],units=config['formation']['formation']['units'],targets=config['targets'],
            threats=[dict(constraint_id='USER-THREAT',type='threat',applies_to='all',intensity=.85,
                area={'polygon':[[-30,30],[30,30],[30,-30],[-30,-30]]})])
        before=deepcopy(edit);draft=edited_draft(backend,edit,config['request'])
        self.assertEqual(edit,before);self.assertFalse(draft['request']['randomize_tasks'])
        self.assertEqual([z for z in draft['formation']['constraints'] if z['type']=='threat'],edit['threats'])
        self.assertEqual([z for z in draft['formation']['constraints'] if z['type']!='threat'],[z for z in config['formation']['constraints'] if z['type']!='threat'])
        edit['threats']=[];draft=edited_draft(backend,edit,config['request'])
        self.assertFalse(any(z['type']=='threat' for z in draft['formation']['constraints']))
    def test_cannot_replace_obstacles_through_threat_editor(self):
        config=configuration(backend,'interop_patrol',map_id='residential')
        edit=dict(tasks=config['message']['tasks'],units=config['formation']['formation']['units'],threats=[dict(type='no_go')])
        with self.assertRaises(ValueError):edited_draft(backend,edit,config['request'])
