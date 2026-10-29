# -*- coding: utf-8 -*-
"""
planner.py —— 规则规划器（V1 主线）

一次规划做 6 步，每一步都会往 events 里留痕：

  1 能力过滤   剔除不可行的 (平台, 作业) 组合
  2 代价打分   按当前优化目标
  3 分配求解   满足 crew>=N 的前提下指派
  4 时序排程   排入时间窗
  5 冲突消解   平台时间重叠 / crew 不足 / 超出时间窗
  6 输出校验   整份方案再过一遍能力约束（不只是单个指派）

输出：每个作业未来 H 步内的 (子任务, 时序, 时间窗, 协同约束)
"""

import math
from typing import Dict, List, Optional, Tuple

from contract import Assignment, GroupSnapshot, Plan, dist

RULE_VERSION = "rule-v0.1"

# V1 只启用续航与载荷两项校验（会议一·36 阶段口径）。
# 传感器与运动性能的判断逻辑已经写好，参数到位后加进这个集合即可。
# 未启用的项会在统计里显式列出，不静默省略。
ENABLED_CHECKS = {"battery", "payload"}
ALL_CHECKS = {"battery", "payload", "sensor", "motion"}

# 滚动重规划时，是否保持上一版已经发出去的指派。
# 关掉它就能看到"作业永远做不完"的经典故障。
KEEP_COMMITMENT = True

# 排程时是否按"截止最早先干"（EDF）。
# 实测（8 seed × 60 步 / 4 seed × 120 步）：开它消解率上升（约 56%→67%），
# 但完成数下降（38/8seed → 34/8seed，且延到 120 步也追不回来）——
# 因为不紧急的作业被反复挤出规划视野，属于被"饿死"。
# 所以默认关。保留开关是为了让这个结论可被复现，不是留着当默认。
URGENCY_FIRST = False

# 排不进时间窗时，是否在"加人"之后继续尝试"换人"。
# 加人只能缩短工期，缩短不了路上的时间——慢在路上时只能靠换人。
SWAP_TO_FIT = True

# 排程串行化时，"紧迫"占多大分量（强化学习可调这一个数）。
#   排序键 = 开工时刻 + URGENCY_WEIGHT × 窗口余量
#   0   = 只看谁先开工（原行为，会短视：近的不急的活先干，把急的堵死）
#   越大 = 越倾向"急的先干"
# 做成连续可调而不是布尔开关，是因为硬性 EDF 实测会饿死不紧急的作业，
# 而连续权重可以让学习自己找到折中点。
URGENCY_WEIGHT = 0.0

# ------------------------------------------------------------------
# 分配求解器（WP1）
#
# crew==1 的作业本质上是"平台↔作业"的一对一匹配，存在多项式最优解（匈牙利）。
# 原来的贪心在这类问题上不是最优的，差多少要**打印出来**才知道值不值得换。
#
# 做成开关而不是直接改死：匈牙利是**一对一**的，而原来的贪心允许一台平台
# 顺序接多个活——两者可行域不同，必须能对照着看。
# ------------------------------------------------------------------
USE_HUNGARIAN = True

# 不可行的 (平台, 作业) 在代价矩阵里填这个值。
# 必须是有限大数而不是 inf：自带的 JV 实现里 inf 会让 delta 比较失效。
BIG_COST = 1e7

# ------------------------------------------------------------------
# 分散度目标的代价项（我方暂定，甲方未给任何参数）
#   SPREAD_SCALE  距离归一化尺度（场景 100×100，质心到角落约 70）
#   W_SPREAD      分散项权重：把平台派到"离编队质心更远的作业点"是收益（取负）
#   W_CROWD       聚集惩罚权重：作业点周围我方平台越密，暴露风险越高
#   W_TIME_DISP   分散目标里保留多少"工期"分量
#
# 这三个数是**扫出来的，不是拍的**（8 seed × 60 步，见 README 五之二）：
#   W_TIME_DISP=1.0 时，dispersion 的完成数（33）与 makespan（33）持平，
#   于是"分散度更高"不能再被解释成"干得少所以没聚拢"——对照才成立。
#   取 0.2 时完成数掉到 17/8seed，虽然分散度更高，但那是少干活的假象。
#   W_TIME_ENERGY 同理：energy 取 0 时 seed0 一个作业都完不成，
#   取 0.3 后完成数回到 makespan 的 79%，每作业能耗才谈得上可比。
# ------------------------------------------------------------------
SPREAD_SCALE = 50.0
W_SPREAD = 20.0
W_CROWD = 10.0
W_TIME_DISP = 1.0
W_TIME_ENERGY = 0.3

