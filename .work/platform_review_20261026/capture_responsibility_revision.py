from pathlib import Path
import json,hashlib,re
ROOT=Path(r"C:\Users\ammo\Desktop\MARL项目")
WORK=ROOT/".work/platform_review_20261026"
TOPIC=Path(r"D:\obsidianNOTE\ammo\10_项目\MARL")
meta=json.loads((WORK/"responsibility_revision_backup.json").read_text(encoding="utf-8"))
files=[Path(x["original"]) for x in meta["files"] if str(x["original"]).endswith(".md")]
originals={p:Path(next(x["backup"] for x in meta["files"] if x["original"]==str(p))).read_bytes() for p in files}
for p,b in originals.items():
    expected=next(x["sha256"] for x in meta["files"] if x["original"]==str(p))
    if hashlib.sha256(b).hexdigest()!=expected:raise RuntimeError("Concurrent note change: "+p.name)
review_name="审查_planning_middle_demo指标与系统可用性_2026-10-26"
report="C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/planning_middle_demo责任分工与对接核查.docx"
review="""---
type: review
updated: '2026-10-26'
status: 已按用户明确范围修订为责任版；真实对接待联合验证；自身缺陷保留
cssclasses: [ammo-note]
---
# planning_middle_demo 责任矩阵与对接核查

> [!abstract] 当前口径
> 用户已明确：M1至M7归外协或平台方交付，M8并入M3；中间层只承担与自身有关的“对接+消费”。平台功能不在本目录，不能据此记为我方欠交付。中间层自己的状态、身份、版本与记录质量仍由我方负责。

## 谁交付 谁对接 谁验证

| 模块 | 谁交付 | 我方对接与消费 | 谁验证 |
| --- | --- | --- | --- |
| M1 | 外协M1，平台统筹 | 实例状态、时钟和可用状态 | 供方自测；我方测消费；平台联验 |
| M2 | 平台牵头指定承接人 | 正式场景、导调事件及结果回报 | M2测生成；我方测解析消费 |
| M3及M8 | 平台牵头指定承接人 | 约定配置、映射和必要输出 | M3/M4测内部传递；我方测必要字段 |
| M4 | 平台牵头指定承接人 | 约定环境/策略边界、版本和结果 | M4测训练/API；我方测边界调用 |
| M5 | 外协M5 | 所需观测和数据引用；本层事件输出 | M5测采集；我方测数据消费 |
| M6 | 外协M6 | 本层状态/结果/时戳输出 | M6测显示；双方测关联 |
| M7 | 外协M7 | 本层依赖、启动、配置和状态 | M7测部署；我方测组件；平台联验 |
| Bridge及执行 | 外协Bridge、下游执行方 | 命令、确认、取消与真实反馈 | 供方测通信/执行；双方测语义 |

文件事实：《外协内容》列M1、Bridge、M5、M6、M7。本次用户决定将M2、M3/M8、M4也明确归平台侧，由平台方落实承接人；不虚构具体人名或已经取得各方共同确认。

平台内部M2→M1、M3→M4、M4→M5的连接由对应交付方完成；中间层不承担平台内部集成或默认兜底开发。导航、控制和任务级执行适配由平台/下游明确交付方。

## 对接状态怎样写

使用“供方交付项、我方消费项、谁验证、当前依赖”；区分待供方接口、待我方适配、待联合验证。供方交付情况本次没有逐模块核验，不能推断供方已经完成或尚未完成。

撤回旧版将跨模块条目按11条局部、3条缺失来呈现我方完成度的方式。原14条编号只用于责任拆分和对接参考，不等同我方平台建设清单。

## 已有软件证据与自身责任

此前固定快照中rules/timeline已有本地子集；45项测试通过。本次没有重跑测试或修改业务源码。

普通工单复现的Q1至Q6保留：拒绝反馈仍改位置、NaN进入状态、非法配置被放过、计划编号错位、默认运行身份接受旧反馈、有效配置与manifest不一致。这些属于中间层自身质量责任，不能随平台分工转移。

本地原型可运行；真实联调可用性仍需看本层可靠性与双方接入证据。平台GUI、训练后台和UE5不在本目录，不作为本层不可交付的理由。

## 当前报告与证据

[责任版Word报告](REPORT_LINK)共12页，已逐页渲染检查。第2节为责任总矩阵，第3至4节为13类接口矩阵，其后按原条款、平台功能及验证责任逐项展开。

证据目录：C:/Users/ammo/Desktop/MARL项目/outputs/planning_middle_demo审查_20261026/。
旧版Word保留为历史；当前阅读以责任版为准。source_manifest.json、baseline_tests.txt、audit_results.json及runs/仍是此前快照证据，没有被改写为新一次实测。

相关：[[00_项目入口]] · [[需求与验收]] · [[方案_通用多机器人仿真系统工程设计]]。
""".replace("REPORT_LINK",report)
design="""---
type: design
created: '2026-10-24'
updated: '2026-10-26'
status: 用户已明确平台侧交付；我方只对接与消费；真实联调待验证
cssclasses: [ammo-note]
---
# 中间层对接与消费方案

> [!abstract] 当前责任
> M1至M7由外协/平台交付，M8并入M3。中间层只交付自身所需的接口适配、解析消费、状态更新、结果输出与留痕，不建设想定编辑器、训练后台、采集平台、UE5和部署平台。

本口径来自用户2026-10-26最新明确指示。此前“若M2/M3/M4归我方则需大量新增”的分支不再作为当前计划；旧正文在修订前作库外精确备份。外协清单本身列M1、Bridge、M5、M6、M7，其余平台模块由平台方落实具体承接人。

## 输入与输出边界

| 边界 | 供方负责 | 中间层负责 | 验证 |
| --- | --- | --- | --- |
| 场景与导调 | M2提供正式文件、事件、版本和样例 | 适配并消费与本层有关的输入 | M2测生成；我方测消费；联合核对 |
| 状态与观测 | M1/Bridge/M5/下游提供真实数据 | 校验身份、单位、时间与必要字段，更新本层状态 | 供方测数据来源；我方测解析 |
| 命令与执行反馈 | Bridge/下游提供执行、确认、取消与终态 | 输出约定消息并消费确认/反馈 | 下游证明执行停止；双方核对关联 |
| 训练与策略边界 | M3/M4提供配置、训练、模型/API | 只提供/消费明确约定的边界数据和版本 | M4测服务；我方测调用 |
| 展示与采集 | M5/M6提供存储、监控、显示与回放 | 输出本层事件、结果和关联时间 | 供方测展示采集；双方核对记录 |
| 部署 | M7提供环境、安装、编排和恢复 | 提交本层依赖、配置、启动与健康说明 | M7测全包；我方测本层启动消费 |

平台内部集成由平台统筹。只有速度话题时，由平台明确任务级执行适配的供方；中间层不自动承接导航或控制开发。完整训练环境封装由M4牵头落实，中间层只承担明确约定的数据适配。

## 对接评价与资料

评价拆为供方交付、我方消费和联合验证。待供方样例、待我方适配、待联合验证分别记录；不能把平台功能不存在于本目录写成我方缺口，也不能以责任已划分代替真实接通证据。

每个边界最少需要负责人/端点、协议版本、单位/坐标/时间、正常和错误样例、就绪与失败语义、运行/消息关联规则、供方自测和双方联调记录。M2/M3/M4具体承接人由平台方落实，不回流为我方开发事项。

## 当前资产与质量责任

保留planning_middle_demo的本地消息、rules/timeline子集和报告资产；旧MARLlib环境用于历史复现，不为本次责任修订升级依赖。当前真实消费验证仍未完成。

上一轮固定快照45项测试通过，同时复现Q1至Q6通用问题。拒绝消息的状态一致性、数值/配置检查、计划关联、运行隔离和有效配置留痕属于我方责任；本轮没有修复或重测。其证据及责任版Word统一见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]。

## 本轮修改

优化责任矩阵和评审口径，保留原始测试、源码与旧实验。建议下一步先处理本层质量，再消费供方真实样例并联合验证；建议不表示已经实施。本文限通用接口和软件质量，不扩展具体作战决策或业务优化设计。
"""
updates={}
for p,b in originals.items():
    old=b.decode("utf-8-sig")
    if p.name=="00_项目入口.md":
        old=old.replace("用户仍将我方定位为“中间层”，具体模块尚不清晰。新收到的两份文件描述完整仿真训练平台及部分外协分工，不能据此认定剩余模块全由我方承担。先保留原型，明确任务规划与平台训练服务的边界，再接通用仿真实验。","用户已明确：M1至M7归外协/平台交付，M8并入M3；中间层只负责约定边界的“对接+消费”。平台方落实M2/M3/M4承接人，我方保留自身接口、状态和留痕质量责任。责任矩阵及Word入口见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]。")
        old=old.replace("先用一张责任表确定：我们交付的是原任务规划模块，还是还包括智能体配置与训练服务。当前可先整理通用配置和接口样例；依赖责任确认的 GUI、大规模训练与底层移动暂不当作既定任务。建议过程见阶段计划，尚未实施。","平台方落实各模块具体承接人并提供真实接口/样例；我方处理自身质量问题，完成约定输入的适配与消费，随后联合验证。无需为M1至M7新建平台功能。")
        old=old.replace("| 工程怎么拆、里程碑与定时任务            | [[10_项目/MARL/计划_工程分解与里程碑]]                    |","| 谁交付、谁对接、谁验证 | [[审查_planning_middle_demo指标与系统可用性_2026-10-26]] |")
        old=old.replace("| 先做什么，何时扩规模 | [[计划_工程分解与里程碑]] |","| 谁交付、谁对接、谁验证 | [[审查_planning_middle_demo指标与系统可用性_2026-10-26]] |")
        updates[p]=old
    elif p.name=="需求与验收.md":
        old=old.replace("用户确认“我们是中间层”，尚未确认 M2、M3/M8、M4 的归属。","用户现已明确M1至M7归外协/平台，M8并入M3；中间层只承担与自身有关的对接、消费和质量责任。")
        old=old.replace("| 未明确归属 |","| 平台方牵头交付；我方只对接与消费 |")
        marker="## 新文件的范围"
        update="## 本次责任澄清\n\n2026-10-26用户明确M1至M7归外协/平台。文件已列外协M1、Bridge、M5、M6、M7；M2、M3/M8、M4由平台方落实承接人。下表按该最新边界维护，不把平台功能缺少于本目录作为我方欠交付，也不虚构各方已共同签字。\n\n"
        old=old.replace(marker,update+marker,1)
        old=old.replace("1. 一张责任表：模块唯一负责人、双方提供的接口/样例、联调参与方及验收证据。","1. 责任分组与对接矩阵已形成，见 [[审查_planning_middle_demo指标与系统可用性_2026-10-26]]；平台方继续落实具体承接人、端点及联调材料。")
        updates[p]=old
    elif p.name.startswith("方案_"):updates[p]=design
    else:updates[p]=review
for p,b in originals.items():
    current=p.read_bytes()
    normalized=updates[p].replace("\r\n","\n").replace("\r","\n")
    previous_attempt=updates[p].replace("\n","\r\n").encode("utf-8")
    allowed=(b,normalized.encode("utf-8"))
    if p.name=="00_项目入口.md":allowed=allowed+(previous_attempt,)
    if current not in allowed:raise RuntimeError("Concurrent change before write")
for p,s in updates.items():
    normalized=s.replace("\r\n","\n").replace("\r","\n")
    p.write_bytes(normalized.encode("utf-8"))
    if p.read_text(encoding="utf-8")!=normalized:raise RuntimeError("Readback mismatch")
receipt={"backup":meta["backup"],"report":report,"pages":12,"notes":[str(p) for p in updates],"readback":"exact","scope":"Responsibility/report revision only; no business-code changes; no new testing"}
(ROOT/"outputs/planning_middle_demo审查_20261026/responsibility_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(receipt,ensure_ascii=False,indent=2))
print(review[:700])

