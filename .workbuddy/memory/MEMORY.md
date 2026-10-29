# 项目长期记忆 · MARL

## 项目定位（用户明确的前提）

- 原采购项目已结束，当前是**个人练手与能力建设**，不应用于具体作战决策。
- 教学与演示只用**通用协作环境**（MPE `simple_spread` 等），不展开具体作战决策实现。
- 方案、工期、人力均按询价文件做工程推演，不构成对真实采购任务的承诺。

## 笔记位置（2026-10-16 用户重构后）

- **MARL 笔记在 `D:\obsidianNOTE\ammo\10_项目\MARL\`**，入口 `00_项目入口.md`。
- 上级已改为编号目录：`00_收件箱 / 10_项目 / 20_学习 / 30_科研 / 40_探索 / 50_讨论 / 60_工具 / 90_归档 / _模板 / _规范`。
- 文件名是中文无编号的，例如 `MARLlib使用与算法概念.md`、`实操_四算法对照记录.md`、`实操_加载模型与独立评估.md`、`实操_延长训练与行为诊断.md`、`需求与验收.md`、`工具与工程核对.md`；早期稿件在 `历史/`。
- `D:\obsidianNOTE\ammo\MARL\` 已不存在。
- 写作约定：区分“已验证”与“计划/候选解释”；不编造数值；修正已有错误而不是堆叠摘录。

## 笔记库维护约定（2026-10-21 首次大整理后）

- **改前先问 + 库外备份**：`_规范/已有笔记修改须先确认.md` 是用户硬规则（改/移/删都要先确认；有未提交内容时先备份到库外带日期目录）。本次备份在 `C:/Users/ammo/Desktop/MARL项目/.workbuddy/backups/2026-10-21_MARL笔记/`。**改动保持 git 未提交供审阅，不要擅自 commit。**
- **整理后的目录事实**：MARL 下 16 篇 → 15 篇（周一.md 归到 `90_归档/MARL/`）。入口 `00_项目入口.md` 已重写为"按问题找笔记"索引，进度按日期倒排。
- **已清理的旧笔记**（不再引用，需要查 git 基线 `edb142f`）：实操_加载模型与独立评估、实操_四算法对照记录、实操_延长训练与行为诊断、学习进展与交接、历史/两天展示计划、历史/交付方案草案。MPE 阶段的可用结论已并入速览篇与 MARLlib 概念篇。
- **`需求_向甲方索取的资料与数据清单` 从未存在过**，遇到这个链接就改指 `方案_任务规划中间层_优化版` 第七节的 7 项待确认。
- **两处同源内容**：会议纪要与需求与验收 §十四（重复度 85-90%）。用户选择两篇都保留：纪要是带时间戳/发言人/责任表的底稿，需求篇是压缩摘要，**不一致时以纪要为准**。
- 断链检查可用脚本扫全库 `[[...]]` 并比对文件名，本次整理后全库断链为 0。

## 运行环境

- WSL Ubuntu：`/home/ammo/miniconda3/envs/marllib/bin/python`（Python 3.8），仓库 `/home/ammo/MARLlib`，需 `PYTHONPATH=/home/ammo/MARLlib`。
- 实验脚本与产物都在项目下 `learning_mpe/`，**原始训练结果保留，不要覆盖**。
- 助手沙箱**禁止启动 `wsl.exe`**，无法直接执行 Ubuntu 内命令；分工是助手写脚本、用户在 Ubuntu 跑、助手读日志。
- 但 Windows 侧可直接读 WSL 文件系统：`//wsl.localhost/Ubuntu/home/ammo/MARLlib/...`，用于核对源码版本非常有效。
- 先核对本地版本再写代码，不要把现代 Ray / Gymnasium 用法套进这个旧环境；不无故升级依赖。

## 免跑机的核对技巧

- Ray tune 的 trial 目录下有 `params.json`（纯 JSON），Windows 侧直接可读，用来核对 `params.pkl` 内容、环境名、`force_coop` 等，比反复跑脚本快得多。
- 训练曲线可直接读 `results_*/<algo>_*/*/progress.csv`；manifest 在 `results_*/<algo>_manifest.json`。

## taskalloc 环境的数据与训练事实（2026-10-19 核实）

