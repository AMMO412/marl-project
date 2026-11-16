"""回放数据的身份、距离和时间语义回归检查。"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trajectory_v2 import build_replay_data, render, load_scene_background
from workbench_server import execution_exposure


def feedback(t, pos, **extra):
    event = dict(worker_id='rover_21', sim_s=t, pos=pos, status='progress',
                 phase='travel', job_id='A', command_id='cmd-A')
    event.update(extra)
    return dict(kind='feedback_applied', sim_s=t, event=event)


class ReplayDataTests(unittest.TestCase):
    def setUp(self):
        self.scenario = dict(platforms=[dict(robot_no=21, pos=[0, 0]),
                                       dict(robot_no=41, pos=[5, 5])], jobs=[])
        self.report = dict(motion='real', simulated_until_s=4,
                           platforms=[dict(pid='rover_21', robot_no=21,
                                           kind='TANK', pos=[90, 90], battery=1)])

    def test_robot_number_resolves_identity_and_idle_platform_is_kept(self):
        data = build_replay_data(self.scenario, self.report, [])
        a, b = data['workers']
        self.assertEqual((a['pid'], a['kind'], a['kind_name']),
                         ('rover_21', 'TANK', '履带车'))
        self.assertEqual((b['pid'], b['kind'], b['samples']), ('rover_41', 'WING', []))
        self.assertNotEqual(a['color'], b['color'])

    def test_cumulative_distance_includes_initial_leg_and_return(self):
        data = build_replay_data(self.scenario, self.report,
                                 [feedback(1, [3, 4]), feedback(2, [0, 0])])
        w = data['workers'][0]
        self.assertEqual(w['distance'], 10)
        self.assertEqual(w['displacement'], 0)
        self.assertEqual([s['distance'] for s in w['samples']], [5, 10])

    def test_same_time_last_record_wins_and_times_are_sorted(self):
        data = build_replay_data(self.scenario, self.report,
                                 [feedback(2, [3, 4]), feedback(1, [0, 0]),
                                  feedback(2, [0, 4], status='succeeded')])
        samples = data['workers'][0]['samples']
        self.assertEqual([s['t'] for s in samples], [1, 2])
        self.assertEqual(samples[-1]['status'], 'succeeded')
        self.assertEqual(samples[-1]['distance'], 4)

    def test_behavior_samples_preserve_recorded_turn_for_exposure(self):
        self.scenario['platforms'] = [dict(robot_no=21, pos=[0, 5])]
        self.report['platforms'] = [dict(pid='rover_21', robot_no=21,
                                         kind='TANK', pos=[10, 5], battery=1)]
        direct = [feedback(0, [0, 5]), feedback(1.5, [10, 5])]
        detailed = direct + [dict(
            kind='behavior_event', sim_s=0,
            event=dict(kind='behavior_samples', job_id='A', samples=[
                dict(t=0, phase='机动', agents={'rover_21': [0, 5, 0, 0]}),
                dict(t=.5, phase='机动', agents={'rover_21': [0, -1, 0, 0]}),
                dict(t=1, phase='机动', agents={'rover_21': [10, -1, 0, 0]}),
                dict(t=1.5, phase='机动', agents={'rover_21': [10, 5, 0, 0]}),
            ]))]
        threats = [dict(type='threat', applies_to='ground', intensity=1,
                        area=dict(polygon=[[4, 4], [6, 4], [6, 6], [4, 6]]))]
        direct_replay = build_replay_data(self.scenario, self.report, direct)
        detailed_replay = build_replay_data(self.scenario, self.report, detailed)
        self.assertGreater(execution_exposure(direct_replay, threats)[0], 0)
        self.assertEqual(execution_exposure(detailed_replay, threats)[0], 0)
        self.assertEqual([s['t'] for s in
                          detailed_replay['workers'][0]['samples']],
                         [0, .5, 1, 1.5])

    def test_behavior_motion_keeps_same_time_feedback_metadata(self):
        trace = [
            feedback(1, [0, 0], status='succeeded', battery=73,
                     progress=10),
            dict(kind='behavior_event', sim_s=1,
                 event=dict(kind='behavior_samples', job_id='A', samples=[
                     dict(t=1, phase='完成',
                          agents={'rover_21': [1, 2, 0, 0]})])),
        ]
        sample = build_replay_data(
            self.scenario, self.report, trace)['workers'][0]['samples'][0]
        self.assertEqual((sample['x'], sample['y']), (1, 2))
        self.assertEqual(sample['status'], 'succeeded')
        self.assertEqual((sample['battery'], sample['progress']), (73, 10))

    def test_final_report_does_not_supply_initial_position_or_battery(self):
        original = copy.deepcopy((self.scenario, self.report))
        data = build_replay_data(self.scenario, self.report, [])
        self.assertEqual(data['workers'][0]['start'], [0, 0])
        self.assertIsNone(data['workers'][0]['initial_battery'])
        self.assertEqual((self.scenario, self.report), original)

    def test_background_uses_same_transform_as_position_feedback(self):
        self.scenario['_meta'] = dict(source='simple_city.world', scale=0.35,
                                      offset_x=110, offset_y=137)
        bg = load_scene_background(self.scenario)
        first = bg['roads'][0]
        self.assertEqual(first['name'], 'road_y_1')
        self.assertAlmostEqual(first['points'][0][0], (-45 + 110) * 0.35)
        self.assertAlmostEqual(first['points'][0][1], (-103.7 + 137) * 0.35)
        self.assertAlmostEqual(first['width'], 7.4 * 0.35)

    def test_background_is_not_added_to_an_unrelated_scenario(self):
        self.assertEqual(load_scene_background(self.scenario)['roads'], [])

    def test_background_rejects_mismatched_source_coordinates(self):
        self.scenario['_meta'] = dict(source='simple_city.world', scale=0.35,
                                      offset_x=110, offset_y=137)
        self.scenario['platforms'][0]['_src_xy_m'] = [0, 0]
        self.assertEqual(load_scene_background(self.scenario)['roads'], [])

    def test_missing_background_keeps_replay_available(self):
        self.scenario['_meta'] = dict(source='simple_city.world', scale=0.35,
                                      offset_x=110, offset_y=137)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_scene_background(self.scenario,
                             Path(folder) / 'absent.csv')['roads'], [])

    def test_offline_html_escapes_embedded_script_and_preserves_raw_files(self):
        self.scenario['jobs'] = [dict(job_id='</script><script>alert(1)</script>',
                                      type='generic', pos=[0, 0])]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            originals = {'scenario.json': json.dumps(self.scenario).encode(),
                         'report.json': json.dumps(self.report).encode(),
                         'trace.jsonl': b''}
            for name, content in originals.items():
                (root / name).write_bytes(content)
            output = render(root).read_text(encoding='utf-8')
            self.assertNotIn('</script><script>alert(1)</script>', output)
            self.assertIn('\\u003c/script>', output)
            self.assertNotIn('__REPLAY_DATA__', output)
            self.assertIn('id="timeline"', output)
            for name, content in originals.items():
                self.assertEqual((root / name).read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
