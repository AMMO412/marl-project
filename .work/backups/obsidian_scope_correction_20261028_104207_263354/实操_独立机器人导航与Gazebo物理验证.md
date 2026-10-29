---
type: practice
updated: '2026-10-28'
cssclasses: [ammo-note]
---
# 实操 · 独立机器人导航与 Gazebo 物理验证

> [!abstract] 已验证结论
> 用户确认改做独立的普通机器人导航教学。新工程 `robot_navigation_lab/` 已能根据命令计算绕开建筑的路线，通过 Gazebo 轮式驱动执行，读取实际世界位姿，到入口后切换循环巡检。网页已验证暂停、继续、取消，再重新执行完整两圈。场景采用公开合成城市的三个真实声明的碰撞盒局部重建，不是实地采集城市。

## 从哪里开始

工程根目录：`C:/Users/ammo/Desktop/MARL项目/robot_navigation_lab/`。

1. 双击 `start_gazebo.cmd`，打开 <http://127.0.0.1:8788>。
2. 选择“移动到入口，然后循环巡检”，保留 2 圈，点“开始执行”。观察小车先绕开建筑到右侧入口，再循环经过四个检查点。
3. 可暂停、继续、取消；完成后点“打开本轮完整回放与报告”，拖动时间轴或点击事件。
4. 改为“移动到指定位置”，输入 `(22, 9.356)` 或点击地图选点。建筑内或地图外目标会被拒绝。

每次新命令是一次独立试验，从固定起点重新开始。关闭网页不会自动取消执行；启动窗口按 Ctrl+C 停止服务并取消未完成的命令。单轮有时间上限，暂停也计入上限。

`start_kinematic.cmd` 打开 <http://127.0.0.1:8787> 的二维版本。它明确标记为运动学结果，适合快速学习，不作为物理碰撞证据。完整说明、全部参数和文件字段在工程 `README.md`。

## 实现分层与边界

```text
输入到点/巡检命令
→ 校验目标与障碍地图
→ 按车体半径+余量膨胀，A* 搜索与路径段碰撞检查
→ 根据当前位置/航向产生持续速度指令
→ Gazebo Transport /lesson/cmd_vel (Twist)
→ DiffDrive 驱动车轮关节，DART 执行运动和碰撞
→ /model/lesson_bot/pose 世界位姿反馈
→ 实际到点判定、巡检切换、检查点停留与圈数累计
→ 轨迹、事件、报告、独立 HTML 回放
```

底图只是显示；碰撞体负责物理阻挡，导航程序负责在碰撞前规划绕行，执行状态机负责判断是否到了入口及是否完成巡检。三者必须分别有实际实现，画出道路和建筑不能代替它们。

当前直接使用 Gazebo Transport，未安装/接入 ROS、Nav2、SLAM 或激光雷达导航。控制器读取仿真真值位置，障碍物来自已知静态地图，没有未知/动态障碍物感知或定位噪声。它没有导入原五类任务规划器，也不证明原工程已经完成 Gazebo 联调。

## 场景、输入与主要参数

来源为公开 OSRF citysim 的 `simple_city.world` 位置与 `osrf/gazebo_models` 中对应 SDF `collision/box`。模型下载 URL、SHA256 和许可证随工程保存；按文件哈希固定，没有声称固定 Git commit。选用三个 box，未加载完整城市及外观网格；整体 z 减 5.01 米以在教学平地落地，XY 保留。

| 对象 | 中心 XY / 米 | 碰撞盒长×宽×高 / 米 |
| --- | --- | --- |
| thrift_shop / 旧货店 | (1.35, 9.356) | 7.213 × 5.432 × 11.389 |
| law_office / 办公楼 | (8.47, 9.356) | 6.844 × 5.432 × 13.925 |
| salon / 理发店 | (15.7, 9.356) | 7.213 × 5.379 × 11.389 |

| 输入/配置 | 实际默认值 |
| --- | --- |
| 起点 | (-5, 9.356)，航向 0 弧度 |
| 地图范围 | x [-8,26]，y [-4,20] 米 |
| 到点命令 | `{"kind":"navigate","goal":[22,9.356]}` |
| 巡检入口 | (22,9.356) |
| 检查点顺序 | (22,15)、(-5,15)、(-5,3)、(22,3) |
| 圈数/停留 | 2 圈；检查点停留 0.5 仿真秒 |
| 网格/导航包络半径/额外余量 | 0.25 / 0.42 / 0.38 米 |
| 最大线速度/角速度命令 | 0.8 米/秒；1.4 弧度/秒 |
| 到点/中间航点容差 | 0.22 / 0.18 米 |
| 轮半径/轮间距 | 0.10 / 0.46 米 |
| 物理步长/位姿频率/目标 RTF | 0.001 秒；40 Hz 仿真时间；4 |
| 单轮上限 | 600 仿真秒；Gazebo 墙钟 240 秒 |

到达入口后才开始巡检；到第一个检查点后，按顺序走完其余点并返回第一个点才累计一圈。时间流逝本身不能完成阶段。暂停发送零速度，实际制动需要时间。

## 已验证结果与产物

所有路径均相对于工程目录；原输出不覆盖。

