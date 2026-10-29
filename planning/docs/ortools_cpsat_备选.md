# OR-Tools CP-SAT：备用材料（**未启用、未在本环境验证**）

> [!warning] 状态
> WP1 的决定是**暂不引入** OR-Tools（理由见 `README.md` 5.6）。
> 本文件只是把它存档，等触发条件满足时照抄即可。
> **环境里没有 ortools，下面这段代码从未被跑过**——不要引用它当已验证结论。

---

## 一、什么时候才该把它拿出来

满足任一条件就重开这个议题：

1. 出现**先后关系**（precedence）约束——A 干完才能干 B。贪心和匈牙利都表达不了。
2. 出现**互斥/耦合资源**约束（同一时刻最多 N 台在某区域）。
3. 甲方给出真正的"消解时限"口径，需要对"排得进去/排不进去"给出**可证明的判定**，
   而不是像现在这样靠"加人→换人→defer"启发式兜底。
4. 规模上到 30+ 作业，且资源紧张成为常态（平台/作业 < 1）。

**在那之前不要引入**：交付环境不支持外网（一·19），多一个二进制依赖就多一处部署风险。

---

## 二、安装

```bash
# 开发机（WSL Ubuntu，有外网）
/home/ammo/miniconda3/envs/marllib/bin/python -m pip install ortools

# 验证
/home/ammo/miniconda3/envs/marllib/bin/python -c \
  "from ortools.sat.python import cp_model; print(cp_model.__name__)"
```

交付环境（离线）：需要**预先下载 wheel 随包携带**，再离线安装：

```bash
# 有网的机器上
pip download ortools -d ./wheels --no-deps
# 目标机上
pip install --no-index --find-links=./wheels ortools
```

> 这一步必须先跟甲方确认能不能带第三方二进制进环境。**没确认就不要做。**

---

## 三、最小示例：带 crew、时间窗、先后关系的排程

下面的例子只表达"三类硬约束"，不含优化目标——
因为优化目标该用什么，取决于甲方确认的口径，现在定了也是白定。

```python
# -*- coding: utf-8 -*-
"""
最小 CP-SAT 排程示例：**未启用、未验证**。

约束：
  - 每个作业要 crew[i] 台平台，且同一台平台同一时刻只能干一个活（NoOverlap）
  - 每个作业必须在 [ws, we] 窗口内完工
  - 可选的先后关系 prec = [(先, 后), ...]

与现有 planner 的接口边界：
  CP-SAT 只负责"给定可行集，求一个满足硬约束的排程"。
  能力闸门（续航/载荷/传感器/运动性能）仍然由 planner.feasible() 先过滤，
  ——硬约束不能指望求解器，可行性必须先在候选集上剪掉。
"""
from ortools.sat.python import cp_model


def schedule(tasks, platforms, prec=(), horizon=200):
    """tasks:      [dict(tid, crew, dur, ws, we), ...]
       platforms:  [pid, ...]
       返回 {tid: (start, end, [pid...])}，无解返回 None
    """
    m = cp_model.CpModel()
    n_t, n_p = len(tasks), len(platforms)

    # 决策变量：每个作业的开始/结束/工期
    start = {i: m.NewIntVar(0, horizon, "s%d" % i) for i in range(n_t)}
    end = {i: m.NewIntVar(0, horizon, "e%d" % i) for i in range(n_t)}
    for i, t in enumerate(tasks):
        m.Add(end[i] == start[i] + t["dur"])
        m.Add(start[i] >= t["ws"])
        m.Add(end[i] <= t["we"])

    # 指派变量：x[i][p] = 作业 i 是否用平台 p
    x = {(i, p): m.NewBoolVar("x%d_%d" % (i, p))
         for i in range(n_t) for p in range(n_p)}
    for i, t in enumerate(tasks):
        m.Add(sum(x[i, p] for p in range(n_p)) == t["crew"])

    # 同一平台的作业不重叠：用可选区间 + NoOverlap
    for p in range(n_p):
        intervals = []
        for i in range(n_t):
            iv = m.NewOptionalIntervalVar(start[i], tasks[i]["dur"], end[i],
                                          x[i, p], "iv%d_%d" % (i, p))
            intervals.append(iv)
        m.AddNoOverlap(intervals)

    # 先后关系（这是现有贪心/匈牙利**表达不了**的部分，也是引入 CP-SAT 的主要理由）
    for a, b in prec:
        m.Add(start[b] >= end[a])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return {
        tasks[i]["tid"]: (solver.Value(start[i]), solver.Value(end[i]),
                          [platforms[p] for p in range(n_p) if solver.Value(x[i, p])])
        for i in range(n_t)
    }
```

---

## 四、接入时要注意的三件事（照现有架构抄）

1. **可行集仍由 `planner.feasible()` 给**。CP-SAT 里的 `x[i,p]` 只能取
   `feasible(p, t)` 为真的那些 (i,p)，否则求解器会给出 capability 越界的解。
   做法：把这些 (i,p) 的 `x` 直接 `m.Add(x[i,p] == 0)`。
2. **`need_report` 的语义必须保留**。CP-SAT 返回 INFEASIBLE 不等于"这个活不干了"，
   仍然要走 `defer → need_report=True → 上报上层`，不许静默放弃。
3. **留痕格式不变**：求解结果要转成 `planner.plan()` 的 `events` 结构
   （`conflict` / `resolved` / `violation`），否则下游 `metrics.ConflictTracker`
   与 `flow_trace.jsonl` 全部断掉。
