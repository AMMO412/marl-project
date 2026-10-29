import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

root = Path('C:/Users/ammo/Desktop/MARL项目')
work = root / '.work/project_cleanup_20261028'
manifest = json.loads((work / 'manifest.json').read_text(encoding='utf-8-sig'))
allowed_changes = {
    'AGENTS.md',
    'planning_middle_demo/docs/下层接口草案.md',
    '资料/需求与任务/五类作战任务_10月26日修改.md',
    '资料/平台调研/四类平台参数指标与Gazebo实现详尽调研_更新版20261027.md',
    'outputs/figures/三类任务_生图提示词.md',
    'outputs/20261026-对比询价指标/pipeline-state.yaml',
}
verified = []
intentional_changes = []
for item in manifest['before']:
    old = item['path'].replace('\\', '/')
    if any(old == entry['path'].replace('\\', '/') or old.startswith(entry['path'].replace('\\', '/') + '/') for entry in manifest['deletions']):
        continue
    new = old
    for move in manifest['moves']:
        source, destination = move['source'].replace('\\', '/'), move['destination'].replace('\\', '/')
        if old == source or old.startswith(source + '/'):
            new = destination + old[len(source):]
            break
    path = root / new
    assert path.is_file(), f'Missing retained file: {new}'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item['sha256']:
        assert new in allowed_changes, f'Unexpected file change: {new}'
        intentional_changes.append(new)
    else:
        verified.append(new)

links = []
for document in [root / '学习入口.md', root / '资料/README.md', root / 'outputs/README.md', root / 'outputs/目录整理_20261028.md', *list((root / '资料').rglob('*.md'))]:
    text = document.read_text(encoding='utf-8')
    for raw in re.findall(r'\]\(([^)\n]+)\)', text):
        target = raw.strip('<>').replace('\\_', '_')
        if target.startswith(('http:', 'https:', 'mailto:', '#', 'data:')):
            continue
        target = unquote(target.split('#')[0])
        path = Path(target) if re.match(r'^[A-Za-z]:[/\\]', target) else document.parent / target
        assert path.exists(), f'Broken local link: {document.name} -> {target}'
        links.append(str(path))

class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
    def handle_starttag(self, tag, attrs):
        self.references += [(tag, value) for key, value in attrs if key in ('src', 'href')]

page = root / 'outputs/任务动态示意_20261027/index.html'
parser = References()
parser.feed(page.read_text(encoding='utf-8'))
for tag, value in parser.references:
    if value.startswith(('data:', '#', 'http:', 'https:')):
        continue
    assert (page.parent / unquote(urlsplit(value).path)).exists(), f'Broken HTML asset: {value}'

state_response = json.loads(urlopen('http://127.0.0.1:8788/api/state', timeout=8).read())
state = {'http': 200, 'status': state_response.get('status'), 'backend': state_response.get('backend')}
assert not (root / 'output').exists()
assert not (root / '_extract').exists()
assert not (root / '.slidep').exists()
assert not list(root.rglob('__pycache__'))
result = {'unchanged_files_sha256_verified': len(verified), 'intentional_text_changes': intentional_changes,
          'local_links_verified': len(links), 'standalone_page_assets_verified': True,
          'navigation_service': state, 'visible_root': sorted(p.name for p in root.iterdir() if not p.name.startswith('.'))}
(work / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
