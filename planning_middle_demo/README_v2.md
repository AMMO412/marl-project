# 任务规划中间层 · 规划能力版（middle-demo/v2）

在 v1 消息骨架（`run_id / plan_id / command_id / attempt / 反馈核对 / 取消-确认-重试`）**不变**的前提下，把旧版 `planning/` 的六步规则规划器装进来，形成"贴近项目又自洽"的融合版：

- **消息骨架**（来自 v1）：中间层是运行状态唯一写入者、独立消息替身、反馈身份/去重/时间/进度核对、超时只请求取消、失败可重试。
- **规划能力**（来自 `planning/planner.py`）：能力过滤 → 代价打分 → 分配求解（含匈牙利）→ 时序排程 → 冲突消解 → 方案级校验，再加滚动重规划与五类独立触发源。
- **项目贴近**（来自《机器人移动话题说明》与《四类平台参数指标》）：下游 50 台编成、四类平台、每台一个 `/container_00/robot_XXX` 移动话题（2026-10-30 起替换旧 `/rover_XX/cmd_vel`），只有空中平台支持 `linear.z`；能力参数与公开参考参数**分表、不混用**。

本目录是**个人练手与能力建设**的演示，不用于具体作战决策，不连接真实 ROS/Gazebo，也不是已完成的真实交付版本。

## 统一接口融合层（2026-10-30，interop/）

新增 `interop/`：把 M2 的 4.1/4.2 契约、任务分解、能力闸门、协同组匈牙利、三目标与风险 A* 并入本工程，形成一条**只做中性任务**的统一链路：

```powershell
cd planning_middle_demo
python -m interop.cli plan --message interop/scenarios/patrol_checkpoint.message.json `
  --formation interop/scenarios/patrol_checkpoint.formation.json --out ..\outputs\interop_demo\patrol

# 4.1 输入直接驱动基座运行链（规划→下发→反馈→报告/回放）
python -m interop.cli demo --message interop/scenarios/mixed_inspection.message.json `
  --formation interop/scenarios/mixed_inspection.formation.json `
  --out ..\outputs\interop_demo\runtime_mixed --max-ticks 260
```

- 输入：1028 4.1 消息（`schema_version` 严格 0.3）+ 编成表；输出：4.2 `plan.json` / `assignments.csv` / `commands.csv` / `report.md` / `manifest.json`。
- 只覆盖 T-RCN/T-SEC/T-PTL/T-HLD；T-ASL 明确拒绝，不含攻击阵位、`fires`、毁伤判定。
- `interop.runtime` 已接进 `CoordinatorV2`：`run_demo_v2 --planner auto` 对中性场景优先用统一层，含突击/效果判定的场景自动回退基座；工作台“新建演示”可选 `interop_neutral` + `融合统一层`。
- `to-v2` 按已确认规则拒绝无法无损转换的输入，列出任务、参数、约束和时钟缺口，不生成或覆盖场景。运行对接不走有损转换，而是内存中的 `_meta.interop` 运行视图（保留原始 4.1 作为权威输入）。`compare` 是离线规划对比，基座归一化实验条件会单独披露，不能当作同参数执行验证。
- 协调器、反馈、行为层、工作台的行为语义未改；只新增了可插拔规划器入口。说明见 [interop/README.md](interop/README.md)。

## 可视化工作台（2026-10-28）

双击本目录的 `启动工作台.cmd`，或在项目根目录执行：

```powershell
py -3.14 planning_middle_demo/workbench_server.py --open
```

打开 `http://127.0.0.1:8766`。只用 Python 标准库和本地 HTML/CSS/JS，无需 npm、WSL 或新增依赖。端口占用时可加 `--port 8767`。服务只监听本机；关闭启动窗口或按 Ctrl+C 停止。

1. **按任务观看执行**：不显示道路底图；任务窗口可在“图层设置”中单独开关避障碰撞盒。原“跟踪平台”改为“选择任务”。选择任务或点击任务卡片，直接打开接近整窗的大画幅执行回放，从该任务下发时刻以1倍速播放。只显示该任务的成员、路线/检查点/岗位或已记录探索点，不混入其他任务。
2. **大画幅任务回放**：顶部可切换任务，选择“从任务下发看起”或主动“跳到到位后动作”；时间轴仅覆盖所选区间，并显示区间经过时间，绝对仿真时刻在右侧。右侧显示阶段、工作量、行为指标、成员反馈和最近事件。任务结束自动停止，最终动作结构保留；点播放可重播，关闭或Esc返回总览。任务视图复用同一个画布，不新增第二套播放器。窄屏可在窗口内部向下滚动查看细节。
3. **新建演示**：选择场景、异常模式、运动方式、目标及建筑绕障/到位后行为开关，后台复用现有 `run_demo_v2.simulate()`；新结果保存到独立 `outputs/workbench_<时间>/`。到位行为需城市场景逐步运动和建筑绕障。旧记录未启用动作时会明确显示“到点工作量模型”，可点击“载入动作演示”返回已有动作记录。暂停只暂停回放。
4. **实验与报告 / 项目文件**：查看各轮最终统计、下载原始 JSON/JSONL、独立窗口打开本轮报告。原 `trajectory.html` 保留为原始产物；历史行为示例和固定时间轴示意在“项目文件”的参考资料链接中，不另设重复的工作台回放页。

前端在 `workbench/`，服务在 `workbench_server.py`。工作台复用 `trajectory_v2.build_replay_data()` 的反馈数据、动作结构与地标，并读取本地 SDF 盒体。未接 ROS/Gazebo。已有动作记录与历史工作量模型分别标注，不据页面完成数推断物理执行或验收结果。

**完整过程起点已修正**：选择任务默认从下发时刻开始，先显示实际接近过程，默认使用空间回放。主播放器“重新开始”回到完整任务起点；主动跳到到位后动作时，来源栏明确注明跳过了多少秒。推荐入口不再预设中途时间。原并行J4记录为72秒下发、110秒行为启动、111秒进入执行；旧默认跳过了38秒接近过程。重合点不再标成正常“已到执行位”，显示“动作未验证”及数据质量提示。本轮仅修回放与标签，原记录点位退化问题仍未修复。浏览器逐项核对1642个任务视图时刻，无脚本错误；证据在 `.work/workbench_replay_start_20261028/verification.json`。

