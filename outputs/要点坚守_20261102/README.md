# 要点坚守（T-HLD）记录 · 2026-11-02

> 口径：**本地替身 + 行为状态机 + 4.1 输入回放**，不是真实平台 / ROS / Gazebo 联调。
> 效果类结论（反击、压制、击退）全部来自 `assessment.Adjudicator` 的**桩判定**，
> 标 `verified=false`，只作过程证据，不作战果。

## 1 本轮验证了什么

| 项 | 结果 | 数据来源 |
| --- | --- | --- |
| 4.1 样例可解析 / 可分解 / `to_v2_dict` 通过 `check_scenario_v2` | 是（4 个槽位：3 阵位 + 1 预备队） | `interop/scenarios/key_point_hold.*` |
| 4.2 产物齐全且字段不变 | `plan.json` / `assignments.csv` / `commands.csv` / `ros2_commands.txt` / `report.md` | [interop_demo/hold_run](../interop_demo/hold_run/report.md) |
| `commands` 只到 TRANSIT / HOLD / STOP | 是（HOLD 8、STOP 4、TRANSIT 10；STOP 全零） | 同上 `commands.csv` |
| 控制建立 | T+17 s，在位 3 台（下限 2） | `hold_result.metrics` |
| 至少 1 次"到位才撤"的轮换 | 2 次：P1 67→74 s、P2 117→126 s，均 `arrival_before_departure=true` | `hold_result.handovers` |
| 1 次增援（按敌我比触发） | 是：T+95 触发，T+104 到位（9 s，时限 60 s，准时） | `hold_result.reinforcements` |
| 撤离 | 坚守满 150 s → T+167 撤离 → T+180 到位（时限 45 s） | 时间线 `withdraw_started` / `withdrawn` |
| 抽象效果走桩判定 | 3 次反击 / 3 条 `effect_adjudicated`，`verified=false`，adjudicator=`constructed_assessment_stub` | `hold_result.effects` |
| 判定 | `succeeded`：控制保持率 100%、控制中断 0 s、最长观察中断 0 s、敌方进攻 3 次 / 突破 0 次、我方损失 0 | `hold_result.items` |
| 工作台页签 + 覆盖层 | 页签切换与时间同步正常，无 console 错误 | 见下方截图 |
| 单测 | `tests/test_hold.py` 41 项通过；全量 239 项通过（跳过 2） | `python -m unittest discover -s tests` |

## 2 截图

| 图 | 内容 |
| --- | --- |
| [工作台_要点坚守_120s.png](工作台_要点坚守_120s.png) | “要点坚守”页签 T+120 s：要点、3 个阵位（含朝向与在位编号）、2 条威胁扇区、在位甘特、逐项判定、桩判定清单、过程时间线 |
| [工作台_要点坚守_整页.png](工作台_要点坚守_整页.png) | 同上整页（含 6 项 KPI 与右侧面板全貌） |
| [工作台_全局分配覆盖层.png](工作台_全局分配覆盖层.png) | “全局分配”页签的要点覆盖层：要点菱形、阵位在位着色、威胁扇区、任务标记 |

## 3 运行记录

- 工作台运行（页签数据来源）：`planning_middle_demo/outputs/workbench_20261102_160316_596092/`
  （`normal` 模式、逐步运动、建筑绕障、行为层开启、规划器 `interop`，181 仿真秒）。
- 命令行 4.2 计划 + 完整运行链：`outputs/interop_demo/hold_run/`
  （`plan.json`、`assignments.csv`、`commands.csv`、`report.md`、`ros2_commands.txt`，
  以及 `run/{report.json,trace.jsonl,trajectory.html}`）。

复现命令（在 `planning_middle_demo/` 下）：

```powershell
python -m interop.tools.build_scenarios
python -m interop.cli demo `
  --message interop/scenarios/key_point_hold.message.json `
  --formation interop/scenarios/key_point_hold.formation.json `
  --out ..\outputs\interop_demo\hold_run --motion real --behavior --max-ticks 260
```

工作台：双击 `启动工作台.cmd` → “新建演示” → 选 **要点坚守演示（T-HLD）** → 运行；
落在“演示总览 / 要点坚守”页签，可切到“全局分配”对照机动与阵位。

## 4 不能从本记录推出的结论

- 不能作为真实平台、ROS 2 话题或 Gazebo 场景已验证的证据；
- 反击/压制/击退的 `succeeded` 是**桩判定**，不是战果，也不代表真实毁伤或压制效果；
- 控制权口径是"有效在位数量 + 阵位状态"的模型近似（1028 §2.5.2 明确覆盖状态不等于现实控制权）；
- 轮换/增援的及时性只反映本地运动模型下的时序，不含通信中断、识别误差与人为延误。
