# 接口与想定 Schema 对照（对齐《技术实施方案》§3.1）

> 生成日期：2026-10-26。本文回答一个问题：**《智能体开发训练平台技术实施
> 方案》§3.1 列出的 13 类标准化接口，与本目录（`planning_middle_demo/`）的
> 现有实现是什么关系——哪些已对齐、哪些是平台侧、哪些是"要改的接口空缺"。**
>
> 本文只做对照与指向，不冻结协议，也不声称任何字段"已符合方案要求"。
> 现有 `scenarios/*.json` 的字段是我方暂定口径，方案 §3.1 是平台级 Schema，
> 两者粒度不同；接入真实方案时**改哪几个文件**在第四节逐条给出。

## 一、先分清三层东西

| 层 | 谁负责 | 本目录的角色 |
| --- | --- | --- |
| 平台侧（M1 仿真 / M5 采集 / M6 UE5 / M7 部署 / Bridge） | 其他团队 | **不做**，只在下发/反馈里对齐它们的接口形状 |
| 训练侧（M4 训练框架 + 实验管理） | 其他团队 + 我方 `planning/rl/` | 只对齐"训练配置 Schema"这一项的字段 |
| 中间层（本目录） | 我方 | 编组→规划→下发→反馈→重规划，是本文主体 |

方案 §3.1 的 13 类接口，按"与本目录的关系"分四档：

## 二、13 类接口分档

### A 档：本目录已对齐（4 类）

| # | 方案接口 | 载体 | 现有实现 | 对齐状态 |
| --- | --- | --- | --- | --- |
| 6 | 想定 YAML Schema | scene/entities/tasks/rules/timeline 五段 | `scenarios/*.json` | 见第三节逐段对照 |
| 2 | ROS2 Topic（位姿+传感器） | .msg × 2 | `contracts_v2.delivery_block`（`cmd_vel_topic`/`pose_topic`） | 话题名对齐，传感器消息体未定义 |
| 3 | Gymnasium 环境接口 | reset()/step() | `Coordinator.plan(now)` + 五类触发源的滚动循环 | 语义对应，非逐签名对齐 |
| 13 | 容器网络约定 | CycloneDDS XML + env | 不涉及（本目录无 ROS 运行） | 仅记录，见边界 |

### B 档：训练侧相关，但主体不在本目录（2 类）

| # | 方案接口 | 载体 | 现有实现 | 说明 |
| --- | --- | --- | --- | --- |
| 8 | 训练配置 Schema | algorithm/hyperparams/env_config/reward_fn/net_topology | `planning/rl/learn_weights.py` 的参数 | 见第四节 P1 |
| 12 | 实验管理 API | FastAPI | 无 | 训练侧（M4），本目录不实现 |

### C 档：与中间层相关、需声明边界（1 类）

| # | 方案接口 | 载体 | 现有实现 | 说明 |
| --- | --- | --- | --- | --- |
| 9 | 多智能体配置 Schema | groups/roles/shared_obs/comm_channels/reward_mode/curriculum | 无（本层是"平台-作业分配"，无分组/角色/通信概念） | 见第四节 P2 边界声明 |

### D 档：平台侧，本目录不做（6 类）

| # | 方案接口 | 归属模块 |
| --- | --- | --- |
| 1 | ROS2 Service（仿真控制）.srv × 7 | M2 导调控制台（平台侧） |
| 4 | WebSocket 协议（双引擎） | M6 UE5 |
| 5 | 推理 API（FastAPI） | M4 训练侧 |
| 7 | Gazebo 物理参数 Schema | M1 域随机化 |
| 10 | 域随机化 Schema | M2 域随机化面板 |
| 11 | 数据集格式 Schema | M5 数据采集 |

## 三、想定 Schema（#6）逐段对照

方案 §3.1 把想定定义为 **scene / entities / tasks / rules / timeline 五段**。
本目录 `scenarios/*.json` 是**压缩后的演示口径**，不是五段结构。逐段对照如下：

| 方案五段 | 语义 | 现有实现（`scenarios/*.json` + `contracts_v2.py`） | 差异 |
| --- | --- | --- | --- |
| scene | 场景级元信息（地图/坐标/来源） | `_meta`（source/coord_note/scale/offset） | 已有一致语义，字段名不同 |
| entities | 平台 + 作业的实体定义 | `platforms[]`（robot_no/pos）+ `jobs[]`（job_id/type/pos） | 已对齐实体层；能力参数在 `fleet.PLANNING_PARAMS` 而非实体里 |
| tasks | 任务的具体要求 | `jobs[]` 的 `work/window/crew/need_payload/need_sensor/altitude` | 已对齐；五类模板在 `JOB_SPECS` |
| rules | 约束/规则（能力边界、时间窗规则） | 能力闸门在 `planner_v2`（过滤+方案级校验）；可配置参数进 `rules` 段（dev_threshold/grace_s/max_attempts），**检查逻辑仍由代码执行** | 已落地（2026-10-26）：参数可配、检查不可关 |
| timeline | 时间线（导调事件、想定脚本） | `timeline` 数组（member_lost/job_fail/job_delay/job_slow），数据驱动注入 | 已落地（2026-10-26）：见 `README_v2.md` 与 `test_timeline_rules.py` |

