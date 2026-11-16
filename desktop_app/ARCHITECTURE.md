# 原生桌面兼容端架构说明

核对日期：2026-11-16。默认浏览器工作台的入口与数据位置见 [工程 README](../README.md)；本文仅说明保留的 C# 端。

## 组件

```text
MARL界面预览.exe（WinForms / .NET Framework 4.8）
├─ 原生主窗口：菜单、工具栏、项目树、属性、状态栏
├─ 场景视图 / 平台列表 / 运行记录
│  └─ 仅地图画布由 WebView2 绘制，原生缩放/图层/播放条控制
├─ 原生配置窗口：常用运行参数、4.1 消息 JSON、编成表 JSON、校验
├─ 原生日志 / 事件筛选与跳转 / 真实输出文件
├─ 原生报告 / 模板目标对照 / 项目说明窗口
├─ BackendSupervisor：兼容性探测、启动、健康检查、关闭回收
└─ DesktopApi：有超时的本地 HTTP 请求、错误解析、文件下载
    └─ workbench_server.py → desktop_workflow.py → 既有解析器与执行层
```

## 输入与运行

1. 后端探测 8766–8771，要求 `desktop_bridge`、`desktop_workflow`、
   `urban_benchmark_scenarios` 和实际版本能力检查；只回收本窗口自己启动的服务。
2. 原生配置窗口读取模板，或读取历史记录的输入快照；没有快照的旧轮次明确标记模板回退。
3. 校验复用 `validate_config` 与 `interop.message.parse_message`，不把契约有效当作任务执行成功。
4. 新运行先冻结草稿，再创建独立目录，保留 `desktop_input.json`、`input_message.json`、`input_formation.json`、请求、日志和哈希；不覆盖模板或历史记录。
5. 原生窗口跟踪创建接口返回的实际运行编号；报告、事件和文件都绑定该编号。快速切换记录时忽略旧请求的迟到响应。
6. 任务仍由原有融合规划/执行层处理，本轮不更改规划算法。4.1 消息是业务输入的权威来源。

## 场景同步

`desktop_bridge.js` 隐藏网页导航，只保留所选任务的画布。页面脚本处理绘图与摄像机，桌面负责其余界面。

桥提供 `selectRun`、`selectTask`、`play/pause`、`setTime`、`setSpeed`、`fit`、`zoom`、`setLayer`、`focusPlatform`、`getState` 等方法。运行切换串行载入，回传实际已载入的编号；原生端忽略旧轮次的场景消息和过期位置响应。

回放时长采用完整运行记录（包括已记录的返程），时间、任务进度和图层状态回传原生控件。图层菜单由主窗口持有，关闭下拉菜单不释放实例。图例使用同一绘图器提供的平台小图标；网格坐标复用同事版方法。截图导出合成原生窗口与 WebView2 画布。

## 桌面接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/catalog` | 版本、能力、场景、运行历史和后台状态 |
| `GET /api/desktop/run/<id>?t=` | 原生任务/平台/属性的指定回放时刻视图 |
| `GET /api/desktop/config?scenario=&run=` | 模板或历史原始输入及来源 |
| `POST /api/desktop/editor-metadata` | 返回五类任务目录、目标插槽和当前目标展开结果 |
| `POST /api/desktop/editor-targets` | 将红方目标面板写回原 4.1 参数，不启动运行 |
| `POST /api/desktop/validate` | 校验草稿，不创建运行目录 |
| `POST /api/desktop/runs` | 冻结输入并创建新轮次 |
| `GET /api/desktop/details/<id>` | 报告、manifest、计划与文件清单 |
| `GET /api/desktop/events/<id>` | 完整事件记录，供原生筛选/定位 |
| `GET /artifacts/<id>/<name>` | 白名单产物下载，供预览和完整另存 |

保留既有完整回放、目标对照与源码说明接口。桌面请求仍遵守后端本地访问与 Origin 检查，新增入口不接受任意代码、命令或文件路径。

“全链路追溯”从“输出文件”“运行记录”或“工具”菜单打开独立 WebView2 窗口，加载 `/artifacts/<id>/chain_viewer.html`，不替换场景地图。`desktop_workflow_version=12` 起，同一运行目录还保存 `chain_summary.json`、`chain_verification.json`、`chain_raw.json`、`initial_config.json`、`final_config.json`、`ros2_plan_node.py` 与 `archive/`。追溯页从实际协调器收发记录生成，不按最终报告反推；完整性校验不表示任务成功或外部平台验收。

## 数据与验证

当前默认运行记录在 `desktop_app/dist/data/runs/`；该目录不存在时回退 `planning_middle_demo/outputs/`，`MARL_WORKBENCH_OUTPUTS` 优先。WebView2 用户目录及回退策略见 `DesktopIntegration.cs`。程序诊断日志在 exe 同目录的 `desktop.log`，界面底部显示本次操作与后端日志。

2026-11-09：地图浏览器缓存改为独占文件锁分配的可复用槽位，运行中的窗口各用不同目录和浏览器进程。优先 `%LOCALAPPDATA%/MARL界面预览/WebView2Profiles/slot-XX/profile`，不可写时回退到 exe 同目录 `data/webview2-profiles/`，再回退系统临时目录；不使用旧版共用的 `data/webview2/`。关闭释放槽位，不删除缓存或运行记录。初始化有重入与关闭检查，遇到已知缓存占用/访问错误时重建控件并换槽位，最多三次。

地图页面在脚本未完整加载时最多重载两次，失败资源写入诊断日志。本地 HTTP 服务扩大并发连接等待队列，桌面要求后端兼容版本 7。`--webview-verify` 检查实际浏览器目录、独占锁、初始化重入和页面就绪；双进程并行及一次脚本 503 恢复证据见 `outputs/webview_busy_20261109/`。

`--verify` 检查原生结构和空载状态；`--live-verify` 检查真实地图与原生交互；`--run-verify` 先经桌面入口创建运行。证据见 `outputs/native_workflow_20261106/`，能力及未完成项见 [NATIVE_FEATURES.md](NATIVE_FEATURES.md)。

当前仍是本地开发版。五类任务专用表单与红方目标集中编辑已完成；平台仍主要使用通用字段表。浏览器工作台已能暂停时刻续算、回放中途编辑和未完成任务动态改派；原生桌面兼容入口当前仍以复制配置后新建运行为主。全部场景工况和目标机交付验收未完成。地图仍依赖 WebView2，不代表 C# 原生绘图引擎。
