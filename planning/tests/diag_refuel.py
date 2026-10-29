# -*- coding: utf-8 -*-
"""诊断：给差一点点的平台"先补给再出发"，到底划不划算。

补给不是免费的，它有三笔代价：
  1. 绕路去补给点的路程
  2. 补给本身耗时
  3. 因此推迟的开工时间（可能把作业挤出时间窗）

所以必须算，不能凭直觉说"补上所差再去干"。

用法：
    python tests/diag_refuel.py --seed 0 --refuel-steps 5
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner                                   # noqa: E402
from contract import (PLATFORM_SPECS, dist, sample_scenario)   # noqa: E402

# 我方暂定：补给点位置与补给耗时。真实值要甲方/想定给。
REFUEL_POINT = (50.0, 50.0)


def direct(p, t):
    """直达：到达 + 工期，以及需要的续航。"""
    arrive = planner._travel_time(p, t)
    work_t = int(math.ceil(planner._remain(t) / max(p.work_rate, 1e-6)))
    return arrive, work_t, arrive + work_t


def via_refuel(p, t, refuel_steps, now=0):
    """先去补给点补满，再去干。

    返回 (能否成行, 总完工, 明细)。补满后续航 = 该类型的满值。
    """
    full_bat = PLATFORM_SPECS[p.ptype]["battery"]
    full_pay = PLATFORM_SPECS[p.ptype]["payload"]

    d1 = dist(p.pos, REFUEL_POINT) / max(p.speed, 1e-6)
    if p.battery < d1:
        return False, None, "连补给点都到不了(需%.0f,剩%.0f)" % (d1, p.battery)

    d2 = dist(REFUEL_POINT, t.pos) / max(p.speed, 1e-6)
    work_t = planner._remain(t) / max(p.work_rate, 1e-6)
    need_after = d2 + work_t
    if need_after > full_bat:
        return False, None, "补满仍不够(需%.0f,满%.0f)" % (need_after, full_bat)
    if full_pay < t.need_payload:
        return False, None, "载荷是固有能力，补给补不出来(需%.1f,满%.1f)" % (
            t.need_payload, full_pay)

    total = d1 + refuel_steps + d2 + work_t
    detail = "绕路%.0f+补%d+再走%.0f+干%.0f" % (d1, refuel_steps, d2, work_t)
    return True, now + total, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--refuel-steps", type=int, default=5,
                    help="补给耗时（我方暂定）")
    a = ap.parse_args()

    snap = sample_scenario(seed=a.seed, n_platforms=15, n_tasks=8)
    print("补给点 %s，补给耗时 %d 步（均为我方暂定）"
          % (REFUEL_POINT, a.refuel_steps))
    print()

    for t in snap.tasks:
        if t.status in ("done", "failed"):
            continue

        # 直达：谁可行、谁不可行
        ok_list, bad_list = [], []
        for p in snap.platforms:
            if not p.alive:
                continue
            ok, why = planner.feasible(p, t)
            arrive, work_t, end = direct(p, t)
            (ok_list if ok else bad_list).append((p, why, end))

        if ok_list:
            best = min(ok_list, key=lambda x: x[2])
            print("%s：直达可行（最优 %s 完工 %d，窗口 %d）→ 不需要补给"
                  % (t.tid, best[0].pid, best[2], t.window[1]))
            continue

        print("=" * 70)
        print("%s：直达无人可派。窗口 [%d, %d]，需 %d 人，需载荷 %.1f"
              % (t.tid, t.window[0], t.window[1], t.crew, t.need_payload))
        reasons = {}
        for p, why, _e in bad_list:
            reasons[why.split("(")[0]] = reasons.get(why.split("(")[0], 0) + 1
        print("  卡住的原因：%s" % reasons)

        # 经补给：找最优平台
        cands = []
        for p in snap.platforms:
            if not p.alive:
                continue
            ok, end, detail = via_refuel(p, t, a.refuel_steps)
            if ok:
                cands.append((end, p, detail))
        if not cands:
            print("  经补给也无人可派：")
            for p in snap.platforms[:4]:
                ok, _e, detail = via_refuel(p, t, a.refuel_steps)
                print("    %s：%s" % (p.pid, detail))
            continue

        cands.sort(key=lambda x: x[0])
        end, p, detail = cands[0]
        verdict = "赶得上" if end <= t.window[1] else "仍超窗"
        print("  经补给最优：%s，%s → 完工 %.0f（窗口 %d）%s"
              % (p.pid, detail, end, t.window[1], verdict))
        # 顺带报告：补给换来的是"能派出去"，代价是晚多少
        if len(cands) > 1:
            print("    其他候选：%s" % ", ".join("%s(完工%.0f)" % (c[1].pid, c[0])
                                                 for c in cands[1:4]))


if __name__ == "__main__":
    main()
