# Gazebo 场景与机器人模型下载解析结果

核对日期：2026-10-26。已读取用户提供的调研 DOCX 与移动话题说明，只把文档用作背景资料。以下是本次实际下载的公开源码与静态解析结果，尚未启动 Gazebo、完成导航或接入现有规划器。

## 先看哪些文件

- `parsed/scene_map.html`：打开即可查看场景原点分布与道路，悬停显示坐标，无外部网页依赖。
- `parsed/scene_objects.csv`：692 条世界直属模型/include 原点，含 xyz（m）、RPY（rad）、来源文件与 URI。
- `parsed/roads.csv`：11 段道路的宽度及三维折线点。
- `parsed/geometry.csv`：370 条 visual/collision 几何声明，保留所属 link、局部位姿、原始尺寸或 mesh URI。
- `parsed/asset_inventory.json`：质量、惯量、关节、传感器、完整插件参数、依赖及文件校验。
- `parsed/robot_models/`：从官方世界提取的独立差速车、履带车 SDF 与 model.config；参数未改，未运行验证。
- `source_manifest.json`：43 个来源文件的固定版本、原始下载链接与 Git blob SHA。并非完整离线资源包。

692 是 8 个世界文件/变体的合计，含仓库有顶/无顶及演示模型，不是 692 个不同障碍物；忽略 XML 注释和保存状态 `<state>`，只读取活动的初始化声明。

## 可下载场景及本次读出的内容

