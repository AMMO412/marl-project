"""Return flight and replay contracts introduced with the imported runtime."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mock_fleet import MockFleet
from trajectory_v2 import build_replay_data
from workbench_server import validate_config


def returning_fleet(air=False):
    fleet = MockFleet(motion='real', home={'rover_41': (0.0, 0.0)})
    fleet.platforms['rover_41'] = dict(
        pos=(6.0, 0.0), z=6.0 if air else 0.0, yaw=0.0,
        battery=100.0, active=False, dead=False,
        return_profile=dict(can_climb=air, speed=3.0, move_cost=0.1))
    return fleet


class ReturnRuntimeTests(unittest.TestCase):
    def test_member_reserved_for_pending_work_does_not_return(self):
        fleet = returning_fleet()
        fleet.step_returns(1, {'rover_41'})
        self.assertFalse(fleet.return_state)
        self.assertEqual(fleet.platforms['rover_41']['pos'], (6.0, 0.0))
        fleet.step_returns(2, set())
        self.assertEqual(fleet.return_state['rover_41']['status'], 'returning')

    def test_air_return_is_complete_only_after_landing(self):
        fleet = returning_fleet(air=True)
        for now in range(1, 4):
            fleet.step_returns(now, set())
        state = fleet.platforms['rover_41']
        self.assertEqual(state['pos'], (0.0, 0.0))
        self.assertGreater(state['z'], 0)
        self.assertTrue(fleet.returns_pending())
        for now in range(4, 8):
            fleet.step_returns(now, set())
        self.assertEqual(state['z'], 0)
        self.assertFalse(fleet.returns_pending())
        completed = [e for e in fleet.drain_behavior_events() if e['kind'] == 'return_completed']
        self.assertEqual(len(completed), 1)
        self.assertTrue(completed[0]['landed'])

    def test_active_or_lost_member_does_not_start_return(self):
        for field in ('active', 'dead'):
            with self.subTest(field=field):
                fleet = returning_fleet()
                fleet.platforms['rover_41'][field] = True
                fleet.step_returns(1, set())
                self.assertFalse(fleet.return_state)

    def test_return_samples_extend_replay_past_task_completion(self):
        scenario = dict(platforms=[dict(robot_no=41, pos=[0, 0])], jobs=[])
        report = dict(motion='real', simulated_until_s=5,
                      platforms=[dict(pid='rover_41', kind='WING', pos=[0, 0], battery=1)])
        trace = [dict(kind='behavior_event', sim_s=t,
                      event=dict(kind='return_sample', pid='rover_41', pos=pos, z=z,
                                 phase=phase, battery=1, yaw=0))
                 for t, pos, z, phase in [(2, [3, 4], 6, 'return'),
                                           (5, [0, 0], 0, 'returned')]]
        replay = build_replay_data(scenario, report, trace)
        worker = replay['workers'][0]
        self.assertEqual(worker['distance'], 10)
        self.assertEqual(worker['samples'][-1]['phase'], 'returned')
        self.assertEqual(replay['end'], 5)

    def test_new_workbench_scenarios_enable_execution(self):
        for name, limit in [('interop_patrol', 320), ('interop_recon', 220),
                            ('interop_relay', 380)]:
            with self.subTest(scenario=name):
                config = validate_config(dict(scenario=name, planner='interop'))
                self.assertEqual(config['motion'], 'real')
                self.assertTrue(config['avoid'] and config['behavior'])
                self.assertEqual(config['max_ticks'], limit)


if __name__ == '__main__':
    unittest.main()
