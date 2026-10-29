from pathlib import Path
import json,re,hashlib
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
WORK=ROOT/".work/platform_review_20261026"
OUT=ROOT/"outputs/planning_middle_demo审查_20261026"
V=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
meta=json.loads((WORK/"scope_correction_backup.json").read_text(encoding="utf-8"))
B=Path(meta["backup"])
for p in [WORK/"responsibility_content.json",WORK/"build_responsibility_docx.py",OUT/"responsibility_receipt.json"]:
    if p.exists():(B/p.name).write_bytes(p.read_bytes())
new={}
p=V/"00_项目入口.md";s=p.read_text(encoding="utf-8")
s=s.replace("updated: '2026-10-26'","updated: '2026-10-27'")
old="> 用户已明确：M1至M7归外协/平台交付，M8并入M3；中间层只负责约定边界的“对接+消费”。平台方落实M2/M3/M4承接人，我方保留自身接口、状态和留痕质量责任。责任矩阵及Word入口见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]。"
assert old in s
s=s.replace(old,"> 2026-10-27纠正：M3（含M8）和M4由我方建设、交付与自测；M1、Bridge、M5、M6、M7按外协清单由外协交付，我方负责相应对接；M2归属待核对。此前“M1至M7全归外部、我方只消费”是责任判断错误，已撤回。矩阵与修正版Word见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]。")
old="平台方落实各模块具体承接人并提供真实接口/样例；我方处理自身质量问题，完成约定输入的适配与消费，随后联合验证。无需为M1至M7新建平台功能。"
assert old in s
s=s.replace(old,"先核对我方M3/M4已有资产，补齐真实功能交付清单；另行确定M2负责人。外协提供其模块接口与样例，我方完成M3/M4建设、内部集成和外部对接，双方联合验证。planning_middle_demo只是我方子组件，不能代表M3/M4整体完成。")
new[p]=s
p=V/"需求与验收.md";s=p.read_text(encoding="utf-8")
s=s.replace("updated: '2026-10-26'","updated: '2026-10-27'")
old="用户现已明确M1至M7归外协/平台，M8并入M3；中间层只承担与自身有关的对接、消费和质量责任。"
assert old in s
s=s.replace(old,"用户2026-10-27明确M3（含M8）和M4属于我方；外协清单列M1、Bridge、M5、M6、M7；M2归属待核对。我方既交付M3/M4，也承担相应对接和质量责任。")
s=s.replace("| 用户 2026-10-26 回复 | “具体不太清晰，我们是中间层，你来看着办” | 延续中间层定位；没有授权自动扩大到整个平台 |","| 用户 2026-10-27 澄清 | M3/M8智能体配置、M4训练框架和实验管理是我方工作 | 纠正此前把平台层误当外部团队的责任判断；M2仍需单独核对 |")
old="2026-10-26用户明确M1至M7归外协/平台。文件已列外协M1、Bridge、M5、M6、M7；M2、M3/M8、M4由平台方落实承接人。下表按该最新边界维护，不把平台功能缺少于本目录作为我方欠交付，也不虚构各方已共同签字。"
assert old in s
s=s.replace(old,"2026-10-27纠正：此前将平台层模块等同于外部团队交付，错误地把M3/M4也缩成对接消费项；该判断撤回。按用户本次澄清，我方建设并交付M3/M8与M4，外协交付其清单模块，M2归属待核对。当前责任表不代表各方已完成合同签署或功能验收。")
s=s.replace("| M2 | 想定编辑、导调、随机化配置界面 | 平台方牵头交付；我方只对接与消费 |","| M2 | 想定编辑、导调、随机化配置界面 | 承接方待核对；不默认划给我方或外协 |")
s=s.replace("| M3/M8 | 状态动作、奖励与网络配置、多智能体分组通信 | 平台方牵头交付；我方只对接与消费 |","| M3/M8 | 状态动作、奖励与网络配置、多智能体分组通信 | 我方建设、交付与自测；对接M4及外部数据 |")
s=s.replace("| M4 | 算法训练、推理、实验与模型管理、调参 | 平台方牵头交付；我方只对接与消费 |","| M4 | 算法训练、推理、实验与模型管理、调参 | 我方建设、交付与自测；对接仿真、桥接、采集和部署 |")
s=s.replace("“中间层”既可能指原任务规划模块，也可能被用来指配置与训练服务；同一个称呼不能代替交付边界。M2 的编辑器和导调界面尤其不能因未外协就自动算给我方。","“中间层”这一称呼不能代替交付边界。现已明确我方M3/M4并非只消费接口；M2不能因未写入外协就自动算给我方。planning_middle_demo中未出现M3/M4完整功能，属于本目录实现证据不足；目录外资产需另行核对，不能直接判断整个项目毫无实现。")
new[p]=s
new[V/"方案_通用多机器人仿真系统工程设计.md"]="""---
type: design
created: '2026-10-24'
updated: '2026-10-27'
status: M3及M8与M4归我方；M2待核对；真实联调待验证
cssclasses: [ammo-note]
---
# 我方M3/M4建设与外部对接边界

> [!abstract] 当前责任
> 我方交付M3（含M8）智能体配置和M4训练框架、实验管理；外协交付M1、Bridge、M5、M6、M7，我方对接这些模块；M2负责人待核对。“我方只对接和消费”不能覆盖全部工作。

2026-10-27责任纠错：此前把平台层位置误当成外部团队归属，并据此删去了我方M3/M4建设责任。该判断撤回，不再作为当前计划。

## 我方交付

| 模块 | 建设内容 | 验证责任 |
| --- | --- | --- |
| M3/M8 | 状态动作配置、奖励编辑与受控执行、网络拓扑编辑与生成、多智能体分组/策略/观测/奖励配置 | 我方功能自测，与M4及外部数据方联验 |
| M4 | 算法和环境封装、训练与检查点恢复、模型和推理API、实验比较、超参数搜索与训练调度 | 我方训练、恢复和API自测；跨仿真、采集、部署联合验证 |
| 原规划子组件 | 现有消息、rules/timeline子集与留痕等资产 | 我方维护组件正确性；不将它等同完整M3/M4 |

M3→M4是我方内部集成；M4所需环境封装与训练软件不能再统归外部平台。M3/M4不要求全部放入planning_middle_demo，同属我方交付即可。目录外已有资产需单独核对；本次没有重新审查其完成度。

## 外部对接

| 外部模块 | 外协交付 | 我方承担 |
| --- | --- | --- |
| M1/Bridge | 仿真实例、通信和数据来源 | 接入我方环境/配置，提供必要请求，消费状态与观测并联验 |
| M5 | 采集、监控和数据管理 | 提供真实训练指标和本层结果，消费所需数据 |
| M6 | 显示、同步和回放 | 提供约定数据与时间，核对关联 |
| M7 | 安装、编排、资源和部署包 | 提交M3/M4软件及依赖配置，验证部署后自身运行 |

M2界面和想定导调服务的交付方仍需核对；不能因为未外协便自动归我方，也不能写成已有其他平台团队承接。外部数据样例、单位/坐标/时间、协议版本、错误和就绪语义是联调依赖，不会替代我方M3/M4功能交付。

## 现有证据与限制

2026-10-26固定快照45项本地测试通过，同时复现Q1至Q6：拒绝消息改状态、非有限数值、非法配置、计划关联、运行隔离和有效配置留痕问题。仍由我方负责；本轮没有修复或重测。

现有原型可运行不等于平台可交付。Qt配置、训练后台、模型/实验服务的证据需逐项核对；ROS/Gazebo等真实联调尚不能据演示结果认定已完成。保留历史代码和实验，不在本次责任纠错中升级依赖。

修正版Word、责任矩阵和证据位置见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]；需求来源见 [[需求与验收]]。
"""
new[V/"审查_planning_middle_demo指标与系统可用性_2026-10-26.md"]="""---
type: review
updated: '2026-10-27'
status: 已纠正M3及M8与M4归属；本次仅改文档；功能交付及真实联调待核对
cssclasses: [ammo-note]
---
# planning_middle_demo 责任矩阵与实现边界

> [!abstract] 当前口径
> M3（含M8）和M4由我方建设、交付与自测；M1、Bridge、M5、M6、M7按外协清单由外协交付，我方对接；M2归属待核对。此前“M1至M7全部归外部、我方只消费”是错误的责任推断，已撤回。

## 谁交付 谁对接 谁验证

| 模块 | 谁交付 | 我方责任 | 谁验证 |
| --- | --- | --- | --- |
| M1 | 外协M1 | 对接实例、状态、时钟和可用性 | 外协自测；我方测消费；双方联验 |
| Bridge | 外协Bridge | 通信与字段适配 | 外协测桥接；双方联验 |
| M2 | 负责人待核对 | 保留已确认的输入消费；界面交付待定 | 明确归属后拆分 |
| M3及M8 | 我方 | 建设配置、奖励/网络编辑、多智能体配置 | 我方功能自测；与M4和数据方联验 |
| M4 | 我方 | 建设算法/环境封装、训练/推理、模型/实验、搜索与调度 | 我方自测；与仿真、采集、部署方联验 |
| M5 | 外协M5 | 提供训练指标与结果，消费所需数据 | 外协测采集；双方测关联 |
| M6 | 外协M6 | 提供约定状态与时间 | 外协测显示；双方测关联 |
| M7 | 外协M7 | 提供M3/M4可部署组件、依赖和配置 | 外协测安装；我方测自身运行 |

文件事实：《外协内容》只列M1、Bridge、M5、M6、M7。用户2026-10-27明确M3/M8及M4属于我方。“位于平台层”不等于“由别人做”，不能再次据层名转移责任。M3→M4是我方内部集成；M4→M5等是双方对接。

## 实现程度怎样判断

M3/M4属于我方，配置界面、网络/奖励编辑、训练框架和实验服务不能再全部写成“外部平台交付，我方仅消费”。planning_middle_demo固定快照没有这些模块的完整实现证据，仍需我方核对与补齐。

这不要求把完整平台塞入演示目录。应区分原型子组件、我方M3/M4功能、外协模块；目录外代码未在本次重新审查，不能由本目录缺少功能推断全项目没有资产。

外协条目记录“谁交付、我方对接项、待接口/样例、待联合验证”；我方条目记录“已实现、局部实现、本目录无完整证据、目录外待核对”。不以原14条混合指标给出我方整体完成率。

## 已有软件证据与自身责任

2026-10-26固定快照已有rules/timeline本地子集，45项测试通过。本次责任纠错没有修改业务代码或重跑测试，这些旧结果不能证明M3/M4完成。

Q1至Q6仍保留：拒绝反馈仍改位置、NaN进入状态、非法配置被放过、计划编号错位、默认运行身份接受旧反馈、有效配置与manifest不一致。这些是我方软件质量责任。

本地原型能运行；完整系统可用性还需M3/M4功能证据、组件可靠性与真实跨模块联调记录。不能用责任划分代替验收。

## 修正版报告与证据

[责任归属纠正版Word](C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/planning_middle_demo责任分工与对接核查.docx)，修订日期2026-10-27，共5页，已逐页渲染检查。内容为责任矩阵、M3/M8和M4我方交付项、13类接口归属与原型结论修正。

原12页责任版已由此文件替换，错误划分停止使用；替换前Word和4篇笔记精确备份于项目.work/backups/2026-10-27_scope_correction_657dbce2。原15页实现审查保留为历史技术证据，责任归属以本次纠正为准。

证据目录：C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/。source_manifest.json、baseline_tests.txt、audit_results.json及runs/仍是此前固定快照的原始证据。

相关：[[00_项目入口]] · [[需求与验收]] · [[方案_通用多机器人仿真系统工程设计]]。
"""
for p,s in new.items():
    record=next(x for x in meta["files"] if x["original"]==str(p))
    assert hashlib.sha256(p.read_bytes()).hexdigest()==record["sha256"],"Concurrent change: "+str(p)
    s=s.replace("\r\n","\n").replace("\r","\n")
    p.write_bytes(s.encode("utf-8"))
    assert p.read_text(encoding="utf-8")==s
    assert "\r\r\n" not in p.read_bytes().decode("utf-8")
    print(str(p))
