# 接到 MARLlib 上真训一次：方案与障碍

> 状态：**方案已定，代码未写**。
> 原因见第三节——两套代码不是同一个世界模型，直接接会产出对不上的数字。
> 本文件记录设计、障碍、步骤与验收标准，供 WP4（11/07）落地。

---

## 一、要接的是什么

目标形态（与 `rl/learn_weights.py` 的分层一致）：

```
规则层（planning/planner.py）  →  能力过滤、方案级校验、冲突消解   ← 硬保证，学习不能碰
学习层（MARLlib 策略）         →  在可行集里选"更好的那个"          ← 学长期回报
```

MARLlib 的价值恰恰是 `learn_weights.py`（学固定权重）跨不过去的那道坎：

| | 学 8 个固定权重 | MARLlib 学策略 |
| --- | --- | --- |
| 决策依据 | 一组**固定**的特征线性组合 | **当前状态**（还有哪些活、多急、谁在忙） |
| 能否治短视 | **不能**（已实测） | **能** —— 策略可以看情况选"急的先干"还是"近的先干" |
| 表达力 | 8 维 | 神经网络 |

---

## 二、三个接入点（精确位置）

| 接入点 | 现有位置 | 要换成 |
| --- | --- | --- |
| **1 可行集（mask）** | `learning_mpe/taskalloc_env.py:165` `action_mask()` 自己算（载荷/传感器/续航） | `planning/planner.py` 的 `feasible()`，与规则层共用同一个 `ENABLED_CHECKS` |
| **2 奖励** | 环境内部 `step()` 返回 | `planning/rl/learn_weights.py:38` 的 `reward()`（已写入 `spec/SPEC.md`） |
| **3 评估口径** | `eval_taskalloc.py` 自有统计 | `planning/metrics.py` 的冲突去重口径 + 消解率 |

第 3 点最关键：**没有同口径评估，"规则 vs 学习"的对照就不成立**，
训练得再好也只是自说自话。

---

## 三、障碍：两套代码不是同一个世界模型（实测确认）

| | `learning_mpe/taskalloc_env.py`（旧） | `planning/contract.py`（新） |
| --- | --- | --- |
| 平台类型 | heavy / fast / endurance / sensor-rig | 坦克 / 无人战车 / 固定翼无人机 a、b |
| 速度 | 0.07–0.15（归一化） | 0.8–2.0（**步/单位距离**） |
| 续航 | 0.70–1.50（归一化） | 60–120（**步数**） |
| 载荷 | 1.0–3.0 | 1.5–8.0 |
| 能耗 | 每单位距离 0.3 | 按移动/作业分步计 |

**结论：不能把 planning 的规则层"贴"到旧环境上。**
mask 用 planning 算、奖励用旧环境算，两者对不上能耗口径，
产出的数字既不能和规则基线对照，也不能和旧实验对照。

> 这也正是 `planning/README` 里记过的教训：
> **能耗模型与续航校验必须同一套口径，不能两套算法各算各的。**

### 正确做法：用 planning 的世界模型**新写**一个 MARLlib 环境

`planning/rl/marl_env.py`，内部直接复用 `planner` + `executor`：

| 要素 | 设计 |
| --- | --- |
| agent | 每台平台一个（15 个），共享策略 `share_policy=all` |
| 观测 | 自身状态（位置/续航/载荷/类型 one-hot）+ 全部作业特征（位置/工作量/剩余/crew/窗口）+ 目标 one-hot |
| **动作** | `Discrete(n_tasks + 1)`，+1 = 待命（与现有环境同形） |
| **mask** | `planner.feasible()` 算，**规则层给可行集** |
| 一步 | 各平台选一个作业 → 交给 planner 排程与冲突消解 → executor 推进 |
| 奖励 | `rl/learn_weights.py` 的 `reward()`（我方暂定） |
| 终止 | 达到 max_steps 或全部作业完成/失败 |

复用 `planner.plan()` 意味着：**第 4–6 步（排程、冲突消解、方案级校验）仍然由规则层做**，
学习层只决定"选哪个作业"。这正是分层原则的落地。

---

## 四、分两步走

### 步骤 A（现在就能做）：确认 MARLlib 管线还活着

先别改任何代码，用**已跑通过的旧链路**做一次冒烟，
确认 MARLlib、Ray、环境注册都还正常（这一步不涉及 planning）：

```bash
cd ~/MARLlib && export PYTHONPATH=/home/ammo/MARLlib
cd /mnt/c/Users/ammo/Desktop/MARL项目/learning_mpe

# 1) 环境自检（不需要 MARLlib）
/home/ammo/miniconda3/envs/marllib/bin/python test_taskalloc_env.py

# 2) 冒烟训练：只要 2 轮，验证管线通不通
/home/ammo/miniconda3/envs/marllib/bin/python train_taskalloc.py \
    --algo mappo --iterations 2 --steps 40

# 3) 正式小规模（300 轮，约 10 分钟）
/home/ammo/miniconda3/envs/marllib/bin/python train_taskalloc.py \
    --algo mappo --iterations 300
```

**看什么**：
- `REGISTERED_ENV:` 打印出来 → 三个注册表都注上了
- `MASK_FLAG: True` → CC/IL 族 mask 生效（mappo/ippo 才行，qmix/vdn 会是 False）
- `HYPERPARAM_DROPPED:` 出现是正常的（算法不认识的参数被丢掉，设计好的降级）
- `RESULT:` 里有 `episode_reward_mean` 且在变 → 真的在学

