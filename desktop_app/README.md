# MARL界面预览（桌面演示端）

## 定位

这是规划中间层的 **本地可视化演示软件**。主窗口保留原有桌面布局，任务视图复用本地工作台的真实运行回放；真实平台展示目标是接入 Gazebo、在 UE5 中呈现，本软件不代表真实平台联调完成。

## 直接运行

已构建版本：

```text
desktop_app\dist\MARL界面预览.exe
```

首次启动会自动寻找并启动本机 Python 后端；已存在的兼容后端会被复用。关闭程序时只终止本程序启动的后端。

## 构建

依赖：

- Windows 10/11 x64
- .NET Framework 4.8（系统自带 `csc.exe`）
- WebView2 Evergreen 运行时
- Python 3.14（开发期）；发布包使用便携 Python

```powershell
cd desktop_app
.\build.cmd
```

输出：`desktop_app\dist\MARL界面预览.exe`，以及 WebView2 DLL/许可证。

## 验证

```powershell
desktop_app\dist\MARL界面预览.exe --verify <输出目录>
desktop_app\dist\MARL界面预览.exe --live-verify <输出目录>
```

- `--verify`：原生布局、属性、回放控制、图层等静态检查，并生成截图。
- `--live-verify`：等待后端和任务视图就绪，载入真实运行，生成主视图/任务/平台截图和 `live-verification.txt`。

## 便携发布包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File desktop_app\packaging\build_release.ps1
```

生成 `desktop_app\release\MARL界面预览\` 和 `MARL界面预览_v0.5.0.zip`，包含：

- `runtime/`：Python 3.14.7 embeddable
- `app/planning_middle_demo/`：后端与工作台
- `app/资料/接口说明/`：SDF 与模型
- `data/runs/`：随包样例运行
- `lib/webview2/`：WebView2 SDK（DLL 与 exe 同目录）
- `LICENSES/`、`VERSION.txt`、`启动说明.txt`、`SHA256SUMS.txt`

## 目录

```text
desktop_app/
├─ src/                 # C# 源码
│  ├─ DesktopPreview.cs # 原布局、场景、属性、日志
│  ├─ DesktopApi.cs     # HTTP API、模型、后端进程管理
│  └─ DesktopIntegration.cs # WebView2、任务视图、原生面板联动
├─ lib/webview2/        # WebView2 SDK
├─ packaging/           # 发布包构建
├─ build.cmd / build.ps1
├─ dist/                # 构建产物（不提交）
└─ release/             # 发布产物（不提交）
```

## 当前边界

- 主演示场景：T-SEC 区域封控。
- 其他四类任务有场景入口和通用任务/平台列表；专用视图后续接入。
- 原生场景页是“布局示意”；任务视图显示真实运行记录。
- 未接 ROS2/Gazebo/UE5；本地演示结果不等于平台验收结果。
- 未签名 exe 可能触发 SmartScreen。

## 关键接口

- 后端：`GET /api/catalog`、`GET /api/desktop/run/<id>`、`POST /api/runs`。
- 页面桥：`window.MarlDesktop`（`selectRun`、`selectTask`、`play`、`pause`、`setTime`、`fit`、`startReplay`）。
- 数据目录：`MARL_WORKBENCH_OUTPUTS`。
