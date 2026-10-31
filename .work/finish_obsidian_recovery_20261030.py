from pathlib import Path
import json,tempfile,subprocess,sys,hashlib
B=Path(Path('D:/Desktop/MARL项目/.work/obsidian_update_backup_path.txt').read_text(encoding='utf-8-sig').strip())
script=(B/'restore_snapshot.py').read_text(encoding='utf-8')
# Exercise restoration on an isolated temporary fixture, never on real notes.
with tempfile.TemporaryDirectory(prefix='obsidian_recovery_test_') as tmp:
    root=Path(tmp); vault=root/'vault'; backup=root/'backup'
    vault.mkdir();backup.mkdir()
    (vault/'existing.md').write_bytes(b'after');(vault/'created.md').write_bytes(b'created')
    (backup/'existing.md').write_bytes(b'before')
    def sha(data):return hashlib.sha256(data).hexdigest().upper()
    rows=[{'path':'existing.md','existed_before':True,'before_sha256':sha(b'before'),'after_sha256':sha(b'after')}, {'path':'created.md','existed_before':False,'before_sha256':None,'after_sha256':sha(b'created')}]
    (backup/'manifest-changes.json').write_text(json.dumps(rows),encoding='utf-8')
    test_script=backup/'restore_snapshot.py'
    test_script.write_text(script.replace("Path('D:/obsidianNOTE/ammo').resolve()",f'Path({str(vault)!r}).resolve()'),encoding='utf-8')
    def run(*args):return subprocess.run([sys.executable,'-X','utf8',str(test_script),*args],capture_output=True,text=True,encoding='utf-8')
    assert run().returncode==0 and (vault/'existing.md').read_bytes()==b'after'
    (vault/'existing.md').write_bytes(b'newer edit')
    assert run('--apply').returncode!=0 and (vault/'created.md').exists()
    (vault/'existing.md').write_bytes(b'after')
    result=run('--apply');assert result.returncode==0,result.stderr
    assert (vault/'existing.md').read_bytes()==b'before' and not (vault/'created.md').exists()
    rescue=list(backup.glob('before_rollback_*'))
    assert len(rescue)==1 and (rescue[0]/'existing.md').read_bytes()==b'after'
    tested={'preview_without_changes':True,'refuse_newer_content':True,'restore_original_bytes':True,'remove_only_created_file':True,'preserve_pre_rollback_content':True,'tested_in_temporary_fixture':True}
    (B/'recovery-test.json').write_text(json.dumps(tested,indent=2),encoding='utf-8')

readme=f'''# 本次更新的备份与回档

备份位置：`{B.as_posix()}`。
范围：_规范、_模板、10_项目/MARL、00_知识库入口.md、AGENTS.md。
修改前33个现存文件已逐一SHA256比对；现存附件包括在内。之前已缺失的文件没有凭空补回。
`manifest-before.json`记录原始文件，`manifest-changes.json`只列本轮20个写入文件。
其中12个是既有文件更新，2个为新增模板，6个为本轮历史快照及说明。
Git原提交与工作区状态见git-head-before.txt、git-status-before.txt；没有提交、暂存、推送或全库恢复。

## 先预览，后执行

在PowerShell中执行（要求Python 3.9或以上）：

```powershell
python -X utf8 "{B.as_posix()}/restore_snapshot.py"
```

默认只预览，文件不会改变。要恢复本轮全部20个文件，确认预览范围后执行：

```powershell
python -X utf8 "{B.as_posix()}/restore_snapshot.py" --apply
```

只恢复项目入口：

```powershell
python -X utf8 "{B.as_posix()}/restore_snapshot.py" --path "10_项目/MARL/00_项目入口.md" --apply
```

按文件回档不执行全库reset/clean；不操作Git暂存区。回档前会把最新内容另存到本备份目录的before_rollback_*。
如果本轮更新后文件又被编辑、移走或删除，工具拒绝执行，避免盖掉新内容；此时请按需要人工比较和合并。原备份文件哈希不符也拒绝执行。
恢复动作只覆盖选中的原有文件、移除本轮明确新增的文件，不递归清理目录。
回档工具已在临时测试目录验证：预览不修改、拒绝新改动、恢复原字节、保留回档前内容与只删除本轮新增文件；真实笔记未执行回档。

## 查改动与核对结果

修改前副本与同路径当前文件可直接对比。
`verification.json`记录正文回读、链接与历史字节保留检查；`recovery-test.json`记录回档工具隔离测试。
本轮未重跑项目代码或仿真，没有新增功能验收结果。
'''
(B/'恢复说明.md').write_text(readme,encoding='utf-8')
assert (B/'恢复说明.md').read_text(encoding='utf-8')==readme
print(json.dumps(tested))
print('Recovery guide written and read back.')
