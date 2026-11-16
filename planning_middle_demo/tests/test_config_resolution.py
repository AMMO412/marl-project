import unittest
from interop.config_resolution import config_resolution

class ConfigResolutionTests(unittest.TestCase):
    def test_no_edits_and_same_subtask_reissues_have_no_measured_rate(self):
        result=config_resolution([],[],[],100,8)
        self.assertEqual(result['total'],0)
        self.assertIsNone(result['rate'])
        commands=[dict(command_id=cid,action='start',config_version=version,
                       worker_id='p',subtask_id='A-S1',dispatched_sim_s=at)
                  for cid,version,at in [('old','v1',0),('new','v2',10)]]
        feedback=[dict(command_id=cid,sim_s=at,accepted=True,status='accepted')
                  for cid,at in [('old',0),('new',11)]]
        edits=[dict(kind='config_updated',sim_s=10,revision=1,interrupted_commands=['old'])]
        result=config_resolution(edits,commands,feedback,200,8)
        self.assertEqual(result['total'],0)
        self.assertIsNone(result['meets_threshold'])

    def test_budget_and_feedback_acceptance(self):
        def start(cid, version, pid, subtask, time):
            return dict(command_id=cid, action='start', config_version=version,
                        worker_id=pid, subtask_id=subtask, dispatched_sim_s=time)

        commands = [
            start('a', 'v1', 'p1', 'A-S1', 0),
            start('b', 'v1', 'p2', 'A-S2', 0),
            start('c', 'v2', 'p1', 'B-S1', 10),
            start('d', 'v2', 'p2', 'B-S2', 10),
            start('e', 'v2', 'p3', 'B-S3', 10),
        ]
        audit = [dict(kind='config_updated', sim_s=10, revision=1,
                      interrupted_commands=['a', 'b'])]
        feedback = [dict(command_id=cid, sim_s=at, accepted=accepted, status='accepted')
                    for cid, at, accepted in [('a', 0, True), ('b', 0, True),
                                              ('c', 130, False), ('c', 170, True),
                                              ('d', 171, True), ('e', 10, True)]]
        short = config_resolution(audit, commands, feedback[:3], 100, 8)
        self.assertEqual((short['total'], short['insufficient']), (0, 2))
        final = config_resolution(audit, commands, feedback, 180, 8)
        self.assertEqual((final['resolved'], final['total']), (1, 2))
        self.assertEqual(final['by_round'], {'1': 0, '5': 0, '10': 0, '20': 0.5})
        self.assertEqual([row['status'] for row in final['switches']], ['resolved', 'expired'])
