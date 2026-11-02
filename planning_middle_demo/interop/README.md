# interop · 1028 4.1/4.2 统一接口与五类任务规划（融合层）

`interop` 是本工程（`planning_middle_demo`，基座）与 M2 编队规划器融合后的
统一入口。它不是把 M2 整体搬过来，而是把两边**通用**的长处合成一条可运行
的链路：

```
4.1 任务消息（schema 0.3）+ 编成表
        ↓  严格解析/校验（interop.message）
统一 Scenario（平台、任务、约束、meta）
        ↓  分解 → 能力闸门 → 协同组匈牙利 → 风险 A* → 三目标评分 → 排程
4.2 计划层 assignments + 执行层 commands
        ↓
plan.json / assignments.csv / commands.csv / report.md / manifest.json
```

边界写在代码里，不靠口头约定：

- **做五类任务**：`T-RCN`（协同侦察）、`T-SEC`（区域封控）、`T-PTL`（巡逻警戒）、
  `T-HLD`（要点坚守）、`T-ASL`（机动突击）。T-ASL 只规划侦察/突击/评估席位、
  时序与机动；打击动作、弹药消耗和毁伤/压制/夺占判定由基座行为层与评估接口执行。
- 不发布 ROS、不启动 Gazebo、不写运行终态；`result_status=PLAN_ONLY`、
  `evidence_source=NO_EXECUTION_EVIDENCE` 表示“只有计划，没有执行证据”。
- 本层只输出 TRANSIT/HOLD/STOP；任务段动作由基座行为层接管。T-ASL 的
  `assignments` 带 `role`，但 4.2 指令契约不新增火力动作。
- 计划报告只证明“谁、何时、走哪条路”，不把计划当成效果已达成；效果结论以
  运行记录里的 `assessment_received` / `behavior_result` 为准（默认桩判定）。

## 1 快速开始

在 `planning_middle_demo/` 目录下运行：

```powershell
# 单次规划（输出 4.2 全套产物）
python -m interop.cli plan `
  --message interop/scenarios/patrol_checkpoint.message.json `
  --formation interop/scenarios/patrol_checkpoint.formation.json `
  --out ..\outputs\interop_demo\patrol --objective timeliness

# 同输入对比 unified / 基座 planner_v2 / M2
python -m interop.cli compare --suite `
  --out ..\outputs\interop_compare_20261030 `
  --objectives timeliness,energy --backends unified,base_v2,m2

# 检查能否无损转为旧场景：当前样例将明确拒绝，退出码2，并列出缺失能力
# 不生成或覆盖 --out；不要把它作为 run_demo_v2 的成功转换步骤
python -m interop.cli to-v2 `
  --message interop/scenarios/area_recon.message.json `
  --formation interop/scenarios/area_recon.formation.json `
  --out ..\outputs\interop_demo\area_recon.scenario.json

# 校验 4.2 数据契约（不代表指令已发布、执行或任务成功）
python -m interop.cli validate --plan ..\outputs\interop_demo\patrol\plan.json

# SDF → 编成表骨架
python -m interop.cli sdf --sdf ..\资料\接口说明\container_00_combined_scene.sdf `
  --robots 1,21,31,41 --out ..\outputs\interop_demo\sdf_formation
```

样例生成（可重复）：

```powershell
python -m interop.tools.build_scenarios
```

### 1.1 运行对接（融合版作为新主体）

规划不再只停在文件层：`interop` 已接到基座的 `CoordinatorV2` 上，
**换规划引擎、不换运行语义**。指令下发、反馈核对、取消/重试、工作台回放
仍是基座的；统一层只决定“谁、何时、走哪条路、做哪个作业”。

```powershell
# 4.1 输入直接驱动完整运行链（规划 + 下发 + 反馈 + 报告/回放）
python -m interop.cli demo `
  --message interop/scenarios/mixed_inspection.message.json `
  --formation interop/scenarios/mixed_inspection.formation.json `
  --out ..\outputs\interop_demo\runtime_mixed --max-ticks 260

# 基座入口也可切规划器；auto 会优先用统一层，遇到突击场景回退基座
python run_demo_v2.py --scenario <场景.json> --planner auto
python run_demo_v2.py --scenario <场景.json> --planner interop   # 强制统一层
```

