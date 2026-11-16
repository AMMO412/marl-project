# 规划与执行主程序

当前融合版由 `interop/` 的统一规划层和同目录执行基座组成；默认展示为 `workbench/` 浏览器工作台。启动、当前能力和结果位置统一见 [工程入口](../README.md)，接口契约详见 [interop 说明](interop/README.md)。

## 调用链

```text
workbench_server / desktop_workflow
  → workbench_browser / workbench_task_editor / workbench_target_editor
  → interop.message / templates / gate / scheduler / routing
  → coordinator_v2 → mock_fleet → behavior_runtime / behaviors / motion
  → trajectory_v2 / execution_evidence / chain_trace
  → workbench 浏览器地图、报告、运动导出与追溯
```

| 文件/目录 | 当前职责 |
| --- | --- |
| `interop/scenarios/` | 软件任务消息和编成模板；运行时派生输入保留于每轮目录 |
| `interop/urban_maps/` | 随包三张城市地图；规划与显示共享变换后的几何 |
| `assets/` 与 `../资料/接口说明/` | 城市/SDF/建筑资产，保留原路径 |
| `workbench_live.py` / `workbench_sessions.py` | 实时暂停、继续、结束保存和同编号续算发布 |
| `workbench_replay_editor.py` | 恢复暂停时刻、锁定完成项、应用未完成内容变更 |
| `workbench/` | HTML/CSS/JS；显示实际记录，近期拖尾默认 10 秒 |
| `tests/` | 本地回归；`fixtures/` 是历史基座输入，不是软件场景菜单 |
| `outputs/` | 命令行、历史运行和专项诊断；本轮整理未改写其中结果 |

`scenario.json` 是派生的执行视图，原始 4.1 消息与编成表仍是业务输入依据。运行结果应区分任务终态、返航终态、计划指标和执行指标；手动结束只保留部分结果。

## 常用命令

在本目录执行：

```powershell
py -3 -X utf8 workbench_server.py --open
py -3 -X utf8 -m interop.cli --help
py -3 -X utf8 -m unittest discover -s tests -q
```

工作台默认写 `../desktop_app/dist/data/runs/`；若该目录不存在则回退本目录 `outputs/`，环境变量 `MARL_WORKBENCH_OUTPUTS` 优先。命令行输出遵从 `--out`。

旧 `README_v2.md` 保留为兼容跳转；其早期基座长文已作为历史原件归档，不能据旧的六场景、瞬移或中性任务限制操作当前工作台。本地模拟不代表外部 ROS2/Gazebo/UE5 联调完成。
