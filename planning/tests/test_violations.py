# -*- coding: utf-8 -*-
"""
越界用例集 —— 验证 2.3（5）「不生成超出平台能力边界的子任务方案」

跑法（纯标准库，Windows 侧也能跑）：
    python tests/test_violations.py

每个用例都是最小场景：改一个参数，看规划器拦不拦得住。

输出明确区分三种状态，不要把没做的当成通过：
    PASS  校验项已启用，且确实拦住了  → 可计入覆盖
    FAIL  应该拦住却没拦住            → 这是真 bug，必须修
    SKIP  校验项尚未启用              → 未覆盖，不能算通过
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner
from contract import GroupSnapshot, Platform, Task

BASE_P = dict(pid="P00", ptype="ugv", pos=(0.0, 0.0), battery=100.0,
              payload=6.0, speed=1.0, work_rate=1.0, sensor="eo", alive=True)
BASE_T = dict(tid="T00", ttype="patrol", pos=(10.0, 0.0), work=10.0,
              window=(0, 60), crew=1, need_payload=0.0, need_sensor=None)


def build(n_plat=1, n_task=1, p_over=None, t_over=None, t_over_list=None):
    """搭一个最小场景。t_over_list 用来给多个作业各自不同的覆盖。"""
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
    return GroupSnapshot(version=1, step=0, objective="makespan",
                         platforms=plats, tasks=tasks)


RESULTS = []


def case(name, check_name, fn):
    """跑一个用例。check_name 为 None 表示这条不依赖开关（常量逻辑）。"""
    enabled = (check_name is None) or (check_name in planner.ENABLED_CHECKS)
    if not enabled:
        RESULTS.append((name, "SKIP", "校验项 %s 尚未启用 → 未覆盖" % check_name))
        return
    try:
        ok, note = fn()
        RESULTS.append((name, "PASS" if ok else "FAIL", note))
    except Exception as e:
        RESULTS.append((name, "FAIL", "用例本身报错：%r" % e))


# ------------------------------------------------------------------ 用例

def c_feasible_ok():
    snap = build()                       # 续航 100，作业需 20
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 1, "正例：可行组合应放行，实得 %d 条" % len(pl.assignments)


def c_battery():
    snap = build(p_over=dict(battery=5.0))     # 需要 20，只剩 5
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "续航不足应无指派，实得 %d 条" % len(pl.assignments)


def c_payload():
    snap = build(p_over=dict(payload=0.5), t_over=dict(need_payload=3.0))
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "载荷不足应无指派，实得 %d 条" % len(pl.assignments)


def c_dead():
    snap = build(p_over=dict(alive=False))
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "平台失联应无指派，实得 %d 条" % len(pl.assignments)


def c_sensor():
    snap = build(t_over=dict(need_sensor="sar"))    # 平台只有 eo
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "传感器不匹配应无指派，实得 %d 条" % len(pl.assignments)


def c_motion():
    # 作业很远，一个时间窗内赶不到
    snap = build(p_over=dict(speed=0.01), t_over=dict(pos=(90.0, 90.0), window=(0, 5)))
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "运动性能不足应无指派，实得 %d 条" % len(pl.assignments)


def c_combined():
    """组合型越界：单条都合法，叠加起来超续航。这是第 6 步存在的理由。

    必须用 crew=2：crew=1 的作业在 WP1 之后走**一对一最优指派**，
    一台平台只会接一个 crew=1 的作业，根本构不成"叠加"。
    用两个 crew=2 的作业让同一批平台被两条指派占用，才是第 6 步要抓的情形。
    """
    # 2 台平台、2 个 crew=2 的作业：两条指派都会用到 P00/P01
    # 单条 need=20 ≤ 25 合法，两条叠加 30 > 25 越界
    snap = build(n_plat=2, n_task=2, p_over=dict(battery=25.0),
                 t_over_list=[dict(pos=(10.0, 0.0), crew=2),
                              dict(pos=(10.0, 0.0), crew=2)])
    pl, ev = planner.plan(snap, 0, H=60)
    viol = [e for e in ev if e.get("kind") == "violation"]
    return len(viol) > 0, "方案级校验应报越界，实得 %d 条（指派 %d 条）" % (
        len(viol), len(pl.assignments))


def c_crew_short():
    snap = build(n_plat=1, t_over=dict(crew=3))
    pl, ev = planner.plan(snap, 0, H=60)
    conf = [e for e in ev if e.get("type") == "crew_short"]
    return len(pl.assignments) == 0 and len(conf) > 0, \
        "协同人数不足应放弃并留痕，指派 %d 条 / 冲突 %d 条" % (len(pl.assignments), len(conf))


def c_window():
    # 续航必须给足，否则会在过滤阶段就被拦下、根本进不了排程，
    # 测出来的就不是时间窗而是续航了。让时间窗成为唯一的卡点。
    snap = build(p_over=dict(battery=1000.0), t_over=dict(window=(0, 5)))
    pl, ev = planner.plan(snap, 0, H=60)
    win = [e for e in ev if e.get("type") == "window"]
    return len(pl.assignments) == 0 and len(win) > 0, \
        "超出时间窗应放弃并留痕，指派 %d 条 / 冲突 %d 条" % (len(pl.assignments), len(win))


def c_done_task():
    snap = build(t_over=dict(status="done"))
    pl, ev = planner.plan(snap, 0, H=60)
    return len(pl.assignments) == 0, "已完成的作业不应再指派，实得 %d 条" % len(pl.assignments)


def main():
    case("01 正例：可行组合应放行", None, c_feasible_ok)
    case("02 续航不足应拦住", "battery", c_battery)
    case("03 载荷不足应拦住", "payload", c_payload)
    case("04 平台失联应拦住", None, c_dead)
    case("05 传感器不匹配应拦住", "sensor", c_sensor)
    case("06 运动性能不足应拦住", "motion", c_motion)
    case("07 组合型：单条合法叠加超续航", "battery", c_combined)
    case("08 协同人数不足应放弃", None, c_crew_short)
    case("09 超出时间窗应放弃", None, c_window)
    case("10 已完成作业不再指派", None, c_done_task)

    print("\n越界用例集（2.3（5）能力边界校验）")
    print("=" * 68)
    for name, st, note in RESULTS:
        print("%-32s %-6s %s" % (name, st, note))
    print("=" * 68)

    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    n_skip = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    n_enabled = n_pass + n_fail
    print("已启用 %d 条：通过 %d，失败 %d" % (n_enabled, n_pass, n_fail))
    print("未启用（未覆盖）%d 条：%s" % (
        n_skip, [n for n, s, _ in RESULTS if s == "SKIP"]))
    if n_enabled:
        print("已启用项的通过率：%.0f%%" % (100.0 * n_pass / n_enabled))
    print("\n未启用的校验项：%s" % sorted(planner.ALL_CHECKS - planner.ENABLED_CHECKS))
    print("注意：SKIP 不是通过。未覆盖就是未覆盖，不能计入达标。")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