工作台：`启动工作台.cmd` 打开“融合版中性任务”的新建演示；场景下拉现有三个入口：
融合版中性任务（`interop_neutral`）、融合版机动突击（`interop_asl`，4.1 T-ASL 样例）、
以及 `asl_city` 历史入口。两个融合样例固定 `interop` + 逐步运动，`interop_asl`
自动开行为与城市避障。运行完成后，4.2 的 `plan.json` / `assignments.csv` /
`commands.csv` / `report.md` / `ros2_commands.txt` 会和反馈轨迹一起保存在
`planning_middle_demo/outputs/workbench_*/`，可在“项目文件”页直接下载。
`asl_city` 继续用基座 `planner_v2` 作历史对照。

对接实现（`interop/runtime.py`）：

| 环节 | 做法 |
| --- | --- |
| 权威输入 | 4.1 消息 + 编成表；写入 `_meta.interop` 的是原始输入，不是有损转换 |
| 运行时状态 | 每次滚动规划快照平台位姿/存活/在途占用（`busy_until_s`）与待派作业剩余工作量 |
| 调度 | 统一层分解/能力闸门/协同匈牙利/风险 A*/三目标 |
| 回写基座 | 槽位分配折回 job 级 `Assignment`（pids/start/end/travel/dur），交给 Coordinator 下发 |
| 进度口径 | `work = 槽位时长 × 成员 work_rate 之和`，使计划时长与基座逐步进度一致 |
| 参数口径 | 4.1 编成表的速度/续航/载荷/传感器同步给协调器，规划闸门与行为层用同一套参数；否则会退回 fleet 默认的 0.8 m/s、6/8/2/1.5 载荷 |
| 计划留存 | 工作台运行后把 4.2 计划产物复制到运行目录，路径/指令/发布命令可追溯 |
| 槽位同步 | 基座没有“同作业多段串行槽位”的表达，运行适配器把所有槽位对齐为同时开始 |
| T-ASL 对接 | 4.1 T-ASL → `type=assault` 基座作业 + `_behavior`；侦察/突击/评估席位与出发时刻由统一层定，打击与判定归行为层 |

### 1.2 机动突击（T-ASL）

- **4.1 输入**：`task_type=T-ASL`，目标是单点（`point`/`key_point`/`target_list` 单点）；
  `params` 至少给 `effect`（`damage`/`suppress`/`seize`，接受中文标签），
  阈值 `required_level` / `required_duration` / `required_control_s`，
  突击载荷下限 `payload_required`，侦察/评估席位 `scout` / `assessor`
  （`count` + `capabilities` + 可选 `unit`），以及 `attack_window`、`staging_center`、
  `assessment_post`、`assessment_delay`、`confirmation_deadline`、`execute_deadline`、
  `withdraw*`、`roe` 等；`duration_s` 默认 140。
- **分解**：侦察席（观察位，先行）→ 突击席（目标环，带载荷下限，等侦察席完成后
  开始）→ 评估席（评估观察位，与突击同时段机动）。显式 `scout_unit` /
  `assessor_unit` 时固定到指定平台；缺省按编成能力选（RCN 高者侦察、次高者评估）。
- **计划**：`assignments[].role` 为 `scout` / `assault` / `assessor`，
  `assignments.csv` 增列 `role`；`commands` 仍只产 TRANSIT/HOLD/STOP，
  打击段不在 4.2 表达。报告 §2.1 列出效果参数与席位，但只代表计划要求。
- **运行**：`to_v2_dict` 生成 `type=assault` 的基座作业与 `_behavior`
  （效果、几何、时序、侦察/评估 pid），`InteropPlanner` 只回写 pids/start/end/travel，
  不改写突击作业的 `work`（进度按行为阶段计）。行为层执行打击与评估，
  `assessment.py` 出逐项结论。
- **样例**：`interop/scenarios/asl_junction.message.json` +
  `asl_junction.formation.json`；命令行 `python -m interop.cli demo --message ...`
  会自动开行为/城市避障/逐步运动（`--max-ticks 700`）。

### 1.3 五类任务支持矩阵

