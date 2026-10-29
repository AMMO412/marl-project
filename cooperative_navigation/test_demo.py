import copy
import unittest
from demo import ROOT, read_scene, simulate, NavMap, distance, peer_obstacle
import json


class DemonstrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = read_scene()
        cls.config = json.loads((ROOT / 'scenario.json').read_text(encoding='utf-8'))
        cls.record = simulate(cls.scene, cls.config)

    def test_source_and_ground_classification(self):
        self.assertEqual(self.scene['sha256'], '68a3ff5e0d3762f047ae7683fc635c63226f2f73122add47fb0333ba56eacadf')
        self.assertEqual(len(self.scene['items']), 39)
        self.assertEqual(len(self.scene['unresolved']), 9)
        self.assertFalse(self.scene['geometry_complete'])
        self.assertFalse(next(x for x in self.scene['items'] if x['kind'] == 'ground')['blocking'])
        self.assertTrue(all(not x['blocking'] for x in self.scene['items'] if x['kind'] == 'road'))

    def test_every_motion_segment_and_speed(self):
        nav = NavMap(self.record['navigation_bounds'], [x for x in self.scene['items'] if x['blocking']],
                     radius=self.config['robot_radius_m'] + self.config['margin_m'])
        for a, b in zip(self.record['frames'], self.record['frames'][1:]):
            moving = [p for p in a['poses'] if distance(a['poses'][p], b['poses'][p]) > 1e-8]
            self.assertLessEqual(len(moving), 1)
            for pid in moving:
                self.assertTrue(nav.segment_free(a['poses'][pid], b['poses'][pid]))
                self.assertLessEqual(distance(a['poses'][pid], b['poses'][pid]),
                                     self.config['speed_mps'] * (b['t'] - a['t']) + 1e-8)
                for other, point in a['poses'].items():
                    if other != pid:
                        peer = NavMap(self.record['navigation_bounds'], [peer_obstacle(other, point, self.config['robot_radius_m'])],
                                      radius=self.config['robot_radius_m'] + self.config['margin_m'])
                        self.assertTrue(peer.segment_free(a['poses'][pid], b['poses'][pid]))

    def test_arrival_barriers_from_positions(self):
        run = self.record
        self.assertEqual(run['frames'][0]['poses']['robot_001'], [0.0, -22.5])
        starts = [e for e in run['events'] if e['kind'] == 'stage_started']
        self.assertEqual(len(starts), 3)
        all_arrived = [e for e in run['events'] if e['kind'] == 'all_arrived']
        self.assertEqual(len(all_arrived), 3)
        for e, targets in zip(all_arrived, [self.config['assembly']] + self.config['checkpoints']):
            frame = next(f for f in run['frames'] if f['t'] == e['t'])
            for pid, goal in zip(self.config['robots'], targets):
                self.assertLess(distance(frame['poses'][pid], goal), 1e-6)
        self.assertGreaterEqual(starts[1]['t'], all_arrived[0]['t'])
        self.assertEqual(run['feedback']['status'], 'completed')
        self.assertEqual(len([e for e in run['events'] if e['kind'] == 'arrived']), 9)
        self.assertTrue(any(not p['straight_line_ok'] for p in run['paths']))

    def test_invalid_obstructed_targets_and_overlap(self):
        for targets in [[[110, -92], [94, -86], [94, -90]], [[94, -82]] * 3,
                        [[999, 999], [94, -86], [94, -90]]]:
            cfg = copy.deepcopy(self.config)
            cfg['assembly'] = targets
            with self.assertRaises(ValueError):
                simulate(self.scene, cfg)
        cfg = copy.deepcopy(self.config)
        cfg['speed_mps'] = float('nan')
        with self.assertRaises(ValueError):
            simulate(self.scene, cfg)

    def test_timeout_never_reports_success(self):
        cfg = copy.deepcopy(self.config)
        cfg['timeout_seconds'] = 2
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            simulate(self.scene, cfg)

    def test_edited_checkpoint_is_executed(self):
        cfg = copy.deepcopy(self.config)
        cfg['checkpoints'][-1] = [[90, -100], [90, -104], [90, -110]]
        changed = simulate(self.scene, cfg)
        for pid, goal in zip(cfg['robots'], cfg['checkpoints'][-1]):
            self.assertLess(distance(changed['feedback']['final_positions'][pid], goal), 1e-6)


if __name__ == '__main__':
    unittest.main()
