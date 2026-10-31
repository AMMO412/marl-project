from pathlib import Path
import json,re,hashlib,urllib.parse
V=Path('D:/obsidianNOTE/ammo')
B=Path(Path('D:/Desktop/MARL项目/.work/obsidian_update_backup_path.txt').read_text(encoding='utf-8-sig').strip())
manifest=json.loads((B/'manifest-changes.json').read_text(encoding='utf-8'))
md=list(V.rglob('*.md'))
issues=[]; checked=0; external=0
for row in manifest:
    if '/历史/' in row['path']: continue
    f=V/row['path']; text=f.read_text(encoding='utf-8')
    assert hashlib.sha256(f.read_bytes()).hexdigest().upper()==row['after_sha256'],f
    assert '\ufffd' not in text, f
    if text.startswith('---\n'):
        front=text.split('---',2)[1]
        assert 'type:' in front and 'updated:' in front and 'cssclasses:' in front,f
    for target in re.findall(r'\[\[([^\]]+)\]\]',text):
        target=target.split('|',1)[0].split('#',1)[0]
        if not target:continue
        target_file=target if target.endswith('.md') else target+'.md'
        candidates=[f.parent/target_file,V/target_file]
        if not any(p.is_file() for p in candidates):
            matches=[p for p in md if p.stem==target]
            if len(matches)!=1:issues.append({'file':row['path'],'target':target,'kind':'wiki','matches':len(matches)})
        checked+=1
    for raw in re.findall(r'\]\((?:<([^>]+)>|([^\s)]+))\)',text):
        target=urllib.parse.unquote(raw[0] or raw[1])
        if re.match(r'^[A-Za-z]:/',target):
            external+=1
            # These lesson links are explicitly retained as historic source context.
            if not Path(target).exists() and row['path'].endswith('学习_ROS与Gazebo入门.md'):
                issues.append({'file':row['path'],'target':target,'kind':'historical_external'})
            elif not Path(target).exists():issues.append({'file':row['path'],'target':target,'kind':'external'})
for row in manifest:
    if '/历史/20261030_主题整理前/' in row['path'] and not row['path'].endswith('00_整理说明.md'):
        name=Path(row['path']).name
        assert (V/row['path']).read_bytes()==(B/'10_项目/MARL'/name).read_bytes(),name
report={'files_written':len(manifest),'active_wikilinks_checked':checked,'external_paths_checked':external,'issues':issues,'archive_bytes_preserved':True,'code_or_simulation_rerun':False}
(B/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
