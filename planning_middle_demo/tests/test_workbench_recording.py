"""Verify saved recordings are adapted without rewriting execution evidence."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench_recording import load_recording


class RecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'outputs/behavior_20261028_verify/behavior_trace.json').read_bytes()
        cls.saved = json.loads(cls.raw)
        cls.adapted = load_recording(ROOT)

    def test_every_recorded_pose_is_preserved(self):
        normalized = {(w['pid'], s['job'], s['t']): [s['x'], s['y'], s['yaw']]
                      for w in self.adapted['replay']['workers'] for s in w['samples']}
        expected = {(pid, job['job_id'], sample['t']): position
                    for job in self.saved['jobs'] for sample in job['samples']
                    for pid, position in sample['agents'].items()}
        self.assertEqual(normalized, expected)

    def test_routes_keep_geometry_and_convert_only_the_local_clock(self):
        routes = [e for e in self.adapted['trace'] if e.get('source') == 'saved_route']
        expected = [(j['job_id'], j['t0'] + r['t'], r)
                    for j in self.saved['jobs'] for r in j['routes']]
        self.assertEqual(len(routes), len(expected))
        for jid, when, route in expected:
            matches = [e for e in routes if e['event']['job_id'] == jid
                       and e['event']['route']['pid'] == route['pid']
                       and e['event']['route']['t'] == route['t']]
            self.assertTrue(any(e['sim_s'] == when and
                                e['event']['route']['path'] == route['path']
                                for e in matches))

    def test_recording_never_fabricates_planner_or_feedback_audit(self):
        self.assertFalse(any(e['kind'] in ['plan_emitted', 'feedback_applied',
                                          'job_dispatched', 'job_succeeded']
                             for e in self.adapted['trace']))
        original = [e for j in self.saved['jobs'] for e in j['events']]
        events = [e['event'] for e in self.adapted['trace']
                  if e.get('source') == 'saved_behavior_event']
        key = lambda e: json.dumps(e, sort_keys=True)
        self.assertEqual(sorted(map(key, original)), sorted(map(key, events)))
        self.assertIsNone(self.adapted['report']['plans'])
        self.assertEqual(self.adapted['report']['recording_source']['sha256'],
                         hashlib.sha256(self.raw).hexdigest())
        self.assertTrue(self.adapted['manifest']['read_only'])