| 场景 | 本次实际结果 | 适合用途与限制 |
| --- | --- | --- |
| [AWS 小仓库](https://github.com/aws-robotics/aws-robomaker-small-warehouse-world/blob/3c23a698bf0b4e366ddf8b084af507c519bd3483/worlds/small_warehouse.world) | 有顶 26 个模型、无顶 25 个；货架、杂物、桶和墙的原点 | 通用仓储巡检/取送；mesh 碰撞边界尚未解码，资源需下载完整仓库 |
| [OSRF CitySim 小城市](https://github.com/osrf/citysim/blob/3928b08e2598f5ead2e9b24640fe1bde262a136d/worlds/simple_city.world) | 621 个世界直属模型/include 原点、11 段道路 | 建筑/道路坐标参考；这是 Classic 资产，未迁移到 Gazebo Sim |
| [ArduPilot 飞翼跑道](https://github.com/ArduPilot/ardupilot_gazebo/blob/80dc9664dda7efd6c5d1a71a79198d1d6b708c0e/worlds/zephyr_runway.sdf) | 坐标轴模型、跑道、飞翼三个对象；含地理原点 | 新 Gazebo/SITL 示例；飞行还依赖气动插件和 ArduPilot SITL |
| [官方履带越障世界](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/tracked_vehicle_simple.sdf) | 6 个世界直属对象；包括履带车、楼梯、圆柱、箱体及外部引用 | 原生 gz-sim8 示例，适合检查履带运动与接触，部分外部资源需补齐 |
| [官方差速车世界](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/diff_drive.sdf) | 地面和两台差速车，模型均在文件内部 | 原生 gz-sim8，适合先检查命令、运动、里程计链路 |
| [官方高度图世界](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/heightmap.sdf) | 四个球与一个 Fuel 高度图模型引用 | 可作真实高度图碰撞入口；本次未下载 Fuel 高度图，未生成逐点高程 |
| [官方电池演示](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/linear_battery_demo.sdf) | 地面和两台带电池车辆 | 学习能源配置；示例参数不能冒充四类平台续航 |

这些是候选路线，不是一套已完成集成的共同环境。Gazebo Classic 与新 Gazebo 的插件不能直接混用；XML 可读不代表当前版本可运行。先核对自己机器实际发行版，不为下载资产直接升级现有环境。

## 真正读出的坐标示例

所有表中 xyz 均为模型/include 原点，单位 m；它们不等于几何中心、边缘或可达的工单目标点。

| 文件中的对象 | x | y | z | 补充 |
| --- | ---: | ---: | ---: | --- |
| 仓库 ShelfF_01_001 | -5.795143 | -0.956635 | 0 | yaw=0 rad |
| 仓库 ShelfE_01_001 | 4.73156 | 0.57943 | 0 | yaw=0 rad |
| 仓库 Bucket_01_020 | 0.433449 | 9.631706 | 0 | yaw=-1.563161 rad |
| 城市 fire_station_113 | 63.8 | 76.18 | 5.01 | 不能将地面高度默认为 0 |
| 跑道 include | -29 | 545 | 0 | 原文件 degrees=true，yaw=363°；表中已转 rad |
| 履带车 simple_tracked | 3 | 0 | 0.1 | 模型初始原点 |
| 楼梯 stairs_very_simple | 7 | 0 | 0 | yaw=1.5708 rad |
| 箱体 box_obstacle | 2 | 2 | 0.028 | roll=1.7821 rad，不能当水平箱体 |

城市 `road_y_1` 的宽度为 **7.4 m**，中心折线端点为 **(-45, -103.7, 5.02) → (-45, 104.2, 5.02)**。道路声明给出带宽和折线，不自动构成车道拓扑或可行驶碰撞面。

**本次重要发现**：[city_terrain/model.sdf](https://github.com/osrf/citysim/blob/3928b08e2598f5ead2e9b24640fe1bde262a136d/models/city_terrain/model.sdf) 的 visual 用高度图（size=500 500 75，局部 pos=40 -20 0），但 collision 实际采用 500×500 m 的平面；碰撞高度图被注释。不能因为画面看见山坡，就认为车辆会沿同样的山坡爬升。

## 对应四类运动形态的模型

下表是示例模型配置，所有质量为显式 link 质量合计，不是厂家整机实测。尺寸举例均注明对应碰撞体，不冒充整机外包络。

| 形态 | 文件 | 已解析数值 | 尚不能据此确定 |
| --- | --- | --- | --- |
| 轮式无人车参考 | [DiffDrive 示例](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/diff_drive.sdf)，本地已提取 `vehicle_blue` | 质量 6.14395 kg；底盘碰撞盒 2.01142×1×0.568726 m；轮半径 0.3 m，轮距 1.25 m；线速度命令限幅 ±0.5 m/s，角速度命令限幅 ±1 rad/s | 整车包络、真实速度测量、传感器、续航；该车为通用演示尺寸 |
| 履带运动参考 | [TrackedVehicle 示例](https://github.com/gazebosim/gz-sim/blob/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb/examples/worlds/tracked_vehicle_simple.sdf)，本地已提取 `simple_tracked` | 质量 28.26 kg；底盘盒 0.50017×0.24093×0.139 m；履带中心距 0.4 m；各 TrackController 的速度范围 ±1 m/s | 履带速度上限不等于实测车速；不能替代真实重型平台、土壤与悬挂性能 |
| 常规固定翼 | [PX4 rc_cessna](https://github.com/PX4/PX4-gazebo-models/blob/e5997f455e33ec071c7c677fc59a65781de496a4/models/rc_cessna/model.sdf) | 质量约 1.67000006 kg（12 个 link）；机体盒 0.65×0.08×0.10 m；翼部盒 0.1×1×0.01 m；IMU 250 Hz、NavSat 30 Hz、气压 50 Hz、磁力计 100 Hz；有 LiftDrag 和推进配置 | 巡航/失速/最大速度、有效载荷与续航需另证；碰撞盒不是整机尺寸 |
| 飞翼 | [Zephyr 基础模型](https://github.com/ArduPilot/ardupilot_gazebo/blob/80dc9664dda7efd6c5d1a71a79198d1d6b708c0e/models/zephyr/model.sdf) + [气动与飞控扩展](https://github.com/ArduPilot/ardupilot_gazebo/blob/80dc9664dda7efd6c5d1a71a79198d1d6b708c0e/models/zephyr_with_ardupilot/model.sdf) | 包括被 include 的基础模型后显式质量合计 1.9 kg；IMU 在基础模型中为 1000 Hz；扩展含多组 LiftDrag 与 ArduPilotPlugin | 扩展文件直接 link 数为零不表示质量为零；未取得可靠的最大速度/续航 |

飞机已有气动配置也不表示能直接用你现有的简化 `cmd_vel` 接口完成真实飞行；PX4/ArduPilot 示例各自需要对应系统与控制链路。

## 有实际产品参数的补充选择

[TurtleBot3 Burger SDF](https://github.com/ROBOTIS-GIT/turtlebot3_simulations/blob/a35a56c8b04877dc89772b598084d8ce648a9023/turtlebot3_gazebo/models/turtlebot3_burger/model.sdf) 含轮距 0.160 m、轮径 0.066 m；IMU 200 Hz；激光 5 Hz、360 点、量程 0.12–3.5 m、噪声标准差 0.01 m。激光为本次版本中的 HLS-LFCD 配置，不能与新产品表的其他 LDS 型号混为同一硬件版本。

[ROBOTIS 官方性能表](https://emanual.robotis.com/docs/en/platform/turtlebot3/features/#specifications) 列出 Burger：尺寸 **0.138×0.178×0.192 m**，最大线速度 **0.22 m/s**，期望运行时间 **2 h 30 min**，电池 **11.1 V、1.8 Ah / 19.98 Wh**。这些是产品页数值，不是从这个 SDF 得到或实测的；该 SDF 未声明电池耗能插件及车体 0.22 m/s 限幅。产品表与下载模型有版本差异，采用前需核对配置。

该版本 TurtleBot3 使用 `libgazebo_ros_*.so`，属于 Classic 插件路线，不能当作当前新 Gazebo 下的即插即用模型。SDF 内显式质量之和 1.00173292 kg，但两个 link 没有显式 mass，因此解析器不将其认定为完整有效整机质量。

续航应另列来源与工况。官方电池演示绿色车配置电压 4.2 V、容量 2.5 Ah、负载 2.1 W，是能源插件示例；不要将简单容量÷功率估算当作任何飞机或履带车的运行结果。蓝车示例还重复声明了 power_load，原值均已保留，不擅自选择其一。

## 完整仓库下载链接

本地只保存用于核对的文本源码与少量 DAE；要在仿真中加载场景，优先从固定版本完整下载，再处理版本、插件、模型路径和外部资源。

| 内容 | 固定版本 ZIP | 上游分支 |
| --- | --- | --- |
| 小仓库 | [完整仓库 ZIP](https://codeload.github.com/aws-robotics/aws-robomaker-small-warehouse-world/zip/3c23a698bf0b4e366ddf8b084af507c519bd3483) | ros1；作为资产来源，不等于要求采用 ROS 1 |
| 小城市 | [完整仓库 ZIP](https://codeload.github.com/osrf/citysim/zip/3928b08e2598f5ead2e9b24640fe1bde262a136d) | master |
| gz-sim 官方示例 | [完整仓库 ZIP](https://codeload.github.com/gazebosim/gz-sim/zip/d540cfd3aa204bc2a75f164478f2f09e01bd3bbb) | gz-sim8；整个源码仓库较大 |
| PX4 模型 | [完整仓库 ZIP](https://codeload.github.com/PX4/PX4-gazebo-models/zip/e5997f455e33ec071c7c677fc59a65781de496a4) | main |
| ArduPilot Gazebo | [完整仓库 ZIP](https://codeload.github.com/ArduPilot/ardupilot_gazebo/zip/80dc9664dda7efd6c5d1a71a79198d1d6b708c0e) | main |
| TurtleBot3 仿真 | [完整仓库 ZIP](https://codeload.github.com/ROBOTIS-GIT/turtlebot3_simulations/zip/a35a56c8b04877dc89772b598084d8ce648a9023) | humble；网格还可能来自 turtlebot3_description |

ZIP 链接依据已核对的 GitHub 固定提交构造，本次没有逐个下载完整 ZIP。具体文件原始下载链接见 `source_manifest.json` 的 raw_url。保留上游许可证，第三方模型可能另有许可。

## 怎样用于下一次实际验证

建议的最小闭环是“普通仓储巡检/取送”，仍是建议，尚未实现：

1. **先让一台车在同版 Gazebo 跑通**：用官方差速世界核验 cmd_vel → 真值位姿/里程计，记录仿真时间与反馈，不先扩到 50 台。
2. **再引入具体场景**：选择仓库，补齐网格、核对版本，基于 collision 和各层位姿生成占据图/可通行图，再按车体包络膨胀障碍；模型原点不能代替障碍边界。
3. **定义普通工单**：在确认可达的自由位置设置起点/巡检点/交付点，明确开始条件、到达容差、停留时间、超时与失败反馈。点位与工单语义需要人为定义，world 不自动提供。
4. **跑规则基线闭环**：规划器分配“哪台车到哪个点”，导航器产生轨迹与速度，位姿和工单反馈决定完成/失败/重试；保存路径长度、实际耗时、碰撞与完成率。当前项目的规则沙盒不是这一步的 Gazebo 联调证据。
5. **最后接学习策略**：保持相同地图、任务和初始条件，对比规则与 MARL。固定翼先在各自单机飞行示例核对，之后才考虑共同场景与统一任务接口。

有了本包，可以先做真实文件驱动的场景输入整理；仍需导航、反馈与任务完成判据，才能成为真实执行系统。

## 复现解析与证据边界

解析脚本仅使用 Python 标准库，不安装/升级依赖，不改现有业务代码。此处实际使用 Windows Python 3.12.15；脚本语法按 Python 3.8 兼容处理，未在 MARLlib 环境运行。

```powershell
& 'C:\Users\ammo\.venv-html-to-docx\Scripts\python.exe' 'C:\Users\ammo\Desktop\MARL项目\outputs\gazebo_assets_2026-10-26\inspect_assets.py'
```

解析其他文件：`python inspect_assets.py --file 文件.sdf --out 新输出目录`。只在本包内按同仓库 model:// 查找引用；任意命名 frame、mesh 包络、Fuel 缓存、URDF/xacro 展开与完整 SDFormat 语义不由这个轻量解析器负责，正式导图应使用匹配版本的 libsdformat/仿真运行时。

28 个 SDF/world 原始文件均与来源 Git blob SHA 精确匹配。官方电池示例注释含 shell `--`，不符合严格 XML 注释语法；解析时只在内存忽略注释，保留上游原文件，未改动参数。通过静态字段交叉核验不等于通过 Gazebo 运行验证。