| 试验 | 实际结果 | 产物 |
| --- | --- | --- |
| 自动测试 | 13 项通过；覆盖障碍/边界、转角、不可达、地图变化、非法反馈、状态机和完整巡检 | `tests/test_navigation.py` |
| 二维巡检 | 完成两圈；190.157 米；258.1 仿真秒 | `outputs/kinematic_inspection_verified/` |
| Gazebo 到点 | 绕行到达；30.527 米；44.725 仿真秒；早期轮次未核实接触传感器 | `outputs/gazebo_navigate_verified/` |
| Gazebo 网页最终巡检 | 暂停/继续/取消通过后，另开新轮完成两圈；190.199 米；262.625 仿真秒；墙钟 95.81 秒；最小导航包络外缘间隙 0.3254 米；发现传感器发布话题，车身-商铺接触记录 0 | `outputs/live_20261028_002522_413595/` |
| 独立直行碰撞对照 | 不调用规划器，持续给 0.8 米/秒；建筑挡住小车，最后两秒 x 无变化；8723 条接触记录；最大数值穿入约 0.7 毫米 | `outputs/gazebo_collision_final/` |
| 网页与回放 | 实时控制、时间轴、事件、图层、窄屏检查通过，无页面脚本错误 | `outputs/gazebo_live_verification.json`、最终轮次 `preview.png` |

最终回放：`C:/Users/ammo/Desktop/MARL项目/robot_navigation_lab/outputs/live_20261028_002522_413595/index.html`。

每轮的 `scene.json` / `command.json` 保留场景与输入；`trace.jsonl` 记录 t、x、y、yaw、state、paused、round、goal、path_version、clearance 和速度命令；`events.json` 保留到点和阶段事件；`report.json` 保留结果；`world.sdf` / `gazebo.log` 是实际加载世界和进程日志。

`clearance` 是位置到最近障碍/地图边界的距离减去导航包络半径。`obstacle_contacts` 是车身接触记录条数，不是独立碰撞事件次数，也不包括车轮/脚轮；话题未发现时应为 null，不能据零条消息推定无碰撞。单次教学试验不代表任意场景或真实小车可靠性。

## 可复现命令

在 Windows 项目根目录：

```powershell
py -3 robot_navigation_lab/start_console.py --backend gazebo

wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/run_lesson.py --backend gazebo

wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/run_lesson.py --backend gazebo --kind navigate --goal 22 9.356

py -3 -m unittest discover -s robot_navigation_lab/tests -v

wsl -d Ubuntu -- /usr/bin/python3 /mnt/c/Users/ammo/Desktop/MARL项目/robot_navigation_lab/tools/verify_collision.py
```

## 环境变更与排错结论

本次实测为 WSL `Ubuntu`、Ubuntu 26.04.1；使用 `/usr/bin/python3`。安装 Gazebo Jetty 无界面服务器：`gz-sim10-server 10.5.0-2~resolute`、`python3-gz-transport15 15.1.0-3~resolute`、`python3-gz-msgs12 12.0.2-2~resolute`。APT 新增 400 个含间接依赖的包，并升级系统 `libbrotli1` 与 `zlib1g`；没有在 MARLlib Conda 环境中安装包。详见 `outputs/environment_verified.json` 和 WSL `/var/log/apt/history.log`。

新增 OSRF keyring 和 `robot-navigation-gazebo.list`。原 Ubuntu 源配置保留；下载阶段临时使用清华镜像，仍校验 Ubuntu/OSRF 签名，没有关闭 HTTPS 证书或包校验。重装步骤在 README，日常启动不需要再次安装。

| 本次遇到的问题 | 修正与通用认识 |
| --- | --- |
| 收到位姿，但时间一直为 0，随后反馈超时 | PosePublisher 把时间写在每个 Pose 的 `header.stamp`，不能读外层 Pose_V 的空 header |
| 建筑挡住小车，但接触订阅始终为 0 | Contact 系统读取 `contact/topic`；修正后直行对照收到实际接触记录。没有先做正对照就不能相信“零碰撞” |
| 拖到时间轴末端仍显示巡检中 | Gazebo 采样末时刻为 262.625 秒，原滑条 0.05 步长到不了；改为任意步长，保留最后一帧和完成事件 |

后续若增加真实性，建议单独引入激光雷达、定位误差、未知障碍物与成熟导航栈，并逐项验证；这些尚未完成，不计入本次结果。

## 来源与相关笔记

- [Gazebo Jetty 安装与无界面服务器](https://gazebosim.org/docs/jetty/install_ubuntu/)
- [Gazebo Transport 15 Python](https://gazebosim.org/api/transport/15/python.html)
- [DiffDrive](https://gazebosim.org/api/sim/10/classgz_1_1sim_1_1systems_1_1DiffDrive.html)
- [Contact 系统源码](https://github.com/gazebosim/gz-sim/blob/gz-sim10/src/systems/contact/Contact.cc)
- [OSRF citysim](https://github.com/osrf/citysim) · [OSRF gazebo_models](https://github.com/osrf/gazebo_models)
- [[学习_ROS与Gazebo入门]] · [[00_项目入口]]
