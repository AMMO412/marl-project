# 演示验证记录（2026-11-06）

## 结论

- 全量 Python 测试：**263 项，通过 263，跳过 2，0 失败/0 错误**（见 `python-tests.log`）。
- 桌面端静态验证：通过，截图在 `static/`。
- 桌面端实时验证：WebView2 已连接本地后端，载入真实 T-SEC 运行并播放；截图在 `live/`。
- 便携包：包含 Python 3.14.7 embeddable、应用、SDF/模型、样例运行、WebView2 SDK；在未使用系统 Python 的情况下启动并验证通过。

## 运行信息

| 项 | 值 |
| --- | --- |
| 分支 | `work/20261106-demo` |
| 检查点 | `e9746aa` |
| 标签 | `demo-baseline-20261106` |
| 当前演示版本 | v0.5.0 |
| 当前运行 | `workbench_20261106_163934_573502` |
| 运行时长 | 229.0 s |
| 任务/平台 | 1 / 50 |
| 后端 | 本地 `workbench_server.py`，`desktop_bridge=True` |

## 截图

- `live/live-preview.png`：原生布局 + 任务视图真实回放。
- `live/live-tasks.png`：任务列表真实数据。
- `live/live-platforms.png`：平台列表真实数据。
- `static/preview.png`：静态布局验证。
- `static/tasks.png`：任务页签。

## 发布包

```text
desktop_app\release\MARL界面预览_v0.5.0.zip
大小：14,347,838 字节（约 13.7 MB）
SHA-256：E632BF1BFCC9811A37232FE5FB3D5A01D92253D50DA287812586F976E3A5A538
```

解压后目录约 45 MB。启动方式：双击 `MARL界面预览.exe`。

## 已验证

- 双击启动，自动选择空闲端口并启动便携 Python 后端。
- 复用现有兼容后端；关闭程序后本程序启动的后端退出（8767 端口释放）。
- T-SEC 真实运行、任务视图回放、播放/暂停/时间轴、任务/平台/属性/日志联动。
- 运行记录、项目树、任务和平台数据来自真实运行。
- 关于页明确说明本地演示与 Gazebo/UE5 目标边界。

## 未验证/限制

- 其他四类任务的专用视图未完成；当前为通用入口/列表。
- 未接 ROS2/Gazebo/UE5，真实平台指标未测。
- WebView2 Evergreen 运行时为本机已有；正式交付需检测或内置 Fixed Version。
- 未签名 exe 可能触发 SmartScreen。
- 本次为单次运行验证，不是统计结论。

## 复现

```powershell
cd D:\Desktop\MARL项目\planning_middle_demo
py -3.14 -B -m unittest discover -s tests -q

cd D:\Desktop\MARL项目
desktop_app\dist\MARL界面预览.exe --live-verify <可写目录>
```

发布包构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File desktop_app\packaging\build_release.ps1
```
