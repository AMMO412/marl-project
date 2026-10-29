from pathlib import Path
import shutil, hashlib, json
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
OUT=ROOT/"outputs"/"planning_middle_demo审查_20261026"
OUT.mkdir(exist_ok=False)
SRC=ROOT/"planning_middle_demo"
DST=OUT/"snapshot"/"planning_middle_demo"
DST.mkdir(parents=True)
records=[]
for p in SRC.rglob("*"):
    rel=p.relative_to(SRC)
    if any(x in ("outputs","__pycache__",".git") for x in rel.parts) or not p.is_file():
        continue
    if p.suffix not in (".py",".json",".md",".png",".svg",".yml",".yaml",".txt") and p.name!=".gitignore":
        continue
    data=p.read_bytes()
    dest=DST/rel
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(data)
    h=hashlib.sha256(data).hexdigest()
    if hashlib.sha256(p.read_bytes()).hexdigest()!=h:
        raise RuntimeError("Concurrent source modification: "+str(rel))
    records.append({"path":str(rel).replace("\\","/"),"sha256":h,"bytes":len(data)})
sources=OUT/"sources"
sources.mkdir()
for p in [ROOT/"对手编队决策模型建模询价要求与报价单20261008.docx",Path(r"C:\Users\ammo\Desktop\智能体开发训练平台技术实施方案.docx"),Path(r"C:\Users\ammo\Desktop\外协内容.docx"),ROOT/"机器人移动话题说明.md"]:
    if p.exists():
        shutil.copy2(p,sources/p.name)
(OUT/"source_manifest.json").write_text(json.dumps({"review_date":"2026-10-26","snapshot":str(DST),"files":records},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"output":str(OUT),"files":len(records)},ensure_ascii=False))

