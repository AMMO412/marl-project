from pathlib import Path
import json,hashlib,uuid
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
OUT=ROOT/"outputs"/"planning_middle_demo审查_20261026"
TOPIC=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
name="审查_planning_middle_demo指标与系统可用性_2026-10-26"
dest=TOPIC/(name+".md")
if dest.exists():raise RuntimeError("Review note already exists")
entry=TOPIC/"00_项目入口.md"
design=TOPIC/"方案_通用多机器人仿真系统工程设计.md"
originals={p:p.read_bytes() for p in (entry,design)}
backup=ROOT/".work/backups"/("2026-10-26_demo_audit_"+uuid.uuid4().hex[:8])
backup.mkdir(parents=True)
for p,b in originals.items():(backup/p.name).write_bytes(b)
note="""---
type: review
updated: '2026-10-26'
status: 固定快照审查完成；缺陷未修复；真实联调未完成
cssclasses: [ammo-note]
---
# planning_middle_demo 指标与系统可用性审查

> [!abstract] 结论
> 具备可重复运行的本地原型价值，尚不能作为独立联调或正式交付系统。原中间层14条技术指标均未取得完整达标证据，其中11条局部实现、3条未实现；这不是工作量完成率。

## 本次新增证据

当前快照已加入 rules 的三个白名单参数与 timeline 的四类实验事件，不能沿用早先“完全未实现”的判断。两者仍不等于正式平台五段 Schema 或在线导调。

Windows 打包运行时 Python 3.12.14 实跑45项测试，全部通过、无跳过；normal/failure/timeout/deviation均6/6，motion替身6/6；kill为5/6、未settled、达到60步限制。未启动WSL、ROS、Gazebo或UE5。

使用普通工单补充检查已复现：

- Q1：反馈返回拒绝，但位置已写入状态。
- Q2/Q3：NaN反馈和部分非法配置通过校验；未知根字段可被静默忽略。
- Q4：内部计划0与消息计划1不一致。
- Q5：默认运行/命令身份相同，另一轮旧反馈被接受。
- Q6：实际rules参数与manifest记录不一致。

此外尚无独立真实通信、状态恢复和严格复盘；同刻多事件测试仅验证列表保留数量，不证明全部事件执行。以上问题与“缺外部资料”分开，不能都归因于资料未到位。本轮没有修复源码。

## 报告与证据

[Word审查报告](C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/planning_middle_demo指标实现与系统可用性审查.docx)逐项盘点原14条指标、新平台13类接口、模块功能、交付资料与系统可用性。报告共15页，已渲染检查。

产物根目录：C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/。
固定源码20个文件在snapshot/planning_middle_demo/；source_manifest.json保存SHA256；baseline_tests.txt、audit_results.json及runs/保存实测证据。

## 建议与边界

建议先处理通用软件的状态一致性、运行隔离、计划关联及有效配置留痕，再用普通工单取得独立进程联调、中断与恢复证据。此为建议，未实施，不扩展具体作战任务算法。

本次仅审查和文档留痕；保留原始实验与源码。笔记修改前已做库外备份；不提交Git或改动其他主题。

相关：[[00_项目入口]] · [[方案_通用多机器人仿真系统工程设计]] · [[需求与验收]]。
"""
old_entry=originals[entry].decode("utf-8-sig")
anchor="## 已有成果与限制"
if anchor not in old_entry:raise RuntimeError("Entry anchor missing")
new_entry=old_entry.replace(anchor,anchor+"\n\n- **最新独立审查**：[["+name+"]]。当前快照45项测试通过，另复现状态/身份/版本/配置记录问题；rules与timeline已具备本地子集，真实联调仍未完成。",1)
old_design=originals[design].decode("utf-8-sig")
anchor2="## 改动有多少"
latest="## 最新系统审查\n\n2026-10-26 后续固定快照已加入 rules/timeline，本轮45项测试通过，同时复现六类通用软件问题。当前定位为本地可执行原型，不能作为独立联调或正式验收系统。逐项状态、Word报告、复现证据与限制统一见 [["+name+"]]；下方早先评估保留为历史时点。\n\n"
if anchor2 not in old_design:raise RuntimeError("Design anchor missing")
new_design=old_design.replace(anchor2,latest+anchor2,1).replace("## 2026-10-26 续评 rules 与 timeline","## 2026-10-26 早先评估 rules 与 timeline 历史记录",1)
for p,b in originals.items():
    if p.read_bytes()!=b:raise RuntimeError("Concurrent note change")
for p,content in [(entry,new_entry),(design,new_design),(dest,note)]:
    p.write_text(content,encoding="utf-8")
    if p.read_text(encoding="utf-8")!=content:raise RuntimeError("Readback mismatch")
manifest=json.loads((OUT/"source_manifest.json").read_text(encoding="utf-8"))
changed=[f["path"] for f in manifest["files"] if hashlib.sha256((ROOT/"planning_middle_demo"/f["path"]).read_bytes()).hexdigest()!=f["sha256"]]
qa={"note":str(dest),"note_backup":str(backup),"source_changes_since_snapshot":changed,"docx":str(OUT/"planning_middle_demo指标实现与系统可用性审查.docx"),"rendered_pages":len(list((OUT/"render_final").glob("page-*.png"))),"readback":"exact"}
(OUT/"delivery_receipt.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(qa,ensure_ascii=False,indent=2))
print(note[:540])

