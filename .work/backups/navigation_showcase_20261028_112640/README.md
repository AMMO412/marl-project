# 独立机器人导航教学

这是与 `planning_middle_demo` 分开的普通轮式机器人项目。输入到点命令或循环巡检命令，程序计算避开建筑的路线、发送速度、根据实际位置判断到达，并保存完整执行记录。

## 先试一次

Windows 双击本目录的 **`start_gazebo.cmd`**，打开执行台。默认地址为 <http://127.0.0.1:8788>。

1. 选择“移动到入口，然后循环巡检”，保留 2 圈，点击“开始执行”。
2. 小车从左侧起点出发，绕开三栋建筑，到右侧入口后按四个检查点循环巡检。
3. 蓝色虚线是当前规划路线，绿色是收到的位置反馈；可暂停、继续或取消。
4. 完成后点“打开本轮完整回放与报告”，拖动时间轴查看执行事件。

也可选择“移动到指定位置”，输入 `(22, 9.356)`，或点击地图选点。建筑内部、地图外的目标会被拒绝。每次新命令都是独立试验，从设定起点重新开始；关闭网页不会自动取消已提交的命令。启动窗口按 Ctrl+C 停止服务并取消未完成的命令。

**`start_kinematic.cmd`** 启动 Windows 二维教学后端，地址 <http://127.0.0.1:8787>。页面会明确标记其为二维运动学，不能将它的结果当作 Gazebo 物理结果。

## 实际执行链路

```text
网页/命令行提交目标
  → 校验输入与障碍地图
  → 按车体半径和余量膨胀障碍，A* 搜索，检查每条连接与转角
  → 根据实际位置与航向持续产生线速度、角速度
  → Gazebo Transport /lesson/cmd_vel (Twist)
  → DiffDrive 插件驱动车轮关节，DART 计算运动与碰撞
  → /model/lesson_bot/pose 返回世界位姿与仿真时间
  → 判断到点，切换巡检，记录检查点和闭合圈数
  → JSON/JSONL 报告与独立 HTML 回放
```

控制器没有通过修改模型位置来移动小车。二维后端共用导航逻辑，将 Gazebo 替换为显式标记的运动学积分与扫掠碰撞检查。

当前直接使用 Gazebo Transport，**没有接入 ROS、Nav2、SLAM、激光雷达或未知/动态障碍物感知**。控制器订阅的是仿真世界真值位姿，没有模拟定位误差。安全余量是教学配置，尚不是现实机器人安全性能结论。

## 场景究竟是什么

使用公开 **OSRF citysim / simple_city** 场景中三家商铺的位置，以及 `osrf/gazebo_models` 对应模型的 SDF `collision/box` 尺寸，重建一个局部场景。它是公开的合成仿真场景，**不是实地采集的真实城市**，也没有加载完整城市或建筑外观网格。

`build_scene.py` 解析 include/model/link/collision 的平面刚体变换与碰撞盒，读取源文件 SHA256；缺少支持的碰撞形状会报错，不会把地标中心随意放大成障碍。当前只支持选定模型的平面变换与 box。整体 z 减去 5.01 米，使商铺在本教学项目的平地上落地；XY 和实际声明的碰撞盒尺寸保留。

| 建筑 | 碰撞盒中心 XY / 米 | 长 × 宽 × 高 / 米 |
| --- | --- | --- |
| thrift_shop / 旧货店 | (1.35, 9.356) | 7.213 × 5.432 × 11.389 |
| law_office / 办公楼 | (8.47, 9.356) | 6.844 × 5.432 × 13.925 |
| salon / 理发店 | (15.7, 9.356) | 7.213 × 5.379 × 11.389 |

源 SDF、世界文件、许可证保留在 `assets/`；模型下载地址和哈希在 `assets/gazebo_models/sources.json`。下载来源按文件哈希固定，没有声称固定 Git commit。部分额外下载的模型没有加入当前场景。

## 输入与参数

