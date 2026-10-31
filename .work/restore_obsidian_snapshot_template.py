"""Preview by default. Use --path with manifest-relative path(s), then --apply to restore."""
from pathlib import Path
import argparse,datetime,hashlib,json,shutil
backup=Path(__file__).resolve().parent
vault=Path('D:/obsidianNOTE/ammo').resolve()
parser=argparse.ArgumentParser(description='Preview scoped rollback. Changed-since-update files are refused.')
parser.add_argument('--path',action='append',help='Exact vault-relative path from manifest-changes.json; repeatable')
parser.add_argument('--apply',action='store_true',help='Apply after all selected targets pass checks')
args=parser.parse_args()
rows=json.loads((backup/'manifest-changes.json').read_text(encoding='utf-8'))
if args.path:
    requested={x.replace('\\','/') for x in args.path}
    known={x['path'] for x in rows}
    if requested-known: raise SystemExit('Unknown path(s): '+repr(requested-known))
    rows=[x for x in rows if x['path'] in requested]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest().upper()
problems=[]
for row in rows:
    dest=(vault/row['path']).resolve()
    if not dest.is_relative_to(vault):raise SystemExit('Path outside vault')
    if not dest.is_file() or sha(dest)!=row['after_sha256']:
        problems.append(row['path'])
    if row['existed_before']:
        source=(backup/row['path']).resolve()
        if not source.is_relative_to(backup) or not source.is_file() or sha(source)!=row['before_sha256']:
            raise SystemExit('Original backup missing or modified: '+row['path'])
    print(('RESTORE ' if row['existed_before'] else 'REMOVE CREATED FILE ')+row['path'])
if problems:raise SystemExit('Refused: newer/missing files require manual merge; no files changed: '+repr(problems))
if not args.apply:
    print('Preview only. Add --apply to restore, or --path for selected files.')
    raise SystemExit(0)
rescue=backup/('before_rollback_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
for row in rows:
    dest=vault/row['path']; saved=rescue/row['path']
    saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
for row in rows:
    dest=vault/row['path']
    if sha(dest)!=row['after_sha256']:raise SystemExit('Concurrent update detected; stopped: '+row['path'])
    if row['existed_before']:
        shutil.copy2(backup/row['path'],dest)
        assert sha(dest)==row['before_sha256']
    else:dest.unlink()  # exact manifest file only; no recursive removal
print('Restored. Latest content preserved in '+str(rescue))
