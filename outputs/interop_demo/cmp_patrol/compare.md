# 同输入对比：unified / 基座 planner_v2 / M2

审计口径：时间窗、平台时段重叠、能力、目标禁入区、路径穿禁入区、依赖；协同对齐单列。能耗/风险绝对值不跨后端比较。

## INTEROP-container_00（6 平台 / 3 任务）

| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s | 里程 / m | 硬违规 | 能力缺口 | 协同未对齐 | 路径几何 | 规划耗时 / ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| timeliness | unified | 3/3 | 3 | 1 | 300.0 | 277 | 0 | 0 | 0 | 有 | 7680 |
| timeliness | base_v2 | 3/3 | 4 | 0 | 292.0 | — | 2 | 2 | 0 | 无 | 184 |
| timeliness | m2 | 3/3 | 6 | 1 | 300.0 | 495 | 2 | 0 | 0 | 有 | 13654 |
| energy | unified | 3/3 | 3 | 1 | 300.0 | 330 | 0 | 0 | 0 | 有 | 6043 |
| energy | base_v2 | 3/3 | 4 | 0 | 292.0 | — | 2 | 2 | 0 | 无 | 31 |
| energy | m2 | 3/3 | 6 | 1 | 480.3 | 330 | 0 | 0 | 0 | 有 | 13666 |

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


## 读法

- 硬违规优先于 makespan：一个更快的计划如果穿建筑/超窗口，不认为更好。
- 基座计划层没有路径几何，`路径几何=无` 表示无法静态验证避障、里程记 `—`；这不是“零里程”，也不能据此判它更省。
- `能力缺口` 单列：基座 middle-demo/v2 契约没有 4.1 的能力编码，只有 payload/sensor/altitude，这一列反映契约差异，不是算法违规。
- M2 的 `simultaneous_arrival` 只保证同组不同平台，不保证同时开始；统一层把开始时刻对齐，所以这一列会不同。
- 任务拆分超过 `max_units` 计入硬违规（M2 的区域/路线拆分不读该上限）。
- 能耗/风险是各自模型值，不能跨后端排名；只在同一后端内看目标切换效果。
