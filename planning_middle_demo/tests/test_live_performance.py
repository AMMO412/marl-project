from copy import deepcopy
import unittest
from workbench_sessions import live_trace_window

class LiveWindowTests(unittest.TestCase):
    def test_history_is_retained_in_source_but_live_pose_window_is_bounded(self):
        rows=[dict(kind='feedback_applied',sim_s=i,event=dict(worker_id='P',pos=[i,0])) for i in range(100)]
        rows += [dict(kind='behavior_event',sim_s=i,event=dict(kind='behavior_samples',job_id='A',samples=[i])) for i in range(100)]
        rows.append(dict(kind='config_updated',sim_s=2,message={'tasks':[]}))
        before=deepcopy(rows);window=live_trace_window(rows,99,20)
        self.assertEqual(rows,before)
        self.assertEqual(len([r for r in window if r['kind']=='feedback_applied']),22)
        self.assertEqual(len([r for r in window if r['kind']=='behavior_event']),22)
        self.assertIn(rows[-1],window)
        self.assertEqual(min(r['sim_s'] for r in window if r['kind']=='feedback_applied'),78)
