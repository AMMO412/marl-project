# 测试夹具

`base_scenarios/`：执行基座与导航的历史输入，用于回归，不是软件场景菜单。
`interop_legacy/`：接口转换拒绝、计划审计等最小历史样例，仅供测试。

当前软件任务模板在 `interop/scenarios/`，还使用 `interop/benchmark_scenarios.py` 生成复杂基准；实际可选场景以 `workbench_server.ALL_SCENARIOS` 为准，不再写成固定六组。内部测试可用瞬移隔离状态机，产品创建运行只接受逐步运动。