| 任务 | 4.1 分解 | 计划层可见 | 执行层 | 结论来源 |
| --- | --- | --- | --- | --- |
| T-RCN 协同侦察 | 区域竖条 / 路线分段 / 目标点 | assignments / commands | `recon` 行为 | 覆盖率、任务反馈 |
| T-SEC 区域封控 | 边界段 / 门哨 / 机动组 | `role=boundary/gate/...` | `blockade` 行为 | 封控运行结果 |
| T-PTL 巡逻警戒 | 路线分段 / 巡逻区 / 点 | assignments / commands | `patrol` 行为 | 圈数、任务反馈 |
| T-HLD 要点坚守 | 阵位 / 预备队 / 支援 / 中继 | `role=post:P1/reserve:...` | `hold` 行为（KeepBehavior） | `hold_result` 逐项判定（效果为桩判定） |
| T-ASL 机动突击 | 侦察 / 突击 / 评估席位 | `role` + 效果参数 | `assault` 行为 + `assessment` | `assessment_received` 逐项结算 |

前四类的“是否完成”由基座任务状态与行为反馈给出；T-ASL 的效果结论只看
评估回传（默认桩判定），计划报告不代替它。

`to-v2` 仍是**无损性检查**：缺能力就拒绝并不写文件。运行对接不走它，
而是在内存里生成带 `_meta.interop` 的 v2 运行视图；该视图只用于基座
协调/进度/回放，不冒充等价旧场景。

## 2 输入契约

### 2.1 任务消息（4.1）

`schema_version` **只接受 `"0.3"`**；`0.1`/`0.2` 明确拒绝（已确认的外部
接口规则，不做静默兼容）。必填：`message_id`、`issued_at`（ISO 8601）、
`source`（上级/调整/自主或 UPPER/ADJUST/AUTONOMOUS）、非空 `tasks`。

任务字段：`task_id/task_type/priority/target/window/required_capabilities/
min_units/max_units/params`，可选 `depends_on`（或 `prerequisites`，两者
不能同时给）、`allow_split`、`description`。

`target` 必须恰好给出一种：`area/sector/patrol_area/defense_area/route/
point/key_point/target_list`。`window` 用 `{start_s, end_s}`，单位秒。

### 2.2 编成表

沿用 M2 的 `formation.units[]` 字段，并补基座的画像字段（两边字段都保留，
不合并成同一个数）：

| 字段 | 含义 |
| --- | --- |
| `unit_id` / `robot_id` | 规划编号 / 机器人编号（UGV 1–20、TANK 21–30、PLANE 31–40、WING 41–50） |
| `platform_class` / `platform_type` | 四类平台 / 具体类型描述 |
| `position` / `altitude_m` / `heading_rad` | 初始位姿（场景单位、米、rad） |
| `speed_mps` / `endurance_s` / `vertical_speed_mps` | 速度、累计续航、垂向速度 |
| `capabilities` | 能力编码→等级（0–3），4.1 的能力闸门用它 |
| `payload` / `sensor` / `battery` / `work_rate` / `move_cost` / `work_cost` | 基座画像，`to-v2` 与对比适配器用它 |

`meta`：`cell_size_m`（1 场景单位 = 多少米，默认 1）、`grid_cell_m`、
`grid_margin_m`、`plan_id`。`constraints` 支持 `no_go` 与 `threat`
（`intensity`、`applies_to=ground/all`、`height_m`）。

## 3 输出契约（4.2）

| 文件 | 内容 |
| --- | --- |
| `plan.json` | `plan_id`/`assignments`/`commands` + `schema_version=0.3`、`objective`、`objective_metrics`、`metrics`、`unassigned`、`conflicts`、`explain`、`source_message` |
| `assignments.csv` | 每个槽位一行，含路径、里程、风险、能耗、窗口、协同 |
| `commands.csv` | 每条 cmd_vel，含 `command_id`/`attempt`/`action`、六分量、`at_s`、`duration_s`、阶段 |
| `ros2_commands.txt` | 4.2 执行层 → 可直接粘贴的 `ros2 topic pub -r 20 /container_00/robot_XXX ...`（含 at/duration 注释） |
| `report.md` | 指标、分配、执行层、未分配/冲突、解释、口径边界 |
| `manifest.json` | 输入/输出 SHA256、后端、目标、Python 平台、命令 |

**话题命名（2026-10-30 起）**：移动话题为 `/container_00/robot_XXX`（三位编号，
无 `/cmd_vel` 后缀），位姿为 `/model/robot_XXX/pose`；旧 `/rover_XX/cmd_vel`
只存在于历史记录。容器名/后缀可用 `FLEET_CONTAINER_NAME`、
`FLEET_CMD_SUFFIX` 覆盖；桥接命名完全不一致时用
`FLEET_CMD_TOPIC_TEMPLATE`（占位符 `{robot}`/`{robot_no}`/`{no}`/`{container}`）
显式指定整条话题，不在代码里猜。

