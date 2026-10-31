# 同输入对比：unified / 基座 planner_v2 / M2

审计口径：时间窗、平台时段重叠、能力、目标禁入区、路径穿禁入区、依赖；协同对齐单列。能耗/风险绝对值不跨后端比较。
基座结果是调整过电量、效率和工作量的离线对比实验；排名仅适用于本表实验设定，不代表同参数运行验证或外部执行。

## area_recon（4 平台 / 3 任务）

| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s | 里程 / m | 模型风险 | 模型能耗 | 硬违规 | 能力缺口 | 协同未对齐 | 路径几何 | 规划耗时 / ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| timeliness | unified | 3/3 | 6 | 0 | 183.6 | 342 | 0.00 | 117.6 | 0 | 0 | 0 | 有 | 6163 |
| timeliness | base_v2 | 3/3 | 4 | 0 | 177.0 | — | — | — | 0 | 1 | 0 | 无 | 173 |
| timeliness | m2 | 3/3 | 7 | 0 | 182.1 | 420 | 0.00 | 133.8 | 1 | 0 | 1 | 有 | 13709 |
| energy | unified | 3/3 | 6 | 0 | 277.3 | 260 | 0.00 | 87.0 | 0 | 0 | 0 | 有 | 26 |
| energy | base_v2 | 3/3 | 4 | 0 | 177.0 | — | — | — | 0 | 1 | 0 | 无 | 16 |
| energy | m2 | 3/3 | 7 | 0 | 276.0 | 311 | 0.00 | 109.2 | 1 | 0 | 1 | 有 | 13026 |

- base_v2 / timeliness：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功
- base_v2 / energy：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功

<details><summary>m2 / timeliness 的违规明细</summary>

- FORCE_LIMIT：任务 T1 用了 4 台，超过 max_units=3

</details>

<details><summary>m2 / energy 的违规明细</summary>

- FORCE_LIMIT：任务 T1 用了 4 台，超过 max_units=3

</details>


## capability_gap（6 平台 / 4 任务）

| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s | 里程 / m | 模型风险 | 模型能耗 | 硬违规 | 能力缺口 | 协同未对齐 | 路径几何 | 规划耗时 / ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| timeliness | unified | 3/4 | 5 | 2 | 130.2 | 326 | 0.00 | 142.7 | 0 | 0 | 0 | 有 | 5862 |
| timeliness | base_v2 | 3/4 | 4 | 1 | 198.0 | — | — | — | 0 | 3 | 0 | 无 | 68 |
| timeliness | m2 | 3/4 | 5 | 2 | 130.2 | 326 | 0.00 | 142.7 | 0 | 0 | 1 | 有 | 12880 |
| energy | unified | 3/4 | 5 | 2 | 129.6 | 310 | 0.00 | 135.4 | 0 | 0 | 0 | 有 | 20 |
| energy | base_v2 | 3/4 | 4 | 1 | 198.0 | — | — | — | 0 | 3 | 0 | 无 | 67 |
| energy | m2 | 3/4 | 5 | 2 | 129.6 | 310 | 0.00 | 135.4 | 0 | 0 | 1 | 有 | 12956 |

- base_v2 / timeliness：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功
- base_v2 / energy：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功


## mixed_inspection（7 平台 / 4 任务）

| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s | 里程 / m | 模型风险 | 模型能耗 | 硬违规 | 能力缺口 | 协同未对齐 | 路径几何 | 规划耗时 / ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| timeliness | unified | 4/4 | 9 | 0 | 210.0 | 885 | 3.54 | 265.7 | 0 | 0 | 0 | 有 | 144 |
| timeliness | base_v2 | 4/4 | 5 | 0 | 291.0 | — | — | — | 0 | 3 | 0 | 无 | 49 |
| timeliness | m2 | 4/4 | 10 | 0 | 210.0 | 1080 | 3.86 | 312.9 | 1 | 0 | 1 | 有 | 13114 |
| energy | unified | 4/4 | 9 | 0 | 437.3 | 809 | 3.54 | 204.6 | 0 | 0 | 0 | 有 | 148 |
| energy | base_v2 | 4/4 | 5 | 0 | 291.0 | — | — | — | 0 | 3 | 0 | 无 | 49 |
| energy | m2 | 4/4 | 10 | 0 | 492.6 | 822 | 3.86 | 217.2 | 0 | 0 | 2 | 有 | 13105 |

- base_v2 / timeliness：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功
- base_v2 / energy：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功

<details><summary>m2 / timeliness 的违规明细</summary>

