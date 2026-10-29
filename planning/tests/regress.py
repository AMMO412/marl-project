# -*- coding: utf-8 -*-
"""统一回归入口。

不是只测"能不能跑"，而是检查**不变量**——今天改了这么多处，
必须有一个命令能一次验证全部关键性质：

  1. 串行不变量：同一份计划里，同一台平台的作业区间**不重叠**
     （曾因加人/换人撤销错峰而被破坏，产出"一台平台同时干两个活"）
  2. 拦截不变量：被判"方案级越界"的作业**必须已撤下**，不能出现在下发清单里
     （第 6 步曾只记录不拦截，照样下发会半路没电的方案）
  3. 能力不变量：每条指派的 (平台, 作业) 都通过能力闸门
  4. crew 不变量：每条指派的人数 ≥ 作业要求的协同人数

外加：单元测试、场景冒烟、脚本冒烟。

用法：
    python tests/regress.py            # 全部
    python tests/regress.py --quick    # 跳过较慢的学习脚本
"""

import argparse
import contextlib
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PY = sys.executable

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  %-52s %s" % (name, "PASS" if ok else "FAIL")
          + ("   " + detail if detail else ""))
    return ok


def run_py(args, timeout=600):
    """跑一个脚本，返回 (退出码, 输出)。"""
    try:
        p = subprocess.run([PY] + args, cwd=ROOT, timeout=timeout,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **kw), buf.getvalue()


def invariants(seeds, steps=60):
    """核心：滚若干轮，逐份计划检查不变量。

    除了默认场景，还要跑**资源紧张**场景（平台少、作业多）：
    串行化 bug（加人换人撤销错峰）只在触发"加人/换人消解"时才出现，
    默认 15 平台太宽松几乎不触发——只查默认场景的回归是**假的**。
    """
    from contract import sample_scenario
    from run_flow import run
    import planner

    overlap_bad, intercept_bad, cap_bad, crew_bad = [], [], [], []
    solve_bad = []
    plans = 0

    configs = [(15, 8, s) for s in seeds]
    configs += [(3, 8, s) for s in (0, 1)]      # 资源紧张：易触发冲突消解
    configs += [(2, 6, s) for s in (0, 1)]      # 更紧张

    for nplat, ntask, s in configs:
        (traces, events, stats), _out = quiet(
            run, seed=s, n_platforms=nplat, n_tasks=ntask, T=steps,
            verbose=False, out_path=None)
        # 5 求解器不变量：最优总代价必须 ≤ 贪心总代价（同一可行域）
        # 这条能抓住"匈牙利实现写错"这类静默错误——写错了照样能跑，只是不是最优。
        for e in events:
            if e.get("kind") == "assign_solve" and e["optimal"] > e["greedy"] + 1e-9:
                solve_bad.append("seed%d 最优 %.2f > 贪心 %.2f"
                                 % (s, e["optimal"], e["greedy"]))

        for tr in traces:
            plans += 1
            asms = tr.get("assignments", [])

            # 1 串行：同一 pid 不重叠
            by_pid = {}
            for a in asms:
                for pid in a["pids"]:
                    by_pid.setdefault(pid, []).append((a["start"], a["end"], a["tid"]))
            for pid, iv in by_pid.items():
                iv.sort()
                for i in range(1, len(iv)):
                    if iv[i][0] < iv[i - 1][1]:
                        overlap_bad.append("seed%d %s: %s 与 %s"
                                           % (s, pid, iv[i - 1], iv[i]))

            # 2 拦截：判了越界的必须已撤下
            viol_tids = {e.get("tid") for e in tr.get("evidence", [])
                         if e.get("kind") == "violation" and e.get("tid")}
            present = {a["tid"] for a in asms}
            for tid in viol_tids:
                if tid in present:
                    intercept_bad.append("seed%d %s 判越界却仍在下发清单" % (s, tid))

            # 3/4 能力与 crew（用初始快照的作业定义核对）
            snap = sample_scenario(seed=s, n_platforms=nplat, n_tasks=ntask)
            tmap = {t.tid: t for t in snap.tasks}
            pmap = {p.pid: p for p in snap.platforms}
            for a in asms:
                t = tmap.get(a["tid"])
                if t is None:
                    continue
                if len(a["pids"]) < t.crew:
                    crew_bad.append("seed%d %s 人数 %d < 需 %d"
                                    % (s, a["tid"], len(a["pids"]), t.crew))
                for pid in a["pids"]:
                    p = pmap.get(pid)
                    if p is None:
                        continue
                    ok, why = planner.feasible(p, t)
                    if not ok:
                        cap_bad.append("seed%d (%s,%s) %s" % (s, pid, a["tid"], why))

    # 5 构造场景：串行化 bug 的**确定触发点**。
    # 随机场景（哪怕 2 平台 6 作业）实测触发不到加人消解，
    # 只查随机场景的回归是假的——必须有一个必现的场景兜底。
    sys.path.insert(0, HERE)
    import test_myopia
    pl, _ev = planner.plan(test_myopia.build(), now=0, H=60, plan_id=0)
    by_pid = {}
    for a in pl.assignments:
        for pid in a.pids:
            by_pid.setdefault(pid, []).append((a.start, a.end, a.tid))
    overlap_bad += ["%s: %s 与 %s" % (pid, iv[i - 1], iv[i])
                    for pid, iv in by_pid.items()
                    for i in range(1, len(sorted(iv)))
                    if sorted(iv)[i][0] < sorted(iv)[i - 1][1]]

    print("\n[不变量] 共检查 %d 份计划（含构造触发场景）" % plans)
    check("1 串行不变量：同一平台作业区间不重叠",
          not overlap_bad, overlap_bad[0] if overlap_bad else "")
    check("2 拦截不变量：判越界的作业不在下发清单",
          not intercept_bad, intercept_bad[0] if intercept_bad else "")
    check("3 能力不变量：指派组合均通过能力闸门",
          not cap_bad, cap_bad[0] if cap_bad else "")
    check("4 crew 不变量：人数 ≥ 协同要求",
          not crew_bad, crew_bad[0] if crew_bad else "")
    check("5 求解器不变量：最优总代价 ≤ 贪心总代价",
          not solve_bad, solve_bad[0] if solve_bad else "")


