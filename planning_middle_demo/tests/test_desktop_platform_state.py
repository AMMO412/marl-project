"""Replay cursor semantics for sparse native platform telemetry."""
import unittest
from unittest.mock import patch

import workbench_server as backend


class PlatformStateTests(unittest.TestCase):
    def document(self):
        return dict(replay=dict(end=10, events=[
            dict(kind='job_dispatched', sim_s=1, job_id='T1', pids=['p']),
            dict(kind='job_succeeded', sim_s=6, job_id='T1'),
        ], workers=[dict(pid='p', start=[1, 2], start_z=0,
                         initial_battery=100, samples=[
            dict(t=1, x=2, y=3, battery=95, job='T1', status='progress', phase='travel'),
            dict(t=1.5, x=3, y=4, battery=None, job='T1', status='progress', phase='在位'),
            dict(t=5, x=4, y=5, battery=0, job='T1', status='progress', phase='在位'),
            dict(t=7, x=3, y=4, battery=None, job=None, status='progress', phase='return'),
            dict(t=10, x=1, y=2, battery=0, job=None, status='succeeded', phase='returned'),
        ])]), report=dict(platforms=[dict(pid='p', kind='UGV', pos=[99, 99], battery=0)]))

    def at(self, time, document=None):
        with patch.object(backend, 'load_run', return_value=document or self.document()):
            return backend.desktop_run('fixture', time)['platforms'][0]

    def test_substep_holds_past_battery_and_preserves_phase(self):
        row = self.at(1.5)
        self.assertEqual((row['battery'], row['phase'], row['position']), (95, '在位', [3, 4]))

    def test_rewind_restores_past_state_and_zero_is_real(self):
        self.assertEqual(self.at(7)['battery'], 0)
        self.assertEqual(self.at(1.5)['battery'], 95)
        self.assertEqual(self.at(0)['battery'], 100)

    def test_before_first_sample_does_not_show_future_job_or_final_pose(self):
        row = self.at(0)
        self.assertEqual((row['job'], row['status'], row['position']), (None, 'idle', [1, 2]))

    def test_completed_task_clears_current_job_and_return_stays_distinct(self):
        row = self.at(6)
        self.assertEqual((row['job'], row['status']), (None, 'succeeded'))
        row = self.at(7)
        self.assertEqual((row['job'], row['phase']), (None, 'return'))
        self.assertEqual(self.at(10)['phase'], 'returned')

    def test_missing_battery_stays_unknown_instead_of_using_final_value(self):
        doc = self.document()
        doc['replay']['workers'][0]['initial_battery'] = None
        self.assertIsNone(self.at(0, doc)['battery'])

    def test_unsorted_samples_and_late_loss_do_not_leak_future(self):
        doc = self.document()
        doc['replay']['workers'][0]['samples'].reverse()
        doc['replay']['events'].append(dict(kind='member_lost', sim_s=8, pids=['p']))
        self.assertEqual(self.at(1.5, doc)['battery'], 95)
        self.assertTrue(self.at(7, doc)['alive'])
        self.assertEqual((self.at(9, doc)['alive'], self.at(9, doc)['status']), (False, 'lost'))


if __name__ == '__main__':
    unittest.main()
