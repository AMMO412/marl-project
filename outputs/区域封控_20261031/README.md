# 区域封控（T-SEC）实现记录 · 2026-10-31

依据：[无人集群编队五类任务定义](../../资料/需求与任务/无人集群编队五类任务定义_1028.docx) 2.2 节。
实现与参数说明：[区域封控任务_20261031.md](../../docs/区域封控任务_20261031.md)。

## 本轮交付

| 位置 | 内容 |
| --- | --- |
| `planning_middle_demo/containment_geom.py` | 边界弧长分段、占位点、覆盖统计（规划层与执行层共用） |
| `planning_middle_demo/interop/templates.py` | T-SEC 按 `roles` 拆成 边界段 / 通道哨位 / 机动拦截 / 预备队 |
| `planning_middle_demo/behaviors.py` | `ContainmentBehavior`：监视→警告→拦阻→处置 + 在岗巡视 + 逐项判定 |
| `planning_middle_demo/interop/scenarios/area_containment.*` | 4.1 样例：集结待机区 → 140×90 m 封控区，5 台平台，2 未授权 + 1 授权目标 |
| `planning_middle_demo/workbench/containment.js` | 封控视图：全程/封控区镜头、控制画面、指标、目标闭合、时间线 |
| `planning_middle_demo/tests/test_containment.py` | 20 项测试（几何/分解/执行/巡视/回放/样例一致性） |

## 场景与视图

- **场景链路**：集结待机区（约 150–220 m 外）→ 4.2 计划路径 → 到达占位点
  （T+23 s `control_established`）→ 封控时段 180 s → 判定与回放。
- **在岗巡视**：占位组沿自己负责的边界段来回巡视（限速 2 m/s），门哨在通道口
  横向游走，机动组在待机点小圈待机；不再“钉在原地”。覆盖率因此是随时间变化的
  真实值，而不是一个固定站位算出来的常数。
- **工作台**：演示总览顶部有两个页签——**全局分配 / 区域封控**，同一轮运行、
  同一时间轴（切换时时刻互相同步）。只含一个封控作业的运行默认打开"区域封控"
  页签；不再有独立的封控路由，也没有"数据来源"下拉。

## 验证结果（本地仿真）

命令：

```powershell
cd planning_middle_demo
python -m interop.cli demo `
  --message interop/scenarios/area_containment.message.json `
  --formation interop/scenarios/area_containment.formation.json `
  --out ..\outputs\interop_demo\containment_run15 `
  --motion real --behavior --max-ticks 320
```

工作台运行 `workbench_20261031_161356_779332`（界面口径）：

| 指标 | 值 |
| --- | --- |
| 判定 | succeeded |
| 控制建立 / 结束 | 23 s / 203 s |
| 未授权接近 / 进入 | 2 / 0（漏控率 0） |
| 拦阻 | 1 次尝试、1 次成功（T+56 s） |
| 警告 | 2 次，有效撤离 1 次 |
| 授权放行 | 1 次（未误拦） |
| 边界监视覆盖率 | 0.61（巡视中随时间起伏） |
| 持续占位率 | 0.94 |
| 平均响应时间（发现→指派拦阻） | 1.0 s |

测试：`python -m unittest tests.test_containment` 20/20 通过；全量 192 项中除
并行会话正在改写的 T-ASL 用例 `test_rejects_asl` 外无失败。

## 截图

- [演示总览 · 全局分配页签](总览_全局分配页签.png)
- [演示总览 · 区域封控页签（T+70 s）](总览_区域封控页签.png)
- [封控区近景：巡视与处置（T+130 s）](封控区_巡视与处理.png)

## 边界

本地行为状态机 + 4.1 输入的回放，不含火力/毁伤；识别按输入授权标记，
误拦与传感器遮挡未建模；未接真实平台、ROS、Gazebo，不作为联调成功证明。
