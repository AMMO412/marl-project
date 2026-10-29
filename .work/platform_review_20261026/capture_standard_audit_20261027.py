from pathlib import Path
import json,hashlib,uuid,re
from pypdf import PdfReader
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目");O=ROOT/"outputs/planning_middle_demo指标核查_20261027";V=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
paths=[V/"审查_planning_middle_demo指标与系统可用性_2026-10-26.md",V/"00_项目入口.md"]
previous={p:p.read_bytes() for p in paths};B=ROOT/".work/backups"/("2026-10-27_standard_audit_"+uuid.uuid4().hex[:8]);B.mkdir(parents=True)
for p,b in previous.items():(B/p.name).write_bytes(b)
s=previous[paths[0]].decode("utf-8").replace("\r\n","\n")
s=s.replace("status: 已纠正M3及M8与M4归属；本次仅改文档；功能交付及真实联调待核对","status: 已完成当前版本逐项核查及54项测试；M3和M4未完整交付；外部联调未完成")
s=s.replace("# planning_middle_demo 责任矩阵与实现边界","# planning_middle_demo 指标逐项核查与系统可用性")
a=s.index("## 实现程度怎样判断")
s=s[:a]+"""## 当前指标核查结果

2026-10-27按两份新材料逐项核查，另保留原询价14条技术指标。范围为本目录22个文本源文件及1个外部道路素材；目录外资产和外协交付状态未核验。

| 对象 | 本目录完成程度 | Word位置 |
| --- | --- | --- |
| M3/M8 | 18项核查记录均未完成；缺配置界面、奖励/网络编辑及多智能体配置和验收 | 第4—5页 |
| M4 | 18项中运行登记资产为部分完成，其余未完成；缺训练、推理、模型/实验、搜索与调度成品 | 第6—7页 |
| 十三类接口 | 已有部分JSON字段/记录，实际ROS、Gazebo、UE5及部署联调未完成 | 第9—10页 |
| 外协要求 | 分别记录供方未核验与我方对接进度，不判定外协功能未完成 | 第11—14页 |
| 阶段验收及交付物 | 已有源码、README和本地日志；正式训练、性能、耐久及平台交付资料未齐 | 第15—17页 |
| 原询价14条 | 保留原编号逐条核查；与新文件范围关系仍需确认 | 第18—19页 |

以上为条目记录，不能换算工作量完成率。现有本地JSON、消息、rules/timeline、日志、HTML及反馈轨迹数据功能单独列于第3页；本地子功能不代表平台整项完成。

## 本次测试与缺陷

当前目录和固定快照均通过54项测试，0失败、0错误、0跳过；固定快照测试用时1.582s。六组既有演示重跑：normal、failure、timeout、deviation均6/6；motion=real为6/6，在演示步62结束；kill为5/6、未settled、退出码2且达到60步上限。全为MockFleet，不是ROS/Gazebo/UE5运行。

Q1至Q6本次仍复现：拒绝反馈改位置、NaN进入状态、非法配置获准、计划版本错位、默认运行身份接受旧消息、有效rules与manifest不一致。

新增Q7：轨迹底图依赖项目outputs下的roads.csv，仅复制源码快照时1项测试错误；补齐带SHA256的原素材后54项通过。回放代码缺底图时可退化为网格，但该测试需要实际道路数据。独立交付应包含素材依赖。

本目录可用于本地演示；正式系统交付尚缺M3/M4功能、通用缺陷处理、真实接口联调、规模/性能与2h稳定性证据。本次没有修改业务源码或升级依赖。

## 当前报告与证据

[指标逐项核查报告](C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo指标核查_20261027/planning_middle_demo指标逐项核查报告.docx)，22页，已逐页检查。每条包含原文出处、指标、责任方、完成状态、当前实现依据及未完成内容/所需资料。

证据目录：C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo指标核查_20261027/。source_manifest.json、sources_text.json、baseline_tests.txt、live_tests_20261027.txt、audit_results.json、runs/及snapshot/保留源文定位、指纹、实测和代码。

旧5页责任纠正版只保留为历史分工说明；原15页和45项测试为2026-10-26历史证据，当前版本以本次22页报告及54项测试为准。修订前笔记备份于"""+str(B).replace("\\","/")+"""。

相关：[[00_项目入口]] · [[需求与验收]] · [[方案_通用多机器人仿真系统工程设计]]。
"""
entry=previous[paths[1]].decode("utf-8").replace("\r\n","\n")
entry=entry.replace("矩阵与修正版Word见","逐项指标、完成程度与22页Word见")
entry=entry.replace("当前快照45项测试通过，另复现状态/身份/版本/配置记录问题；rules与timeline已具备本地子集，真实联调仍未完成。","2026-10-27当前代码54项测试通过；已按文件逐项核查，M3/M4尚未完整实现，真实联调未完成。新增反馈轨迹回放；原Q1至Q6仍复现，另发现底图素材打包依赖Q7。")
entry=entry.replace("- 本次静态核对：","- 当前代码核对：")
entry=entry.replace("- v2 笔记记录 2026-10-26 五种模式结果：正常/失败重试/超时/偏差均 6/6，成员损失 5/6；这是既有模拟实验记录，本次未重跑。README 的 ","- 2026-10-27重跑六组演示：正常/失败重试/超时/偏差均6/6；成员损失5/6且未结束；motion=real为6/6。README 的 ")
new={paths[0]:s,paths[1]:entry}
for p,text in new.items():
 assert p.read_bytes()==previous[p],"Concurrent note change"
 p.write_bytes(text.encode("utf-8"));assert p.read_text(encoding="utf-8")==text
 print("READBACK",str(p))
manifest=json.loads((O/"source_manifest.json").read_text(encoding="utf-8"));changed=[]
for r in manifest["files"]:
 p=ROOT/"planning_middle_demo"/r["path"]
 if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=r["sha256"]:changed.append(r["path"])
assert not changed,changed
pdf=next((O/"render_final").glob("*.pdf"));assert len(PdfReader(pdf).pages)==22
doc=O/"planning_middle_demo指标逐项核查报告.docx"
receipt={"date":"2026-10-27","report":str(doc),"sha256":hashlib.sha256(doc.read_bytes()).hexdigest(),"pages":22,"visual_review":"all 22 pages reviewed","notes_readback":[str(p) for p in new],"notes_backup":str(B),"source_changes_since_snapshot":changed,"tests":json.loads((O/"audit_results.json").read_text(encoding="utf-8"))["baseline"],"business_source_modified":False}
(O/"delivery_receipt.json").write_bytes(json.dumps(receipt,ensure_ascii=False,indent=2).encode("utf-8"))
print(json.dumps({"pages":22,"test_count":54,"source_unchanged":not changed,"readback_notes":len(new),"report":str(doc)},ensure_ascii=False))