`assignments[].path` 单位是**米**（已按 `cell_size_m` 折算），不是编成表的
原始场景单位；这是统一层的显式归一化。

## 4 吸收自 M2 的长处

| M2 的做法 | 在 interop 中的落点 | 是否改动语义 |
| --- | --- | --- |
| 4.1 消息与编成表分离、严格校验 | `message.py` | 收紧：只接受 0.3；五类任务均校验，T-ASL 额外校验效果参数与角色席位 |
| 父任务→子任务→分配→指令分层 | `templates.py` / `scheduler.py` / `model.py` | 保留，便于追溯 |
| 能力闸门与拒绝原因 | `gate.py`、`unassigned[].reason` | 保留 |
| 协同组匈牙利匹配 | `assignment.py`、`scheduler._solve_group` | **修**：统一开始时刻，组内平台预留 |
| 三目标（时效/风险/能耗） | `cost.py` | 保留，系数仍为演示值 |
| 风险感知栅格 A* | `routing.py` | 保留，改 8 邻域 + octile |
| 结构化冲突/未分配 | `model.Conflict`、`validate.py` | 保留并补路径穿障碍检查 |
| JSON 全量 + CSV 字段子集 + report | `output.py` | 保留并补 manifest |
| SDF 显式盒体→障碍 | `sdf_scene.py` | 保留，场景生成工具使用 |

**同轮修正的 M2 问题**（对比样例中可复现）：

- 区域/路线拆分段数不受 `max_units` 约束 → interop 取上限；
- `simultaneous_arrival` 只保证同组不同平台，不保证同时到达 → interop
  把所有槽位对齐到同一开始时刻；
- 协同组匹配后平台可能被别的任务抢走 → interop 在组内落实前预留平台；
- 子任务目标在禁入区时整组拒绝（父任务目标同样检查）。

## 5 与基座的关系

保留不动：`CoordinatorV2`（运行协调、取消/确认/重试）、`mock_fleet`、
`behaviors.py`、`city_nav.py`、工作台与轨迹回放、原有 `scenarios/` 与
历史 `outputs/`。

新增的融合点：

- `interop/` 是 4.1/4.2 的**统一入口**，也是中性任务场景的**默认规划器**；
- `runtime.py` 把统一层接进 `CoordinatorV2`：基座只换“规划引擎”，
  下发/反馈/取消/重试/工作台全部沿用；`run_demo_v2 --planner auto`
  优先统一层，突击场景自动回退基座；
- 工作台“新建演示”可选 `interop_neutral` + `融合统一层`，即走同一运行链；
- `to-v2` 先检查旧契约的表达能力。按用户确认，无法无损转换时退出码2，
  一次列出任务行为、几何、依赖、能力、平台参数、约束和时间基准等差异，
  不写文件。当前四个样例均不具备无损转换条件，尚未提供成功转换分支。
  不再把路线取首点、恢复默认画像、丢弃约束后称为融合成功；
- `compare` 用同一输入分别跑 unified、基座 `planner_v2`、M2，输出同口径审计。

## 6 已知差异（对比时不要误读）

- 基座 `planner_v2` 的契约没有 4.1 能力编码，只有 payload/sensor/altitude；
  对比里单列“能力缺口”，不混进算法违规。
- 基座排程只检查完工截止，不检查窗口下界（本轮样例出现 112 s 早于 120 s）。
- 基座计划层没有路径几何，无法静态验证避障，里程记为不可比。
- M2 的能耗/风险系数与基座电量模型不同，**绝对值不能跨后端排名**。
- 本层性能是“离线一次规划”的量级（秒级），不是 20 Hz 在线规划。
- 基座对比适配器是归一化离线实验，固定 `work_rate=1`、`battery=1e6`、
  `work=duration×crew`；JSON附带 `normalization` 与 `runtime_equivalent=false`，
  Markdown显示同一说明。它不等价于旧场景实际运行，现有排名仅针对该实验设定。

`validate` 只接受 schema 0.3，检查容器及记录类型、标识、时刻、机器人/话题、
完整六分量速度及有限数，拒绝布尔时长、NaN/Infinity、重复标识及非零STOP。
4.2最小示例未要求的 `command_id/phase/at_s` 不被擅自升级为必填项；如提供则校验。
未知扩展字段保留。校验通过表示数据结构有效，不证明物理可达、无碰撞或效果达成。

## 7 测试

