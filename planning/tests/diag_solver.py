# -*- coding: utf-8 -*-
"""
diag_solver.py —— 分配求解器诊断：最优（匈牙利）到底比贪心好多少

为什么需要这个脚本：
`run_flow.py` 末尾那行"最优合计 vs 贪心合计"在**默认场景（15 平台 8 作业）下恒为 0**，
因为平台远多于 crew=1 的作业，贪心随便挑都不会撞车。
只看默认场景会得出"换求解器没用"的结论，而那是**场景太宽松**造成的，
不是求解器的问题。

这个脚本按"资源紧张度"扫一遍，看差距什么时候才出现——
这个数字直接决定要不要上 OR-Tools CP-SAT 做带约束排程。

跑法（纯标准库）：
    python tests/diag_solver.py
    python tests/diag_solver.py --seeds 8
"""

import argparse
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from run_flow import run        # noqa: E402


def quiet(**kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return run(T=60, verbose=False, out_path=None, **kw)[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    a = ap.parse_args()
    seeds = list(range(a.seeds))

    configs = [(15, 8), (8, 8), (6, 8), (4, 8), (3, 8), (2, 6)]
    print("=" * 84)
    print("分配求解器诊断：crew=1 作业的最优（匈牙利）vs 贪心")
    print("  %d 个 seed × 60 步；只统计真做了最优指派的那些轮次" % len(seeds))
    print("=" * 84)
    print("%-6s %-6s %-8s %-11s %-11s %-9s %-8s"
          % ("平台", "作业", "求解轮数", "最优合计", "贪心合计", "差距", "完成数"))
    print("-" * 84)
    for nplat, ntask in configs:
        opt = grd = 0.0
        rounds = 0
        done = 0
        for s in seeds:
            st = quiet(seed=s, n_platforms=nplat, n_tasks=ntask)
            for e in st.get("solves", []):
                opt += e["optimal"]
                grd += e["greedy"]
                rounds += 1
            done += st["done"]
        gap = grd - opt
        pct = ("%.1f%%" % (100.0 * gap / opt)) if opt > 0 else "—"
        print("%-6d %-6d %-8d %-11.1f %-11.1f %-9s %-8d"
              % (nplat, ntask, rounds, opt, grd,
                 ("%+.1f %s" % (gap, pct)) if rounds else "—", done))
    print("-" * 84)
    print("读法：")
    print("1. 差距是**同一可行域**（一对一）下比的，不是拿不同可行域硬凑。")
    print("2. 平台越紧张，贪心越容易捡了芝麻丢了西瓜，差距才显现。")
    print("3. 差距为 0 不代表求解器错了，只说明这个场景下贪心已经是最优。")
    print("4. 完成数是 makespan 目标下的 8 seed 合计，用来看代价，不是验收指标。")


if __name__ == "__main__":
    main()