def unit_tests():
    print("\n[单元测试]")
    rc, out = run_py(["tests/test_violations.py"])
    ok = (rc == 0) and ("失败 0" in out)
    check("越界用例集 8/8 通过", ok, out.strip().splitlines()[-1] if out else "")

    rc, out = run_py(["tests/test_planner_units.py"])
    ok = (rc == 0) and ("失败 0" in out)
    line = [l for l in out.splitlines() if l.startswith("通过 ")]
    check("规划器单元测试无失败", ok, line[0] if line else "")

    rc, out = run_py(["tests/test_myopia.py"])
    # 退出码 0 表示"短视缺陷如实复现"——这是记录已知缺陷，不是回归失败
    check("短视缺陷用例可复现（退出码 0）", rc == 0,
          "缺陷仍在，属已知待修项" if rc == 0 else "用例未复现或异常")


def scenarios():
    print("\n[场景冒烟]")
    from run_flow import run

    def done_of(stats):
        return stats["done"]

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None)
    base = done_of(st)
    check("默认场景能跑且完成 > 0", base > 0, "完成 %d" % base)

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None,
                            keep_commitment=False)
    check("--no-keep 复现已知故障（完成 0）", st["done"] == 0,
          "完成 %d" % st["done"])

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None, H=45)
    check("--H 45 完成数 ≥ 默认", st["done"] >= base,
          "H45 完成 %d vs 默认 %d" % (st["done"], base))

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None,
                            delay_prob=0.3, fail_prob=0.05)
    check("噪声注入场景能跑", True, "完成 %d" % st["done"])

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None,
                            kill_at=15)
    killed = any("成员" in k for k in st["replan_reasons"])
    check("--kill-at 15 触发成员损失重规划", killed, str(st["replan_reasons"]))

    (_t, _e, st), _ = quiet(run, seed=0, T=60, verbose=False, out_path=None,
                            scenario_path="spec/sample_scenario.json")
    check("场景文件加载能跑", True, "完成 %d" % st["done"])


def scripts(quick):
    print("\n[脚本冒烟]")
    for name, args, to in [
        ("diag_window 诊断", ["tests/diag_window.py", "--seed", "0", "--now", "40"], 120),
        ("diag_refuel 补给验算", ["tests/diag_refuel.py", "--seed", "0"], 120),
        ("analyze 三目标汇总", ["analyze.py", "--seeds", "2"], 300),
    ]:
        rc, out = run_py(args, timeout=to)
        check(name, rc == 0, (out.strip().splitlines()[-1] if out.strip() else "")[:60])

    if not quick:
        rc, out = run_py(["rl/learn_weights.py", "--gens", "2", "--samples", "4",
                          "--seeds", "0"], timeout=300)
        check("rl/learn_weights 能跑完", rc == 0,
              (out.strip().splitlines()[-1] if out.strip() else "")[:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过较慢的学习脚本")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3])
    a = ap.parse_args()

    print("=" * 78)
    print("统一回归：不变量 + 单元测试 + 场景冒烟 + 脚本冒烟")
    print("=" * 78)

    invariants(a.seeds)
    unit_tests()
    scenarios()
    scripts(a.quick)

    print("\n" + "=" * 78)
    bad = [r for r in results if not r[1]]
    print("合计 %d 项，通过 %d，失败 %d" % (len(results), len(results) - len(bad), len(bad)))
    if bad:
        print("\n失败项：")
        for name, _ok, detail in bad:
            print("  - %s  %s" % (name, detail))
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