| 项目 | 默认值/含义 | 文件 |
| --- | --- | --- |
| 世界单位 | 米、弧度、仿真秒 | `scenes/city_shops.json` |
| 地图范围 | x ∈ [-8,26]，y ∈ [-4,20] | 同上 |
| 起点 | (-5,9.356)，航向 0 | 同上 |
| 到点输入 | `{"kind":"navigate","goal":[22,9.356]}` | 网页/API/命令行 |
| 巡检输入 | kind=inspection、入口、检查点、rounds、dwell_s | 同上 |
| 巡检入口 | (22,9.356) | 场景 inspection |
| 检查点 | (22,15)、(-5,15)、(-5,3)、(22,3) | 同上 |
| 圈数/停留 | 2 圈；每次到检查点停留 0.5 秒 | 同上 |
| 网格分辨率 | 0.25 米 | grid_resolution |
| 导航车体包络半径 | 0.42 米，覆盖物理小车 | robot.radius |
| 规划附加余量 | 0.38 米 | robot.clearance |
| 最大速度/角速度命令 | 0.8 米/秒；1.4 弧度/秒 | robot |
| 到点/中间航点容差 | 0.22 / 0.18 米 | robot |
| 轮半径/轮间距 | 0.10 / 0.46 米 | `gazebo_backend.py` |
| 车身碰撞盒 | 0.50 × 0.32 × 0.18 米，另有车轮和脚轮 | 同上 |
| 物理步长/目标推进比 | 0.001 秒；RTF 目标 4，实际推进由负载决定 | 同上 |
| 位姿发布频率 | 40 Hz 仿真时间 | 同上 |
| 单轮上限 | 600 仿真秒；Gazebo 墙钟 240 秒 | `run_lesson.py` |

移动到入口不算巡检完成；先到第一个检查点，再按顺序经过其余点并返回第一个点，才累计一圈。计时流逝不能替代实际到点。暂停时发送零速度，物理小车仍需制动，不能假定瞬间静止。暂停也会占用单轮运行时限。

## 输出和状态

每轮输出到本目录 `outputs/` 的独立子目录，既有输出不覆盖。

| 文件/字段 | 含义 |
| --- | --- |
| `index.html` | 可独立打开的实际记录回放，含输入、执行报告和事件 |
| `scene.json` / `command.json` | 本轮场景快照与输入 |
| `trace.jsonl` | t、x、y、yaw、state、paused、round、goal、path_version、clearance、linear、angular |
| `events.json` | 接收命令、计算路线、实际到点、开始巡检、完成一圈、完成/取消/失败等 |
| `report.json` | 后端、最终状态、圈数、实际路程、最小外缘间隙、接触记录、采样数等 |
| `manifest.json` | 生成时间、场景快照哈希、后端标记 |
| `world.sdf` / `gazebo.log` | 该轮实际加载的 Gazebo 世界与进程日志 |
| `error.txt` | 启动、输入或运行异常，不能当作成功结果 |
| `clearance` | 位置到最近障碍/地图边界的距离，减去导航包络半径 |
| `contact_sensor_advertised` | 实际传输中是否发现车身接触传感器发布话题 |
| `obstacle_contacts` | 车身与商铺的接触**记录条数**，不是独立碰撞事件次数；不监测车轮/脚轮；传感器未发现时为 null |

执行状态主要为 `idle → navigating_to_entry → inspecting → complete`；到点命令是 `navigating → complete`；不可达、碰撞保护或预算耗尽会失败。取消进入 `cancelled`。执行台每次命令运行一轮程序，完成后保存回放；回放播放/暂停只影响查看，不改变执行记录。

## 复现命令

在 Windows 项目根目录执行：

```powershell
# 网页执行台：真实 Gazebo 后端，自动启动 WSL Ubuntu 的服务
py -3 robot_navigation_lab/start_console.py --backend gazebo

# 只跑一轮，保存实际 Gazebo 位姿，不启动网页服务
wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/run_lesson.py --backend gazebo

# 指定目标；默认输出自动使用新目录
wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/run_lesson.py --backend gazebo --kind navigate --goal 22 9.356

# Windows 二维快速运行（不是物理仿真）
py -3 robot_navigation_lab/run_lesson.py --backend kinematic

# 导航、状态机与完整巡检的自动测试
py -3 -m unittest discover -s robot_navigation_lab/tests -v

# 独立碰撞对照：刻意持续直行撞向商铺，检查物理阻挡与接触记录
wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/tools/verify_collision.py
```