- **每局数据由环境自己生成**（`reset()`）：`ep_seed=(seed*100003+episode_count) mod 2^31`；平台类型/位置、作业类型/位置、优化目标均独立均匀抽样，**不保证每局 4 类平台或 5 类作业齐全**。真实系统应来自上层订阅，演示里是替身，讲解时必须先说清。
- **观测看不到队友个体**：`_observe()` 只有自身状态 + 全部 8 个作业的特征（含"已到位几台"）+ 目标 one-hot + 全局两个聚合量。**没有队友的位置/电量/类型**。→ 冲突降不下来的候选根因，优先考虑改观测而不是换算法。
- **样本预算：同 `--iterations 300` 两族差 3 倍。** CC/IL 每轮 320 步（8 局×40），VD 每轮 1000 步（25 局×40）→ 9.6 万 vs 30 万步。两者传的都是 `batch_episode=8`，换算机制未核实。**跨族比较一律用 `timesteps_total` 对齐。**
- 超参来源：`hyperparam_source="mpe"` → `hyperparams/finetuned/mpe/<algo>.yaml`。我们只覆盖 3 个：`batch_episode=8`(yaml 128)、`num_sgd_iter=2`(yaml 10)、VD `buffer_size=500`(yaml 5000)。其余（lr 0.0005 / entropy 0.01 / clip 0.3 / vf_clip 20.0 / complete_episodes；VD 另 optimizer=rmsprop、target_update 200、epsilon 0.05/50000）都是库规定。
- **VD 的顶层超参不落进 `params.json`**（顶层仅 10 键）。核对 VD 配置必须直接读 yaml，不能只读 params.json。
- `build_algo()` 会自动丢弃算法不认识的参数，日志 `HYPERPARAM_DROPPED: num_sgd_iter` 是设计好的降级，不是 bug。
- 动作空间是 `Discrete(9)`。判定源码：`run_vd.py:55,93`（VD 非 Discrete 直接 raise）、`run_cc.py:78~88`（maddpg 只吃连续、coma 只吃离散）、`cc_mlp.py:58,108`（Box 分支）。因此本项目 VD 合法、DDPG 系（maddpg/facmac/iddpg）不可用。

## 笔记写作口径（多 AI 共用同一个 Obsidian 库时的约定）

用户会用 Codex 等其他 AI 改写同一批笔记。处理原则：

- **判断要敢下，但要标举证层次**，不要靠堆免责声明。空话式的「本环境不能据此声称 X」信息量为零。
- 用**举证档位**替代谨慎语气：L0 环境不覆盖 / L1 有规则（能演示，非证据）/ L2 可测数（内部相对比较，不能对标绝对阈值）/ L3 策略行为可测（能讨论学到与否）。
- 别人的判断若只是"数字含糊"，应**补依据**，不要删掉结论——含糊可以修，删掉等于丢信息。
- 发现"待核对冲突"时，先查自己有没有一手证据（比如 `logs/` 里的日志），多数冲突是可以消解的，而不是存疑挂起。
- 凡是新写的技术约束，能引源码行号的一定引（例：`group_agents_wrapper.py:106-120` 缺员即 `ValueError: Missing member of group`）。

## 已核实的实验事实（2026-10-16）

- 四算法 500 迭代训练成功，但**样本预算不等**：CC/IL = 10 万步，VD = 50 万步。跨族比较必须标步数。
- 训练期 10 次迭代滑动均值：VDN -92.2@500k、IPPO -99.1@100k、MAPPO -103.1@100k、QMIX -107.1@500k（QMIX 在 100k 处为 -197.8，之后恢复；**“持续恶化”是截断误判，已更正**）。
- 冻结独立评估（30 局配对种子）目前只有 mappo / ippo 可用；vdn / qmix 的评估尚未跑通。
- 随机基线：团队回报 -111.59、覆盖距离 2.21、碰撞对步数 0.67。
- 学到/没学到：两种算法都显著降低覆盖距离（2.21 → 约 1.37），但碰撞大幅上升（0.67 → 15~21），MAPPO 的团队回报几乎没涨。

## VD 族（vdn/qmix/iql）推理适配的五个坑

均在 `MARLlib使用与算法概念.md` 有详细记录，要点：

1. `JointQTrainer` 在 `VD/iql_vdn_qmix.py`，`IPPOTrainer` 在 `IL/ppo.py`，不能按算法名拼导入路径。
2. VD 的 `config["model"]` 只有 `custom_model_config`，没有 `custom_model`。
3. 联合 Q 一次吃全队观测、吐全队动作，必须经 `Trainer.compute_single_action` 走训练期预处理器。
4. 组环境名 `grouped_<env>_<map>` 只在训练进程注册，评估进程要在 `ray.init()` 前自行 `register_env`。
5. 训练用的是 `JointQTrainer.with_updates(default_config=JointQ_Config)` 派生类，其 `reward_standardize/optimizer/mixer/training_intensity` 等顶层键不在 Ray 的 DEFAULT_CONFIG 也不进 params.pkl，必须按 `hyperparams/finetuned/<env>/<algo>.yaml` 补齐。

配套两点：联合 Q 必须传 `policy.get_initial_state()`（否则 `hidden_state[0]` IndexError）；返回值是 `(action, state, extra)` 三元组（state 恒非空）。

另：`run_vd.py` 把 `COOP_ENV_REGISTRY` 起别名为 `ENV_REGISTRY`，所以 **VD 始终训练在 FCOOP 环境上，与 `force_coop` 标志无关**；奖励求和后与 IL/CC 同口径。

## taskalloc 环境的技术约束（2026-10-17 实跑核实）

