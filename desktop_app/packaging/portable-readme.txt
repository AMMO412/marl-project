MARL 协同规划 · Windows x64 便携演示包

使用方法
1. 完整解压到本机可写目录，例如 D:\MARL演示。不要在压缩包内直接启动。
2. 双击“启动软件.cmd”。程序会检查环境；缺少 WebView2 时使用随包离线安装程序安装。
3. 如果提示缺少 .NET Framework 4.8，先运行 prerequisites\ndp48-x86-x64-allos-enu.exe，按提示完成安装或重启，再启动软件。
4. 可直接查看区域封控、要点坚守、巡逻、侦察四类成功样例；选择场景并点“运行”可生成新记录。

已包含 Python，无需额外安装 Python、WSL、MARLlib 或开发工具。
系统要求：Windows 10/11 x64，.NET Framework 4.8 或更新的 4.x 版本。缺少的运行环境安装程序已放在 prerequisites，可离线使用；系统或企业策略可能要求管理员权限。

文件与数据
- data\runs：随包样例和新运行。移动或备份时保留整个软件目录。
- app：后端、场景模板、地图和说明，必须保留。
- runtime：便携 Python，必须保留。
- prerequisites：微软官方离线运行环境安装程序。
- LICENSES：Python 与 WebView2 SDK 许可；微软运行环境许可由各安装程序提供。
- SAMPLES.json：随包样例清单。
- SHA256SUMS.txt：发布时校验值。新运行、日志和缓存生成后会增加文件或改变运行数据。

本包是本地规划、模拟与回放演示。ROS 2 / Gazebo 对接脚本仍需在相应环境中联调；不包含 Gazebo、ROS 2、UE5，也不代表真实平台联调完成。
启动失败时请保留 backend.log、desktop.log 和具体报错。

官方运行环境来源
Python：https://www.python.org/downloads/release/python-3147/
WebView2：https://developer.microsoft.com/microsoft-edge/webview2/
.NET：https://dotnet.microsoft.com/download/dotnet-framework/net48
