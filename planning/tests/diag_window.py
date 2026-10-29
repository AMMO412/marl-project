# -*- coding: utf-8 -*-
"""诊断：排不进时间窗的作业，到底卡在哪。

用法：
    python tests/diag_window.py --seed 0

会打印每个作业的：时间窗、工作量、被派了谁、各人的到达步数与效率、
算出来的完工步数、以及"能不能靠加人救回来"。
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner                     # noqa: E402
from contract import dist, sample_scenario   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--now", type=int, default=0,
                    help="在第几步做这次诊断规划（默认 0，即开局）")
    a = ap.parse_args()

    snap = sample_scenario(seed=a.seed, n_platforms=15, n_tasks=8)
    pmap = {p.pid: p for p in snap.platforms}
    now = a.now

    print("场景：15 平台 / %d 作业 / 目标=%s / 诊断时刻 t=%d"
          % (len(snap.tasks), snap.objective, now))
    print()

    # 先跑一次规划，拿到真实的指派结果
    plan, events = planner.plan(snap, now=now, H=20, plan_id=0)

    assigned = {x.tid: x for x in plan.assignments}
    rejected_by_tid = {}
    for r in plan.rejected:
        rejected_by_tid.setdefault(r["tid"], []).append(r["reason"])

    for t in snap.tasks:
        if t.status in ("done", "failed"):
            continue
        print("=" * 66)
        print("%s  工作量 %.0f(剩 %.0f)  时间窗 [%d, %d]  需 %d 人  需载荷 %.1f"
              % (t.tid, t.work, planner._remain(t),
                 t.window[0], t.window[1], t.crew, t.need_payload))

        if t.tid in assigned:
            asm = assigned[t.tid]
            arrive = max(planner._travel_time(pmap[p], t) for p in asm.pids)
            rate = sum(pmap[p].work_rate for p in asm.pids)
            dur = int(math.ceil(planner._remain(t) / max(rate, 1e-6)))
            print("  ✓ 派出去：%s" % ",".join(asm.pids))
            print("    排程 [开工 %d, 完工 %d]，窗口上限 %d → %s"
                  % (asm.start, asm.end, t.window[1],
                     "赶上" if asm.end <= t.window[1] else "超时窗"))
        else:
            # 注意：rejected 里既有"不可行组合"，也有"排程后被拒"。
            # 只打印第一条会严重误导（曾因此误判成"续航不足"），
            # 真正的卡点要看全部原因，尤其是"超出规划视野"。
            why = rejected_by_tid.get(t.tid, [])
            scope = [w for w in why if "规划视野" in w]
            cap = [w for w in why if "续航" in w or "载荷" in w]
            print("  ✗ 没派出去。全部原因：")
            for w in sorted(set(why)):
                print("      - %s" % w)
            if scope:
                print("    ↑ 真正卡点：开工时间超出规划视野 H=%d，本轮不排。"
                      % 20)
                print("      这不是能力不足，是视野太窄。试试 --H 45。")

        # 所有可行平台按"到达步数"排序，看最快的谁
        cands = []
        for p in snap.platforms:
            ok, _ = planner.feasible(p, t)
            if ok:
                cands.append(p)
        if not cands:
            print("    没有任何平台可行（能力闸门全挡）")
            continue
        cands.sort(key=lambda p: planner._travel_time(p, t))
        best = cands[:max(t.crew, 3)]
        arrive_max = max(planner._travel_time(p, t) for p in best)
        rate = sum(p.work_rate for p in best)
        dur = int(math.ceil(planner._remain(t) / max(rate, 1e-6)))
        end = now + arrive_max + dur
        print("    最近的 %d 台：%s" % (
            len(best), ", ".join(
                "%s(到达%d,效率%.1f)" % (p.pid, planner._travel_time(p, t), p.work_rate)
                for p in best)))
        print("    用最近的这批：完工 %d，窗口上限 %d → %s"
              % (end, t.window[1], "能赶上" if end <= t.window[1] else "仍然赶不上"))
        if end > t.window[1]:
            gap = end - t.window[1]
            print("    → 差 %d 步。加人只能缩短工期，缩短不了到达时间；"
                  % gap)
            print("      若最近的平台到达就要 %d 步，那么加多少人也没用，只能换更近的。"
                  % arrive_max)

    print()
    print("=" * 66)
    print("本次规划事件里的 window 冲突：")
    for e in events:
        if e.get("type") == "window":
            print("  %s" % e)


if __name__ == "__main__":
    main()
