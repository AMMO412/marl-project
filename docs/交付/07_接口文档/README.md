# 接口文档（骨架）

## 文档控制

| 项 | 内容 |
| --- | --- |
| 文档编号 | 07 |
| 版本 | v0.5（骨架） |
| 日期 | 2026-11-06 |
| 状态 | 待逐项核对 |

## 目录大纲

1. 接口总览与版本
2. 4.1 输入消息 Schema
3. 4.2 计划输出 Schema
4. 编成表 Schema
5. 规划中间层内部模块接口
6. 工作台 HTTP API
7. 桌面端 JS 桥
8. 配置项 Schema
9. 错误码与 HTTP 状态
10. 版本兼容
11. 示例请求/响应
12. 未实现接口与后续计划

## 当前接口清单

### 工作台 HTTP

- `GET /api/catalog`
- `GET /api/runs/<run_id>`
- `GET /api/desktop/run/<run_id>?t=<seconds>`
- `GET /api/source/<source_id>`
- `GET /artifacts/<run_id>/<file>`
- `POST /api/runs`
- `POST /api/compare`

### 桌面端 JS 桥

- `window.MarlDesktop.getState()`
- `selectRun(runId)`
- `selectTask(taskId)`
- `navigate(page)`
- `play()` / `pause()`
- `setTime(seconds)`
- `setLayer(name, visible)`
- `fit()`
- `startReplay(taskId, seconds)`

### 环境变量

- `MARL_WORKBENCH_OUTPUTS`：覆盖运行记录目录。

## 待补内容

- 每个接口的请求/响应字段表。
- 错误码表。
- 实际示例（从运行记录提取）。
- 与 4.1/4.2 原文逐条对照。
