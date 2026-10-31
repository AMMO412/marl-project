"""Regression tests for malformed plans and non-destructive conversion refusal."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from interop.cli import main
from interop.plan_contract import validate_plan_document


def minimum_plan():
    return dict(schema_version="0.3", plan_id="P",
                assignments=[dict(unit_id="U1", subtask_id="S1", task_type="T-PTL",
                                  start_s=0, end_s=1, target={"point": [0, 0]})],
                commands=[dict(robot_id=1, topic="/container_00/robot_001", duration_s=1,
                               twist=dict(linear=dict(x=0, y=0, z=0),
                                          angular=dict(x=0, y=0, z=0)))])


class PlanContractRegressionTests(unittest.TestCase):
    def test_minimum_contract_does_not_require_extensions(self):
        self.assertEqual(validate_plan_document(minimum_plan()), [])

    def test_regression_old_version_missing_twist_and_boolean_duration(self):
        data = dict(schema_version="0.1", plan_id="bad", assignments=[],
                    commands=[dict(command_id="bad", phase="STOP", duration_s=True)])
        errors = validate_plan_document(data)
        for name in ("schema_version", "robot_id", "topic", "twist", "duration_s"):
            self.assertTrue(any(name in error for error in errors), name)

    def test_wrong_root_and_collection_types_are_rejected(self):
        for value in (None, [], 3, "plan"):
            with self.subTest(value=value):
                self.assertTrue(validate_plan_document(value))
        for key in ("assignments", "commands"):
            data = minimum_plan()
            data[key] = {}
            self.assertTrue(validate_plan_document(data))

    def test_non_object_records_and_identity_lists_do_not_crash(self):
        for key in ("assignments", "commands"):
            for value in ([], None, 4, "record"):
                data = minimum_plan()
                data[key] = [value]
                self.assertTrue(validate_plan_document(data))
        data = minimum_plan()
        data['assignments'][0]['subtask_id'] = []
        self.assertTrue(validate_plan_document(data))

    def test_non_finite_boolean_and_huge_numbers_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, 10**1000):
            for field in ('duration_s', 'at_s'):
                data = minimum_plan()
                data['commands'][0][field] = value
                self.assertTrue(validate_plan_document(data))
            data = minimum_plan()
            data['commands'][0]['twist']['linear']['x'] = value
            self.assertTrue(validate_plan_document(data))

    def test_missing_velocity_component_rejected(self):
        data = minimum_plan()
        del data['commands'][0]['twist']['angular']['z']
        self.assertTrue(validate_plan_document(data))

    def test_output_polygon_shape_and_invalid_target_coordinates(self):
        data = minimum_plan()
        data['assignments'][0]['target'] = {'area': {'polygon': [[0, 0], [1, 0], [0, 1]]}}
        self.assertEqual(validate_plan_document(data), [])
        for target in ({'point': []}, {'point': [True, 0]}, {'point': [float('nan'), 0]}, {'unknown': [0, 0]}):
            data['assignments'][0]['target'] = target
            self.assertTrue(validate_plan_document(data))

    def test_extension_fields_are_not_dropped_or_modified(self):
        data = minimum_plan()
        data['custom_metadata'] = {'source': 'keep'}
        data['commands'][0]['custom_field'] = [1, 2, 3]
        before = copy.deepcopy(data)
        self.assertEqual(validate_plan_document(data), [])
        self.assertEqual(data, before)

    def test_identity_duplicates_and_topic_mismatch_rejected(self):
        data = minimum_plan()
        data['assignments'].append(copy.deepcopy(data['assignments'][0]))
        self.assertTrue(validate_plan_document(data))
        data = minimum_plan()
        data['commands'][0]['command_id'] = 'C'
        data['commands'].append(copy.deepcopy(data['commands'][0]))
        self.assertTrue(validate_plan_document(data))
        data = minimum_plan()
        data['commands'][0]['topic'] = '/container_00/robot_002'
        self.assertTrue(validate_plan_document(data))

    def test_reversed_assignment_and_nonzero_stop_rejected(self):
        data = minimum_plan()
        data['assignments'][0]['start_s'] = 2
        self.assertTrue(validate_plan_document(data))
        data = minimum_plan()
        data['commands'][0].update(phase='STOP')
        data['commands'][0]['twist']['linear']['x'] = 1
        self.assertTrue(validate_plan_document(data))

    def test_cli_reports_malformed_json_structures_as_validation_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'plan.json'
            for value in ([], dict(schema_version='0.3', plan_id='P', assignments=[None], commands=[])):
                path.write_text(json.dumps(value), encoding='utf-8')
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['validate', '--plan', str(path)]), 1)


class ConversionRefusalTests(unittest.TestCase):
    def test_refusal_keeps_existing_destination_and_input_unchanged(self):
        folder = BASE/'interop/scenarios'
        message = folder/'patrol_checkpoint.message.json'
        formation = folder/'patrol_checkpoint.formation.json'
        before = (message.read_bytes(), formation.read_bytes())
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)/'existing.json'
            output.write_bytes(b'preserve this existing output')
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(['to-v2', '--message', str(message), '--formation', str(formation), '--out', str(output)])
            self.assertEqual(code, 2)
            self.assertEqual(output.read_bytes(), b'preserve this existing output')
            for name in ('TASK_GEOMETRY', 'TASK_BEHAVIOR', 'PLATFORM_PROFILE', 'WORLD_CONSTRAINTS', 'TIME_BASIS'):
                self.assertIn(name, stderr.getvalue())
        self.assertEqual(before, (message.read_bytes(), formation.read_bytes()))


class ComparisonDisclosureTests(unittest.TestCase):
    def test_baseline_normalization_is_present_in_json_and_report(self):
        from interop.message import load_scenario
        from interop.compare import compare_scenario, build_markdown
        folder = BASE/'interop/scenarios'
        scenario = load_scenario(str(folder/'patrol_checkpoint.message.json'),
                                 str(folder/'patrol_checkpoint.formation.json'))
        comparison = compare_scenario(scenario, objectives=('timeliness',), backends=('base_v2',))
        result = comparison['results'][0]
        self.assertNotIn('error', result)
        self.assertEqual(result['comparison_scope'], 'normalized_planning_experiment')
        self.assertFalse(result['normalization']['runtime_equivalent'])
        self.assertEqual(result['normalization']['battery'], 1.0e6)
        report = build_markdown([comparison])
        self.assertIn('1000000', report)
        self.assertIn('不等同于to-v2实际运行', report)


if __name__ == '__main__':
    unittest.main()
