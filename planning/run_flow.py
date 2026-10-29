# -*- coding: utf-8 -*-
"""
run_flow.py —— 把整条链路串起来跑一遍

编组快照 → 规则规划 → 下发 H 步计划 → 替身执行 → 反馈
        → 偏差判定 → 触发重规划 → 回到规划

一次运行会打印：每一步发生了什么、每次规划的依据、最后的统计。
所有留痕写进 flow_trace.jsonl，可以事后复算。

用法见 README.md。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planner
from contract import load_scenario, sample_scenario
from executor import StubExecutor
from metrics import ConflictTracker, format_report

# ------------------------------------------------------------------
# 重规划触发源（WP1：显式化）
#
# 原来的写法是给一个字符串 reason，同一步里多个触发源只会留下最后一个，
# 于是"成员损失 + 执行失败 + 超时"同时发生时，统计里只能看到一个。
# 现在每类触发源独立成条，各自计数、各自留痕，可事后按类查。
# ------------------------------------------------------------------
TRIGGER_LABELS = {
    "init":          "首次规划",
    "member_change": "成员变化",
    "exec_fail":     "执行失败",
    "timeout":       "超时",
    "deviation":     "偏差超阈值",
    "periodic":      "滚动周期",
}


def deviation(plan, snapshot, now):
    """偏差判定：计划该干到哪 vs 实际干到哪。

    返回 (滞后量, 作业号, 类型)。滞后量是工作量单位，不是步数。
    """
    tmap = {t.tid: t for t in snapshot.tasks}
    worst, which, kind = 0.0, None, ""
    for a in plan.assignments:
        t = tmap.get(a.tid)
        if t is None or t.status in ("done", "failed"):
            continue
        if now >= a.end:
            return t.work - t.progress, a.tid, "timeout"
        if a.start <= now < a.end:
            span = max(1, a.end - a.start)
            expect = t.work * (now - a.start + 1) / span
            lag = expect - t.progress
            if lag > worst:
                worst, which, kind = lag, a.tid, "lag"
    return worst, which, kind


def run(seed=0, n_platforms=15, n_tasks=8, objective="makespan",
        H=20, K=5, T=60, dev_threshold=4.0,
        delay_prob=0.0, fail_prob=0.0, kill_at=-1, kill_pid=None,
        retry_failed=True, verbose=True, out_path=None, scenario_path=None,
        conflict_window=20, keep_commitment=True, work_scale=1.0):
    # 做实验要用开关，不要去改代码里的常量——改完容易忘，也污染版本。
    planner.KEEP_COMMITMENT = keep_commitment
    # 给了场景文件就从文件读，否则用替身生成器。
    # 换场景只换文件、不改代码——这是 WP0 的验收点。
    if scenario_path:
        snapshot = load_scenario(scenario_path)
    else:
        snapshot = sample_scenario(seed=seed, n_platforms=n_platforms,
                                   n_tasks=n_tasks, objective=objective,
                                   work_scale=work_scale)
    ex = StubExecutor(seed=seed, delay_prob=delay_prob, fail_prob=fail_prob)
    initial_energy = sum(p.battery for p in snapshot.platforms)

    plan = None
    plan_id = 0
    # 待处理的触发源。用列表而不是单个字符串：同一步里可能同时发生
    # 成员损失、执行失败、超时，只记最后一个等于丢掉另外两个。
    pending = [("init", "首次规划")]

    replan_reasons = {}
    replan_log = []
    all_events = []
    traces = []
    tracker = ConflictTracker(window=conflict_window)

    for step in range(T):
        # ---- 动态事件：成员损失（上层编组通知） ----
        if kill_at >= 0 and step == kill_at:
            target = kill_pid or ("P%02d" % (n_platforms - 1))
            if ex.kill(snapshot, target):
                snapshot.version += 1
                pending.append(("member_change", "成员损失(%s)" % target))
                all_events.append(dict(kind="member_lost", pid=target, at=step))

        # ---- 规划 ----
        if pending:
            plan, events = planner.plan(snapshot, step, H=H, plan_id=plan_id,
                                        prev_plan=plan)
            plan_id += 1
            all_events.extend(events)
            tracker.observe(events, step)
            labels = []
            for src, detail in pending:
                label = TRIGGER_LABELS.get(src, src)
                replan_reasons[label] = replan_reasons.get(label, 0) + 1
                replan_log.append(dict(at=step, source=src, detail=detail,
                                       plan_id=plan.plan_id))
                labels.append("%s:%s" % (label, detail))
            # 留痕四元组：输入快照 / 规则版本 / 输出 / 依据
            traces.append(dict(
                plan_id=plan.plan_id, created_at=step, group_version=snapshot.version,
                rule_version=plan.rule_version, objective=plan.objective,
                assignments=[dict(tid=a.tid, pids=a.pids, start=a.start,
                                  end=a.end, seq=a.seq, coord=a.coord)
                             for a in plan.assignments],
                rejected=plan.rejected,
                triggers=[dict(source=s, detail=d) for s, d in pending],
                evidence=events,
            ))
            if verbose:
                print("[t=%02d] 规划#%d (%s) -> %d 条指派, %d 条拒绝"
                      % (step, plan.plan_id, " + ".join(labels),
                         len(plan.assignments), len(plan.rejected)))
                for a in plan.assignments[:4]:
                    print("        %s  %s  步[%d,%d]  %s"
                          % (a.tid, ",".join(a.pids), a.start, a.end, a.coord))
            pending = []

        # ---- 执行 ----
        _fb, ev = ex.step(plan, snapshot, step)
        all_events.extend(ev)
        for e in ev:
            if verbose and e.get("kind") in ("fail", "task_done", "member_lost"):
                print("        [事件] %s %s" % (e.get("kind"), e))

        # ---- 失败/超时后重新分配（2.1（4）） ----
        if retry_failed:
            for t in snapshot.tasks:
                if t.status == "failed":
                    all_events.append(dict(kind="reassign", tid=t.tid, at=step,
                                           cause="failed", note="失败后释放，重新分配"))
                    t.status = "open"
                    t.progress = 0.0
                    pending.append(("exec_fail", "执行失败(%s)" % t.tid))

        # ---- 偏差判定 ----
        lag, tid, kind = deviation(plan, snapshot, step)
        if tid and lag > dev_threshold:
            if kind == "timeout":
                pending.append(("timeout", "超时(%s,欠%.1f)" % (tid, lag)))
            else:
                pending.append(("deviation", "偏差超阈值(%s,%.1f)" % (tid, lag)))
            all_events.append(dict(kind="deviation", tid=tid, lag=round(lag, 2),
                                   type=kind, at=step))

        # ---- 滚动周期 ----
        if (step + 1) % K == 0:
            pending.append(("periodic", "滚动周期(K=%d)" % K))

        if all(t.status in ("done", "failed") for t in snapshot.tasks):
            if verbose:
                print("[t=%02d] 全部作业已结束，提前收尾" % step)
            break

    # ---------------- 统计 ----------------
    done = [t for t in snapshot.tasks if t.status == "done"]
    failed = [t for t in snapshot.tasks if t.status == "failed"]
    other = [t for t in snapshot.tasks if t.status not in ("done", "failed")]
    conflicts = [e for e in all_events if e.get("kind") == "conflict"]
    resolved = [e for e in all_events if e.get("kind") == "resolved"]
    violations = [e for e in all_events if e.get("kind") == "violation"]
    deviations = [e for e in all_events if e.get("kind") == "deviation"]

    print("\n================ 统计 ================")
    print("作业：共 %d，完成 %d，失败 %d，未结束 %d"
          % (len(snapshot.tasks), len(done), len(failed), len(other)))
    print("规划：共 %d 次，触发原因 %s" % (plan_id, replan_reasons))
    # 四类触发源各自独立计数（WP1）。同一轮可能同时命中多类，
    # 所以各类次数之和会大于规划次数——这不是重复计数，是"一次规划有多个理由"。
    print("重规划触发源（各自独立，同一轮可多条）：")
    for src in ("init", "member_change", "exec_fail", "timeout",
                "deviation", "periodic"):
        c = sum(1 for r in replan_log if r["source"] == src)
        print("    %-14s %-6s %d 次" % (src, TRIGGER_LABELS[src], c))
    print(format_report(tracker.report(), raw_conflicts=len(conflicts)))
    # 措辞要准：这些是"检测到并已撤下"，不是"发出去了"。
    # 第 6 步现在会拦截——检测到叠加超续航的指派会撤下，不再进下发清单。
    print("方案级越界：检测到 %d 次，均已撤下（不再下发）" % len(violations))
    if violations:
        print("          样例：%s" % violations[0])
    print("偏差触发重规划：%d 次" % len(deviations))

    # ---- 三类优化目标各自的"成绩单"：必须有这三个数，
    #      否则"切换优化目标真的改变了行为"这句话无从验证（2.3（4））----
    used_energy = initial_energy - sum(p.battery for p in snapshot.platforms)
    done_at = [e["at"] for e in all_events if e.get("kind") == "task_done"]
    makespan = max(done_at) if done_at else None
    alive = [p for p in snapshot.platforms if p.alive]
    if len(alive) >= 2:
        cx = sum(p.pos[0] for p in alive) / len(alive)
        cy = sum(p.pos[1] for p in alive) / len(alive)
        spread = sum(((p.pos[0] - cx) ** 2 + (p.pos[1] - cy) ** 2) ** 0.5
                     for p in alive) / len(alive)
    else:
        spread = 0.0
    # 注意：不能直接比总能耗。干得少的策略天然更省电，
    # 那是"少干活"不是"更省电"。必须按完成的作业数归一化。
    per_task_energy = (used_energy / len(done)) if done else None
    print("成绩单：总能耗 %.1f，完成时刻(makespan) %s，分散度 %.2f"
          % (used_energy, makespan if makespan is not None else "未完成", spread))
    print("          每完成一个作业的能耗 %s，完成数 %d"
          % ("%.2f" % per_task_energy if per_task_energy is not None else "无完成作业",
             len(done)))
    print("（比总能耗会被\"干得少\"骗到，要比就比归一化后的每作业能耗）")

    rej_reasons = {}
    scope_tids = set()
    for tr in traces:
        for r in tr.get("rejected", []):
            key = r["reason"].split("(")[0]
            rej_reasons[key] = rej_reasons.get(key, 0) + 1
            if "规划视野" in r["reason"] and r.get("tid"):
                scope_tids.add(r["tid"])
    print("派不出去的原因分布：%s" % rej_reasons)
    print("（次数是按 (平台×作业) 组合计的，所以『续航不足』天然条数多，")
    print("  看瓶颈要按『有多少个作业被卡』看，不能只看次数）")

    # 自动提醒：有作业因"开工时间超出规划视野"被本轮跳过，说明瓶颈可能是
    # H 太小，而不是能力不足。这个坑极易误判——曾把视野问题当成续航问题。
    if scope_tids:
        print("注意：%d 个作业因开工超出规划视野(H=%d) 本轮未排：%s"
              % (len(scope_tids), H, sorted(scope_tids)))
        print("      这不是能力不足。可试 --H 45 对照"
              "（实测 H 20→45：6 seed 完成数 24→36，消解率 43%→65%）")
    print("未启用的能力校验项：%s"
          % sorted(planner.ALL_CHECKS - planner.ENABLED_CHECKS))

    # 本层穷尽手段仍然无解的作业，必须上报。
    # 不能让它静默悬着——那等于"既没解决，也没吱声"。
    # 两类会进这里：排不进时间窗（加人换人都无效）、可行平台数结构性不足。
    need_report = sorted({e["tid"] for e in all_events
                          if e.get("need_report")})
    print("需上报上层（本层已无解，须由上层决定：放宽窗口/增派资源/正式放弃）：%s"
          % (need_report if need_report else "无"))

    # ---- 分配求解器对照：最优 vs 贪心 ----
    # 这个差值直接回答"换求解器值不值"。同一个一对一可行域下比，才叫可比。
    solves = [e for e in all_events if e.get("kind") == "assign_solve"]
    if solves:
        g = sum(e["greedy"] for e in solves)
        o = sum(e["optimal"] for e in solves)
        print("crew=1 指派求解（共 %d 轮，求解器 %s）：最优合计 %.2f，贪心合计 %.2f，"
              "差 %.2f（%.1f%%）"
              % (len(solves), solves[-1]["solver"], o, g, g - o,
                 (100.0 * (g - o) / o) if o > 0 else 0.0))
        worst = max(solves, key=lambda e: e["gap"])
        print("          单轮最大差距：t=%s，最优 %.2f vs 贪心 %.2f（差 %.2f）"
              % (worst.get("at"), worst["optimal"], worst["greedy"], worst["gap"]))
    else:
        print("crew=1 指派求解：本轮场景没有 crew=1 的作业，跳过")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for tr in traces:
                f.write(json.dumps(tr, ensure_ascii=False) + "\n")
            for e in all_events:
                f.write(json.dumps(dict(record="event", **e), ensure_ascii=False) + "\n")
        print("留痕已写入：%s" % out_path)

    stats = dict(
        seed=seed, objective=objective,
        n_tasks=len(snapshot.tasks), done=len(done), failed=len(failed),
        other=len(other),
        conflicts_total=tracker.report()["total"],
        conflicts_raw=len(conflicts),
        resolved=tracker.report()["resolved"],
        within_rate=tracker.report()["within_rate"],
        used_energy=used_energy,
        per_task_energy=per_task_energy,
        makespan=makespan, spread=spread,
        violations=len(violations), deviations=len(deviations),
        replans=plan_id, replan_reasons=replan_reasons,
        triggers={s: sum(1 for r in replan_log if r["source"] == s)
                  for s in TRIGGER_LABELS},
        solves=solves,
        need_report=need_report,
    )
    return traces, all_events, stats


def main():
    ap = argparse.ArgumentParser(description="任务规划中间层：最小流程跑通")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--platforms", type=int, default=15)
    ap.add_argument("--tasks", type=int, default=8)
    ap.add_argument("--objective", default="makespan",
                    choices=["makespan", "dispersion", "energy"])
    ap.add_argument("--H", type=int, default=20, help="一次规划向前覆盖多少步")
    ap.add_argument("--K", type=int, default=5, help="采纳多少步后重新规划")
    ap.add_argument("--steps", type=int, default=60, help="总共跑多少步")
    ap.add_argument("--dev-threshold", type=float, default=4.0,
                    help="偏差判定阈值（工作量单位）。这个数应由噪声实验测出，不是拍的")
    ap.add_argument("--no-retry", action="store_true",
                    help="关闭失败作业的重新分配（2.1（4））")
    ap.add_argument("--delay-prob", type=float, default=0.0, help="替身延迟概率")
    ap.add_argument("--fail-prob", type=float, default=0.0, help="替身失败概率")
    ap.add_argument("--kill-at", type=int, default=-1, help="在第几步模拟成员损失")
    ap.add_argument("--no-keep", action="store_true",
                    help="关掉「承诺保持」，复现「开工时间被无限推迟、作业永远做不完」的故障")
    # 这两个开关默认 None = 不改动 planner 里的默认值。
    # 否则"不传参数"会被强制设成某个值，把模块默认悄悄覆盖掉（踩过）。
    ap.add_argument("--urgency", dest="urgency", action="store_true", default=None,
                    help="开「截止最早先干」(EDF)。实测提消解率但掉完成数，默认关")
    ap.add_argument("--no-urgency", dest="urgency", action="store_false", default=None,
                    help="关 EDF，退回按开始时间排（默认）")
    ap.add_argument("--swap", dest="swap", action="store_true", default=None,
                    help="开「换人消解」（默认开）")
    ap.add_argument("--no-swap", dest="swap", action="store_false", default=None,
                    help="关「换人消解」，排不进窗口时只加人（对照用）")
    ap.add_argument("--no-hungarian", dest="hungarian", action="store_false",
                    default=None,
                    help="关掉 crew=1 的最优一对一指派，退回贪心（对照用）")
    ap.add_argument("--hungarian", dest="hungarian", action="store_true",
                    default=None, help="开 crew=1 最优指派（默认开）")
    ap.add_argument("--scenario", default=None,
                    help="从 JSON 场景文件加载，而不是用替身生成器")
    ap.add_argument("--save-scenario", default=None,
                    help="把本次的替身场景写成 JSON 文件后退出")
    ap.add_argument("--out", default="flow_trace.jsonl")
    ap.add_argument("--work-scale", type=float, default=1.0, dest="work_scale",
                    help="作业量缩放，调节资源紧张程度（默认 1.0，不改变原有结果）。"
                         "与 RL 环境对照时两边必须用同一个值，否则对照不成立。")
    a = ap.parse_args()

    if a.save_scenario:
        from contract import save_scenario
        snap = sample_scenario(seed=a.seed, n_platforms=a.platforms,
                               n_tasks=a.tasks, objective=a.objective)
        save_scenario(snap, a.save_scenario)
        print("场景已写入：%s（%d 平台 / %d 作业）"
              % (a.save_scenario, len(snap.platforms), len(snap.tasks)))
        return

    if a.urgency is not None:
        planner.URGENCY_FIRST = a.urgency
    if a.swap is not None:
        planner.SWAP_TO_FIT = a.swap
    if a.hungarian is not None:
        planner.USE_HUNGARIAN = a.hungarian

    run(seed=a.seed, n_platforms=a.platforms, n_tasks=a.tasks,
        objective=a.objective, H=a.H, K=a.K, T=a.steps,
        dev_threshold=a.dev_threshold, delay_prob=a.delay_prob,
        fail_prob=a.fail_prob, kill_at=a.kill_at,
        retry_failed=not a.no_retry, out_path=a.out,
        scenario_path=a.scenario, keep_commitment=not a.no_keep,
        work_scale=a.work_scale)


if __name__ == "__main__":
    main()
