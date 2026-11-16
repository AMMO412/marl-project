# 单平台智能体任务清单

来自实际下发的动态规划版本；每个槽位绑定计划版本、任务尝试和指令。计划为该尝试的全程估计，执行仅统计同次尝试的实际轨迹；整轮（含返航）另列。失败/取消/未完成尝试不作为完整执行差值。

同步到达 simultaneous_arrival：同父任务的协同槽位使用不同平台、开始时刻对齐（校验容差 0.001 s）；handover：交接标记。其他约束保留原编码，具体执行支持以规划器和运行层为准。

## UGV-09 · rover_09

| 顺序 | 子任务 / 父任务 | 类型 / 角色 | 机动起点 → 作业开始 → 结束 / s | 时间窗口 / s | 前置子任务 | 协同约束 / 同组成员 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | T1-S1 / T1 [计划 0 / 尝试 1] | T-RCN / search:1 | 4.652 → 24.841 → 144.841 | 0.0 → 220.0 | 无显式条目 | simultaneous_arrival / 同组：UGV-10:T1-S2；UGV-19:T1-S3；UGV-20:T1-S4 |

## UGV-10 · rover_10

| 顺序 | 子任务 / 父任务 | 类型 / 角色 | 机动起点 → 作业开始 → 结束 / s | 时间窗口 / s | 前置子任务 | 协同约束 / 同组成员 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | T1-S2 / T1 [计划 0 / 尝试 1] | T-RCN / search:2 | 1.781 → 24.841 → 144.841 | 0.0 → 220.0 | 无显式条目 | simultaneous_arrival / 同组：UGV-09:T1-S1；UGV-19:T1-S3；UGV-20:T1-S4 |

## UGV-19 · rover_19

| 顺序 | 子任务 / 父任务 | 类型 / 角色 | 机动起点 → 作业开始 → 结束 / s | 时间窗口 / s | 前置子任务 | 协同约束 / 同组成员 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | T1-S3 / T1 [计划 0 / 尝试 1] | T-RCN / search:3 | 10.288 → 24.841 → 144.841 | 0.0 → 220.0 | 无显式条目 | simultaneous_arrival / 同组：UGV-09:T1-S1；UGV-10:T1-S2；UGV-20:T1-S4 |

## UGV-20 · rover_20

| 顺序 | 子任务 / 父任务 | 类型 / 角色 | 机动起点 → 作业开始 → 结束 / s | 时间窗口 / s | 前置子任务 | 协同约束 / 同组成员 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | T1-S4 / T1 [计划 0 / 尝试 1] | T-RCN / search:4 | 0.0 → 24.841 → 144.841 | 0.0 → 220.0 | 无显式条目 | simultaneous_arrival / 同组：UGV-09:T1-S1；UGV-10:T1-S2；UGV-19:T1-S3 |

## 本计划未分配子任务的平台

U1（rover_01）、U2（rover_02）、UGV-03（rover_03）、UGV-04（rover_04）、UGV-05（rover_05）、UGV-06（rover_06）、UGV-07（rover_07）、UGV-08（rover_08）、UGV-11（rover_11）、UGV-12（rover_12）、UGV-13（rover_13）、UGV-14（rover_14）、UGV-15（rover_15）、UGV-16（rover_16）、UGV-17（rover_17）、UGV-18（rover_18）、TANK-21（rover_21）、TANK-22（rover_22）、TANK-23（rover_23）、TANK-24（rover_24）、TANK-25（rover_25）、TANK-26（rover_26）、TANK-27（rover_27）、TANK-28（rover_28）、TANK-29（rover_29）、TANK-30（rover_30）、PLANE-31（rover_31）、PLANE-32（rover_32）、PLANE-33（rover_33）、PLANE-34（rover_34）、PLANE-35（rover_35）、PLANE-36（rover_36）、PLANE-37（rover_37）、PLANE-38（rover_38）、PLANE-39（rover_39）、PLANE-40（rover_40）、U3（rover_41）、U4（rover_42）、WING-43（rover_43）、WING-44（rover_44）、WING-45（rover_45）、WING-46（rover_46）、WING-47（rover_47）、WING-48（rover_48）、WING-49（rover_49）、WING-50（rover_50）

## 未分配子任务与计划冲突

未分配：[]

冲突：[]