corrected=(WORK/"corrected_scope_20261027.json").read_bytes()
(WORK/"responsibility_content.json").write_bytes(corrected)
stable=(WORK/"build_corrected_scope.py").read_text(encoding="utf-8").replace("corrected_scope_20261027.json","responsibility_content.json")
(WORK/"build_responsibility_docx.py").write_bytes(stable.encode("utf-8"))
receipt={"revision_date":"2026-10-27","reason":"纠正M3/M8与M4归属；撤回M1至M7全部归外部","pages":5,"docx":str(OUT/"planning_middle_demo责任分工与对接核查.docx"),"render":str(OUT/"render_scope_correction_20261027"),"backup":str(B),"notes":[str(p) for p in new],"code_changed":False,"tests_rerun":False,"basis":"2026-10-26固定快照及2026-10-27用户责任澄清"}
receipt["docx_sha256"]=hashlib.sha256(Path(receipt["docx"]).read_bytes()).hexdigest()
(OUT/"responsibility_receipt.json").write_bytes(json.dumps(receipt,ensure_ascii=False,indent=2).encode("utf-8"))
(OUT/"scope_correction_receipt_20261027.json").write_bytes(json.dumps(receipt,ensure_ascii=False,indent=2).encode("utf-8"))
print("READBACK VERIFIED: 4 notes; corrected report receipt; no code or tests changed.")

