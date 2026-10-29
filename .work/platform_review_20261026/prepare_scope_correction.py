from pathlib import Path
import json,hashlib,uuid
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
WORK=ROOT/".work/platform_review_20261026"
OUT=ROOT/"outputs/planning_middle_demo审查_20261026"
TOPIC=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
backup=ROOT/".work/backups"/("2026-10-27_scope_correction_"+uuid.uuid4().hex[:8])
backup.mkdir(parents=True)
paths=[OUT/"planning_middle_demo责任分工与对接核查.docx"]+[TOPIC/n for n in ["00_项目入口.md","需求与验收.md","方案_通用多机器人仿真系统工程设计.md","审查_planning_middle_demo指标与系统可用性_2026-10-26.md"]]
records=[]
for p in paths:
    b=p.read_bytes();(backup/p.name).write_bytes(b)
    records.append({"original":str(p),"backup":str(backup/p.name),"sha256":hashlib.sha256(b).hexdigest()})
meta={"backup":str(backup),"files":records}
(WORK/"scope_correction_backup.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
base=(WORK/"build_responsibility_docx.py").read_text(encoding="utf-8")
base=base.replace("responsibility_content.json","corrected_scope_20261027.json").replace("2026-10-26","2026-10-27")
base=base.replace("责任分工与对接核查","责任归属纠正").replace('dest=OUT/"planning_middle_demo责任归属纠正.docx"','dest=OUT/"planning_middle_demo责任分工与对接核查.docx"')
base=base.replace('if headers[0]=="功能项":widths=[2.45,1.12,3.59]','if headers[0]=="功能项":widths=[1.55,2.1,3.51]')
base=base.replace('if headers[0]=="接口":widths=[1.12,1.18,2.55,2.31]','if headers[0]=="接口":widths=[1.5,2.1,3.56]')
base=base.replace('if headers[0]=="事项":widths=[1.25,1.35,2.4,2.16]','if headers[0]=="事项":widths=[1.45,2.45,3.26]')
(WORK/"build_corrected_scope.py").write_bytes(base.encode("utf-8"))
print(json.dumps({"backup":str(backup),"pages":5},ensure_ascii=False))