上述脚本使用各自所在目录定位资源，不要求切换 Conda 环境。执行台默认只绑定本机回环地址。

## 本机环境变更（2026-10-28）

已在现有 WSL Ubuntu 26.04.1 安装 Gazebo Jetty 无界面服务器和 Python Transport，未安装 ROS/Nav2，未在 MARLlib Conda 环境中安装包。实际版本：

- `gz-sim10-server`：10.5.0-2~resolute。
- `python3-gz-transport15`：15.1.0-3~resolute。
- `python3-gz-msgs12`：12.0.2-2~resolute。

APT 新增 400 个含间接依赖的软件包，并按依赖需求升级了系统 `libbrotli1` 和 `zlib1g`。这不是仅添加三个独立文件；详细记录见 `outputs/environment_verified.json` 和 WSL `/var/log/apt/history.log`。

新增 OSRF 签名密钥 `/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg` 和源配置 `/etc/apt/sources.list.d/robot-navigation-gazebo.list`。Ubuntu 原有源配置保留；下载缓慢时，安装脚本临时复制源配置、使用清华镜像，仍使用 Ubuntu 签名校验。没有关闭 HTTPS 证书或包签名验证。

需要在同样的 Ubuntu 26.04 环境重装时：

```powershell
wsl -d Ubuntu -u root -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/tools/setup_gazebo.py --ubuntu-mirror https://mirrors.tuna.tsinghua.edu.cn/ubuntu
```

该安装命令有系统依赖变更，不应作为日常启动命令重复执行。

## 已验证结果（2026-10-28）

| 试验 | 实际结果 | 产物 |
| --- | --- | --- |
| 导航自动测试 | 13 项通过；含不可达、转角防穿越、地图变化、反馈时间与完整两圈 | `tests/test_navigation.py` |
| 二维完整巡检 | 两圈完成，190.157 米，258.1 仿真秒；非物理结果 | `outputs/kinematic_inspection_verified/` |
| Gazebo 到点 | 绕行到达，30.527 米，44.725 仿真秒；此早期轮次未核实接触传感器 | `outputs/gazebo_navigate_verified/` |
| Gazebo 网页完整巡检 | 暂停/继续/取消验证后另开新轮，完成两圈；190.199 米，262.625 仿真秒，墙钟 95.81 秒；最小包络外缘间隙 0.3254 米；传感器话题已发现，车身-商铺接触记录 0 | `outputs/live_20261028_002522_413595/` |
| 独立直行碰撞对照 | 不调用规划器，持续给 0.8 米/秒；建筑挡住小车，最后两秒 x 无变化；收到 8723 条接触记录；最大数值穿入约 0.7 毫米 | `outputs/gazebo_collision_final/` |
| 页面检查 | 实时控制、完整回放时间轴、事件、图层与窄屏检查通过，无页面脚本错误 | `outputs/gazebo_live_verification.json` 与对应 `preview.png` |

这是一次教学环境验证，不能据单次数据推断任意场景的导航可靠性或现实小车性能。输出目录中还保留了早期探针和失败排错记录，以本表指定的最终产物为准。

## 接口来源

- [Gazebo Jetty 官方安装与无界面服务器](https://gazebosim.org/docs/jetty/install_ubuntu/)
- [Gazebo Transport 15 Python 接口](https://gazebosim.org/api/transport/15/python.html)
- [DiffDrive 轮式驱动接口](https://gazebosim.org/api/sim/10/classgz_1_1sim_1_1systems_1_1DiffDrive.html)
- [Gazebo Contact 系统源码](https://github.com/gazebosim/gz-sim/blob/gz-sim10/src/systems/contact/Contact.cc)：接触话题配置在 `contact/topic` 下，且只在有接触时发布。
- [OSRF citysim](https://github.com/osrf/citysim) / [OSRF gazebo_models](https://github.com/osrf/gazebo_models)。
