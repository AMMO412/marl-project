from pathlib import Path
import json,uuid,hashlib
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
WORK=ROOT/".work/platform_review_20261026"
OUT=ROOT/"outputs/planning_middle_demo审查_20261026"
TOPIC=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
backup=ROOT/".work/backups"/("2026-10-26_responsibility_"+uuid.uuid4().hex[:8])
backup.mkdir(parents=True)
paths=[OUT/"planning_middle_demo指标实现与系统可用性审查.docx",WORK/"report_content.json"]+[TOPIC/n for n in ["00_项目入口.md","需求与验收.md","方案_通用多机器人仿真系统工程设计.md","审查_planning_middle_demo指标与系统可用性_2026-10-26.md"]]
records=[]
for p in paths:
    b=p.read_bytes()
    d=backup/p.name
    d.write_bytes(b)
    records.append({"original":str(p),"backup":str(d),"sha256":hashlib.sha256(b).hexdigest()})
(backup/"manifest.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
(WORK/"responsibility_revision_backup.json").write_text(json.dumps({"backup":str(backup),"files":records},ensure_ascii=False,indent=2),encoding="utf-8")
base=(WORK/"build_audit_docx.py").read_text(encoding="utf-8")
base=base.replace("report_content.json","responsibility_content.json")
base=base.replace("planning_middle_demo指标实现与系统可用性审查.docx","planning_middle_demo责任分工与对接核查.docx")
base=base.replace("planning_middle_demo   实现证据与系统可用性","planning_middle_demo   责任分工与对接核查")
base=base.replace("审查日期 2026-10-26    固定版本    内容审阅与本地验证","修订日期 2026-10-26    责任版    交付 对接 消费 验证")
anchor='    if headers[0]=="功能项":widths=[2.45,.75,3.96]'
replacement='''    if headers[0]=="功能项":widths=[2.45,1.12,3.59]
    if headers[0]=="事项":widths=[1.25,1.35,2.4,2.16]
    if headers[0]=="模块":widths=[.82,1.4,2.5,2.44]
    if headers[0]=="接口":widths=[1.12,1.18,2.55,2.31]
    if headers[0]=="条款":widths=[1.12,1.65,2.65,1.74]
    if headers[0]=="验证对象":widths=[1.35,1.55,1.9,2.36]
    if headers[0]=="依据或产物":widths=[1.48,2.9,2.78]'''
if anchor not in base:raise RuntimeError("Builder anchor missing")
base=base.replace(anchor,replacement)
base=base.replace('if j==1 and (len(headers)==4 or headers[0]=="功能项"):', 'if j==1 and headers[j] in ("状态","本目录状态"):')
(WORK/"build_responsibility_docx.py").write_text(base,encoding="utf-8")
content=json.loads((WORK/"responsibility_content.json").read_text(encoding="utf-8"))
assert "未实现" not in json.dumps(content,ensure_ascii=False)
print(json.dumps({"backup":str(backup),"pages":len(content["pages"]),"platform_missing_labels":0},ensure_ascii=False))

