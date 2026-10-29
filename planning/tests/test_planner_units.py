# -*- coding: utf-8 -*-
"""
规划器单元测试（WP1）

跑法（纯标准库，Windows 侧也能跑）：
    python tests/test_planner_units.py

与 test_violations.py 的分工：
    test_violations 测的是「能力边界有没有被拦住」（越界用例集）
    本文件测的是「规划器本身的决策与求解对不对」

必测的三类（WP1 验收点）：
    1. crew 不足      —— 结构性不足必须上报，不能静默
    2. 超出时间窗     —— 卡点必须是时间窗本身，不能被续航抢先拦掉
    3. 方案级越界     —— 单条合法、叠加越界，必须判越界且撤下

外加匈牙利求解器的正确性（手算小例 + 最优≤贪心不变量 + 与 scipy 互校）。

输出三态：PASS / FAIL / SKIP。**SKIP 不是通过。**
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import planner                                          # noqa: E402
from contract import GroupSnapshot, Platform, Task      # noqa: E402

BASE_P = dict(pid="P00", ptype="ugv", pos=(0.0, 0.0), battery=1000.0,
              payload=6.0, speed=1.0, work_rate=1.0, sensor="eo", alive=True,
              move_cost=1.0, work_cost=1.0)
BASE_T = dict(tid="T00", ttype="patrol", pos=(10.0, 0.0), work=10.0,
              window=(0, 60), crew=1, need_payload=0.0, need_sensor=None)

RESULTS = []


def build(n_plat=1, n_task=1, p_over=None, t_over=None, t_over_list=None,
          objective="makespan"):
    plats = []
    for i in range(n_plat):
        p = dict(BASE_P)
        p["pid"] = "P%02d" % i
        if p_over:
            p.update(p_over)
        plats.append(Platform(**p))
    tasks = []
    for j in range(n_task):
        t = dict(BASE_T)
        t["tid"] = "T%02d" % j
        if t_over_list and j < len(t_over_list):
            t.update(t_over_list[j])
        elif t_over:
            t.update(t_over)
        tasks.append(Task(**t))
    return GroupSnapshot(version=1, step=0, objective=objective,
                         platforms=plats, tasks=tasks)


def case(name, fn, skip=None):
    if skip:
        RESULTS.append((name, "SKIP", skip))
        return
    try:
        ok, note = fn()
        RESULTS.append((name, "PASS" if ok else "FAIL", note))
    except Exception as e:
        RESULTS.append((name, "FAIL", "用例本身报错：%r" % e))


# ---------------------------------------------------------------- 1 crew 不足

def c_crew_structural():
    """结构性不足：可行平台数 < crew，等多少轮都不会变，必须 need_report。"""
    snap = build(n_plat=2, t_over=dict(crew=3))
    pl, ev = planner.plan(snap, 0, H=60)
    conf = [e for e in ev if e.get("type") == "crew_short"]
    rep = [e for e in ev if e.get("need_report")]
    return (len(pl.assignments) == 0 and len(conf) > 0 and len(rep) > 0,
            "指派 %d 条 / crew_short %d 条 / need_report %d 条"
            % (len(pl.assignments), len(conf), len(rep)))


def c_crew_partial():
    """可行平台有 2 台但 crew=3：仍然是凑不满，且被记为结构性不足。"""
    snap = build(n_plat=2, t_over=dict(crew=3))
    pl, ev = planner.plan(snap, 0, H=60)
    note = " ".join(e.get("note", "") for e in ev
                    if e.get("type") == "crew_short")
    return ("结构性" in note and len(pl.assignments) == 0,
            "note=%r，指派 %d 条" % (note, len(pl.assignments)))


def c_crew_no_candidate():
    """一台可行平台都没有：原来会静默消失，现在必须进 rejected 且有留痕。"""
    snap = build(n_plat=1, t_over=dict(need_payload=99.0, crew=2))
    pl, ev = planner.plan(snap, 0, H=60)
    rej = [r for r in pl.rejected if r.get("tid") == "T00"]
    return (len(pl.assignments) == 0 and len(rej) > 0,
            "指派 %d 条 / rejected 命中 %d 条" % (len(pl.assignments), len(rej)))


def c_crew_ok():
    """正例：平台数够，crew 满足，应当放行。"""
    snap = build(n_plat=3, t_over=dict(crew=3))
    pl, ev = planner.plan(snap, 0, H=60)
    got = len(pl.assignments[0].pids) if pl.assignments else 0
    return len(pl.assignments) == 1 and got >= 3, \
        "指派 %d 条，人数 %d" % (len(pl.assignments), got)


# ---------------------------------------------------------------- 2 时间窗

def c_window():
    """唯一卡点是时间窗：续航给足，否则测出来的是续航不是时间窗。"""
    snap = build(p_over=dict(battery=1000.0), t_over=dict(window=(0, 5)))
    pl, ev = planner.plan(snap, 0, H=60)
    win = [e for e in ev if e.get("type") == "window"]
    return len(pl.assignments) == 0 and len(win) > 0, \
        "指派 %d 条 / window 冲突 %d 条" % (len(pl.assignments), len(win))


def c_window_within():
    """正例：窗口足够宽，应当放行。"""
    snap = build(p_over=dict(battery=1000.0), t_over=dict(window=(0, 60)))
    pl, ev = planner.plan(snap, 0, H=60)
    win = [e for e in ev if e.get("type") == "window"]
    return len(pl.assignments) == 1 and not win, \
        "指派 %d 条 / window 冲突 %d 条" % (len(pl.assignments), len(win))


def c_window_defer_reports():
    """排不进窗口且加人换人都无效 → defer 且 need_report=True，不许静默。"""
    snap = build(p_over=dict(battery=1000.0), t_over=dict(window=(0, 5)))
    pl, ev = planner.plan(snap, 0, H=60)
    defer = [e for e in ev if e.get("type") == "window" and e.get("by") == "defer"]
    return len(defer) > 0 and all(e.get("need_report") for e in defer), \
        "defer %d 条，need_report=%s" % (len(defer),
                                         [e.get("need_report") for e in defer])


# ---------------------------------------------------------------- 3 方案级越界

def c_plan_level_violation():
    """单条合法、叠加越界。crew=2 是为了绕开 crew=1 的一对一约束。"""
    snap = build(n_plat=2, n_task=2, p_over=dict(battery=25.0),
                 t_over_list=[dict(pos=(10.0, 0.0), crew=2),
                              dict(pos=(10.0, 0.0), crew=2)])
    pl, ev = planner.plan(snap, 0, H=60)
    viol = [e for e in ev if e.get("kind") == "violation"]
    tids = {e.get("tid") for e in viol}
    still = tids & {a.tid for a in pl.assignments}
    return len(viol) > 0 and not still, \
        "越界 %d 条（作业 %s），仍在下发清单的：%s" % (len(viol), sorted(tids),
                                            sorted(still) or "无")


def c_plan_level_ok():
    """正例：续航够两条叠加，第 6 步不该乱拦。"""
    snap = build(n_plat=2, n_task=2, p_over=dict(battery=200.0),
                 t_over_list=[dict(pos=(10.0, 0.0), crew=2),
                              dict(pos=(10.0, 0.0), crew=2)])
    pl, ev = planner.plan(snap, 0, H=60)
    viol = [e for e in ev if e.get("kind") == "violation"]
    return len(pl.assignments) == 2 and not viol, \
        "指派 %d 条 / 越界 %d 条" % (len(pl.assignments), len(viol))


# ---------------------------------------------------------------- 4 匈牙利

def c_hungarian_known():
    """手算小例：最优 5（r0c1=1, r1c0=2, r2c2=2），贪心 6。"""
    C = [[4, 1, 3],
         [2, 0, 5],
         [3, 2, 2]]
    pairs, solver = planner.hungarian(C, prefer_scipy=False)
    total = sum(C[i][j] for i, j in pairs)
    return len(pairs) == 3 and abs(total - 5.0) < 1e-9, \
        "求解器 %s，匹配 %s，总代价 %s（应为 5）" % (solver, sorted(pairs), total)


def c_hungarian_le_greedy():
    """不变量：最优总代价 ≤ 贪心总代价（同一可行域）。随机 50 组对照。"""
    import random
    rng = random.Random(7)
    bad = 0
    for _ in range(50):
        n = rng.randint(1, 6)
        m = rng.randint(1, 6)
        C = [[round(rng.uniform(0, 20), 2) for _ in range(m)] for _ in range(n)]
        pairs, _ = planner.hungarian(C, prefer_scipy=False)
        opt = sum(C[i][j] for i, j in pairs)
        # 贪心：按代价升序取，行列用过就跳过
        cells = sorted(((C[i][j], i, j) for i in range(n) for j in range(m)),
                       key=lambda x: (x[0], x[1], x[2]))
        ur, uc, g = set(), set(), 0.0
        for c, i, j in cells:
            if i in ur or j in uc:
                continue
            ur.add(i)
            uc.add(j)
            g += c
        if opt > g + 1e-9:
            bad += 1
    return bad == 0, "50 组随机矩阵中，最优 > 贪心 的有 %d 组" % bad


def c_hungarian_rect():
    """矩形矩阵：4 行 × 2 列，应配出 2 对，且行列不重复。"""
    C = [[3, 5], [1, 9], [8, 2], [4, 4]]
    pairs, solver = planner.hungarian(C, prefer_scipy=False)
    rows = [i for i, _ in pairs]
    cols = [j for _, j in pairs]
    return (len(pairs) == 2 and len(set(rows)) == 2 and len(set(cols)) == 2), \
        "求解器 %s，匹配 %s" % (solver, sorted(pairs))


def c_hungarian_vs_scipy():
    """与 scipy 互校（没装 scipy 就 SKIP，不算通过）。"""
    try:
        import numpy as np                       # noqa: F401
        from scipy.optimize import linear_sum_assignment  # noqa: F401
    except Exception:
        return None
    import random
    rng = random.Random(11)
    bad = 0
    for _ in range(30):
        n = rng.randint(1, 6)
        m = rng.randint(1, 6)
        C = [[round(rng.uniform(0, 20), 2) for _ in range(m)] for _ in range(n)]
        a, _ = planner.hungarian(C, prefer_scipy=False)
        b, _ = planner.hungarian(C, prefer_scipy=True)
        ta = sum(C[i][j] for i, j in a)
        tb = sum(C[i][j] for i, j in b)
        if abs(ta - tb) > 1e-6:
            bad += 1
    return bad == 0, "30 组随机矩阵中，内置与 scipy 总代价不一致的有 %d 组" % bad


def c_crew1_one_to_one():
    """crew=1 走一对一：同一台平台不会被派给两个 crew=1 的作业。"""
    snap = build(n_plat=2, n_task=2,
                 t_over_list=[dict(pos=(10.0, 0.0), crew=1),
                              dict(pos=(10.0, 0.0), crew=1)])
    pl, ev = planner.plan(snap, 0, H=60)
    used = [pid for a in pl.assignments for pid in a.pids]
    solve = [e for e in ev if e.get("kind") == "assign_solve"]
    return len(used) == len(set(used)) and len(solve) == 1, \
        "占用 %s，assign_solve %d 条" % (used, len(solve))


# ---------------------------------------------------------------- 5 触发源

def c_trigger_sources():
    """四类触发源各自独立计数（run_flow 层）。成员损失必须落进 member_change。"""
    import io
    import contextlib
    from run_flow import run
    with contextlib.redirect_stdout(io.StringIO()):
        _t, _e, st = run(seed=0, T=30, kill_at=10, verbose=False, out_path=None)
    tg = st.get("triggers") or {}
    return tg.get("member_change", 0) >= 1 and tg.get("periodic", 0) >= 1, \
        "触发源计数 %s" % tg


def main():
    case("01 crew 不足：结构性不足需上报", c_crew_structural)
    case("02 crew 不足：可行平台数 < crew", c_crew_partial)
    case("03 crew 不足：零可行平台不再静默", c_crew_no_candidate)
    case("04 crew 正例：人数够应放行", c_crew_ok)
    case("05 时间窗：超出应放弃并留痕", c_window)
    case("06 时间窗：正例应放行", c_window_within)
    case("07 时间窗：无解时 defer 且 need_report", c_window_defer_reports)
    case("08 方案级越界：单条合法叠加越界", c_plan_level_violation)
    case("09 方案级越界：正例不应误拦", c_plan_level_ok)
    case("10 匈牙利：手算小例最优=5", c_hungarian_known)
    case("11 匈牙利：最优 ≤ 贪心（50 组随机）", c_hungarian_le_greedy)
    case("12 匈牙利：矩形矩阵行/列不重复", c_hungarian_rect)
    r = c_hungarian_vs_scipy()
    if r is None:
        case("13 匈牙利：与 scipy 互校", lambda: (True, ""),
             skip="未装 scipy/numpy → 未覆盖（不算通过）")
    else:
        case("13 匈牙利：与 scipy 互校", lambda: r)
    case("14 crew=1 一对一：平台不重复占用", c_crew1_one_to_one)
    case("15 重规划触发源：四类独立计数", c_trigger_sources)

    print("\n规划器单元测试（WP1）")
    print("=" * 72)
    for name, st, note in RESULTS:
        print("%-38s %-6s %s" % (name, st, note))
    print("=" * 72)
    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    n_skip = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print("通过 %d，失败 %d，跳过 %d（SKIP 不算通过）" % (n_pass, n_fail, n_skip))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