```powershell
python -m unittest discover -s tests -p "test_interop*.py" -v
```

覆盖：schema 0.3 严格性、source 别名、T-ASL 解析/角色分解/载荷闸门/运行视图、字段/依赖/目标校验、
robot_id 分配、能力等级、分解上限、匈牙利、避障 A*、协同对齐、命令阶段与
STOP、确定性、窗口/能力/禁入区拒绝、审计（窗口/穿障碍/兵力上限）、
输出与 manifest、离线CLI端到端、`to-v2`拒绝有损转换且保护已有输出、
畸形计划与数值边界、对比条件显式披露。未验证真实平台接入。

## 8 区域封控（T-SEC）落地

T-SEC 不再只是"把入口点分给平台"：`templates._decompose_sec` 按
`params.roles` 拆成 **边界段占位 / 通道哨位 / 机动拦截 / 预备队**，边界按弧长
均分、占位点从段中点向内缩 `standoff_m`，几何与执行层共用
`containment_geom.py`。角色写入 `assignments[].role`，并随指令
（`task_block.roles`）下发到基座 `behaviors.ContainmentBehavior`，由它执行
监视 → 警告 → 拦阻 → 处置，产出控制时间线与逐项判定。

- 样例：`scenarios/area_containment.{message,formation}.json`（集结待机区 →
  140×90 m 区域，2 段占位 + 2 个门哨 + 1 个机动组，2 条未授权目标 + 1 条授权目标）。
- 运行：`python -m interop.cli demo ... --motion real --behavior`；工作台场景选
  "区域封控 · T-SEC"，运行后在"演示总览"顶部切到 **区域封控** 页签查看
  （占位平台在岗巡视，警告/拦阻/放行按时间轴播放）。
- 参数、指标口径、未做项：见 `docs/区域封控任务_20261031.md`。

## 9 要点坚守（T-HLD）落地

`templates._decompose_hld` 按 `params.positions` + `params.roles` 拆成
**阵位 / 预备队 / 支援 / 中继**：阵位点与朝向来自 4.1 输入，缺省时按
`threat_directions` 在要点外 `post_radius_m` 处布点（几何在
`containment_geom.py` 的「要点几何」一节，与执行层同一套角度）。兵力上限
裁剪顺序固定为 `support → relay → reserve → post`，**阵位最后裁**。

- 角色：`post:P1` / `reserve:standby` / `support:S1` / `relay:standby`，
  写入 `assignments[].role`，随 `task_block.roles` 下发到基座
  `behaviors.KeepBehavior`（`kind='hold'`，仅在 `_behavior.positions` 存在时启用；
  旧的两点轮换演示仍走 `HoldBehavior`）。
- 执行语义：机动进场 → 占位（达到 `min_on_post` 记 `control_established`，到点后
  在阵位前方**左右游走**）→ 观察（`observation_gap` / `observation_restored`）→
  接替轮换（**接替者到位才撤**，`handover_start` / `handover_complete`；撤离开始时
  在途接替记 `handover_aborted`）→ 增援（`reinforce_triggered` /
  `reinforce_arrived` / `reinforce_timeout`）→ 撤离（`withdraw_started` /
  `withdrawn`）→ `hold_result` 结算。
- 抽象效果：敌方进攻是**输入事件**（`enemy_events`），阵内反击/火力控制可用性
  记为 `counter_attack` 事件与 `suppressed` 状态，判定走 `assessment.Adjudicator`
  的桩实现并写 `verified=false`；不建弹道/命中/毁伤模型，也不在规划层判成败。
- 样例：`scenarios/key_point_hold.{message,formation}.json`（要点 + 东南西北 4 条
  威胁方向 + 4 个正对威胁的阵位 + 1 台预备队 + 1 架空中观察席，共 6 台平台；
  坚守 150 s，含 2 次自动轮换、1 次按敌我比触发的增援、1 次按时撤离、4 次敌方
  进攻含一次后方试探；要点按阵位探测圈做全向覆盖判定，空中席 60 m 盘旋）。
- 运行：`python -m interop.cli demo ... --motion real --behavior --max-ticks 260`；
  工作台场景选 "要点坚守 · T-HLD"，运行后在"演示总览"顶部切到 **要点坚守** 页签
  （阵位在位甘特、增援/接替标记、逐项判定、桩判定清单）。
- 参数、指标口径、未做项：见 `docs/要点坚守任务_20261102.md`。