> 若 `--algo mappo` 报错 `_local_ip`，**往前翻日志**——那是次生错误，真因在中段。

### 步骤 B（WP4）：新写 planning 世界的 MARLlib 环境 —— **已写完**

环境在 **`taskalloc/taskalloc_v2_env.py`**（不是 planning/rl/ 下，因为它要复用
`taskalloc/` 已有的训练与评估链路）。内部完全复用 planning：

| 组件 | 来源 |
| --- | --- |
| 世界模型 | `contract.sample_scenario` |
| **可行集（action mask）** | `planner.feasible` —— 就是规则层的能力闸门 |
| 执行 | `executor.StubExecutor`（原样调用，不重写动力学） |
| 奖励口径 | `rl/learn_weights.py:reward` |

规则层管可行性与 crew，学习层只在可行集里挑——**越界在结构上不可能发生**。

难度是量出来的，不是猜的。随机合法策略的完成率：

| 作业数 \ 步数 | 40 | 30 | 25 | 20 |
| --- | --- | --- | --- | --- |
| 16 | 0.740 | 0.667 | 0.635 | 0.469 |
| **24** | 0.542 | **0.389** ← 选定 | 0.278 | 0.167 |
| 32 | 0.380 | 0.203 | 0.135 | 0.073 |

选 24 作业 / 30 步（随机 **40.1%**，8 seed），因为它紧挨着旧环境的随机基线
**0.354**，两个环境才可比。默认场景（16 作业）随机就 74%，学不出差别。

**不要用 `work_scale` 调难度。** 实测 `work_scale=5` 时 100/120 个 (平台, 作业)
组合因「续航不足」被拒——放大作业量同时放大了续航需求，场景从"资源紧张"变成
"物理不可行"，规则基线直接掉到 0（它拒绝得对，不是它弱）。

跑法（`--env v2` 走新环境，不给则是旧环境，已有基线不受影响）：

```bash
cd /mnt/c/Users/ammo/Desktop/MARL项目/taskalloc
export PYTHONPATH=/home/ammo/MARLlib
PY=/home/ammo/miniconda3/envs/marllib/bin/python

# 0) 先自检逻辑（不需要 ray，纯标准库）
$PY check_v2_logic.py

# 1) 环境自检（需要 ray）
$PY taskalloc_v2_env.py

# 2) 冒烟
$PY train_taskalloc.py --env v2 --algo mappo --iterations 2

# 3) 正式（等样本对照，与旧环境可比）
$PY train_taskalloc.py --env v2 --algo mappo --timesteps 300000
$PY train_taskalloc.py --env v2 --algo vdn   --timesteps 300000
```

产出：`rules_vs_learned.md` 对照表（**同种子、同口径**）。

---

## 五、已知坑（都踩过，写在这里避免重踩）

1. **三个注册表缺一必挂**：`base_env.ENV_REGISTRY`、`global_reward_env.COOP_ENV_REGISTRY`、
   `tune.register_env("<env>_<map>")`。见 `taskalloc_env.register_taskalloc`。
2. **mask 生效要两个条件同时满足**：`env_config["mask_flag"]=True` **且**观测 dict 里有
   `action_mask` 键（模型按 `input_dict["obs"]["action_mask"]` 读）。
3. **VD 族（qmix/vdn/iql）没有 mask 分支** —— 能力硬保证不能指望它们，只能靠规则层。
4. **VD 族不支持缺员**（`group_agents_wrapper.py` 缺员抛 `Missing member of group`）。
   **注意它判的是"返回的 agent 数够不够"，不是"平台能不能失联"。** 所以正确写法是
   让失联平台**照常返回观测、动作压成待命**（= planning 的定长槽位设计），
   而不是把它从环境里删掉。见 `taskalloc/check_group_fix.py`（8/8 验证）。
5. **跨族比较必须用 `timesteps_total` 对齐**：同 `--iterations 300` 下，
   CC/IL 每轮 320 步（9.6 万），VD 每轮 1000 步（30 万），样本预算差 3 倍。
6. **VD 的 replay buffer 真实预算 = `buffer_size × episode_limit`**，yaml 默认 5000 会 OOM，用 500。
7. **动作空间必须是 Discrete**，`run_vd.py:55,93` 对非 Discrete 直接 raise。

---

## 六、验收标准（对照表必须能回答这三个问题）

1. **学到了吗**：同一 seed 下，学到的策略 vs 规则基线，完成率 / 能耗 / 冲突三项各多少
2. **有没有越界**：方案级越界必须为 0（规则层保证，学习层碰不到）
3. **口径一致吗**：与规则基线用**同一套** metrics（冲突去重、消解率），不能两套各算各的

> **红线**：这组数字只能回答"学习层有没有学到东西"，
> **不能**对标文档绝对阈值（如 95% 消解率）。那是另一回事。

---

## 七、为什么现在不给脚本

1. 助手沙箱**不能启动 WSL**，写了也无法在本机验证——给一个没跑过的脚本不如不给
2. 两套世界模型的参数不一致（第三节），直接接会产出对不上的数字
3. 步骤 A 还没跑，管线是否活着未知，先确认再动手更省事

**建议顺序**：先跑步骤 A，把输出贴回来 → 确认管线 OK → 再写步骤 B 的环境。
