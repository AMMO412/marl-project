# 工作台展示

主入口：<http://127.0.0.1:8766>。直接观看：[突击专项回放](http://127.0.0.1:8766/?source=behavior_20261028_verify&task=J4&view=spatial)。

- [突击：分阶段与成员轨道](task-assault-process-v2.png)
- [突击：近景运动与各成员执行位](task-assault-spatial-v2.png)
- [坚守：主班、接班与角色时间带](task-hold-process-v2.png)

工作台内可切换“动作详解 / 空间与避障”，也可切换完整的本轮并行记录和专项串行记录。专项数据直接读取用户指定的 `planning_middle_demo/outputs/behavior_20261028_verify/behavior_trace.json`；未改原始坐标、阶段事件与路径。原并行记录J4的集结点/执行点实际重合，界面明确提示，不制造展开运动。

88项测试及904个任务视图时刻检查通过；专项5190个位姿、165条事件、99条路径核对通过。验证证据在 `.work/workbench_task_clarity_20261028/`。本轮未重训、未重跑或改动执行策略。

此前 `workbench-*.png`、`task-*-large.png`、`preview.png` 等截图保留为展示演进记录，当前以本页前三张图和工作台为主。