**结论**：五段里 **entities / tasks / rules / timeline 四段已实质对齐**（rules 走
"参数可配、检查不可关"的折中，timeline 数据驱动），**scene 语义一致字段名不同**。

## 四、接入真实方案时改哪里（逐条）

### P0-A：想定五段对齐（2026-10-26 已落地 rules + timeline）

1. **rules 段（已落地）**：可配置参数（`dev_threshold`/`grace_s`/
   `max_attempts`）进场景 `rules` 段；能力约束检查（续航/载荷/高度/传感器/
   运动性能）仍由 `planner_v2.feasible` 代码执行，场景文件不能开关——任何
   `disable_*`/`enable_*` 字段被 `check_scenario_v2` 拒绝。
2. **timeline 段（已落地）**：`timeline` 数组数据驱动导调事件（`member_lost`/
   `job_fail`/`job_delay`/`job_slow`），替代 `run_demo_v2` 里五种 mode 的
   硬编码注入；`mode` 保留为"预设 timeline"的快捷入口。
3. **字段名映射表（待做）**：`_meta` → `scene`、`platforms/jobs` → `entities`
   的映射，可在 `check_scenario_v2` 加一层兼容读取（新名优先、旧名回落），
   避免破坏现有场景文件。当前 `_meta` 已承载 scene 语义，仅字段名不同。

> 已完成的 1、2 有 45 项测试覆盖（25 旧 + 20 新），缺省行为零回归。

### P0-B：ROS2 Topic 消息体（#2）

`delivery_block` 已对齐话题名（`/rover_XX/cmd_vel`、`/model/rover_XX/pose`），
但方案 `.msg × 2` 的 `/gazebo/model_states` + `/robot/odom_ext` + `/sensor/*`
消息体**未定义**。接真实下层时，把 `mock_fleet` 替换为订阅这些话题的适配器，
`delivery_block` 的运动字段（`motion_caps`）不变。

### P1：训练配置 Schema（#8）对齐锚点

`planning/rl/learn_weights.py` 当前用 CEM（交叉熵方法，无梯度黑箱优化）学
**8 维权值**（7 维代价特征 `COST_WEIGHTS` + 1 维排程紧迫度 `URGENCY_WEIGHT`），
参数硬编码在脚本里，对应方案的 `reward_fn`（奖励函数权重）这一子项。方案 §5.2
"训练层验收"口径是：

> 连续跑 10 个 episode，累计奖励有上升趋势；GPU 显存占用 < 80%。

建议给 `rl/` 补一个**可复现的奖励趋势锚点**（N 个 episode 的累计奖励单调性
/ 末段均值 > 首段均值），并把手动权重、学习权重、随机基线三者并列对照，
对齐方案口径。这部分属于 `planning/rl/`，**不在本目录**，是否迁过来需另议。

### P2：多智能体配置 Schema（#9）边界声明

方案 §2.3 M3+M8 定义分组（roles 攻击者/防守者/协同者）、shared_obs、
comm_channels、reward_mode、curriculum。本目录是**平台-作业调度抽象**，
没有"分组/角色/通信"概念，也**不展开"攻击者/防守者"这类角色定义**（既定边界）。

声明口径（已写入 `README_v2.md` 边界节）：
> 多智能体分组 / 角色 / 通信信道 / 课程学习属平台 M3 配置能力，
> 由智能体训练层消费，不在任务规划中间层实现；本层只负责"把作业派给平台"，
> 不定义平台之间的协作角色或通信拓扑。

## 五、一句话总结

| 判定 | 内容 |
| --- | --- |
| 已对齐 | entities / tasks 两段、ROS2 话题名、Gymnasium 循环语义 |
| 语义一致字段名不同 | scene 段（`_meta`） |
| 接口空缺（要补） | rules 段（硬编码未抽）、timeline 段（未实现）、传感器消息体 |
| 平台侧不做 | 6 类（ROS2 Service / WebSocket / 推理 API / 物理参数 / 域随机化 / 数据集） |
| 边界声明 | 多智能体分组/角色/通信（M3 配置能力） |
