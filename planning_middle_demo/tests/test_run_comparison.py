import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workbench_server as backend


class SavedRunComparisonTests(unittest.TestCase):
    def write_run(self, root, name, objective='makespan', metrics=None, **report):
        directory=root/name;directory.mkdir()
        data=dict(done=1,jobs=[{}],motion='real',objective=objective,
                  makespan=99,used_energy=88,plan_objective_metrics=metrics or {})
        data.update(report)
        (directory/'report.json').write_text(json.dumps(data),encoding='utf-8')
        (directory/'trace.jsonl').write_text('',encoding='utf-8')
        (directory/'manifest.json').write_text(json.dumps(dict(
            workbench_config=dict(scenario='interop_containment'))),encoding='utf-8')

    def test_zero_plan_metrics_survive_and_execution_stays_independent(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'OUTPUTS',Path(temporary)):
            self.write_run(Path(temporary),'zero',metrics=dict(makespan_s=0,total_energy=0,
                total_exposure=0,detection_probability=0),execution_exposure=7,
                execution_detection_probability=.5,retries=0,timeouts=0)
            run=backend.Workbench().catalog()['runs'][0]
            self.assertEqual((run['makespan'],run['plan_energy'],run['exposure'],run['detection_probability']),(0,0,0,0))
            self.assertEqual((run['execution_exposure'],run['execution_detection_probability']),(7,.5))
            self.assertEqual((run['retries'],run['timeouts']),(0,0))

    def test_repeated_objectives_are_preserved_and_missing_metrics_remain_missing(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(backend,'OUTPUTS',Path(temporary)):
            for name in ['repeat_one','repeat_two']:
                self.write_run(Path(temporary),name)
            rows=backend.Workbench().catalog()['runs']
            self.assertEqual(len(rows),2)
            self.assertEqual({r['id'] for r in rows},{'repeat_one','repeat_two'})
            for row in rows:
                self.assertIsNone(row['exposure'])
                self.assertIsNone(row['execution_detection_probability'])
                self.assertIsNone(row['plan_energy'])
                self.assertIsNone(row['makespan'])


if __name__=='__main__':unittest.main()