# 三类优化目标各自的代价项权重（我方暂定）。
# 四项的含义：
#   time    = 完工所需步数（travel + work_t）          —— 越小越早完工
#   energy  = 预计耗电（travel×move_cost + work_t×work_cost）
#   spread  = 分散度损失 = (平台到质心距离 − 作业到质心距离) / SPREAD_SCALE
#             为负说明这次指派让编队更分散 → 代价更小 → 更优先
#   crowd   = 作业点聚集度 = 作业点半径内的存活平台数 / 存活平台总数
# 三个目标各用各的项、互不混叠，是为了让"换目标真的换了行为"这件事可验证。
COST_TERMS = {
    "makespan":   dict(time=1.0,         energy=0.0, spread=0.0,     crowd=0.0),
    "energy":     dict(time=W_TIME_ENERGY, energy=1.0, spread=0.0,     crowd=0.0),
    "dispersion": dict(time=W_TIME_DISP, energy=0.0, spread=W_SPREAD, crowd=W_CROWD),
}

# 代价函数权重（强化学习要学的就是这个）。None = 用下面三个内置分支。
# 六个维度见 _features()：移动时间 / 作业时间 / 能耗 / 拥挤度 / 载荷余量 / 续航余量
COST_WEIGHTS = None

# 手工三目标对应的权重，供学习结果做对照。
# 第 7 维（窗口余量）手工目标一律给 0 —— 即"不考虑紧迫度"，
# 这正是规划器短视的来源。学习若要治短视，就得学到这一维的非零权重。
OBJECTIVE_WEIGHTS = {
    "makespan":   [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "energy":     [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
    "dispersion": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
}


def _features(p, t, crowd: float, max_bat: float, max_pay: float, now: int = 0):
    """把 (平台, 作业) 对变成归一化特征向量。

    归一化是必须的：七个特征量纲不同，不归一化学出来的权重没有可比性。

    第 7 维「窗口余量」是关键：它让代价函数第一次"看得见后面有多急"。
    余量越小（越紧张）代价越小 → 越优先派。负值表示按当前排法已经来不及。
    没有这一维，无论权重怎么学都治不了短视——因为输入里根本没有紧迫信息。
    """
    travel = dist(p.pos, t.pos) / max(p.speed, 1e-6)
    work_t = _remain(t) / max(p.work_rate, 1e-6)
    need = _travel_time(p, t) + _work_time(p, t)
    slack = t.window[1] - (now + travel + work_t)
    return [
        travel / 50.0,                                    # 场景尺度 100×100
        work_t / 30.0,
        _energy_need(p, t) / 80.0,      # WP1：改成真实能耗，不再是"时间"
        crowd / 10.0,
        (p.payload - t.need_payload) / max(max_pay, 1e-6),
        (p.battery - need) / max(max_bat, 1e-6),
        slack / 50.0,
    ]


def _travel_time(p, t) -> int:
    return int(math.ceil(dist(p.pos, t.pos) / max(p.speed, 1e-6)))


def _remain(t) -> float:
    """剩余工作量。

    排程必须基于剩余，不能基于总量——否则已经干了一半的作业
    每次滚动都会被当成"从头开始"，工期被无限刷新。
    """
    return max(0.0, t.work - t.progress)


def _work_time(p, t) -> int:
    return int(math.ceil(_remain(t) / max(p.work_rate, 1e-6)))


def _energy_need(p, t) -> float:
    """一次指派的预计耗电（我方暂定模型）。

        耗电 = 移动步数 × move_cost + 作业步数 × work_cost

    移动与作业分开计价，是因为"跑得快"和"干得快"是两件事：
    无人机跑得快但干得慢，坦克干得快但费油。混在一起就分不出目标。
    """
    return _travel_time(p, t) * p.move_cost + _work_time(p, t) * p.work_cost


def feasible(p, t) -> Tuple[bool, str]:
    """能力闸门。返回 (是否可行, 不可行的原因)。"""
    if not p.alive:
        return False, "平台失联"
    if "battery" in ENABLED_CHECKS:
        # 续航闸门按**电量**算，与 executor 的扣电口径一致。
        # 早先是按"占用步数"算的，引入能耗模型后两个口径对不上：
        # 闸门说够、实际扣电会扣穿。现在统一成电量。
        need = _energy_need(p, t)
        if p.battery < need:
            return False, "续航不足(需%.1f剩%.1f)" % (need, p.battery)
    if "payload" in ENABLED_CHECKS:
        if p.payload < t.need_payload:
            return False, "载荷不足(需%.1f剩%.1f)" % (t.need_payload, p.payload)
    if "sensor" in ENABLED_CHECKS:
        if t.need_sensor and p.sensor != t.need_sensor:
            return False, "传感器不匹配(需%s有%s)" % (t.need_sensor, p.sensor)
    if "motion" in ENABLED_CHECKS:
        if _travel_time(p, t) > t.window[1] - t.window[0]:
            return False, "运动性能不足(赶不到)"
    return True, ""


def _cost(p, t, objective: str, crowded: float = 0.0,
          centroid: Optional[Tuple[float, float]] = None,
          n_alive: int = 1) -> float:
    """代价越小越优先。优化目标不同，代价函数不同。

    WP1 之前的版本有两个毛病，都已修：
      1. energy 只是 (travel+work)×(1+0.5/效率)，跟 makespan 高度同向
         → 换目标几乎换不出差别。现在按真实能耗模型算。
      2. dispersion 的拥挤度只跟**作业**有关、跟平台无关，
         于是"选哪台平台"这一步 dispersion 和 makespan 完全一样
         → 分散度数字纹丝不动。现在加了**平台侧**的分散收益项。

    centroid / n_alive 不传时，分散两项退化为 0（向后兼容老调用）。
    """
    travel = _travel_time(p, t)
    work_t = _work_time(p, t)

    time_term = float(travel + work_t)
    energy_term = _energy_need(p, t)

    if centroid is None:
        spread_term = 0.0
    else:
        # >0：把这台平台从"离质心更远的地方"调到"更近的作业点" → 编队更集中 → 惩罚
        # <0：把平台派到比它现在更远离质心的作业点 → 编队更分散 → 奖励
        spread_term = (dist(p.pos, centroid) - dist(t.pos, centroid)) / SPREAD_SCALE

    crowd_term = crowded / max(n_alive, 1)

    w = COST_TERMS.get(objective, COST_TERMS["makespan"])
    return (w["time"] * time_term
            + w["energy"] * energy_term
            + w["spread"] * spread_term
            + w["crowd"] * crowd_term)


# ------------------------------------------------------------------
# 匈牙利（一对一最优指派）
# ------------------------------------------------------------------

def _hungarian_stdlib(C):
    """矩形代价矩阵 C（行 × 列）的最小和一对一指派。

    自带实现（Jonker-Volgenant 最短路增广，O(n^3)），纯标准库。
    为什么要自带一份：
      - 交付环境不支持外网（一·19），不能假设目标机装了 scipy/numpy；
      - 开发机（Windows 侧）也没有 scipy，没有它这条链连自测都跑不了。
    有 scipy 时优先用 scipy，两者结果在单测里互校（见 tests/test_planner_units.py）。

    返回 [(行号, 列号), ...]，长度 = min(行数, 列数)。
    """
    n = len(C)
    m = len(C[0]) if n else 0
    if n == 0 or m == 0:
        return []
    transposed = False
    if n > m:                       # 算法要求 行 <= 列，多了就转置
        C = [[C[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
        transposed = True

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)               # p[j] = 第 j 列配到的行（1-based）
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            row = C[i0 - 1]
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = row[j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            if j1 < 0:              # 理论上不会走到（代价全有限时）
                break
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:                   # 回溯增广路
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    res = []
    for j in range(1, m + 1):
        if p[j]:
            i, col = p[j] - 1, j - 1
            res.append((col, i) if transposed else (i, col))
    return res


def hungarian(C, prefer_scipy: bool = True):
    """返回 (匹配列表, 求解器名)。scipy 不可用时自动退回自带实现。"""
    if prefer_scipy:
        try:
            import numpy as np
            from scipy.optimize import linear_sum_assignment
            r, c = linear_sum_assignment(np.array(C, dtype=float))
            return [(int(i), int(j)) for i, j in zip(r, c)], "scipy"
        except Exception:
            pass
    return _hungarian_stdlib(C), "内置JV"


def solve_crew1(plats, tasks, cost_of) -> Dict:
    """crew==1 作业的一对一指派：最优（匈牙利）与贪心的对照。

    cost_of(p, t) -> float，不可行返回 None。

    返回 dict：
        assign   {tid: pid} 最优指派（只含可行对）
        optimal  最优总代价
        greedy   贪心总代价（**同样受一对一约束**，否则两者不可比）
        solver   求解器名
        n_pair   配成的对数

    为什么贪心也要一对一：原来的贪心允许一台平台接多个活，可行域更大，
    拿它的总代价去跟一对一的最优值比，比出来的是"可行域不同"而不是"算法差"。
    """
    BIG = BIG_COST
    C = [[BIG] * len(tasks) for _ in plats]
    for i, p in enumerate(plats):
        for j, t in enumerate(tasks):
            c = cost_of(p, t)
            if c is not None and c < BIG:
                C[i][j] = c

    pairs, solver = hungarian(C)
    assign, optimal = {}, 0.0
    for i, j in pairs:
        if C[i][j] >= BIG:          # 不可行的配对不算数
            continue
        assign[tasks[j].tid] = plats[i].pid
        optimal += C[i][j]

    # 贪心：按代价从小到大取，行/列用过就跳过（与最优解同一可行域）
    cells = sorted(((C[i][j], i, j)
                    for i in range(len(plats)) for j in range(len(tasks))
                    if C[i][j] < BIG), key=lambda x: (x[0], x[1], x[2]))
    ur, uc = set(), set()
    greedy = 0.0
    for c, i, j in cells:
        if i in ur or j in uc:
            continue
        ur.add(i)
        uc.add(j)
        greedy += c

    return dict(assign=assign, optimal=optimal, greedy=greedy,
                solver=solver, n_pair=len(assign),
                gap=(greedy - optimal) if optimal > 0 else 0.0)


def _add_crew_to_fit(tid, pids, pmap, tmap, feasible_pairs, now,
                     window_limit, anybody_used, earliest=None):
    """排不进时间窗时，尝试加人缩短工期，使作业能落进窗口。

    协同作业的效率是各成员 work_rate 之和，所以加一台就能缩短工期。
    优先挑没被别的作业占用的平台，避免为了消解一个冲突而制造新的冲突。

    earliest：该作业最早可开工时刻，必须把串行化（第 5 步 shift）的结果传进来。
    不传就会退回到 now+路上时间，等于把刚才的错峰撤销掉，
    产出「一台平台同时干两个活」的重叠计划（真出过这个 bug）。
    返回 (新成员列表, 新开始, 新结束)，做不到就返回 None。
    """
    t = tmap[tid]
    floor = now if earliest is None else max(now, earliest)
    cands = [((ttid, pid), c) for (ttid, pid), c in feasible_pairs.items()
             if ttid == tid and pid not in pids]
    # 空闲优先，其次代价低
    cands.sort(key=lambda kv: (kv[0][1] in anybody_used, kv[1]))

    cur = list(pids)
    added = []
    # 迭代加人：加一台不够就再加，直到能落进窗口或没有候选为止
    while True:
        rate = sum(pmap[x].work_rate for x in cur if x in pmap)
        if rate > 0:
            dur = max(1, int(math.ceil(_remain(t) / rate)))
            arrive = max(now + _travel_time(pmap[x], t) for x in cur)
            start = max(arrive, floor)      # 不能早于串行化给定的时刻
            if start + dur <= window_limit:
                return cur, start, start + dur
        nxt = None
        for (_, pid), _c in cands:
            if pid not in cur:
                nxt = pid
                break
        if nxt is None:
            return None          # 候选耗尽仍进不了窗口
        cur.append(nxt)
        added.append(nxt)


def _swap_to_fit(tid, pids, pmap, tmap, feasible_pairs, now, window_limit,
                 earliest=None):
    """加人也救不回来时，换掉拖后腿的成员。

    为什么必须换人：加人只能缩短「工期」，缩短不了「路上的时间」。
    如果最近的可用平台赶过去就要 40 步、而窗口只剩 30 步，
    那么加多少人都没用——只能换成更近、更快的平台。

    换人仍然只从 feasible_pairs 里挑，所以不会突破能力约束。
    earliest 同 `_add_crew_to_fit`：必须继承串行化的结果，否则会撤销错峰。
    返回 (新成员列表, 新开始, 新结束)，做不到返回 None。
    """
    t = tmap[tid]
    floor = now if earliest is None else max(now, earliest)
    cands = [pid for (ttid, pid) in feasible_pairs if ttid == tid]
    # 候选按"到达早、效率高"排在最前
    cands.sort(key=lambda pid: (_travel_time(pmap[pid], t),
                                -pmap[pid].work_rate))
    cur = list(pids)
    for i in range(len(cur)):
        for pid in cands:
            if pid in cur:
                continue
            trial = list(cur)
            trial[i] = pid
            rate = sum(pmap[x].work_rate for x in trial if x in pmap)
            if rate <= 0:
                continue
            dur = max(1, int(math.ceil(_remain(t) / rate)))
            arrive = max(now + _travel_time(pmap[x], t) for x in trial)
            start = max(arrive, floor)      # 不能早于串行化给定的时刻
            if start + dur <= window_limit:
                return trial, start, start + dur
    return None


def plan(snapshot: GroupSnapshot, now: int, H: int = 20, plan_id: int = 0,
         prev_plan: Optional[Plan] = None):
    """产出一份覆盖 [now, now+H] 的计划，以及这次规划的全部留痕。

    prev_plan 是上一版计划。传入它会触发"承诺保持"：
    已经发出去的指派不在本次重排中推倒重来，否则每滚一次
    开工时间就往后挪一次，作业永远做不完（这正是滚动时域最常踩的坑）。
    """
    events: List[Dict] = []
    rejected: List[Dict] = []
    pmap = {p.pid: p for p in snapshot.platforms}
    tmap = {t.tid: t for t in snapshot.tasks}
    objective = snapshot.objective

    # ---------- 0 承诺保持 ----------
    keep: Dict[str, Tuple[List[str], int]] = {}
    if prev_plan is not None and KEEP_COMMITMENT:
        for a in prev_plan.assignments:
            t = tmap.get(a.tid)
            if t is None or t.status in ("done", "failed"):
                continue
            pids = [pid for pid in a.pids
                    if pmap.get(pid) is not None and pmap[pid].alive]
            if len(pids) < t.crew:
                continue        # 成员损失导致凑不齐，交给下面的重新分配
            keep[a.tid] = (pids, a.start)

    # ---------- 1 能力过滤 + 2 代价打分 ----------
    # 拥挤度：作业点周围还活着多少平台。dispersion（暴露风险用分散度代理）
    # 要靠它才有区分度——不传这个参数，它就退化成 makespan。
    crowding: Dict[str, float] = {}
    for t in snapshot.tasks:
        if t.status in ("done", "failed"):
            continue
        crowding[t.tid] = float(sum(
            1 for p in snapshot.platforms
            if p.alive and dist(p.pos, t.pos) < 30.0))

    # 编队质心与存活数：分散度目标要靠它们才有区分度。
    # 只算存活平台——失联的平台不构成"暴露"，也不该把质心拽偏。
    alive_plats = [p for p in snapshot.platforms if p.alive]
    n_alive = len(alive_plats)
    if n_alive:
        centroid = (sum(p.pos[0] for p in alive_plats) / n_alive,
                    sum(p.pos[1] for p in alive_plats) / n_alive)
    else:
        centroid = None

    max_bat = max((p.battery for p in snapshot.platforms), default=1.0) or 1.0
    max_pay = max((p.payload for p in snapshot.platforms), default=1.0) or 1.0
    feat_map: Dict[Tuple[str, str], List[float]] = {}

    feasible_pairs: Dict[Tuple[str, str], float] = {}
    for t in snapshot.tasks:
        if t.status in ("done", "failed"):
            continue
        for p in snapshot.platforms:
            ok, why = feasible(p, t)
            if ok:
                feats = _features(p, t, crowding.get(t.tid, 0.0),
                                  max_bat, max_pay, now)
                feat_map[(t.tid, p.pid)] = feats
                if COST_WEIGHTS is not None:
                    # 学习模式：代价 = 权重 · 特征
                    feasible_pairs[(t.tid, p.pid)] = sum(
                        w * v for w, v in zip(COST_WEIGHTS, feats))
                else:
                    feasible_pairs[(t.tid, p.pid)] = _cost(
                        p, t, objective, crowding.get(t.tid, 0.0),
                        centroid, n_alive)
            else:
                rejected.append(dict(tid=t.tid, pid=p.pid, reason=why))
    events.append(dict(kind="filter", feasible_pairs=len(feasible_pairs),
                       rejected_pairs=len(rejected)))

    # ---------- 3 分配求解 ----------
    # 分两路：
    #   3a crew==1 → 一对一最优指派（匈牙利），可行域就是"一台对一个活"
    #   3b crew>1  → 排序补位（按代价从小到大凑满 N 台），保持原行为
    # crew>1 不能硬套匈牙利：一个作业要 N 台已经不是一对一了。
    per_task: Dict[str, List[str]] = {}
    for tid, (pids, _s) in keep.items():
        per_task[tid] = list(pids)          # 先保证承诺，再谈优化

    # 同一个作业的候选平台，按代价从小到大
    pairs_by_tid: Dict[str, List[Tuple[str, float]]] = {}
    for (tid, pid), c in sorted(feasible_pairs.items(), key=lambda kv: kv[1]):
        pairs_by_tid.setdefault(tid, []).append((pid, c))

    # 已承诺的平台：在 crew=1 的一对一模型里不再参与分配
    # （一台平台已经专属某一作业了）。crew>1 仍沿用"一台可顺序接多活"的老口径。
    committed = set()
    for _tid, (pids, _s) in keep.items():
        committed.update(pids)

    open_tids = [t.tid for t in snapshot.tasks
                 if t.status not in ("done", "failed")]
    single_tids = [tid for tid in open_tids
                   if tmap[tid].crew == 1 and tid not in keep]
    multi_tids = [tid for tid in open_tids
                  if tmap[tid].crew > 1 and tid not in keep]

    # ---- 3a crew==1 ----
    def _cost_of(p, t):
        return feasible_pairs.get((t.tid, p.pid))

    use_h = USE_HUNGARIAN and any(tid in pairs_by_tid for tid in single_tids)
    if use_h:
        cand_plats = [p for p in snapshot.platforms
                      if p.alive and p.pid not in committed]
        single_tasks = [tmap[tid] for tid in single_tids]
        info = solve_crew1(cand_plats, single_tasks, _cost_of)
        for tid, pid in info["assign"].items():
            per_task[tid] = [pid]
        # 最优 vs 贪心：这个差值就是"换求解器值不值"的直接证据
        events.append(dict(kind="assign_solve", scope="crew1", at=now,
                           n_task=len(single_tasks), n_plat=len(cand_plats),
                           n_pair=info["n_pair"],
                           optimal=round(info["optimal"], 2),
                           greedy=round(info["greedy"], 2),
                           gap=round(info["gap"], 2),
                           solver=info["solver"]))
    else:
        for tid in single_tids:
            lst = per_task.setdefault(tid, [])
            for pid, _c in pairs_by_tid.get(tid, []):
                if len(lst) >= tmap[tid].crew:
                    break
                if pid in lst:
                    continue
                lst.append(pid)

    # ---- 3b crew>1：排序补位 ----
    # 注意：这一步不存在"抢平台"。贪心分配允许一台平台被多个作业占用
    # （顺序执行），真正的竞争要到第 4/5 步排程时才发生。
    # 所以 EDF（截止最早的优先）要装在排程那一步，装在这里是无效的
    # ——这一点是实测确认的，不是推测。
    for tid in multi_tids:
        lst = per_task.setdefault(tid, [])
        for pid, _c in pairs_by_tid.get(tid, []):
            if len(lst) >= tmap[tid].crew:
                break
            if pid in lst:
                continue
            lst.append(pid)

    # 一个可行平台都没有的作业，原来会**静默消失**（连 rejected 都不记）。
    # 补进来，让它跟其它"凑不满人"一样进入上报口径——静默消失是最坏的结果。
    for tid in open_tids:
        if tid not in per_task:
            per_task[tid] = []

    # crew 凑不满 → 记为冲突，本轮放弃，留给下一次滚动
    for tid in list(per_task.keys()):
        need, got = tmap[tid].crew, len(per_task[tid])
        if got < need:
            events.append(dict(kind="conflict", type="crew_short", tid=tid,
                               need=need, got=got))
            # 分清两种"凑不齐"：
            #   可行平台数 < crew → 结构性不足，等多少轮也不会变，必须上报
            #   可行平台够但被别人占了 → 下轮还有机会，留待下一轮
            n_cand = len(pairs_by_tid.get(tid, []))
            structural = n_cand < need
            events.append(dict(
                kind="resolved", type="crew_short", tid=tid, by="defer",
                need_report=structural,
                note=("可行平台仅 %d 台 < 需 %d 台，结构性不足，需上报"
                      % (n_cand, need)) if structural else "留待下一轮"))
            rejected.append(dict(tid=tid, reason="协同人数不足(%d/%d)" % (got, need)))
            del per_task[tid]

    # ---------- 4 时序排程 ----------
    base: Dict[str, List] = {}
    for tid, pids in per_task.items():
        t = tmap[tid]
        remain = _remain(t)
        if remain <= 0:
            continue
        if tid in keep:
            start = max(now, keep[tid][1])   # 已在途或已开工，不重算到达时间
        else:
            start = max(now + _travel_time(pmap[pid], t) for pid in pids)
        rate = sum(pmap[pid].work_rate for pid in pids if pid in pmap)
        dur = max(1, int(math.ceil(remain / max(rate, 1e-6))))
        base[tid] = [start, start + dur, pids]

    # ---------- 5 冲突消解：同一平台的作业串行化 ----------
    by_platform: Dict[str, List[str]] = {}
    for tid, (_s, _e, pids) in base.items():
        for pid in pids:
            by_platform.setdefault(pid, []).append(tid)

    for pid, tids in by_platform.items():
        # 同一台平台上撞车的作业，谁先干？
        #   URGENCY_FIRST 开：截止早的先干（EDF）—— 让最紧的作业拿到最早的档期
        #   URGENCY_FIRST 关：谁先开始谁先干（改动前的做法）
        if URGENCY_FIRST:
            tids.sort(key=lambda x: (tmap[x].window[1], base[x][0], x))
        else:
            # 窗口余量越小（越紧张），减去的越少……实际是加上 slack：
            # 紧急的 slack 小 → 键小 → 排前面先干。
            tids.sort(key=lambda x: (
                base[x][0] + URGENCY_WEIGHT * (tmap[x].window[1] - base[x][1]),
                x))
        prev_end = -1
        for tid in tids:
            s, e, _pids = base[tid]
            if s < prev_end:
                events.append(dict(kind="conflict", type="overlap", tid=tid, pid=pid,
                                   planned_start=s, blocked_until=prev_end))
                dur = e - s
                s = prev_end
                e = s + dur
                base[tid][0], base[tid][1] = s, e
                events.append(dict(kind="resolved", type="overlap", tid=tid, pid=pid,
                                   by="shift", new_start=s))
            prev_end = max(prev_end, e)

    assignments: List[Assignment] = []
    anybody_used = set()
    for _s, _e, pids in base.values():
        anybody_used.update(pids)

    for tid, (s, e, pids) in base.items():
        t = tmap[tid]
        if e > t.window[1]:
            events.append(dict(kind="conflict", type="window", tid=tid,
                               end=e, limit=t.window[1]))
            # 先尝试加人缩短工期。协同作业的效率是各成员之和，
            # 加一台就能缩短工期——这是排不进时间窗时最直接的消解手段。
            # 消解手段按代价从小到大试：先加人（多一台干得快），
            # 加人不行再换人（换成更近更快的）。
            fixed = _add_crew_to_fit(tid, pids, pmap, tmap, feasible_pairs,
                                     now, t.window[1], anybody_used,
                                     earliest=s)
            by = "add_crew"
            if fixed is None and SWAP_TO_FIT:
                fixed = _swap_to_fit(tid, pids, pmap, tmap, feasible_pairs,
                                     now, t.window[1], earliest=s)
                by = "swap_crew"
            if fixed is not None:
                new_pids, ns, ne = fixed
                base[tid] = [ns, ne, new_pids]
                anybody_used.update(new_pids)
                s, e, pids = ns, ne, new_pids
                events.append(dict(kind="resolved", type="window", tid=tid,
                                   by=by, crew=len(pids), new_end=e))
            else:
                # 穷尽手段仍排不进 → 必须上报，不能静默悬着。
                # 让上层去决定：放宽窗口、增派资源、还是正式放弃这个作业。
                events.append(dict(kind="resolved", type="window", tid=tid,
                                   by="defer", need_report=True,
                                   note="超时窗(end=%d>%d)，加人与换人均无效，需上报"
                                        % (e, t.window[1])))
                rejected.append(dict(tid=tid, reason="超出时间窗(end=%d>%d)"
                                     % (e, t.window[1])))
                continue
        if s > now + H:
            rejected.append(dict(tid=tid, reason="超出规划视野(H=%d)" % H))
            continue
        assignments.append(Assignment(tid=tid, pids=pids, start=s, end=e,
                                      seq=s, coord="crew>=%d" % t.crew))
    assignments.sort(key=lambda a: (a.start, a.tid))

    # ---------- 6 输出校验：整份方案再过一遍 ----------
    # 关键：单条指派合法 ≠ 整份方案合法。一台平台接三个作业，
    # 每个单看都不超时，加起来可能超续航。这一步就是抓这种情况。
    # 按开工顺序逐条累加。超过续航的那条**从方案里撤下**，而不是照发。
    # 只记录不拦截等于没校验——H 放宽后就真出现了 7 次叠加超续航。
    usage: Dict[str, int] = {}
    drop = set()
    for a in sorted(assignments, key=lambda x: (x.start, x.tid)):
        t = tmap[a.tid]
        need_of: Dict[str, float] = {}
        over = False
        for pid in a.pids:
            p = pmap.get(pid)
            if p is None:
                continue
            # 与闸门同口径：按电量累加（移动一次 + 作业这些步）
            need = (_travel_time(p, t) * p.move_cost
                    + max(1, a.end - a.start) * p.work_cost)
            need_of[pid] = need
            if usage.get(pid, 0) + need > p.battery:
                over = True
                events.append(dict(kind="violation", pid=pid, tid=a.tid,
                                   need=usage.get(pid, 0) + need,
                                   battery=p.battery,
                                   note="方案级越界：单条合法但叠加超续航"))
        if over:
            drop.add(a.tid)
            continue
        for pid, need in need_of.items():
            usage[pid] = usage.get(pid, 0) + need
    if drop:
        assignments = [a for a in assignments if a.tid not in drop]
        for tid in sorted(drop):
            rejected.append(dict(tid=tid, reason="方案级越界（叠加超续航），本轮撤下"))

    pl = Plan(plan_id=plan_id, created_at=now, horizon=H,
              group_version=snapshot.version, rule_version=RULE_VERSION,
              objective=objective, assignments=assignments, rejected=rejected)
    return pl, events


def hungarian_total_cost(snapshot: GroupSnapshot, now: int = 0) -> Optional[float]:
    """一对一最优指派的总代价（保留旧接口，供 README 里的对照命令使用）。

    只在所有作业 crew==1 时有意义；否则一对一模型不适用，返回 None。
    现在自带 JV 实现，没装 scipy 也能算。
    """
    tasks = [t for t in snapshot.tasks if t.status not in ("done", "failed")]
    plats = [p for p in snapshot.platforms if p.alive]
    if not tasks or not plats:
        return None
    if any(t.crew != 1 for t in tasks):
        return None                       # 有协同作业，一对一模型不适用
    info = solve_crew1(plats, tasks,
                       lambda p, t: (_cost(p, t, snapshot.objective)
                                     if feasible(p, t)[0] else None))
    return float(info["optimal"])


def solve_report(snapshot: GroupSnapshot) -> Optional[Dict]:
    """crew==1 作业的最优 vs 贪心对照（run_flow 末尾打印用）。"""
    tasks = [t for t in snapshot.tasks if t.status not in ("done", "failed")
             and t.crew == 1]
    plats = [p for p in snapshot.platforms if p.alive]
    if not tasks or not plats:
        return None
    return solve_crew1(plats, tasks,
                       lambda p, t: (_cost(p, t, snapshot.objective)
                                     if feasible(p, t)[0] else None))
