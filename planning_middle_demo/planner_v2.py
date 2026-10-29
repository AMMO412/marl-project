# -*- coding: utf-8 -*-
"""
planner_v2.py —— 六步规则规划器（自 planning/planner.py 移植）

一次规划 6 步，每步留痕（events）：

  1 能力过滤   剔除不可行的 (平台, 作业) 组合
  2 代价打分   按当前优化目标（makespan / dispersion / energy）
  3 分配求解   crew>=N 前提下指派；crew==1 走一对一最优（匈牙利）
  4 时序排程   排入时间窗，协同作业等人齐
  5 冲突消解   同平台重叠串行后移；排不进窗口时加人→换人→上报
  6 输出校验   整份方案再过一遍续航约束（单条合法≠整份合法）

与 planning/ 原版的差异（只动接口，不动算法结论）：
  * 数据模型换成 contracts_v2 的 Platform/Job（对齐下游 50 台编成）
  * 能力闸门新增 altitude：目标高度>0 的作业只有 PLANE/WING 可接
    （这是下游接口的结构性事实——地面平台没有 linear.z，
    不是"参数未知"，所以不进 ENABLED_CHECKS 开关，恒生效）
  * plan() 直接吃平台/作业列表，不再包 GroupSnapshot

移植时保留的原版已踩坑修复（别退回去）：
  * 排程用剩余工作量 _remain，不是总量（否则滚动时域无限推迟开工）
  * KEEP_COMMITMENT 保持已发指派（关掉即复现"作业永远做不完"）
  * add/swap_crew 必须继承 earliest（否则撤销串行错峰，产出重叠非法计划）
  * EDF 默认关（实测负优化：消解率涨但完成数掉，不紧急作业被饿死）
  * move_cost 与速度正相关（否则 energy 与 makespan 永远同解）
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from contracts_v2 import Job, Platform, dist
import motion

RULE_VERSION = "rule-v1.0-demo"

# 在途时间估算语义（与运动层对齐，勿改回"距离/速度"一刀切）：
#   "teleport" 瞬移：travel = ceil(距离/速度)，只用于算移动电，
#               下层瞬移到达（规划快进）。
#   "real"     真实运动：travel = motion.estimate_arrival_steps，
#               用与下层相同的 GoalController 闭环预演"先转后走+加
#               减速"的实际到达步数。若仍用 ceil(距离/速度) 会系统性
#               低估到达时间，导致 deviation/timeout 误判。
# plan() 会按传入的 motion 设置本开关。
MOTION_SEMANTICS = "teleport"

# 到位后行为模式：plan() 传入 behavior=True 时置位。开启后作业时长用
# BEHAVIOR_DURATION 预估（而非 work/work_rate），使排程与超时/偏差检测
# 与行为状态机的实际耗时对齐。
BEHAVIOR_MODE = False

# V1 只启用续航与载荷校验（参数到位再加 sensor / motion）。
# altitude 不在这里：它是接口结构事实，恒生效（见模块头注释）。
ENABLED_CHECKS = {"battery", "payload"}
ALL_CHECKS = {"battery", "payload", "sensor", "motion", "altitude(always)"}

KEEP_COMMITMENT = True       # 滚动重规划时保持上一版已发出的指派
URGENCY_FIRST = False        # EDF：实测负优化，默认关，保留开关供复现
URGENCY_WEIGHT = 0.0         # 紧迫度连续权重（学习层可调）
SWAP_TO_FIT = True           # 排不进窗口时，加人之后再试换人
USE_HUNGARIAN = True         # crew==1 一对一最优指派
BIG_COST = 1e7               # 不可行对在代价矩阵里的填充值（不能是 inf）

# 分散度目标代价项（我方暂定，扫参得出，见 planning/README 五之二）
SPREAD_SCALE = 50.0
W_SPREAD = 20.0
W_CROWD = 10.0
W_TIME_DISP = 1.0
W_TIME_ENERGY = 0.3

COST_TERMS = {
    "makespan":   dict(time=1.0, energy=0.0, spread=0.0, crowd=0.0),
    "energy":     dict(time=W_TIME_ENERGY, energy=1.0, spread=0.0, crowd=0.0),
    "dispersion": dict(time=W_TIME_DISP, energy=0.0, spread=W_SPREAD, crowd=W_CROWD),
}


# ------------------------------------------------------------------
# 到位后行为（behavior 模式）的作业时长预估（步）
#
# 行为层的完成判定不依赖 work 值（巡逻看圈数、侦察看覆盖率、突击看
# 阶段、坚守看换班次数），实际耗时由状态机决定，远大于 work/work_rate
# 的换算。规划器排程与超时/偏差检测若仍用 work/work_rate，会在行为
# 跑完前就误判超时或进度偏差。这里给每类行为一个保守的经验预估
# （偏大，避免误杀；行为层自带 max_steps/timeout 兜底）。
# ------------------------------------------------------------------
BEHAVIOR_DURATION = {
    "patrol":   72,     # 3 圈 × 6 检查点 × ~4 步/点 + 机动
    "blockade": 90,     # 占位 + 入侵接近 + 拦截处置（对齐 max_steps）
    "recon":    120,    # 覆盖率 0.9 需多轮前沿扩展
    "assault":  60,     # 机动→到位→执行→结果确认 四阶段 + 停留
    "hold":     36,     # 2 次换班 × 12 s + 机动
}



@dataclass
class Assignment:
    job_id: str
    pids: List[str]
    start: int              # 出发时刻（本步立即出发）
    end: int                # 完工时刻（含在途 + 作业）
    travel: int = 0         # 在途时长（步）
    dur: int = 0            # 作业时长（步）
    seq: int = 0
    coord: str = ""


@dataclass
class Plan:
    plan_id: int
    created_at: int
    horizon: int
    objective: str
    rule_version: str
    assignments: List[Assignment]
    rejected: List[dict] = field(default_factory=list)


# ------------------------------------------------------------------
# 基础量
# ------------------------------------------------------------------
def _travel_time(p: Platform, t: Job) -> int:
    """估算在途步数。口径由 MOTION_SEMANTICS 决定（见模块头注释）。

    真实运动口径要带高度与朝向：飞机的爬升也耗时（受 max_linear 限制），
    且平台当前朝向 yaw 非 0 时要先转向（"先转后走"），转向耗时被
    瞬移口径 ceil(水平距离/速度) 漏掉。start 的高度取 0（平台起始高度），
    goal 的高度取作业 altitude。
    """
    if MOTION_SEMANTICS == "real":
        start = (p.pos[0], p.pos[1], 0.0, getattr(p, "yaw", 0.0))
        goal = (t.pos[0], t.pos[1], t.altitude, 0.0)
        return motion.estimate_arrival_steps(
            start, goal, max_linear=max(p.speed, 1e-6),
            can_climb=p.can_climb)
    return int(math.ceil(dist(p.pos, t.pos) / max(p.speed, 1e-6)))


def _remain(t: Job) -> float:
    return max(0.0, t.work - t.progress)


# ------------------------------------------------------------------
# 行为模式的全程里程预估（不是"到作业点那一段"）
#
# 行为层接管后，平台的位移是：当前位 → 集结区 → 执行环 → 撤离点，
# 全部由 BehaviorRunner 推进、按实际行程记电（mock_fleet）。规划期若
# 只算 dist(当前位, 作业点)，就会派出"半路没电"的平台：本场景 16 台
# 全程约 300 米、需 120 电量，而 UGV 只有 100。
#
# assault 用场景 _behavior 给的几何直接算（集结中心/半径、执行环半径、
# 撤离点/半径）；撤离开关关闭时不计返程。其余类型没有显式几何，用保守
# 经验值兜底（区内机动），只在报告里标注为估算，不当作精确航路。
# ------------------------------------------------------------------
BEHAVIOR_MILEAGE = {
    "patrol": 24.0,      # 环路 3 圈（半径 2.4、6 检查点）的周长量级
    "blockade": 8.0,     # 岗位就位 + 一次前出拦截
    "recon": 40.0,       # 覆盖 9 半径区域的前沿跳跃
    "hold": 4.0,         # 岗位/待命位短距轮换
}


def _approach_mileage(p: Platform, t: Job) -> float:
    """机动里程：从当前位到"开始执行"的位置（集结区），不含区内与撤离。"""
    bh = getattr(t, "behavior", None) or {}
    if t.jtype == "assault" and bh.get("staging_center"):
        return (dist(p.pos, [float(v) for v in bh["staging_center"]])
                + float(bh.get("staging_radius", 4.2)))
    return dist(p.pos, t.pos)


def _approach_time(p: Platform, t: Job) -> int:
    """机动步数。行为模式下作战作业的"到位"是到集结区，不是到作业点，
    用作业点算会把机动时间写短（本场景少 27 s）。"""
    if BEHAVIOR_MODE and t.jtype in BEHAVIOR_DURATION:
        return int(math.ceil(_approach_mileage(p, t) / max(p.speed, 1e-6)))
    return _travel_time(p, t)


def _behavior_mileage(p: Platform, t: Job) -> float:
    """行为模式下一次任务的全程里程（含集结、区内机动与撤离）。"""
    bh = getattr(t, "behavior", None) or {}
    if t.jtype not in BEHAVIOR_DURATION:
        return dist(p.pos, t.pos)
    if t.jtype == "assault":
        site = t.pos
        staging = bh.get("staging_center") or site
        first = _approach_mileage(p, t)
        mid = dist(staging, site) + float(bh.get("objective_radius", 1.4))
        last = 0.0
        if bh.get("withdraw") and bh.get("withdraw_point"):
            last = (dist(site, [float(v) for v in bh["withdraw_point"]])
                    + float(bh.get("withdraw_ring", 2.0)))
        return first + mid + last
    return dist(p.pos, t.pos) + BEHAVIOR_MILEAGE.get(t.jtype, 0.0)


def _energy_need(p: Platform, t: Job) -> float:
    """一次指派预计耗电 = 移动里程*move_cost + 作业步数*work_cost。

    行为模式下作业时长由状态机决定、耗电只按实际位移记（mock_fleet 的
    行为分支不扣 work_cost），所以这里也只算全程里程的移动电——少算
    一段会派出半路没电的平台，多算作业电则会误拒。
    """
    if BEHAVIOR_MODE and t.jtype in BEHAVIOR_DURATION:
        return (_behavior_mileage(p, t) / max(p.speed, 1e-6)) * p.move_cost
    return _travel_time(p, t) * p.move_cost + _work_time(p, t) * p.work_cost


def _work_time(p: Platform, t: Job) -> int:
    if BEHAVIOR_MODE and t.jtype in BEHAVIOR_DURATION:
        return BEHAVIOR_DURATION[t.jtype]
    return int(math.ceil(_remain(t) / max(p.work_rate, 1e-6)))


def feasible(p: Platform, t: Job):
    """能力闸门。返回 (可行否, 不可行原因)。"""
    if not p.alive:
        return False, "平台失联"
    if t.altitude > 0 and not p.can_climb:
        return False, "目标高度不可达(需空中平台)"
    if "battery" in ENABLED_CHECKS:
        need = _energy_need(p, t)
        if p.battery < need:
            if BEHAVIOR_MODE and t.jtype in BEHAVIOR_DURATION:
                return False, ("续航不足(全程%.0f需%.1f剩%.1f)"
                               % (_behavior_mileage(p, t), need, p.battery))
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


def _cost(p, t, objective, crowded=0.0, centroid=None, n_alive=1):
    """代价越小越优先；三个目标各用各的项，互不混叠。"""
    travel = _approach_time(p, t)
    work_t = _work_time(p, t)
    time_term = float(travel + work_t)
    energy_term = _energy_need(p, t)
    if centroid is None:
        spread_term = 0.0
    else:
        spread_term = (dist(p.pos, centroid) - dist(t.pos, centroid)) / SPREAD_SCALE
    crowd_term = crowded / max(n_alive, 1)
    w = COST_TERMS.get(objective, COST_TERMS["makespan"])
    return (w["time"] * time_term + w["energy"] * energy_term
            + w["spread"] * spread_term + w["crowd"] * crowd_term)


# ------------------------------------------------------------------
# 匈牙利（一对一最优指派），纯标准库 JV 实现
# ------------------------------------------------------------------
def _hungarian_stdlib(C):
    """矩形代价矩阵的最小和一对一指派。返回 [(行, 列), ...]。

    自带实现的原因：交付环境无外网，不能假设装了 scipy/numpy；
    有 scipy 时 hungarian() 会优先用它，两者在单测互校。
    """
    n = len(C)
    m = len(C[0]) if n else 0
    if n == 0 or m == 0:
        return []
    transposed = False
    if n > m:
        C = [[C[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
        transposed = True

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
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
            if j1 < 0:
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
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    res = []
    for j in range(1, m + 1):
        if p[j]:
            i, col = p[j] - 1, j - 1
            res.append((col, i) if transposed else (i, col))
    return res


def hungarian(C, prefer_scipy=True):
    """返回 (匹配列表, 求解器名)。scipy 不可用自动退回内置实现。"""
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
    """crew==1 的一对一指派：最优（匈牙利）与贪心（同一可行域）对照。"""
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
        if C[i][j] >= BIG:
            continue
        assign[tasks[j].job_id] = plats[i].pid
        optimal += C[i][j]

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


# ------------------------------------------------------------------
# 排不进时间窗的消解：加人 / 换人
# ------------------------------------------------------------------
def _add_crew_to_fit(job_id, pids, pmap, jmap, feasible_pairs, now,
                     window_limit, anybody_used, earliest=None):
    """加人缩短工期使作业落进窗口。返回 (pids, 开工, 完工)。

    earliest 必须继承串行化结果（开工时刻）。"""
    t = jmap[job_id]
    floor = now if earliest is None else max(now, earliest)
    cands = [((jid, pid), c) for (jid, pid), c in feasible_pairs.items()
             if jid == job_id and pid not in pids]
    cands.sort(key=lambda kv: (kv[0][1] in anybody_used, kv[1]))
    cur = list(pids)
    while True:
        rate = sum(pmap[x].work_rate for x in cur if x in pmap)
        if rate > 0:
            dur = max(1, int(math.ceil(_remain(t) / rate)))
            travel = max(_travel_time(pmap[x], t) for x in cur)
            arrive = max(now + travel, floor)
            if arrive + dur <= window_limit:
                return cur, arrive, arrive + dur
        nxt = None
        for (_, pid), _c in cands:
            if pid not in cur:
                nxt = pid
                break
        if nxt is None:
            return None
        cur.append(nxt)


def _swap_to_fit(job_id, pids, pmap, jmap, feasible_pairs, now,
                 window_limit, earliest=None):
    """加人救不回时换成更近更快的平台。返回 (pids, 开工, 完工)。"""
    t = jmap[job_id]
    floor = now if earliest is None else max(now, earliest)
    cands = [pid for (jid, pid) in feasible_pairs if jid == job_id]
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
            travel = max(_travel_time(pmap[x], t) for x in trial)
            arrive = max(now + travel, floor)
            if arrive + dur <= window_limit:
                return trial, arrive, arrive + dur
    return None


# ------------------------------------------------------------------
# 主入口：一次规划
# ------------------------------------------------------------------
def plan(platforms: List[Platform], jobs: List[Job], now: int, H: int = 20,
         plan_id: int = 0, objective: str = "makespan",
         prev_plan: Optional[Plan] = None, motion: str = "teleport",
         behavior: bool = False):
    """产出覆盖 [now, now+H] 的一份计划及全部留痕。

    motion 决定在途时间估算口径：teleport 用"距离/速度"，real 用
    与运动层同源的 GoalController 闭环预演（见 MOTION_SEMANTICS）。
    behavior=True 时，作业时长用行为状态机的经验预估（BEHAVIOR_DURATION）。
    """
    global MOTION_SEMANTICS, BEHAVIOR_MODE
    if motion not in ("teleport", "real"):
        raise ValueError("motion 必须是 teleport 或 real")
    MOTION_SEMANTICS = motion
    BEHAVIOR_MODE = bool(behavior)
    events = []
    rejected = []
    pmap = {p.pid: p for p in platforms}
    jmap = {j.job_id: j for j in jobs}
    open_jobs = [j for j in jobs if j.status not in
                 ("succeeded", "failed", "cancelling")]

    # ---------- 0 承诺保持 ----------
    keep = {}
    if prev_plan is not None and KEEP_COMMITMENT:
        for a in prev_plan.assignments:
            j = jmap.get(a.job_id)
            if j is None or j.status in ("succeeded", "failed", "cancelling"):
                continue
            pids = [pid for pid in a.pids
                    if pmap.get(pid) is not None and pmap[pid].alive]
            if len(pids) < j.crew:
                continue
            keep[a.job_id] = (list(pids), a.start)

    # ---------- 1 能力过滤 + 2 代价打分 ----------
    crowding = {}
    for j in open_jobs:
        crowding[j.job_id] = float(sum(
            1 for p in platforms if p.alive and dist(p.pos, j.pos) < 30.0))
    alive_plats = [p for p in platforms if p.alive]
    n_alive = len(alive_plats)
    if n_alive:
        centroid = (sum(p.pos[0] for p in alive_plats) / n_alive,
                    sum(p.pos[1] for p in alive_plats) / n_alive)
    else:
        centroid = None
    feasible_pairs = {}
    for j in open_jobs:
        for p in platforms:
            ok, why = feasible(p, j)
            if ok:
                feasible_pairs[(j.job_id, p.pid)] = _cost(
                    p, j, objective, crowding.get(j.job_id, 0.0),
                    centroid, n_alive)
            else:
                rejected.append(dict(job_id=j.job_id, pid=p.pid, reason=why))
    events.append(dict(kind="filter", feasible_pairs=len(feasible_pairs),
                       rejected_pairs=len(rejected)))

    # ---------- 3 分配求解 ----------
    per_task = {}
    for job_id, (pids, _s) in keep.items():
        per_task[job_id] = list(pids)

    pairs_by_job = {}
    for (jid, pid), c in sorted(feasible_pairs.items(), key=lambda kv: kv[1]):
        pairs_by_job.setdefault(jid, []).append((pid, c))

    committed = set()
    for _jid, (pids, _s) in keep.items():
        committed.update(pids)

    open_ids = [j.job_id for j in open_jobs]
    single_ids = [jid for jid in open_ids
                  if jmap[jid].crew == 1 and jid not in keep]
    multi_ids = [jid for jid in open_ids
                 if jmap[jid].crew > 1 and jid not in keep]

    def _cost_of(p, t):
        return feasible_pairs.get((t.job_id, p.pid))

    use_h = USE_HUNGARIAN and any(jid in pairs_by_job for jid in single_ids)
    if use_h:
        cand_plats = [p for p in platforms if p.alive and p.pid not in committed]
        single_jobs = [jmap[jid] for jid in single_ids]
        info = solve_crew1(cand_plats, single_jobs, _cost_of)
        for jid, pid in info["assign"].items():
            per_task[jid] = [pid]
        events.append(dict(kind="assign_solve", scope="crew1", at=now,
                           n_task=len(single_jobs), n_plat=len(cand_plats),
                           n_pair=info["n_pair"],
                           optimal=round(info["optimal"], 2),
                           greedy=round(info["greedy"], 2),
                           gap=round(info["gap"], 2),
                           solver=info["solver"]))
    else:
        for jid in single_ids:
            lst = per_task.setdefault(jid, [])
            for pid, _c in pairs_by_job.get(jid, []):
                if len(lst) >= jmap[jid].crew:
                    break
                if pid in lst:
                    continue
                lst.append(pid)

    for jid in multi_ids:
        lst = per_task.setdefault(jid, [])
        for pid, _c in pairs_by_job.get(jid, []):
            if len(lst) >= jmap[jid].crew:
                break
            if pid in lst:
                continue
            lst.append(pid)

    # 零可行平台的作业不许静默消失：补空列表进上报口径
    for jid in open_ids:
        if jid not in per_task:
            per_task[jid] = []

    for jid in list(per_task.keys()):
        need, got = jmap[jid].crew, len(per_task[jid])
        if got < need:
            events.append(dict(kind="conflict", type="crew_short", job_id=jid,
                               need=need, got=got))
            n_cand = len(pairs_by_job.get(jid, []))
            structural = n_cand < need
            events.append(dict(
                kind="resolved", type="crew_short", job_id=jid, by="defer",
                need_report=structural,
                note=("可行平台仅 %d 台 < 需 %d 台，结构性不足，需上报"
                      % (n_cand, need)) if structural else "留待下一轮"))
            rejected.append(dict(job_id=jid,
                                 reason="协同人数不足(%d/%d)" % (got, need)))
            del per_task[jid]

    # ---------- 4 时序排程 ----------
    # 时间语义（与 coordinator/mock_fleet 对齐，勿改）：
    #   teleport：start = 开工时刻（= now + travel），travel 是"延迟开工"；
    #             下层瞬移到达，end = start + dur = 完工时刻。
    #   real    ：start = 出发时刻（= now），平台下发即出发，走 travel 步
    #             到达后再干 dur 步；end = now + travel + dur = 完工时刻。
    #             这样 _dispatch 的"start<=now 才下发"在两种语义下都成立。
    # 承诺保持（KEEP_COMMITMENT）：teleport 保留旧 start（防基准后移）；
    #   real 下 pos 在途漂移、travel 随接近而减小，start 恒 = now。
    base = {}
    for jid, pids in per_task.items():
        j = jmap[jid]
        remain = _remain(j)
        if remain <= 0:
            continue
        travel = max(_approach_time(pmap[pid], j) for pid in pids)
        rate = sum(pmap[pid].work_rate for pid in pids if pid in pmap)
        if BEHAVIOR_MODE and j.jtype in BEHAVIOR_DURATION:
            # 行为模式：作业时长由行为状态机决定，与 crew 无关
            dur = BEHAVIOR_DURATION[j.jtype]
        else:
            dur = max(1, int(math.ceil(remain / max(rate, 1e-6))))
        if MOTION_SEMANTICS == "real":
            start = now                       # 出发时刻
            end = now + travel + dur          # 完工时刻 = 出发 + 在途 + 作业
        elif jid in keep:
            start = max(now, keep[jid][1])
            end = start + dur
        else:
            start = now + travel
            end = start + dur
        base[jid] = [start, end, pids, travel, dur]

    # ---------- 5 冲突消解：同平台串行化 ----------
    by_platform = {}
    for jid, (_s, _e, pids, _tr, _du) in base.items():
        for pid in pids:
            by_platform.setdefault(pid, []).append(jid)

    for pid, jids in by_platform.items():
        if URGENCY_FIRST:
            jids.sort(key=lambda x: (jmap[x].window[1], base[x][0], x))
        else:
            jids.sort(key=lambda x: (
                base[x][0] + URGENCY_WEIGHT * (jmap[x].window[1] - base[x][1]),
                x))
        prev_end = -1
        for jid in jids:
            s, e, _pids, travel, dur = base[jid]
            if s < prev_end:
                events.append(dict(kind="conflict", type="overlap",
                                   job_id=jid, pid=pid,
                                   planned_start=s, blocked_until=prev_end))
                s = prev_end
                # 真实运动下 e = 出发 + 在途 + 作业；瞬移下 e = 出发 + 作业
                if MOTION_SEMANTICS == "real":
                    e = s + travel + dur
                else:
                    e = s + dur
                base[jid][0], base[jid][1] = s, e
                events.append(dict(kind="resolved", type="overlap",
                                   job_id=jid, pid=pid, by="shift",
                                   new_start=s))
            prev_end = max(prev_end, e)

    anybody_used = set()
    for _s, _e, pids, _tr, _du in base.values():
        anybody_used.update(pids)

    assignments = []
    for jid, (s, e, pids, travel, dur) in base.items():
        j = jmap[jid]
        # 行为模式：作业时长由行为状态机决定，时间窗只作排程参考，
        # 不因"预估超窗"而下发前拒收——行为层自带 max_steps/timeout 兜底。
        if e > j.window[1] and BEHAVIOR_MODE:
            events.append(dict(kind="note", type="window_relaxed", job_id=jid,
                               end=e, limit=j.window[1],
                               note="行为模式：时间窗只作参考，行为层自行兜底"))
        elif e > j.window[1]:
            events.append(dict(kind="conflict", type="window", job_id=jid,
                               end=e, limit=j.window[1]))
            fixed = _add_crew_to_fit(jid, pids, pmap, jmap, feasible_pairs,
                                     now, j.window[1], anybody_used,
                                     earliest=s)
            by = "add_crew"
            if fixed is None and SWAP_TO_FIT:
                fixed = _swap_to_fit(jid, pids, pmap, jmap, feasible_pairs,
                                     now, j.window[1], earliest=s)
                by = "swap_crew"
            if fixed is not None:
                new_pids, ns, ne = fixed
                # 保留原 travel/dur 语义：新开工 ns，完工 ne，工期 = ne - ns
                ntravel = max(1, ne - ns)
                ndur = max(1, ne - ns)
                base[jid] = [ns, ne, new_pids, ntravel, ndur]
                anybody_used.update(new_pids)
                s, e, pids, travel, dur = ns, ne, new_pids, ntravel, ndur
                events.append(dict(kind="resolved", type="window", job_id=jid,
                                   by=by, crew=len(pids), new_end=e))
            else:
                events.append(dict(kind="resolved", type="window", job_id=jid,
                                   by="defer", need_report=True,
                                   note="超时窗(end=%d>%d)，加人与换人均无效，需上报"
                                        % (e, j.window[1])))
                rejected.append(dict(job_id=jid,
                                     reason="超出时间窗(end=%d>%d)"
                                            % (e, j.window[1])))
                continue
        # 行为模式：作业时长远超原 work 量（60~120 步），固定 H 视野会
        # 把串行排程推到视野外的作业永久拒收。行为模式作业数量少，放宽
        # 视野（仍排入，靠滚动重规划与行为层兜底）。
        if s > now + H and not BEHAVIOR_MODE:
            rejected.append(dict(job_id=jid, reason="超出规划视野(H=%d)" % H))
            continue
        assignments.append(Assignment(job_id=jid, pids=pids, start=s, end=e,
                                       travel=travel, dur=dur,
                                       seq=s, coord="crew>=%d" % j.crew))
    assignments.sort(key=lambda a: (a.start, a.job_id))

    # ---------- 6 输出校验：整份方案再过一遍续航 ----------
    usage = {}
    drop = set()
    for a in sorted(assignments, key=lambda x: (x.start, x.job_id)):
        j = jmap[a.job_id]
        need_of = {}
        over = False
        for pid in a.pids:
            p = pmap.get(pid)
            if p is None:
                continue
            if BEHAVIOR_MODE and j.jtype in BEHAVIOR_DURATION:
                need = _energy_need(p, j)     # 全程里程（见 _behavior_mileage）
            else:
                need = (_travel_time(p, j) * p.move_cost
                        + max(1, a.end - a.start) * p.work_cost)
            need_of[pid] = need
            if usage.get(pid, 0) + need > p.battery:
                over = True
                events.append(dict(kind="violation", pid=pid, job_id=a.job_id,
                                   need=round(usage.get(pid, 0) + need, 1),
                                   battery=p.battery,
                                   note="方案级越界：单条合法但叠加超续航"))
        if over:
            drop.add(a.job_id)
            continue
        for pid, need in need_of.items():
            usage[pid] = usage.get(pid, 0) + need
    if drop:
        assignments = [a for a in assignments if a.job_id not in drop]
        for jid in sorted(drop):
            rejected.append(dict(job_id=jid,
                                 reason="方案级越界（叠加超续航），本轮撤下"))

    pl = Plan(plan_id=plan_id, created_at=now, horizon=H, objective=objective,
              rule_version=RULE_VERSION, assignments=assignments,
              rejected=rejected)
    return pl, events
