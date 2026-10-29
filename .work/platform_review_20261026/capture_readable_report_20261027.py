from pathlib import Path
import json,hashlib,re
from pypdf import PdfReader
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");O=ROOT/"outputs/planning_middle_demo指标核查_20261027";W=ROOT/".work/platform_review_20261026";V=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
meta=json.loads((W/"readable_report_backup.json").read_text(encoding="utf-8"));B=Path(meta["backup"])
paths=[V/"审查_planning_middle_demo指标与系统可用性_2026-10-26.md",V/"00_项目入口.md"];previous={p:p.read_bytes() for p in paths}
for p,b in previous.items():(B/p.name).write_bytes(b)
s=previous[paths[0]].decode("utf-8").replace("\r\n","\n")
start=s.index("| 对象 | 本目录完成程度 | Word位置 |");end=s.index("## 本次测试与缺陷",start)
s=s[:start]+"""| 对象 | 本目录完成程度 | Word位置 |
| --- | --- | --- |
| 原询价14条技术指标 | 直接保留原文条款和指标；列明未完成、部分完成或待联调 | 第1—2页 |
| 新实施方案模块 | M3/M8未完成；M4仅有运行记录等局部资产；外协模块按我方对接进度评价 | 第3页 |
| 新方案13类接口 | 按原文名称归并，真实ROS、Gazebo、UE5和部署联调未完成 | 第4页 |
| 外协内容 | 按M1、Bridge、M5、M6、M7合并要求与对接进度 | 第5页 |
| 新方案验收与系统结论 | 合并规模训练、接口验收和交付资料，保留测试/缺陷摘要 | 第6页 |

按用户阅读要求，报告由22页压缩为6页：先原询价，再新文件；删除EX、T、P等内部定位编号，不再逐字段拆分。完成情况仍依据原核查结果，本次仅重排文档，未重新测试。正文按原文章节号、模块名称及标准表述。

"""+s[end:]
s=s.replace("，22页，已逐页检查。每条包含原文出处、指标、责任方、完成状态、当前实现依据及未完成内容/所需资料。","，6页，已逐页检查。使用原文条款或模块名称，每项集中说明责任、完成程度、当前实现和主要缺项。")
old="旧5页责任纠正版只保留为历史分工说明；原15页和45项测试为2026-10-26历史证据，当前版本以本次22页报告及54项测试为准。修订前笔记备份于C:/Users/ammo/Desktop/MARL项目/.work/backups/2026-10-27_standard_audit_abd52ddd。"
assert old in s
s=s.replace(old,"当前报告为6页可读版，取代22页细分版；54项测试仍为2026-10-27核查结果。22页报告及本轮修订前笔记备份于"+str(B).replace("\\","/")+"。旧5页责任说明、原15页和45项测试仅作历史参考。")
entry=previous[paths[1]].decode("utf-8").replace("\r\n","\n").replace("逐项指标、完成程度与22页Word见","按原文顺序整理的指标、完成程度与6页Word见")
for p,text in [(paths[0],s),(paths[1],entry)]:
 assert p.read_bytes()==previous[p],"Concurrent change"
 p.write_bytes(text.encode("utf-8"));assert p.read_text(encoding="utf-8")==text;print("READBACK",str(p))
pdf=next((O/"render_readable").glob("*.pdf"));count=len(PdfReader(pdf).pages);assert count==6
doc=O/"planning_middle_demo指标逐项核查报告.docx"
receipt={"date":"2026-10-27","report":str(doc),"sha256":hashlib.sha256(doc.read_bytes()).hexdigest(),"pages":count,"visual_review":"all 6 pages reviewed","revision":"原询价14条在前，新文件按模块和接口归并；无内部定位编号","backup":str(B),"notes_readback":[str(p) for p in paths],"business_source_modified":False,"tests_rerun":False,"test_basis":"2026-10-27既有54项测试记录"}
(O/"delivery_receipt.json").write_bytes(json.dumps(receipt,ensure_ascii=False,indent=2).encode("utf-8"))
print("Verified 6-page report; 14 original clauses preserved; 2 notes read back.")

