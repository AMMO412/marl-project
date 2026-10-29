# -*- coding: utf-8 -*-
"""「短视」缺陷的实证用例（不是回归测试，是记录已知缺陷）。

场景：一台平台、两个活。
  A 近（2 步）但不急（窗口 60），代价 14
  B 远（5 步）但很急（窗口 20），代价 15

贪心按代价排序 → 先派 A → B 被挤到 A 之后开工 → 完工 24 > 窗口 20 → 失败。
而正确做法是先干 B（完工 15 ✓）再干 A（完工 27 ✓），**两个都能成**。

这就是"只看眼前"的代价：近的那个不一定该先干。
也是 WP1「代价函数加强」要做的事——代价里要看得见"后面还有什么、有多急"。

用法：
    python tests/test_myopia.py

退出码 0 = 缺陷如实复现（说明它还没被修好）；
如果哪天这个用例不再复现，说明规划器已经不再短视，应当把本文件改成
正常回归测试并更新文档。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner                                            # noqa: E402
from contract import GroupSnapshot, Platform, Task        # noqa: E402


def build():
    p = Platform(pid="P1", ptype="ugv", pos=(0.0, 0.0), battery=200.0,
                 payload=6.0, speed=1.0, work_rate=1.0, sensor="eo", alive=True)
    A = Task(tid="A", ttype="patrol", pos=(2.0, 0.0), work=12.0,
             window=(0, 60), crew=1, need_payload=0.0, need_sensor=None,
             status="pending", progress=0.0)
    B = Task(tid="B", ttype="patrol", pos=(5.0, 0.0), work=10.0,
             window=(0, 20), crew=1, need_payload=0.0, need_sensor=None,
             status="pending", progress=0.0)
    return GroupSnapshot(version="myopia", step=0, objective="makespan",
                         platforms=[p], tasks=[A, B])


def main():
    snap = build()
    p, A, B = snap.platforms[0], snap.tasks[0], snap.tasks[1]

    print("代价：A=%.1f（近）  B=%.1f（远但急，窗口 %d）"
          % (planner._cost(p, A, "makespan"),
             planner._cost(p, B, "makespan"), B.window[1]))
    print()

    plan, events = planner.plan(snap, now=0, H=60, plan_id=0)
    got = {a.tid: (a.start, a.end) for a in plan.assignments}

    print("规划器实际排出来的：")
    for a in plan.assignments:
        print("   %s 开工 %d 完工 %d" % (a.tid, a.start, a.end))
    deferred = [e for e in events if e.get("by") == "defer"]
    for e in deferred:
        print("   %s 未排：%s" % (e.get("tid"), e.get("note")))

    print()
    print("正确做法（先 B 后 A）：B 5→15 ✓（窗口 20）、A 15→27 ✓（窗口 60）")

    # ---- 判定 ----
    ok_b_first = "B" in got and got["B"][1] <= B.window[1]
    print()
    if "B" not in got:
        print("缺陷复现：B 被挤掉了。规划器先派了代价小的 A，把急的 B 堵死。")
        print("→ 这就是短视（myopic）。待 WP1 修：代价函数要计入紧迫度与后续影响。")
        return 0
    if ok_b_first:
        print("B 已排进且在窗口内 —— 规划器不再短视，请把本用例改写成回归测试。")
        return 1
    print("B 排进去了但超窗 —— 仍是短视的后果。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
