"""Refresh only the HTML viewer, keeping the recorded motion file unchanged."""
import hashlib
import json
from pathlib import Path

root = Path('D:/Desktop/MARL项目/planning_middle_demo')
out = root / 'outputs/behavior_20261028_verify'
trace = out / 'behavior_trace.json'
before = hashlib.sha256(trace.read_bytes()).hexdigest()
data = json.loads(trace.read_text(encoding='utf-8-sig'))
template = (root / 'behavior_demo.html').read_text(encoding='utf-8-sig')
assert template.count('__DATA__') == 1
payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
(out / 'behavior_demo.html').write_text(template.replace('__DATA__', payload), encoding='utf-8')
assert hashlib.sha256(trace.read_bytes()).hexdigest() == before
print(json.dumps({'refreshed': str(out / 'behavior_demo.html'), 'trace_sha256': before}, ensure_ascii=False))