- FORCE_LIMIT：任务 T4 用了 3 台，超过 max_units=2

</details>


## patrol_checkpoint（6 平台 / 3 任务）

| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s | 里程 / m | 模型风险 | 模型能耗 | 硬违规 | 能力缺口 | 协同未对齐 | 路径几何 | 规划耗时 / ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| timeliness | unified | 3/3 | 4 | 0 | 300.0 | 424 | 1.64 | 159.2 | 0 | 0 | 0 | 有 | 208 |
| timeliness | base_v2 | 3/3 | 4 | 0 | 292.0 | — | — | — | 2 | 2 | 0 | 无 | 31 |
| timeliness | m2 | 3/3 | 7 | 0 | 300.0 | 649 | 0.77 | 276.4 | 2 | 0 | 0 | 有 | 13098 |
| energy | unified | 3/3 | 4 | 0 | 434.8 | 592 | 2.22 | 137.6 | 0 | 0 | 0 | 有 | 250 |
| energy | base_v2 | 3/3 | 4 | 0 | 292.0 | — | — | — | 2 | 2 | 0 | 无 | 30 |
| energy | m2 | 3/3 | 7 | 0 | 504.6 | 597 | 2.22 | 191.8 | 0 | 0 | 1 | 有 | 13183 |

- base_v2 / timeliness：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功
- base_v2 / energy：基座 planner_v2：motion=real；计划层不含路径几何，不提供里程；对比实验固定work_rate=1、电量=1000000、work=duration×crew。此归一化实验不等同于to-v2实际运行，不能据此宣称运行参数已对齐或执行成功

<details><summary>base_v2 / timeliness 的违规明细</summary>

- WINDOW：112.0–292.0 超出 120.0–900.0
- WINDOW：112.0–292.0 超出 120.0–900.0

</details>

<details><summary>m2 / timeliness 的违规明细</summary>

- FORCE_LIMIT：任务 T1 用了 3 台，超过 max_units=1
- FORCE_LIMIT：任务 T2 用了 2 台，超过 max_units=1

</details>

<details><summary>base_v2 / energy 的违规明细</summary>

- WINDOW：112.0–292.0 超出 120.0–900.0
- WINDOW：112.0–292.0 超出 120.0–900.0

</details>


## 本轮反复出现的差异（源码可见）

| 后端 | 现象 | 依据 |
| --- | --- | --- |
| 基座 planner_v2 | 不读 4.1 的 required_capabilities，只看 payload/sensor/altitude | `contracts_v2.check_scenario_v2` 的平台只允许 robot_no/pos；`planner_v2.feasible` 无能力编码 |
| 基座 planner_v2 | 排程检查完工截止，但不检查窗口下界 | `planner_v2.plan` 只判 `e > window[1]`；对比中出现 112 s 先于 120 s 窗口开工 |
| 基座 planner_v2 | 计划层不含路径几何，无法静态验证避障 | `Assignment` 只有 start/end/travel/dur |
| M2 | 区域/路线拆分段数不受 `max_units` 约束 | `templates._decompose_rcn/_decompose_ptl` 只按可拆平台数切分 |
| M2 | `simultaneous_arrival` 只保证同组不同平台，不保证同时开始 | M2 README 的边界自述；对比中协同未对齐组数 > 0 |
| unified | 严格 schema 0.3、能力闸门、max_units 上限、协同组统一开始、路径穿障碍审计 | `interop` 实现 |

## 读法

- 硬违规优先于 makespan：一个更快的计划如果穿建筑/超窗口，不认为更好。
- 基座计划层没有路径几何，`路径几何=无` 表示无法静态验证避障、里程记 `—`；这不是“零里程”，也不能据此判它更省。
- `能力缺口` 单列：基座 middle-demo/v2 契约没有 4.1 的能力编码，只有 payload/sensor/altitude，这一列反映契约差异，不是算法违规。
- M2 的 `simultaneous_arrival` 只保证同组不同平台，不保证同时开始；统一层把开始时刻对齐，所以这一列会不同。
- 任务拆分超过 `max_units` 计入硬违规（M2 的区域/路线拆分不读该上限）。
- 能耗/风险是各自模型值，不能跨后端排名；表中的模型风险/能耗只用于同一后端切换目标时对照。
- `compare.json` 里的 best 排序是：硬违规 → 能力缺口 → 未落实任务 → 未分配 → makespan。也就是“先满足 4.1 契约，再比快慢”；只看 makespan 的结论会不同，报告里同时给出了原始列。
