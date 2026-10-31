"""Read-only packaging checks and input-parser tests; no planning/execution runs."""
import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
M2 = Path('D:/Desktop/M2')
OUT = ROOT / 'outputs' / 'M2融合评估_20261030'
OUT.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(M2))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def count_tests(folder):
    result = {}
    for path in sorted(folder.glob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        result[path.name] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and n.name.startswith('test_') for n in ast.walk(tree))
    return result

spec = importlib.util.spec_from_file_location('parser_tests', M2/'tests/test_message_contract.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
names = ['test_envelope_required_fields', 'test_task_required_fields',
         'test_empty_task_list_rejected', 'test_unknown_task_type_rejected',
         'test_source_aliases', 'test_schema_versions', 'test_issued_at',
         'test_target_shape', 'test_unknown_prerequisite_rejected',
         'test_dependency_cycle_rejected', 'test_duplicate_task_id_rejected']
stream = io.StringIO()
suite = unittest.TestSuite(module.MessageContractTests(n) for n in names)
run = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
(OUT/'parser_checks.txt').write_text(stream.getvalue(), encoding='utf-8')

from formation_planner.feedback import FeedbackLog
command = SimpleNamespace(command_id='SYNTHETIC-1', robot_id=1,
                          subtask_id='GENERIC-CHECK', attempt=1)
plan = SimpleNamespace(commands=[command])
def event(**kw):
    data = dict(event_id='E1', command_id=command.command_id, robot_id=1,
                subtask_id=command.subtask_id, attempt=1, sim_s=0,
                status='accepted', progress=0.0)
    data.update(kw)
    return data
feedback_checks = {
    'nan_progress_accepted': FeedbackLog(plan).receive(event(progress=float('nan'))),
    'missing_attempt_accepted': FeedbackLog(plan).receive({k:v for k,v in event().items() if k!='attempt'}),
}

tracked_sources = [M2/'README.md', M2/'formation_planner/message.py',
                   M2/'formation_planner/feedback.py', M2/'formation_planner/coordinator.py',
                   ROOT/'planning_middle_demo/contracts_v2.py',
                   ROOT/'planning_middle_demo/coordinator_v2.py',
                   ROOT/'planning_middle_demo/scenarios/asl_city.json']
result = dict(
    scope='Static source/package audit, parser-only tests, synthetic feedback checks. No planner, tactical task or robot execution.',
    python=sys.version,
    parser_tests=dict(run=run.testsRun, failures=len(run.failures), errors=len(run.errors)),
    synthetic_feedback=feedback_checks,
    missing_example_8uav=not (M2/'examples/scenario_8uav.json').exists(),
    missing_sdf_examples=[n for n in ['sdf_scene_message.json','sdf_scene_fleet.json'] if not (M2/'examples'/n).exists()],
    test_definitions=dict(m2=count_tests(M2/'tests'), ours=count_tests(ROOT/'planning_middle_demo/tests')),
    sdf_hashes={str(p):digest(p) for p in [M2/'assets/container_00_combined_scene.sdf', ROOT/'资料/接口说明/container_00_combined_scene.sdf']},
    source_hashes={str(p):digest(p) for p in tracked_sources},
)
(OUT/'inspection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['source_hashes','test_definitions']}, ensure_ascii=False, indent=2))
print('Static test definitions:', {k:sum(v.values()) for k,v in result['test_definitions'].items()})
