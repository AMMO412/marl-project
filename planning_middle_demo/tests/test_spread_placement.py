from copy import deepcopy
import math
import unittest
import workbench_server as backend
from desktop_workflow import validate_draft
from interop.random_tasks import _task_box, _box, _box_gap

class SpreadPlacementTests(unittest.TestCase):
    def test_regions_threats_and_remote_mission_on_all_maps(self):
        for map_id in ('residential','downtown','mixed'):
            with self.subTest(map_id=map_id):
                message,formation=backend.interop_inputs_for('interop_bench_chokepoint')
                before=deepcopy((message,formation))
                draft,_=validate_draft(backend,dict(request=dict(scenario='interop_bench_chokepoint',
                    map_id=map_id,task_seed=12345,reseed_on_run=False),message=message,formation=formation))
                self.assertEqual((message,formation),before)
                boxes=[_task_box(task) for task in draft['message']['tasks']]
                for i,box in enumerate(boxes):
                    for other in boxes[i+1:]:self.assertGreaterEqual(_box_gap(box,other),20)
                threats=[zone for zone in draft['formation']['constraints'] if zone['type']=='threat']
                for zone in threats:
                    box=_box(zone['area']['polygon'])
                    for other in boxes:self.assertGreaterEqual(_box_gap(box,other),25)
                for i,zone in enumerate(threats):
                    for other in threats[i+1:]:self.assertGreaterEqual(_box_gap(_box(zone['area']['polygon']),_box(other['area']['polygon'])),25)
                remote=[p for p in draft['message']['_meta']['task_placement']['placements'] if p['remote']]
                self.assertEqual(len(remote),1)
                self.assertGreaterEqual(remote[0]['distance_from_start_m'],160)
                original={z['constraint_id']:z for z in formation['constraints'] if z['type']=='threat'}
                for zone in threats:
                    old=original[zone['constraint_id']]
                    self.assertEqual(zone.get('applies_to'),old.get('applies_to'))
                    self.assertEqual(zone.get('intensity'),old.get('intensity'))
