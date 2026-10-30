"""Read-only document/source provenance audit. Does not import project code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
M2 = Path('D:/Desktop/M2')
OUT = ROOT / 'outputs/M2融合评估_20261030'
DOC = ROOT / '资料/需求与任务/无人集群编队五类任务定义_1028.docx'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_inventory():
    paths = [DOC]
    paths += [p for p in (ROOT/'planning_middle_demo').rglob('*')
              if p.is_file() and p.suffix in {'.py', '.js', '.json', '.html', '.css', '.md'}
              and not any(s in {'outputs', '__pycache__'} for s in p.relative_to(ROOT/'planning_middle_demo').parts)]
    for name in ['formation_planner', 'examples', 'assets']:
        paths += [p for p in (M2/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    return {str(p): sha(p) for p in sorted(paths)}

before = source_inventory()
with ZipFile(DOC) as archive:
    body = ET.fromstring(archive.read('word/document.xml')).find('w:body', NS)
items = []
for index, element in enumerate(body):
    if element.tag == '{%s}tbl' % NS['w']:
        rows = []
        for row in element.findall('w:tr', NS):
            cells = []
            for cell in row.findall('w:tc', NS):
                cells.append('\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', NS))
                                       for p in cell.findall('w:p', NS)))
            rows.append(cells)
        text = '\n'.join(' | '.join(row) for row in rows)
    else:
        text = ''.join(t.text or '' for t in element.findall('.//w:t', NS))
        rows = None
    items.append(dict(body_index=index, kind='table' if rows is not None else 'paragraph', text=text))

start = next(i for i, item in enumerate(items) if item['text'].startswith('4.1 '))
end = next(i for i, item in enumerate(items[start+1:], start+1) if item['text'].startswith('4.3 '))
excerpt = items[start:end]
input_begin = next(i for i, item in enumerate(excerpt) if item['text'].strip() == '{')
input_end = next(i for i, item in enumerate(excerpt[input_begin:], input_begin) if item['text'] == '}')
input_example = json.loads('\n'.join(item['text'] for item in excerpt[input_begin:input_end+1]))

def literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)

evidence = {
    'scope': 'Read-only 4.1/4.2 document and source audit; no adapter, planner, controller or simulator executed.',
    'source_document': str(DOC), 'source_document_sha256': sha(DOC),
    'source_locations': 'Zero-based direct child index of word/document.xml w:body; not page numbers.',
    'sections': excerpt,
    'version_facts': {
        'source_table_current': '0.3',
        'source_example_version': input_example['schema_version'],
        'm2_accepted_versions': literal_assignment(M2/'formation_planner/message.py', 'SUPPORTED_SCHEMA_VERSIONS'),
        'user_confirmed_external_version': '0.3',
        'user_confirmed_older_versions': 'reject',
        'decision_implemented_in_business_code': False,
    },
    'source_hashes_before': before,
}
assert evidence['version_facts']['source_example_version'] == '0.1'
assert any('0.3' in x['text'] for x in excerpt if x['kind']=='table')
after = source_inventory()
assert before == after, 'Source content changed during read-only audit'
evidence['source_content_unchanged'] = True
evidence['source_file_count'] = len(before)
OUT.mkdir(parents=True, exist_ok=True)
(OUT/'1028_4.1_4.2原文摘录.txt').write_text(
    '只读摘录；保留原段落文字，表格以 | 分隔单元格。BODY为OOXML正文直接子元素的零基索引，不是页码。\n\n'
    + '\n\n'.join('[BODY %d %s]\n%s' % (x['body_index'], x['kind'], x['text']) for x in excerpt), encoding='utf-8', newline='\n')
(OUT/'接口核对证据.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
saved = json.loads((OUT/'接口核对证据.json').read_text(encoding='utf-8'))
assert saved['source_hashes_before'] == before
assert saved['version_facts']['user_confirmed_external_version'] == '0.3'
print(json.dumps({'source_file_count':len(before), 'source_content_unchanged':True,
                  'source_example_version':input_example['schema_version'],
                  'external_version_decision':'0.3 only; older versions reject; not implemented',
                  'excerpt_body_range':[excerpt[0]['body_index'],excerpt[-1]['body_index']]},ensure_ascii=False))
