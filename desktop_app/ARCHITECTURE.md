# 桌面端架构说明

## 组件

```text
MARL界面预览.exe (WinForms / .NET Framework 4.8)
├─ 原生主窗口
│  ├─ 菜单/工具栏/项目树/文档页签/属性/日志/状态栏
│  ├─ 场景总览（原 T-SEC 画布，标注布局示意）
│  ├─ 任务列表 / 平台列表 / 运行记录
│  └─ 任务视图（WebView2）
├─ BackendSupervisor
│  ├─ 复用已存在的兼容后端
│  ├─ 否则选择空闲端口，启动 runtime/python.exe 或 py -3.14
│  ├─ 健康检查、日志、关闭回收
└─ DesktopApi
   ├─ GET /api/catalog
   ├─ GET /api/desktop/run/<id>?t=
   └─ POST /api/runs
```

## 数据流

1. 启动 → `BackendSupervisor` 探测 8766–8771。
2. 没有兼容后端 → 启动 `planning_middle_demo/workbench_server.py`。
3. `DesktopApi` 读取 catalog，填充场景下拉、运行记录、项目树。
4. 选中运行 → `GET /api/desktop/run/<id>` → 原生任务/平台/属性/日志。
5. 同时 WebView2 导航 `/ ?desktop=1`，`desktop_bridge.js` 隐藏网页导航并暴露 `window.MarlDesktop`。
6. 原生工具栏通过 `ExecuteScriptAsync` 控制页面：选运行、选任务、播放、暂停、时间、图层、适应视图。
7. 页面通过 `postMessage` 回传状态，原生状态栏显示仿真时钟。
8. 关闭 → 只终止本程序启动的后端和 worker。

## JS 桥

```js
window.MarlDesktop = {
  ready: true,
  getState(),
  selectRun(runId),
  selectTask(taskId),
  navigate(page),
  play(),
  pause(),
  setTime(seconds),
  setLayer(name, visible),
  fit(),
  startReplay(taskId, seconds)
};
```

`startReplay` 会轮询页面运行是否载入，然后选任务、跳到指定时刻并播放，避免“页面还没载入就开始播放”的时序问题。

## 后端接口

- `GET /api/catalog`：服务版本、能力标记 `features.desktop_bridge`、场景、运行记录、进程状态。
- `GET /api/desktop/run/<id>?t=`：桌面端精简视图，返回运行元信息、任务、平台、事件、限制说明；`t` 用于按回放时刻取平台位置。
- `GET /api/runs/<id>`：完整回放数据，供页面渲染。
- `POST /api/runs`：启动一次运行。

## 数据目录

- 开发期：默认 `planning_middle_demo/outputs`。
- 发布包：存在 `data/runs` 时通过 `MARL_WORKBENCH_OUTPUTS` 指向随包样例和用户运行。
- WebView2 用户目录：`%LOCALAPPDATA%\MARL界面预览\WebView2`；若被拒绝，回退到程序目录 `data\webview2`。
- 日志：当前显示在底部日志；发布包可扩展写 `logs\`。

## 边界

- 主演示聚焦 T-SEC；其他四类任务为通用入口。
- 原生场景总览为布局示意，不冒充运行结果。
- 未接 ROS2/Gazebo/UE5；本地演示不构成平台验收证据。