1. **action mask 只能给 CC/IL（mappo/ippo）用。** `base_mlp.py:91-105` 有 mask 分支（`output + inf_mask`），VD 的 `jointQ_mlp.py` 一个 mask 都没有。
2. **mask 生效要两个条件同时满足**：`env_config["mask_flag"]=True` **且**观测 dict 里有 `action_mask` 键（模型按 `input_dict["obs"]["action_mask"]` 约定读取）。
3. **mask 不是可选项。** 本环境合法动作平均 3.84/9；不挂 mask 时策略会学成"躺平"（能耗只有随机的 1/5，完成率反而更低）。这是"能力约束必须在采样前施加"的实证。
4. **VD 的 replay buffer 真实预算是 `buffer_size × episode_limit`**。yaml 默认 5000 → 20 万条约 2 GB，会在 6 GB 机器上 OOM。用 `--vd-buffer-size 500`。
5. **VD 专属顶层键必须进 `default_config`，不能进运行 config**，否则 `Unknown config parameter`。用 `JointQTrainer.with_updates(default_config=...)`，照 `scripts/vdn_qmix_iql.py:104-110`。
6. `DYNAMIC=1` 与 VD 硬冲突（分组要求全员常驻，缺员抛 `Missing member of group`，见 `group_agents_wrapper.py:118`）。
7. **推理耗时的量级差来自推理形态**：VD 一次前向出全队动作 0.98 ms vs CC 逐个调用 11.20 ms（15 平台），差 11 倍。

### 已核实的算法表现（2026-10-17，taskalloc 15 平台，300 轮，30 局配对）

- **VDN 是唯一三项同时胜过随机的**：完成率 0.575 vs 0.354（+62%），能耗 −28%，冲突 −67%。
- IPPO(0.325) / QMIX(0.154) 完成率不及随机，其低能耗低冲突是"少动"换来的，**不是学会了分配**。
- VD 族内部量级差异：VDN 0.575 vs QMIX 0.154，结构几乎相同、只差 mixer —— 算法名气 ≠ 适用性。
- 耗时实测：mappo/ippo 各约 10 分钟（9.6 万步），qmix/vdn 各约 53 分钟（30 万步）。）。

## 改动被 shell 调用的脚本后必做

**约定：改完任何 `.py` 的 `add_argument` 后，先跑 `python check_cli_args.py`（在 `learning_mpe/` 下）再让用户执行。**

它用 `ast` 比对 `run_*.sh` 传的 flag 与脚本声明的差异，不需要 ray/marllib。
2026-10-17 曾因 Edit 覆盖掉了 `--output` 的定义，导致四类训练 argpase 秒退、用户白跑一轮。

## 贴近项目的演示环境（2026-10-17 新增）

- `learning_mpe/taskalloc_env.py`：把「编组订阅→任务分解→时序调度→能力边界校验」抽象成通用的平台—作业分配问题，**不含任何战术/交战/攻击决策内容**。
- 结构对应条款：4 类平台（2.3(1)）、5 类作业（2.3(3)）、3 类可切换优化目标（2.3(4)）、时间窗与协同人数（2.2(2) 四类输出）、默认 15 平台。
- 观测定长（88 维）以支持成员动态增减：固定槽位，失联平台不进 obs 字典。
- 自定义环境接入：不改仓库，运行时注册 `register_taskalloc()`；env_config 手工构造，字段对齐 `make_env` 输出（`build_model` 需要 `(实例, 配置)` 元组，不是裸实例）。
- **三处注册表缺一必挂**：`base_env.ENV_REGISTRY`（make_env 状态表）、`global_reward_env.COOP_ENV_REGISTRY`（run_vd 用）、`tune.register_env("<env>_<map>")`（run_cc/run_il 自己从不注册，只有 make_env 会调）。
- 创建函数必须**忽略** Ray 的 `env_context`、复用闭包里的 `env_args`（MARLlib 原生也这么做）。

### 排障：报错必须往前翻

训练失败时终端上的 `AttributeError: 'X' object has no attribute '_local_ip'` 是**假象**，它是 Trainer actor 构造失败的次生错误。真因在日志中部（如 `EnvError` / `KeyError`）。

### 关键判断（不要指望「跑个算法」满足验收）

15 项指标里只有约 5 项能被 MARL 直接影响（任务分配、时序冲突消解、任务类型差异化、优化目标切换、全链路统计）。
时延 / 同步 / 推送 / 想定兼容 / 独立下发 / 能力边界都是系统工程。
**能力边界校验不能交给 RL**：奖励里的惩罚不是保证，必须 action mask + 下发前闸门。

### 免跑机的验证技巧

Windows 侧无 ray/gym，可用 `sys.modules` 注入替身模块跑环境动力学，提前抓逻辑 bug
（本次即靠它抓到 `__init__` 里 `self.seed` 覆盖 `seed()` 方法的问题）。