**当前推荐观看方式**：打开 [突击专项空间回放](http://127.0.0.1:8766/?source=behavior_20261028_verify&task=J4&view=spatial)，在同一任务窗口切换“动作详解 / 空间与避障”。任务窗口的数据来源可切换“专项验证记录（串行）”与当前并行运行，切换会重新载入完整数据，不拼接不同记录的成员或时钟。原有运行默认仍保留。

**突击与坚守的主画面**：突击按机动集结、全员到位、执行动作、结果确认四阶段展开，每位成员有独立轨道，并区分已到位等待协同与仍在移动；阶段卡可点击跳转。坚守直接显示主班/接班侧与角色时间带，时间带只填已播放部分。空间视图使用按阶段固定的近景镜头，标出各成员集结位、执行位与已记录确认目标；坚守不再把未使用的待命位计入镜头。两种视图共用同一画布和时钟，小屏过程图可横向查看。

**已定位的数据问题**：`workbench_20261028_174224_708566` 的J4结构记录中，四个集结位和四个执行位均为 `[30.26,27.06]`。界面会标明点位重合并按成员拆开展示，不修改坐标制造展开效果。用户指定的 `behavior_20261028_verify/behavior_trace.json` 已通过 `workbench_recording.py` 只读接入工作台，来源明确标为串行专项记录。适配器保留原始坐标、事件、路径；只把路径局部时间转换为全局时间，片段边界单独命名，不伪造规划或采纳反馈；缺少的规划/能耗指标不补造。独立页面无需打开，也未被本轮修改。

本轮验证：88项Python测试通过，逐项核对专项记录的5190个成员位姿、165条事件及99条路径；浏览器检查两份记录、六任务及两种视图共904个时刻，验证数据源切换、阶段点击、镜头固定、单时钟、标签避让和返回总览，无页面脚本错误。证据在 `.work/workbench_task_clarity_20261028/verification.json`、`source-proof.json`，截图为 `outputs/工作台展示_20261028/task-*-v2.png`。以下同日验证记录保留为历史。

**任务细节已在工作台实现**：坚守任务使用固定成员色、岗位/待命位、当前角色卡和可点击的交接时间带；两成员任务只展开实际使用的交接岗位，不展示未使用的第二岗位。侦察任务按已记录测绘点逐渐显示传感覆盖，并标出当前目标。路径图层显示当前记录的规划路径；已发生的受阻绕行可在侧栏回看，早于当前观看区间时会切换到任务下发区间。实线为已行轨迹，虚线为规划路径，灰块为碰撞体；净空为规划指标。

新运行通过审计事件 `behavior_detail` 记录角色、参数和增量路径，通过 `approach_route` 记录接近路线；界面使用事件的绝对 `sim_s`，不把行为内部局部时间当全局时刻。旧日志缺少路径信息时明确提示。默认优先载入有细节日志的最新运行，参考串行回放不混入工作台的并行执行数据。

2026-10-28工作台细节验证：运行 `outputs/workbench_20261028_174224_708566/`，6/6完成，仿真187秒。与原工作台记录相比，原有报告字段及953条规划/反馈/状态审计完全一致（含904条采纳反馈）；新增展示用诊断。85项Python测试及六任务共318个执行时刻检查通过，无页面错误；验证了角色切换、节点/路径跳转、旧日志和1366×900窗口。证据在 `.work/behavior_visual_refine_20261028/final-qa.json`、`final-data-proof.json`，展示截图在 `outputs/工作台展示_20261028/workbench-*.png`。

2026-10-28本轮界面合并验证：84项Python测试通过；浏览器核对所选动作记录的188个时刻及关键阶段，包含旧记录切换、原报告打开、图层/平台跟踪、播放暂停和390px窄屏，无脚本错误。原 `workbench_behavior_20261028` 的8个文件哈希未变；本轮直接读取该记录，未重新生成。证据在 `.work/workbench_unify_20261028/`，截图在 `outputs/工作台展示_20261028/unified.png`。

2026-10-28展示降噪验证：浏览器核对188个全局时刻、10秒尾迹及到位分段、固定镜头、完成后收起、标签不重叠、完整轨迹开关、节点跳转和390px窄屏；无页面脚本错误，8项工作台相关Python测试通过。原动作目录8个文件哈希不变。本轮只改前端展示，证据在 `.work/workbench_focus_20261028/`，截图为 `outputs/工作台展示_20261028/global-clean.png`、`focus-clean.png`。

2026-10-28按任务大画幅版本验证：无头Edge逐项检查六个任务共318个时刻；在1600×1050视口下，画布为1239×约621。检查了从执行开始自动播放、仅显示任务成员、任务区间与相对时钟、完成后重播、切换任务、返回总览、Esc和390px窄屏，无脚本错误；8项工作台相关Python测试通过。原动作目录8个文件哈希未变。证据在 `.work/workbench_task_theater_20261028/`，截图为 `outputs/工作台展示_20261028/task-patrol-large.png`、`task-exploration-large.png`、`task-handover-large.png`。下面早期展示验证记录保留为历史。

## 独立串行行为回放

用户指定的已有记录在 `outputs/behavior_20261028_verify/`，双击其中的
`behavior_demo.html` 即可离线查看。默认选中要点坚守；点击播放，或用关键事件
按钮定位接替前后。成员采用固定颜色和引线标签，画面下方的角色时间带只显示
已播放的记录，当前接替次数与整段最终统计分开。协同侦察原有绘制逻辑保留。

`hold_preview.gif` 为原记录接替段的约2.5倍速预览。本次仅刷新HTML展示，
没有重新生成 `behavior_trace.json`、改变实际运动位置或修改行为算法；该记录
按任务串行组织，与工作台并行运行是不同记录。验证证据在
`../.work/behavior_display_20261028/verification.json`。

## 与 v1 的区别

| 维度 | v1（`contracts.py` 等） | v2（`*_v2.py`） |
| --- | --- | --- |
| 作业语义 | 工单（`duration_s`） | 通用任务（工作量/时间窗/协同人数/载荷/传感器/目标高度） |
| 分配 | 先来先服务，交给空闲工位 | 六步规划器 + 匈牙利一对一最优（crew==1） |
| 平台 | 抽象 worker | 下游 50 台编成（UGV/TANK/PLANE/WING 号段） |
| 优化目标 | 无 | makespan / energy / dispersion（可切换） |
| 成员变化 | 无 | 局中失联 → member_change 重规划 |
| 偏差检测 | 无 | 进度落后 → deviation 重规划 |
| 触发源 | — | init / member_change / exec_fail / timeout / deviation / periodic |

v1 的 17 项测试原样保留并通过，v2 另加 17 项。

## 时间语义（关键，勿改）

这是把规划器装进消息骨架时唯一踩得深的坑，记清楚能省一整天：

- `Assignment.start` = **开工时刻**（非承诺作业 = `now + travel`）；`end` = `start + dur` = **完工时刻**。
- 下层（`mock_fleet`）默认**瞬移语义**：到 `start_sim_s` 即视为已到达作业点，不逐步模拟在途——这正是 `planning/executor.py` 原版的做法（"开工即视为已到达"）。逐步在途会让平台位置在滚动重规划中漂移，travel 反复被重算，作业永远做不完。
- `KEEP_COMMITMENT`：滚动重规划时保持上一版已派出的指派（pids + 原 start），排程用 `max(now, keep[jid][1])`，否则开工基准每滚一次就往后挪一次。
- **偏差检测必须用固定基准**（`job.started_at` / `job.planned_end`，首次下发时记录），不能用当前计划的 `a.start`——滚动重规划会重置 `a.start`，用它会反复清零期望进度，lag 永远累积不到阈值。

### 真实运动语义（`--motion real`，新增）

瞬移语义只出"账"不出"戏"：中间层产出的指令能下发，但下层替身不真动。真实对接时下游只有速度级 `Twist` 接口（没有"到达目标点"接口），规划层"去某点"与下游"逐拍发速度"之间的翻译必须由我们补。于是把 `planning/bridge.py` 的 `GoalController` 移植为 `motion.py`，作为可选的真实运动模式：

- **闭环控制**：每步内部推进约 20 拍 Twist，读位姿重算指令，到位靠容差判定（不是"算步数"），因下游 RTF 不确定、"速度×秒数"推不准位移。
- **先转后走**：差速/简化偏航都不能横移（`linear.y` 恒 0），航向没对准时只转不走。
- **只有飞机能爬升**：`linear.z` 仅 PLANE/WING，地面平台 z 恒 0。
- **时间模型与运动同源**：规划器的 travel 估算在真实运动下改用 `motion.estimate_arrival_steps`（与运动层同一控制器预演），**带平台当前朝向**（转向耗时）和**作业高度**（爬升耗时）。若还用瞬移口径 `ceil(距离/速度)`，会系统性低估到达时间，导致 deviation/timeout 误判、作业被冤枉超时。

关键结论（这也是"对接后不废"的实证）：**瞬移语义会掩盖真实运动的时间成本**——带高度作业的爬升、平台转向、加速减速，都会被"距离/速度"一笔带过。真实运动模式把这些成本显式纳入规划，才是能对接真实下层的口径。

### 到位之后做什么：行为层（新增 `behaviors.py`）

原来的执行层只有一句"每步贡献 `work_rate`"：平台到了作业点就原地刷进度，五类任务在代码里没有区别。现在把五类任务的动作补成状态机，**只做决策**（每步返回各平台的下一目标点、阶段、事件），运动交给 `city_nav`：

| 类型 | 代码类 | 规则（可调参数在 `DEFAULTS`） | 关键指标 |
| --- | --- | --- | --- |
| 巡逻警戒 | `PatrolBehavior` | 绕作业区生成闭合环路（半径/检查点数可调），按检查点推进；多机沿环错开 | `revisit_s` 一圈重访间隔、检查点访问序列 |
| 区域封控 | `BlockadeBehavior` | 封控圈按弧段分配岗位；外圈发现入侵者后，最近的平台解算拦截点前出，其余守位 | `intercept_t`、`intruder_start`、事件 `intrusion_detected/intercepted` |
| 协同侦察 | `ReconBehavior` | 共享占据栅格，各机奔向"已知区旁边的未知格"（前沿），到达后按传感器半径并入共享地图；覆盖达标后回传 | `coverage`、`cells`、事件 `map_shared/report_sent` |
| 机动突击 | `AssaultBehavior` | 机动（分进）→ 到位（全员齐）→ 执行（收拢到目标环并处置）→ 结果确认（前出观察点） | `phases` 阶段时刻、事件 `all_staged/effect_applied/confirmed` |
| 要点坚守 | `HoldBehavior` | 主班在位、副班待命；到换班时刻副班先到位，**接替完成才撤**；统计零人在位时长 | `handovers`、`presence_gap_s`、`min_present` |

行为层不直接改位姿：`behavior_runtime.py` 每 1 个仿真步问一次行为要目标，步内用 10 拍 × 0.1 s 闭环跟随执行，并记录逐拍轨迹。因此状态机可以脱开运动学单测（`tests/test_behaviors.py` 用"瞬移执行"验证阶段语义）。

### 真实避障：从直线到绕建筑（新增 `city_nav.py`）

原先 `motion="real"` 只是"先转向再直行"，两点之间被建筑挡住也照走。现在：

1. **障碍来源是真实几何**：解析 `assets/city/simple_city.world` 的 `<include>` 位姿，叠加本地模型 `model.sdf` 里的**显式盒体碰撞**（`geometry/box/size`），按场景 `_meta` 的 `(米 + offset) × scale` 换算到场景坐标。当前 5 个模型共 7 个盒体（含警察局 13 m 见方的主楼）。网格碰撞不猜尺寸。
2. **膨胀栅格 A***：半径 0.6 场景单位（≈1.7 m）的膨胀，8 邻域 + 对角线，路径代价按实际步长；A* 后用"整段可通行"的视线捷径平滑。
3. **路径跟随**：`PathFollower` 取"前瞻范围内、从当前位姿直线可达的最远点"，避免拐角处瞄准墙后点而切角；前向 0.3 拍投影做安全闸，触发即局部重规划。
4. **点位吸附**：作业点常取建筑中心（如警察局），先 `nearest_free` 吸附到最近可通行点，吸附距离写进 `metrics.site_snap_offset`，不悄悄挪点。
5. **接入规划闭环**：`run_demo_v2.py --motion real --avoid` 时，地面平台按 A* 路径逐航点跟随；空中平台保持直飞（越障假设成立，`can_climb` 才允许）。

`behavior_demo.py` 把整条链路串起来：`planner_v2` 出指派 → 每台平台按 A* 绕障机动 → 到位执行对应行为 → 输出 `behavior_trace.json` + 自包含 `behavior_demo.html`（建筑、绕行路径、直线对比、逐拍回放、阶段时间条）。作业按计划开工顺序串行重放，便于看清同一平台跨作业的先后。

**行为层已接入工作台主链**（`--behavior`，2026-10-28）：`run_demo_v2.simulate(behavior=True)` 在真实运动 + 绕障下，平台到位后由 `mock_fleet` 驱动对应 `Behavior` 状态机（不再原地刷 `work_rate`），行为目标点经 `nav.plan` 做 A* 绕障后逐拍跟随。行为推进度（圈数/覆盖率/阶段）经 `progress_frac` 映射回作业进度，行为完成（`behavior_complete`）即作业 `succeeded`；行为细分事件走独立审计通道（`behavior_event`），由工作台时间轴与 `trajectory.html` 展示。规划器的作业时长改用 `BEHAVIOR_DURATION` 经验预估（行为完成由状态机判定，与 `work` 线性模型解耦），行为作业不参与 deviation/timeout 误判（行为层自带 `max_steps`/圈数兜底），时间窗只作排程参考。

避障的边界也要说清：这是**已知静态地图**上的路径规划，不是 SLAM/动态避障；地图只含上述 7 个盒体，其余建筑因碰撞体是网格而未建图。扩大地图只需往 `assets/city/models/` 放盒体碰撞的 SDF，不用改代码。

## 运行

只使用 Python 标准库，Windows 侧即可（无需 WSL/Gazebo）：

```powershell
py -3.14 planning_middle_demo/run_demo_v2.py                 # normal（瞬移）
py -3.14 planning_middle_demo/run_demo_v2.py --mode failure  # 任务级失败一次
py -3.14 planning_middle_demo/run_demo_v2.py --mode timeout  # 在途停滞触发超时
py -3.14 planning_middle_demo/run_demo_v2.py --mode kill     # 局中失联一台平台
py -3.14 planning_middle_demo/run_demo_v2.py --mode deviation # 进度落后触发偏差
py -3.14 planning_middle_demo/run_demo_v2.py --motion real --max-ticks 150  # 真实运动

# 真实城市场景（作业点/平台位取自 OSRF citysim 真实建筑与道路坐标）
py -3.14 planning_middle_demo/run_demo_v2.py --scenario planning_middle_demo/scenarios/simple_city.json
py -3.14 planning_middle_demo/run_demo_v2.py --scenario planning_middle_demo/scenarios/simple_city.json --motion real --max-ticks 200
py -3.14 planning_middle_demo/run_demo_v2.py --scenario planning_middle_demo/scenarios/simple_city.json --motion real --avoid --max-ticks 200  # 带绕障
py -3.14 planning_middle_demo/run_demo_v2.py --scenario planning_middle_demo/scenarios/simple_city.json --motion real --avoid --behavior --max-ticks 250  # 带绕障 + 到位后行为

# 五类任务到位行为 + 避障可视化（自包含 HTML，可离线打开）
py -3.14 planning_middle_demo/behavior_demo.py

py -3.14 -m unittest discover -s planning_middle_demo/tests -v
```

### 数据驱动的 timeline 与 rules（改实验不改脚本）

实验事件（导调事件）可由场景 JSON 的 `timeline` 段描述，规则参数由 `rules`
段配置——**加一个实验只需改场景文件，不用改 `run_demo_v2.py`**。

`timeline` 是事件数组，每项 `{t, event, ...}`，`t` 为绝对仿真步：

| event | 字段 | 语义 |
| --- | --- | --- |
| `member_lost` | `robot_no` | 第 t 步该平台失联（全局事件，与作业无关） |
| `job_fail` | `job_id` | 第 t 步（或作业在途后）该作业任务级失败一次 |
| `job_delay` | `job_id`, `delay` | 第 t 步（或作业在途后）该作业在途延迟 `delay` 步 |
| `job_slow` | `job_id`, `factor` | 第 t 步（或作业在途后）该作业进度按 `factor`(0,1) 打折 |

```json
{
  "timeline": [
    {"t": 3, "event": "job_fail", "job_id": "J1"},
    {"t": 5, "event": "member_lost", "robot_no": 21}
  ],
  "rules": {"max_attempts": 2, "dev_threshold": 2.0, "grace_s": 1}
}
```

- `job_*` 事件在 `now >= t` 且目标作业**已在途**时触发；若 t 时刻作业尚未
  下发，事件等待作业在途后立即触发（"让作业失败"必须等作业先开始）。
- 事件按 t 升序执行，同一步多事件全部执行，不互相吞；同一事件只触发一次。
- `mode`（failure/timeout/kill/deviation）仍保留，是"预设 timeline"的快捷
  入口；不传 `mode`（normal）+ 自定义 timeline 即可纯数据驱动。

`rules` 只开放**明确需要配置的参数**（`dev_threshold` / `grace_s` /
`max_attempts`）。**能力约束检查（续航/载荷/高度/传感器/运动性能）由
`planner_v2.feasible` 代码执行，不能通过场景文件开关或关闭**——任何试图
关闭检查的字段（如 `disable_battery_check`）都会被场景校验拒绝。

**真实场景说明**（`scenarios/simple_city.json`）：

- 坐标来自 [OSRF citysim `simple_city.world`](https://github.com/osrf/citysim/blob/3928b08e2598f5ead2e9b24640fe1bde262a136d/worlds/simple_city.world)（真实 Gazebo 城市，含消防站/警察局/发电厂/桥梁/无线电塔等 621 个对象与 11 段道路），经解析脚本提取（见 `outputs/gazebo_assets_2026-10-26/`）。
- 场景坐标为 `(真实米坐标 + offset) × scale` 的线性映射，**相对位置与道路拓扑为真实值**；每个对象的原始米坐标记录在其 `_src_xy_m` 字段，`_meta` 记录缩放因子与来源。`_` 前缀字段仅供追溯，不参与规划决策。
- 作业点贴合五类任务语义：巡逻=道路路口、封控=桥梁入口、侦察=无线电塔（高空）、突击=警察局、坚守=发电厂/办公楼。
- 场景声明 `H=35 / K=8`（真实地理跨度比手编场景大，需要更长规划视野）；`--H/--K` 未显式指定时默认读取场景声明。

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `--scenario` | `scenarios/fleet_demo.json` | 平台与作业列表 |
| `--mode` | normal | normal / failure / timeout / kill / deviation |
| `--motion` | teleport | teleport=瞬移（规划快进），real=真实运动（GoalController 闭环） |
| `--avoid` | 关闭 | 地面平台按真实建筑轮廓做 A* 绕障（需 `--motion real`） |
| `--behavior` | 关闭 | 到位后运行行为状态机（巡逻/封控/侦察/突击/坚守），需 `--motion real --avoid` |
| `--max-ticks` | 60 | 最多推进多少个仿真步（real 模式建议 ≥150） |
| `--max-attempts` | 2 | 每个作业最多尝试几次 |
| `--grace-s` | 1 | 超时的容忍量 |
| `--H` | 场景声明（缺省 20） | 规划视野（步） |
| `--K` | 场景声明（缺省 5） | 滚动重规划周期（步） |
| `--dev-threshold` | 4.0 | 偏差触发阈值（工作量） |
| `--out` | 新建带时间名称目录 | 必须尚不存在，避免覆盖原实验 |
| `--quiet` | 关闭 | 控制台略去逐条事件 |

产物目录含 `manifest.json / scenario.json / report.json / trace.jsonl / summary.txt / report.html / trajectory.html`（HTML 离线自包含）。

### 动态运动回放

打开 `trajectory.html`，点击“播放”即可看各平台如何移动；支持暂停、重播、倍速、逐步前后查看及拖动时间轴。点击图中编号、表格行或平台下拉框，可突出单台轨迹，查看当前作业、坐标、高度及电量。报告顶部也有回放入口。

- 颜色区分单台平台，形状区分类别；编号按 `robot_no` 与编成表对齐。全部平台均显示，包括未分配或没有位置反馈的平台。
- simple_city 回放内嵌本地 `roads.csv` 的道路和场景中的地标，按 `_meta` 映射到反馈坐标，可分别开关；缺失素材时退回坐标网格。底图展示不等于已实现沿道路寻路。
- 轨迹只画到当前时间；累计路程为位置反馈的逐段平面距离总和，另列起终点位移。高度独立显示；电量是电量单位，不是百分比。
- `real` 是本地逐步运动模拟。播放只对相邻逐步位置记录做显示插值；`teleport` 按时刻跳变，不补画运动。反馈稀疏时保留最近位置，不推测轨迹。
- 已有运行可以只重建回放，不重跑模拟或改动原始 JSON/JSONL（在项目根目录运行）：

```powershell
py -3.14 planning_middle_demo/trajectory_v2.py planning_middle_demo/outputs/<运行目录名>
```

`trajectory_player.html` 是播放器模板，须随 `trajectory_v2.py` 一起保留；生成的 `trajectory.html` 本身不依赖模板或网络。

执行器对五类任务的执行有两种口径，由 `--behavior` 区分：默认（关闭）沿用"到点后按效率累加工作量"的抽象，类型区别来自工作量、时间窗、协同人数、载荷、传感器与高度参数；开启 `--behavior`（需 `--motion real --avoid`）后，到位由 `behaviors.py` 的对应状态机接管，完成判定由行为语义给出（巡逻 3 圈、封控拦截处置、侦察覆盖回传、突击结果确认、坚守换班轮换）。回放遵循原日志，`trajectory.html` 与工作台时间轴会展示行为阶段与细分事件。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `fleet.py` | 下游 50 台编成（号段/话题/位姿话题）、四类规划参数（我方暂定）、公开参考登记 |
| `contracts_v2.py` | 平台/作业/指令/反馈契约 + 场景校验（含 timeline 事件与 rules 参数校验） |
| `planner_v2.py` | 六步规则规划器（自 `planning/planner.py` 移植） |
| `coordinator_v2.py` | 反馈消费、五类重规划触发、下发调度、超时取消重试、偏差检测 |
| `mock_fleet.py` | 独立消息下层：瞬移/真实运动两种在途语义、作业推进、耗电、噪声注入、成员损失、绝对步 timeline 事件；行为模式下到位后驱动 `behaviors` 状态机 |
| `motion.py` | 目标点→Twist 闭环控制器（自 `planning/bridge.py` 移植），供 mock_fleet 与真实下层复用 |
| `run_demo_v2.py` | 入口、五种演示模式、产物导出 |
| `reporting_v2.py` | 文本 + HTML 报告 |
| `scenarios/fleet_demo.json` | 10 台四类平台 + 6 作业（覆盖高度/载荷/传感器/协同），手编坐标 |
| `scenarios/simple_city.json` | 真实城市场景（OSRF citysim `simple_city.world`）：作业点/平台位取自真实建筑与道路坐标，`_meta` 记录缩放因子与原始米坐标 |
| `sdf_state.py` | 从甲方 SDF 提取规划初始状态（50 台平台位姿/尺寸、障碍、道路、地标），生成 `scenarios/sdf_initial_state.json` |
| `scenarios/sdf_initial_state.json` | 生成物：SDF 初始位姿与三维尺寸；工作台也读它画道路/建筑标签，改 SDF 后需重跑 `sdf_state.py` |
| `tests/test_mixed_fleet.py` | SDF 提取值、角色级载荷校核、空地面分流、辅助指标逐项结算 |
| `tests/test_flow_v2.py` | 消息骨架纪律 + 规划器不变量 + 真实运动语义 + 真实场景 |
| `tests/test_timeline_rules.py` | timeline 数据驱动事件 + rules 可配置参数的校验与行为（缺省一致/配置生效/错误拒绝/顺序/重复/隔离） |

## 已验证结果

2026-10-26，Windows Python 3.13.12（代码通过 Python 3.8 语法检查）：

| 模式 | 完成 | 重试 | 超时 | 触发源 |
| --- | --- | --- | --- | --- |
| normal | 6/6 | 0 | 0 | init + periodic |
| failure | 6/6 | 1 | 0 | exec_fail |
| timeout | 6/6 | 1 | 1 | timeout |
| kill | 5/6 | 0 | 0 | member_change |
| deviation | 6/6 | 0 | 0 | deviation（检测→加人→修复） |

kill 模式少 1 个作业是成员损失的真实后果：失联后某个协同作业凑不齐 crew，如实上报，不是 bug。指标只用于内部相对比较，不对标绝对阈值。

## 边界

- 平台能力参数（速度/效率/续航/载荷/传感器）为**我方暂定**，真实值到位只改 `fleet.PLANNING_PARAMS` 一张表；公开参考参数（`config/platform_references.json`）只展示、不参与决策。
- 未连接 ROS/Gazebo 真实执行；`cmd_vel` 发令纪律（单一持续发令源、停止显式全零、约 20 Hz）已写进指令投递块，真实话题对接时替换 `mock_fleet` 即可。
- 能力边界校验不能只靠规划器闸门：奖励/规则不是保证，真实系统仍需下发前闸门（本层已在下层替身里复现"第二道闸门"）。
- **本层对应《技术实施方案》的 M2（导调响应）+ M4（训练决策）**，是横跨模块的"任务规划中间层"，不是独立平台模块。M1 仿真 / M5 采集 / M6 UE5 / M7 部署 / Bridge 属平台侧，本目录不做，只在下发/反馈里对齐它们的接口形状。
- **多智能体分组 / 角色（攻击者/防守者/协同者）/ 通信信道 / 共享观测 / 课程学习属平台 M3 配置能力**，由智能体训练层消费，不在本层实现；本层只负责"把作业派给平台"，不定义平台之间的协作角色或通信拓扑，也不展开"攻击者/防守者"这类角色定义。
- 13 类接口与想定五段 Schema 的逐条对照见 `docs/接口与想定Schema对照.md`。

## 五类任务的动态示意图

`outputs/task_motion_schematics_20261027/index.html` 是按六张用户参考图制作的独立可视化：

- 巡逻警戒：闭合路线循环、检查点亮起与重复经过时间轴。
- 区域封控：不规则区域、边界运动及预设支线返回。
- 机动突击：三条到位曲线、停留、执行图标与确认标记。
- 协同侦察：三间房的预设运动、灰色区域显现与共享图动画。
- 要点坚守：持续停留、进入/离开曲线及交接重叠时间带。

支持播放、暂停、重播、逐秒、倍速、循环、拖动时间轴、编号/尾迹开关、参考图对照和键盘操作。每种画面时长36动画秒；位置、阶段和事件均由固定曲线及关键帧绘制，不调用任务规划器、执行器或机器人接口，也不表示本地模拟或业务验收结果。原运行数据不改变。

源码为 `task_motion_schematics.html`，生成脚本为 `generate_task_schematics.py`。生成时读取包含 `image-1.png` 到 `image-6.png` 的目录：

```powershell
py -3.14 planning_middle_demo/generate_task_schematics.py --references "<六张参考图所在目录>"
```

产物内嵌原始图片，可将单个 `index.html` 复制到别处离线打开；同目录 `manifest.json` 记录原图哈希和示意动画口径。

## 2026-10-29 新 SDF 上的 T-ASL 机动突击演示

`scenarios/asl_container.json` 把 `资料/接口说明/container_00_combined_scene.sdf` 接入本层：39 个内联静态模型中 24 个盒体进入障碍（地面/道路/广场顶面 ≤0.2 m 不计），平台 001/021/022/023 从 SDF 起点出发，`rover_01` 为侦察指示组，其余 3 台为突击组；目标点 ASL-1=(100,-65)，集结区 (35,-38)，观察点 (100,-40)，撤离点 (75,-50)。`contracts_v2` 允许 `type` 作业用 `window` 覆盖模板时间窗，供真实距离使用。

```powershell
py -3.14 planning_middle_demo/behavior_demo.py --scenario planning_middle_demo/scenarios/asl_container.json --out planning_middle_demo/outputs/asl_20261029
```

本次结果（单次运行，非统计）：总时长 291 s；突击组集结到位 57–65 s，侦察组到位并指示目标 127 s；突击开始 128 s；同时到达偏差 2 s（阈值 3 s）；开始处置 221 s（攻击窗口 60–260 s 内）；处置结束 231 s；外部评估回传 246 s（时延 15 s）；撤离 44 s（限 60 s）；总体状态“成功”。6/10 条直线被建筑阻挡，接近路径绕行比 1.009。

口径与限制：评估源为 `constructed_assessment_stub`，属构造数据，不是已接入评估接口；命中率、我方损失、附带损伤未建模；规划速度仍为暂定示例值，未按 SDF 声明的 0.5 m/s 限速；9 处外部引用缺几何，不构成完整地图无碰撞证明；planner 的 plan_start/plan_end 不含评估与撤离，时序以行为 t0/t1 与阶段记录为准。

### 16 台容量验证（单作业）

`scenarios/asl_container_16.json` 用 16 台 UGV（robot_001—016）跑单个 `assault`，作业契约现在允许 `crew` 覆盖模板的 4 台。001 为侦察指示组，002—016 为突击组；目标 (45,-45)，集结区 (20,-30)，集结/攻击环半径 10/12 m。

```powershell
py -3.14 planning_middle_demo/behavior_demo.py --scenario planning_middle_demo/scenarios/asl_container_16.json --out planning_middle_demo/outputs/asl16_20261029
```

结果：16 台全部被指派并到位，184 s 完成；集结 79 s、突击开始 80 s、全员占位与开始处置同为 120 s、评估回传 145 s、撤离 38 s；同时到达偏差 1 s（阈值 10 s），状态“成功”。该目标在开阔区，46 段路径 0 段被建筑阻挡，不能作为避障证据；避障证据仍取 4 台场景的 6/10 段被阻挡与 1.009 绕行比。

边界：SDF 共 50 台，但本层只让 001—030 的地面平台满足突击载荷≥4；031—050 为空中平台，载荷 1.5—2.0，不参与突击。`behavior_demo` 仍是单作业串行重放，“16 台在同一个突击作业里同时行动”已验证；“多作业并行”未验证。环半径必须随台数放大，16 台在 6 m 环上间距约 2.4 m，小于 2×1.75 m 包络，会重叠。

### 城市十字路口建筑群突击（asl_city）

场景最初按 16 台（1 侦察 + 15 突击）验证容量，2026-10-29 收到反馈"一个任务安排太多智能体、太乱"后编成降为 **6 台**——16 台时标签互相遮挡、轨迹线过密，6 台能一眼看清分进路线与阶段推进。同日按《T-ASL 效果判定与逐项结算实现规范》调成侦察/突击/评估三组；**2026-10-29 晚再按"兵力包按角色编成"改成多类型混编**：`rover_31` 固定翼（侦察指示组，巡航 30 m）、`rover_41` 飞翼（评估组，巡航 25 m）、`rover_21/22` 履带与 `rover_01/11` 轮式（突击组）。当时 6 台全为轮式车，工作台上只看得出"一堆方块"，看不出编成差异，这是本轮返工的直接原因。要恢复 16 台：把 `platforms` 加回 16 行、`crew` 改 16 即可（16 台容量验证另见 `asl_container_16` 一节）。

任务点改为 SDF 里左侧带十字路口的建筑群：`env_city_square` 广场（34×34 m，位于 (-95,-145)）与南北/东西两条城市道路的交叉口，四角是 4 栋 `House`（x=-137/-53，y=-185/-105）和 2 栋 `Office Building`（x=-165/-25，y=-145）。目标点取广场中心 (-95,-145)；集结区在目标东北、被 House 4 遮挡的背敌一侧 **(-62,-124)、半径 6 m**，4 台地面平台从出发列到集结区的直线全部被 House 4 挡住（绕行比 1.03–1.05），空中平台直飞；撤离点是目标西南 25 m 的收拢点 (-75,-130)。

集结区一开始放在办公楼东侧的道路上 (-5,-145)，路线确实绕楼、避障证据最足，但全程约 300 m（起点→集结 123 m、集结→路口 90 m、撤离 ~90 m），需要 130–144 电量，而 UGV 只有 100（续航≈250 m）——16 台没有一台够。按"把行为段里程纳入规划估算"的口径处理时，那版几何会被闸门整单拒收，因此把集结区移到了斜向接近线上（仍是场景输入，不是让程序自动选点）。代价是绕行段数减少（46 段里 5 段被建筑挡住，而非 25 段），避障能力本身仍由 `test_city_nav` 里"直线穿办公楼→绕行"的用例保障。

建筑在 SDF 里是 `<include>`，本身没有尺寸，占地得从本地模型算：`资料/接口说明/models` 下放了 Fuel 官方 `House 1/2/3`、`Office Building`，`city_nav.mesh_aabb` 读 COLLADA 的 positions 数组并按视觉场景节点变换（这批文件的 `<matrix>` 是行主序，单位是 inch，按 `<asset><unit meter>` 换算），得到 6 处网格包围盒；办公楼实测 17.6×25.7 m、高 26 m。`load_sdf_obstacles` 现在同时收内联 `<model>` 盒体和 `<include>` 模型，城市场景障碍 13 处（7 处花坛/标识柱 + 6 栋建筑），缺本地模型时记入 `missing` 而不臆造。

```powershell
cd planning_middle_demo
py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json --motion real --avoid --behavior --max-ticks 620 --out outputs/asl_city
py -3.14 behavior_demo.py --scenario scenarios/asl_city.json --out outputs/asl_city_behavior
```

主链结果（`outputs/asl_city`，16 台版）：16 台全部指派，356 s 结算完成。机动与集结在任务时钟内推进：受领任务 t=1 s，侦察指示与全员集结 t=184 s（侦察台先到观察位），突击开始 t=185 s，全员到执行位 t=283 s（同时到达偏差 3 s，阈值 12 s），效能施加与达成 t=283→293 s，结果待评估 t=293 s，评估回传与确认 t=313 s（延迟 20 s），撤离 t=313→356 s（43 s，限 180 s 内）。结算时 16 台剩余电量 13–42，无 `energy_depleted`。行为内部 46 段路径 5 段直线被建筑阻挡。独立演示（`outputs/asl_city_behavior/behavior_demo.html`）同一场景复算为 357 s、13 处障碍、6/46 段被阻挡。降为 6 台后工作台运行 `workbench_20261029_145325_801085`：350 s 结算、步骤条 机动 0 / 全员到位 183 / 执行 184 / 结果确认 291 / 撤离 354 s，阶段节奏与 16 台版一致。

**机动时长的坑（2026-10-29 已修）**：早期实现里替身先把平台"送到"集结位才创建行为 runner，行为时钟从 0 起表，于是工作台显示"机动集结 0 s / 全员到位 0 s"，看起来像瞬移。现在 `_ensure_behavior` 在指令下发当步就建 runner，机动、集结、突击、撤离全部由行为层按实际路径推进；替身也不再另算一条不会执行的"去作业点"路线（旧实现那条路会出现在轨迹与路由统计里，等于虚报一段行程）。回归用例 `test_assault_maneuver_is_not_teleported` 同时校验"集结与受领之间有真实机动耗时"和"反馈相邻两步位移不超过速度"。

**删替身路线连带暴露的搁浅坑（2026-10-29 已修）**：行为层改为从平台**原始位姿**直接起跑后，simple_city 的 rover_01 出生点本身落在建筑膨胀圈内，A* 报 `start_in_obstacle`，J6 巡逻永久 0 进度、rover_01 一直占着不放，连带 J5 每轮都因"成员忙"派不出去（旧实现由替身 approach 路线的 `nearest_free` 吸附兜底，删路线后兜底没了）。修法是 `behavior_runtime._plan_leg` 在起点落障碍时吸附到最近可通行点再试，吸附位移用 `start_snapped` 事件显式记录（不悄悄挪点、不计里程），事件名已进工作台与 `trajectory_v2` 词表；`test_simple_city_behavior_run_completes` 回归锁定"六作业必须全部收尾、不得留 start_in_obstacle"。

口径与限制：绕行来自静态地图的膨胀栅格 A*，不是调参调出来的；建筑占地是轴对齐包围盒近似，斜置构件偏保守，不等于精确轮廓；评估仍是 `constructed_assessment_stub` 构造桩；`planner` 的 plan_start/plan_end 仍不含评估与撤离。**空地面分流（2026-10-29 晚补齐）**：`behavior_runtime` 对 `can_climb` 平台改走直飞航路并爬升到 `_behavior.air_altitude`（30/25 m），`z` 写入反馈与回放；地面平台仍走 A*。空中越障是"建筑高度低于巡航高度"的假设，不是三维低空突防；`nav` 仍只有二维障碍，空中平台不参与地面绕障证据。

**电量口径（2026-10-29 已加续航闸门）**：移动电按行为层实际行程记账（行程 / 速度 × move_cost），不再"到达即一次记清"。早期规划期只按"到作业点"的直线距离估电，于是行为段（集结→执行环→撤离）的电量完全没算进去，那版 300 m 几何下 16 台有 15 台在 t≈318–364 s 电量归零而作业仍判成功。现在 `planner_v2` 的行为模式改用全程里程估电：`_behavior_mileage` = 当前位→集结环 + 集结→执行环 + 目标→撤离环（撤离开关关闭时不计返程），assault 直接读场景 `_behavior` 的几何，其余四类用保守经验里程兜底；`feasible` 的续航检查与方案级叠加检查都用它，所以"派不出去"会明确写成"续航不足(全程…需…剩…)"。机动时间 `_approach_time` 也改为算到集结区，规划里的 start 与行为层实际到位时刻对得上（此前少 27 s）。回归用例 `EnduranceGateTests` 三条：里程口径含撤离、旧几何必被拒、当前几何 16 台全过。

### 效果判定与逐项结算（2026-10-29）

按《T-ASL 效果判定与逐项结算实现规范》补齐"任务目标=对指定目标产生规定效果并在时间窗内完成，效果由评估接口判定"这一层。此前的实现只有一个构造桩，且只要行为走完就判成功——弹药耗尽、超时、评估未回传都不影响结论，等于把"动作结束"冒充"效果达成"。

- **事实分离**：`command_received`（受领）/ `all_staged`（到位）/ `assault_started` + `effect_applied`（动作）/ `effect_achieved`（效果达成）各自独立事件与时间戳；评估是第五个事实：`assessment_requested` → `assessment_received` → `confirmed`。事件词表在工作台与 `trajectory_v2` 同步扩到 20 余项（`salvo_fired`/`ammo_depleted`/`restrike_needed`/`control_established`/`suppression_gap`/`handover`/`deadline_exceeded`/`terminate` 等）。
- **新模块 `assessment.py`**：`Adjudicator.adjudicate(task_ref, evidence) -> Adjudication`；`task_ref` 带 `{job_id, target_id, attempt, effect_kind, params}`，评估结果绑定"本任务+本对象+当前执行版本"。默认实现 `StubAdjudicator` 按开火日志/覆盖区间/控制区间的**确定性规则**判定，`verified=false`，输出一律标注"桩判定·未验证"；接真实裁决只需换同协议实现（HTTP 回调本轮只留说明）。
- **效果三分类**（`effect_kind`，接受 `damage/suppress/seize` 或中文）：毁伤按齐射累计等级（每轮 `rounds_per_salvo` 发、每平台 `ammo` 发、占位在目标环内即命中，另有 `restrike_needed`）；压制要求**连续**覆盖达 `required_duration`，中断超过 `recovery_gap` 则时段断开、连续时长重计；夺占要求控制权保持 `required_control_s`，且**移交后坚守 `hold_required_s` 单列一项**，夺占成功不自动使坚守成功。
- **终止条件**：全体可开火平台弹药为 0 且效果未达成 → `ammo_exhausted`；执行截止 `execute_deadline` 到而未达成 → `deadline_exceeded`；效果达成但评估未在 `confirmation_deadline` 前回传 → 确认项未达成。目标消失、被迫撤离只留配置字段与事件接口，本轮不触发判定。
- **逐项结算**：`result.items[]` 每项 `{id,label,required,status,t,evidence,metric}`，`status ∈ achieved|failed|pending`（信息项 `info`）；overall 规则为"必需项全达成才 succeeded、任一 failed 即 failed、确认截止后仍 pending 按 failed"。终止时按已发生事实结算（效果已达成则该项记 achieved 并注明"未经评估确认"），**部分达成不冒充全部成功**。
- **平台弹药**：`fleet.PLANNING_PARAMS` 增加 `ammo`（UGV 6 / TANK 8 / 空中 2），经 `delivery.ammo` 下发进替身，行为层齐射消耗写回平台状态并出现在反馈里。
- **工作台**：默认运行优先最新 `asl_city` 行为运行；新建演示增加"突击效果类型"下拉（毁伤/压制/夺占），经 `validate_config` 注入场景 `effect.kind`；任务面板新增逐项结果区（达成/未达成/待确认 + 时间与证据 + 终止原因 + 评估来源"桩判定·未验证"）。

本轮工作台运行 `workbench_20261029_162314_901547`（asl_city、6 台按新编成、real+avoid+behavior、620 步上限）：349 s 结算，`ASL-CITY-1` succeeded。逐项结果为 毁伤等级 8.0 ≥ 6.0 达成、时间窗（效果达成 t=285 s，窗 [0,520]）达成、结果确认达成，信息项为 8 发 8 中（命中率 1.0）、二次打击 1 次、四台突击各余弹 4 发；`assessment_requested.by = rover_06`（评估组），`adjudicator = constructed_assessment_stub`、`verified = false`。单次运行，不是统计。

```powershell
cd planning_middle_demo
py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json --motion real --avoid --behavior --max-ticks 620 --out outputs/asl_city
py -3.14 -m unittest discover -s tests -q
```

口径与限制：桩判定只是"按开火/占位日志的确定性规则"；命中率、弹药消耗、二次打击已在辅助指标里给出（2026-10-29 晚补齐），我方损失按失联注入统计，敌方反击是按周期注入的演示事件（默认被击退、不打断控制，可用 `counterattack_break_s` 演示打断），均不是交战模型；"命中即占位在环内"是演示口径，不是弹道或毁伤模型；单次成功不证明长期成功率，本层也不做概率型分配。

### 工作台接入现状（2026-10-29 核验）

- **任务点与初始位置都是场景输入**：`jobs[].pos` 是突击目标，`platforms[].pos` 是初始位；程序不做目标选址，也不会从 SDF/ROS 自动读位姿。缺 `pos` 时 `build_platforms` 回落到 (0,0)。
- **启动侧已接**：`workbench_server.SCENARIOS` 增加 `asl_city`（城市十字路口机动突击），新增 `AVOID_SCENARIOS` 集合（`simple_city/asl_city`）替代原来只允许 `simple_city` 的判断；`max_ticks` 上限放宽到 700，`asl_city` 未指定时默认 620 步。从工作台勾选「真实运动 + 建筑绕障 + 到位行为」可一键启动。
- **`_behavior` 已透传**：场景 → `run_demo_v2` → `MockFleet(behavior_params)` → `_behavior_job_dict` → `make_behavior`。侦察组、攻击窗口、评估延迟、撤离点这些任务级参数不再丢在场景文件里；指令契约里仍不带它们，避免把任务模板塞进每台平台的消息。
- **行为层从下发时刻接管**：`MockFleet._ensure_behavior` 在指令下发当步就建 runner，不再等"全员到达"才起表；机动/集结/突击/撤离全部由行为层推进，替身不另算一条不会执行的路线。
- **运行列表带场景标签（2026-10-29）**：catalog 每条记录标注"场景名 · 任务数 · 细节类型 · 模式"（`_scenario_label` 读工作台请求里的场景键，退回 manifest 的场景文件名）；旧的下拉只有时间戳，看不出哪条是 J1–J6 多任务、哪条是单突击，用户以为"以前的任务没了"。多任务记录没消失，选 `simple_city` 的 6 任务运行（如 `workbench_20261029_150444_820307`，111 s 六作业全部收尾）即可回到五类任务齐全的画面；默认载入优先最新 `asl_city` 行为运行（效果判定演示主场），没有时退回最新含行为细节的运行。注意：改 `workbench_server.py` 后必须重启服务，运行中的旧进程不会热加载新代码。
- **已验证一次完整工作台运行**：`workbench_20261029_145325_801085`（asl_city、6 台、13 处障碍、real+avoid+behavior），350 s、`settled=true`、无 `energy_depleted`；T-ASL 事件齐全；任务面板步骤条为五段：机动集结 0 s / 全员到位 183 s / 执行动作 184 s / 结果确认 291 s / 撤离收拢 354 s（以受领时刻为 0 的相对时间）。16 台版运行 `workbench_20261029_140712_509952` 保留作容量对照。**当前默认运行**为新编成版 `workbench_20261029_162314_901547`（349 s，含评估组与逐项结算）。
- **回放底图同源**：`trajectory_v2.load_sdf_background` 用与寻路同一套 `load_sdf_obstacles` 把 13 处占地画进 `trajectory.html`，取景范围也把障碍算进去，图上所见即规划避开的那几块。工作台画布上的建筑/花坛属"显示障碍"图层（`#show-obstacles`），取消勾选即隐藏。
- **测试**：109 项通过（原 97 项 + 效果判定 12 项，2026-10-29 晚增至 120 项，见文末多类型兵力包一节），含"机动不是瞬移"、三条续航闸门用例、simple_city 六作业收尾回归，以及规范 §8 的十条验收（毁伤成功/弹药耗尽/执行超时/确认超时/压制中断重计/夺占与坚守分算/部分达成不冒充/评估组归属与桩标注/默认运行为 asl_city）。两条校验历史混合录制（J1–J6、累计换班）的用例改为固定 `workbench_20261028_213551_310530`，该目录缺失时 skip，不再随默认运行漂移。
- **仍未接**：`behavior_trace.json`（`behavior_demo.py` 的独立产物）不是工作台要求的 `report.json + trace.jsonl`，`asl_city_behavior` 这类目录不会出现在 catalog；要么加只读 adapter，要么统一走主链。

### 2026-10-29 晚：多类型兵力包、空地面分流与辅助指标

用户反馈原演示"不够直观、部分指标没完成、不能全用轮式车一种、看着太乱、避障演示不到位"。本轮针对这五条逐项改：

1. **"全用轮式车"** → `asl_city` 改成 2 轮式 + 2 履带 + 1 固定翼 + 1 飞翼的兵力包（编成见前文表格）。平台起点、底盘/包络尺寸全部取自 `scenarios/sdf_initial_state.json`（由 `sdf_state.py` 从甲方 SDF 生成），不是手填。为让飞翼（载荷 1.5）进得了 4.0 载荷的突击作业，`planner_v2` 增加**角色级载荷校核**：`_behavior.role_payload={"assault":4.0,"support":0.5}`，突击组按 4.0、侦察/评估组按 0.5；行为层再用 `set_platform_caps` 复核一次，不达标终止为 `role_infeasible`。
2. **"避障演示不到位"** → 地面 4 台的接近路线全部被 House 4 挡住（`straight_line_ok=false`，绕行比 1.016–1.052），空中两台直飞越障；工作台把"被挡直线"默认打开，红虚线 + "直线被挡 · 绕行 ×1.05 · 净空 1.9"直接写在地图上，路径带箭头；"空间与避障"侧栏同时给路径长度/直线长度/规划净空。
3. **"看着太乱"** → 主图改为任务区取景（不再把 150 m 外的出发列拉进来把中间拉空），右上角加全场景缩略图（含出发阵地与当前视窗框），出发列只画一次"出发阵地 · 6 台（轮式2 · 履带2 · 固定翼1 · 飞翼1）"摘要；建筑按类型着色并标"民居 1–4 / 办公楼 1–2"，道路/广场作浅色底图；任务点用准星，目标点单列"目标 · JUNCTION-CROSS-01"。
4. **"不够直观"** → 平台图标按类目区分（轮式圆角方、履带菱形、固定翼三角、飞翼箭头），空中平台带 `z 30 m` 高度牌与地面吊线；成员标签带"类型 · 角色"（如 `#31 固定翼 · 侦察指示组`）；阶段面板的成员 chip 同样带类型；动作详解的阶段卡片从 4 段扩到实际 5 段（机动/到位/执行/结果确认/撤离），不再把"撤离"挤出画布。
5. **"部分指标没完成"** → 三类效果的辅助指标补齐并逐项落盘（见前文"效果判定的辅助指标"表）。工作台在"效果判定"区先显示辅助指标卡（值 + 单位 + 判定 + 口径），再列必需项结算；评估回传早于行为终态时先用 `assessment_received` 展示，不把已确认结论压到结果事件之后。

**本轮结果（单次运行，非统计）**：

| 运行 | 效果 | 完成 | 过程指标 |
| --- | --- | --- | --- |
| `workbench_20261029_181813_611337` | 毁伤 | 299 s | 受领 1 s / 全员到位 165 s / 突击开始 166 s / 动作结束 237 s / 评估回传 258 s / 撤离 299 s；命中率 1.0（8 发 8 中）、弹药消耗 8、二次打击 1 次、我方损失 0；机动 16 段路径 4 段直线被挡（全为地面接近段） |
| `asl_city_suppress` | 压制 | 308 s | 火力覆盖 12 s、最长连续 12 s、目标恢复时间 3 s（模型参数）、压制中断 0、我方损失 0 |
| `asl_city_seize` | 夺占 | 316 s | 控制 10 s、控制区间 1 段、敌方反击 1 次（已击退）、移交 243 s、移交后坚守 10 s、我方损失 0 |

以上评估源均为 `constructed_assessment_stub`（桩判定·未验证），单次运行不代表概率成功率；空中越障是"建筑低于巡航高度"的假设；敌方反击是按周期注入的演示事件，不是交战模型；静态地图 A* 没有动态障碍与 SLAM。

```powershell
cd planning_middle_demo
py -3.14 sdf_state.py                       # 重新提取 SDF 初始状态
py -3.14 run_demo_v2.py --scenario scenarios/asl_city.json --motion real --avoid --behavior --max-ticks 640 --out outputs/asl_city_mixed
py -3.14 -m unittest discover -s tests -q   # 120 项
```

本轮新增 `tests/test_mixed_fleet.py` 11 项：SDF 提取值、场景起点与 SDF 一致、支援组载荷放宽只对支援位生效、突击组仍按 4.0 卡、空地面分流（`air_direct` + 爬升 / `ground_astar`）、角色闸门、毁伤/损失/夺占辅助指标。测试总数 109 → 120，全部通过。
