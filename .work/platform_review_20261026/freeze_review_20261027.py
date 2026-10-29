from pathlib import Path
from datetime import datetime
import json,hashlib,shutil
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");src=ROOT/"planning_middle_demo"
out=ROOT/"outputs/planning_middle_demo指标核查_20261027";out.mkdir(parents=True,exist_ok=True)
snap=out/"snapshot/planning_middle_demo";rows=[]
for p in sorted(src.rglob("*")):
 if not p.is_file() or any(k in p.relative_to(src).parts for k in ("outputs","__pycache__",".git")):continue
 if p.suffix not in (".py",".md",".json",".html") and p.name!=".gitignore":continue
 rel=p.relative_to(src);b=p.read_bytes();dest=snap/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
 rows.append({"path":rel.as_posix(),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
old=json.loads((ROOT/"outputs/planning_middle_demo审查_20261026/source_manifest.json").read_text(encoding="utf-8"))["files"]
od={r["path"]:r["sha256"] for r in old}
changes=[r["path"] for r in rows if od.get(r["path"])!=r["sha256"]]
sources=[]
for p in [Path(r"C:\Users\ammo\Desktop\智能体开发训练平台技术实施方案.docx"),Path(r"C:\Users\ammo\Desktop\外协内容.docx"),ROOT/"对手编队决策模型建模询价要求与报价单20261008.docx"]:
 b=p.read_bytes();dst=out/"sources"/p.name;dst.parent.mkdir(exist_ok=True);dst.write_bytes(b);sources.append({"path":str(p),"sha256":hashlib.sha256(b).hexdigest()})
meta={"review_date":"2026-10-27","snapshot":str(snap),"files":rows,"sources":sources,"changed_from_20261026":changes,"new_files":[r["path"] for r in rows if r["path"] not in od],"missing_old":[p for p in od if not(src/p).exists()]}
(out/"source_manifest.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"files":len(rows),"changed":changes,"new":meta["new_files"],"missing":meta["missing_old"],"out":str(out)},ensure_ascii=False))

