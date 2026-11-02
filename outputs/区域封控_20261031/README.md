# 区域封控（T-SEC）实现记录 · 2026-10-31

依据：[无人集群编队五类任务定义](../../资料/需求与任务/无人集群编队五类任务定义_1028.docx) 2.2 节。
实现与参数说明：[区域封控任务_20261031.md](../../docs/区域封控任务_20261031.md)。

## 本轮交付

| 位置 | 内容 |
| --- | --- |
| `planning_middle_demo/containment_geom.py` | 边界弧长分段、占位点、覆盖统计（规划层与执行层共用） |
| `planning_middle_demo/interop/templates.py` | T-SEC 按 `roles` 拆成 边界段 / 通道哨位 / 机动拦截 / 预备队 / 空中监视 |
| `planning_middle_demo/behaviors.py` | `ContainmentBehavior`：监视→警告→拦阻→处置、在岗巡视、空中盘旋、逐项判定 |
| `planning_middle_demo/interop/scenarios/area_containment.*` | 4.1 样例：集结待机区 → 140×90 m 封控区；5 台地面 + 1 架无人机，2 未授权 + 1 授权目标 |
| `planning_middle_demo/workbench/containment.js` | 区域封控页签：全程/封控区镜头、控制画面、指标、目标闭合、时间线 |
| `planning_middle_demo/tests/test_containment.py` | 21 项测试（几何/分解/执行/巡视/空中监视/回放/样例一致性） |

## 场景与视图

- **兵力**：占位组 2 台、通道哨位 2 台、机动拦截组 1 台、**空中监视 1 架**
  （固定翼，爬升到 60 m 后绕封控区盘旋，参与边界监视覆盖）。
- **链路**：集结待机区（约 150–220 m 外）→ 4.2 计划路径 → 到达占位点
  （T+23 s `control_established`）→ 在岗巡视 + 空中盘旋 → 封控 180 s → 判定。
- **在岗巡视**：占位组沿自己负责的边界段来回巡视（限速 2 m/s），门哨在通道口
  横向游走，机动组在待机点小圈待机。
- **工作台**：“演示总览”顶部两个页签（全局分配 / 区域封控，同一时间轴）。
  两个视角都已去掉虚线：封控区实线边框、探测圈细实线、规划路径细实线，
  “全局分配”按“封控区 + 集结地”取景并对目标标当前状态、画拦阻连线；
  区域封控页签保留完整控制画面（指标、目标闭合、时间线）。
- **新建演示**：场景按“融合版（区域封控 / 五类任务 / 机动突击）+ 历史场景”分组，
  默认选中**区域封控演示**。

## 验证结果（本地仿真）

命令：

```powershell
cd planning_middle_demo
python -m interop.cli demo `
  --message interop/scenarios/area_containment.message.json `
  --formation interop/scenarios/area_containment.formation.json `
  --out ..\outputs\interop_demo\containment_run18 `
  --motion real --behavior --max-ticks 340
```

工作台运行 `workbench_20261102_111027_614168`（界面口径）：

| 指标 | 值 |
| --- | --- |
| 判定 | succeeded |
| 控制建立 / 结束 | 23 s / 203 s |
| 未授权接近 / 进入 | 2 / 0（漏控率 0） |
| 拦阻 | 1 次尝试、1 次成功（T+56 s） |
| 警告 | 2 次，有效撤离 1 次 |
| 授权放行 | 1 次（未误拦） |
| 边界监视覆盖率 | 0.68（含空中监视；随巡视/盘旋起伏） |
| 持续占位率 | 0.94 |
| 平均响应时间（发现→指派拦阻） | 1.0 s |

测试：`python -m unittest tests.test_containment` 21/21 通过；全量 198 项全部通过
（合并 T-ASL 后原 `test_rejects_asl` 已改为接受用例）。

## 截图

- [总览 · 全局分配页签（T+54 s 拦阻中）](总览_全局分配页签.png)
- [总览 · 区域封控页签（T+70 s，已去虚线）](总览_区域封控页签.png)
- [区域封控 · 机动途中（T+9 s，规划路径/探测圈均为实线）](区域封控_机动途中.png)
- [区域封控 · 封控在位（T+70 s）](区域封控_封控在位.png)
- [总览 · 封控区近景（T+120 s）](总览_封控区近景.png)
- [没有封控记录时的说明条](总览_缺封控数据说明.png)

## 边界

本地行为状态机 + 4.1 输入的回放，不含火力/毁伤；识别按输入授权标记，
误拦与传感器遮挡未建模；空中监视按 2D 投影，不建下视角足迹；未接真实平台、
ROS、Gazebo，不作为联调成功证明。
