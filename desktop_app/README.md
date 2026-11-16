# C# 原生桌面兼容入口

当前默认界面为浏览器工作台，启动见 [工程入口](../README.md)。本目录保留 WinForms / .NET Framework 4.8 桌面端，场景画布由 WebView2 复用当前 JavaScript 绘图器；源码和构建依赖保留。

## 运行与构建

已有程序：`desktop_app/dist/MARL界面预览.exe`。需要源码构建时在工程根目录执行：

```powershell
.\desktop_app\build.cmd
```

依赖 Windows、.NET Framework 4.8、WebView2 运行时和本机 Python；DLL 与许可证保留在 `lib/webview2/` 和构建产物目录。浏览器工作台本身不需要 WebView2。

## 当前能力

原生配置、五类任务专用表单、红方目标编辑、运行/平台筛选、回放、高度曲线、文件预览/另存、运行对比与独立追溯窗口仍保留。原生端主要使用修改草稿后新建运行；实时暂停编辑和回放中途同编号续算的完整操作在浏览器工作台提供。

地图显示实际已记录轨迹，近期拖尾默认 10 秒；失联、返航、任务与命令边界保留。界面能打开历史记录不代表使用当前算法复跑。

运行目录从后端读取，当前默认 `dist/data/runs/`，环境变量 `MARL_WORKBENCH_OUTPUTS` 可覆盖。数据、回收站、续算版本和正在使用的服务不作为本次精简对象。

## 开发验证与打包

`--verify` 检查结构；`--live-verify` 检查真实地图与交互；`--run-verify` 会新建一轮。各项 `*Verification.cs` 是可重复检查源码，不按“旧验证”删除。

打包脚本在 `packaging/`，会使用便携 Python、第三方许可证及成功样例。当前目录没有已核验的发布压缩包，不能按历史日期声称已有最新交付包。打包需单独验证，不在本轮清理中重建。

[原生能力边界](NATIVE_FEATURES.md) · [架构](ARCHITECTURE.md) · [运行文件用途](../docs/运行输出文件说明.md)

以上为本地开发工具，不表示真实 ROS2/Gazebo/UE5 联调或正式验收。
