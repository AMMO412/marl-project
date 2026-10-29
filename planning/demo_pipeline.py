# -*- coding: utf-8 -*-
"""
demo_pipeline.py —— 一条命令看完整链路：输入 → 规划 → 执行 → 判定 → 输出

五类任务各来一个，全程打印。用它回答三个问题：
  系统接到了什么、怎么规划的、规划完怎么执行、最后判出来什么。

用法：
    python demo_pipeline.py                     # 默认：5 作业（五类各一）、15 平台、60 步
    python demo_pipeline.py --steps 100         # 跑长一点，看持续型任务
    python demo_pipeline.py --hold-drop-at 25   # 坚守中途抽走一台，看轮换缺口怎么被抓到
    python demo_pipeline.py --event-at 20       # 封控注入一次接近事件，看事件闭合
    python demo_pipeline.py --no-confirm        # 关闭结果确认，看突击停在"结果待确认"
    python demo_pipeline.py --trace             # 逐步打印执行过程

与 `run_flow.py` 的区别：
    run_flow 是**旧口径**（完成=progress>=work），用来跑基线与回归；
    本文件是**新口径**（完成=criteria 判定），用来看五类判据怎么工作。
    两者共用 planner 与 executor，判定方式不同。
"""

import argparse
import math
from typing import Dict, List, Optional

import criteria
import evidence
import planner
from contract import (PLATFORM_SPECS, TASK_SPECS, Assignment, Plan,
                      GroupSnapshot, sample_scenario)
from criteria import Criterion
from executor import StubExecutor
from evidence import Recorder

ORDER = ("patrol", "blockade", "recon", "assault", "hold")
CN = {"patrol": "巡逻警戒", "blockade": "区域封控", "recon": "协同侦察",
      "assault": "机动突击", "hold": "要点坚守"}


def find_overlaps(assignments) -> List[dict]:
    """同一平台在同一时段被排了两个作业 —— 检查不变量 #1。

    为什么要在演示里查这个：判据层只看"每个任务自己的条件满足没有"，
    **它管不了计划本身合法不合法**。一张每个任务都合格、但同一台平台被
    同时派两个活的计划，判据层会全部判 success。两件事必须分开查。
    """
    by: Dict[str, List] = {}
    for a in assignments:
        for pid in a.pids:
            by.setdefault(pid, []).append(a)
    out = []
    for pid, items in by.items():
        items.sort(key=lambda x: x.start)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                lo, hi = max(a.start, b.start), min(a.end, b.end)
                if lo < hi:
                    out.append(dict(pid=pid, a=a.tid, b=b.tid, steps=hi - lo,
                                    span=(lo, hi)))
    return out


def build_criteria(snap: GroupSnapshot, first_start: Dict[str, int],
                   steps: int, legs: int, cells: int,
                   patrol_factor: float, recon_ratio: float) -> Dict[str, Criterion]:
    """为五类各造一份判据配置。阈值全是【我方暂定】，集中在这一处。"""
    out = {}
    for t in snap.tasks:
        spec = TASK_SPECS[t.ttype]
        w0, w1 = spec["window"]
        te = min(w1, steps)
        st = first_start.get(t.tid, w0)
        if t.ttype == "patrol":
            out[t.tid] = Criterion(
                objects=tuple("L%d" % i for i in range(legs)),
                t_start=st, t_end=te,
                threshold=(w1 - w0) / legs * patrol_factor,
                need_kinds=("visit",))
        elif t.ttype == "blockade":
            out[t.tid] = Criterion(objects=(), t_start=st, t_end=te,
                                   threshold=0.0, need_kinds=("presence",))
        elif t.ttype == "recon":
            out[t.tid] = Criterion(
                objects=tuple("c%02d" % i for i in range(cells)),
                t_start=st, t_end=te,
                threshold=cells * recon_ratio,
                need_kinds=("observation",))
        elif t.ttype == "assault":
            out[t.tid] = Criterion(objects=("strike",), t_start=st, t_end=te,
                                   confirm_deadline=te + 10,
                                   threshold=0.0, need_kinds=("event",))
        elif t.ttype == "hold":
            out[t.tid] = Criterion(objects=("K",), t_start=st, t_end=te,
                                   threshold=float(spec["crew"]),
                                   need_kinds=("presence",))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--platforms", type=int, default=15)
    ap.add_argument("--H", type=int, default=45,
                    help="规划视野。**H=20 时封控与突击排不进去**（实测），默认 45")
    ap.add_argument("--K", type=int, default=0,
                    help="滚动周期。**0 = 只规划一次**（演示默认，避免重规划抖动打断持续型任务）；"
                         "给 5 可看滚动时域下持续型被打断的样子")
    ap.add_argument("--objective", default="makespan",
                    choices=("makespan", "dispersion", "energy"))
    ap.add_argument("--legs", type=int, default=evidence.PATROL_LEGS,
                    help="巡逻：把工作量切成几段 = 几次有效访问【我方暂定】")
    ap.add_argument("--cells", type=int, default=evidence.RECON_CELLS,
                    help="侦察：待覆盖区域离散单元数【我方暂定】")
    ap.add_argument("--patrol-factor", type=float, default=1.5,
                    help="巡逻重访间隔上限 = 窗口/段数 × 该系数【我方暂定】")
    ap.add_argument("--recon-ratio", type=float, default=0.9,
                    help="侦察合并覆盖门槛比例【我方暂定】")
    ap.add_argument("--confirm-delay", type=int, default=3,
                    help="突击结果在动作结束后几步返回【我方暂定】")
    ap.add_argument("--no-confirm", action="store_true", help="不返回结果，看'结果待确认'")
    ap.add_argument("--event-at", type=int, default=-1, help="封控：第几步注入一次接近事件")
    ap.add_argument("--hold-drop-at", type=int, default=-1, help="坚守：第几步抽走一台")
    ap.add_argument("--sustain", dest="sustain", action="store_true", default=True,
                    help="持续型（巡逻/封控/坚守）维持到窗口结束，即设计文档 P0 的修法")
    ap.add_argument("--no-sustain", dest="sustain", action="store_false",
                    help="关掉维持：看旧实现'干完工作量就放人'如何被判据层照出来")
    ap.add_argument("--trace", action="store_true", help="逐步打印执行过程")
    a = ap.parse_args()

    # ---------------- 1 输入 ----------------
    snap = sample_scenario(seed=a.seed, n_platforms=a.platforms,
                           n_tasks=len(ORDER), objective=a.objective)
    # 让五类按顺序各一个（sample_scenario 本就是循环取类型）
    print("=" * 78)
    print("一、输入：上层编组送下来的一次快照")
    print("=" * 78)
    print("编组版本 v%d ｜ 目标 %s ｜ 平台 %d 台 ｜ 作业 %d 个"
          % (snap.version, snap.objective, len(snap.platforms), len(snap.tasks)))
    kinds: Dict[str, int] = {}
    for p in snap.platforms:
        kinds[p.ptype] = kinds.get(p.ptype, 0) + 1
    print("平台构成：" + "、".join("%s×%d" % (k, v) for k, v in sorted(kinds.items())))
    print()
    print("%-10s %-6s %-6s %-10s %-8s %-8s" % ("作业", "类型", "crew", "工作量", "时间窗", "载荷/传感器"))
    print("-" * 78)
    for t in snap.tasks:
        s = TASK_SPECS[t.ttype]
        print("%-10s %-6s %-6d %-10.0f %-8s %-8s"
              % (t.tid, CN[t.ttype], t.crew, t.work,
                 "[%d,%d]" % tuple(t.window),
                 "%s/%s" % (s["need_payload"] or 0, s["need_sensor"] or "不挑")))
    print("> 平台参数（速度/续航/载荷/传感器）目前**全部是【我方暂定】**，"
          "下游尚未提供可核验的真实值。")

    # ---------------- 2 规划 ----------------
    print()
    print("=" * 78)
    print("二、规划：planner 六步（过滤→打分→分配→排程→消解→校验）")
    print("=" * 78)
    ex = StubExecutor(seed=a.seed)
    rec = Recorder()
    rec.bind([t.tid for t in snap.tasks], rule_version=planner.RULE_VERSION)
    first_start: Dict[str, int] = {}
    plan: Optional[Plan] = None
    plan_id = 0
    replans = 0
    all_events: List[dict] = []
    dropped = set()

    K = a.K if a.K > 0 else a.steps          # 0 = 只规划一次
    for step in range(a.steps):
        if step % K == 0 or plan is None:
            plan, evs = planner.plan(snap, step, H=a.H, plan_id=plan_id,
                                     prev_plan=plan)
            plan_id += 1
            replans += 1
            all_events.extend(evs)
        if a.sustain:
            # 持续型（巡逻/封控/坚守）维持到窗口结束 —— 设计文档 P0 的修法。
            # 这不是 planner 里的实现，是演示用的外层补丁，用来对照"修"与"没修"。
            for asm in plan.assignments:
                t = next((x for x in snap.tasks if x.tid == asm.tid), None)
                if t is not None and t.ttype in ("patrol", "blockade", "hold"):
                    # +1：executor 的活跃条件是 `start <= now < end`，
                    # 想让最后一步（window[1]）也落在区间内，end 要给到 window[1]+1
                    asm.end = max(asm.end, min(t.window[1], a.steps) + 1)
        if a.hold_drop_at >= 0 and step == a.hold_drop_at:
            for asm in plan.assignments:
                t = next((x for x in snap.tasks if x.tid == asm.tid), None)
                if t is not None and t.ttype == "hold" and len(asm.pids) > 1:
                    victim = asm.pids[-1]
                    ex.kill(snap, victim)
                    snap.version += 1
                    dropped.add(victim)
                    print("  [t=%02d] 导调事件：坚守成员 %s 失联，触发重规划" % (step, victim))

        fbs, evs = ex.step(plan, snap, step)
        all_events.extend(evs)
        # 巡逻维持：完成一圈后归零重新计数，派生出"反复访问"序列。
        # 真实实现应维护检查点序列（设计文档 P2），这里是演示替代。
        if a.sustain:
            for t in snap.tasks:
                if t.ttype == "patrol" and t.progress >= t.work:
                    t.progress = 0.0
                    t.status = "running"
        evidence.observe_step(rec, plan, snap, step,
                              patrol_legs=a.legs, recon_cells=a.cells)
        for t in snap.tasks:
            if t.tid not in first_start:
                if any(x.tid == t.tid and x.start <= step < x.end
                       for x in plan.assignments):
                    first_start[t.tid] = step

        # 侦察：回传确认（真实系统由接收方产生）
        for t in snap.tasks:
            if t.ttype == "recon" and t.status == "done":
                if rec.count(t.tid, "relay") == 0:
                    evidence.relay(rec, t.tid, step)
        # 突击：结果确认（延迟若干步返回）
        if not a.no_confirm:
            for t in snap.tasks:
                if t.ttype == "assault" and t.progress >= t.work:
                    if rec.count(t.tid, "result") == 0:
                        last = max([e.at for e in rec.get(t.tid)
                                    if e.kind == "event"] or [0])
                        if step >= last + a.confirm_delay:
                            evidence.result(rec, t.tid, step, "strike")
        # 封控：注入一次接近事件，其后再补处置结果
        if a.event_at >= 0 and step == a.event_at:
            for t in snap.tasks:
                if t.ttype == "blockade":
                    rec.add(t.tid, "event", step, "gate", obj="E1",
                            value=0.0, valid=True, note="接近事件")
        if a.event_at >= 0 and step == a.event_at + a.confirm_delay:
            for t in snap.tasks:
                if t.ttype == "blockade":
                    evidence.result(rec, t.tid, step, "E1")

        if a.trace:
            act = [x for x in plan.assignments if x.start <= step < x.end]
            if act:
                print("  t=%02d " % step + "；".join(
                    "%s[%d,%d]%s" % (x.tid, x.start, x.end, ",".join(x.pids))
                    for x in act))

    # 打印本次规划结果（用最后一次计划代表）
    print("规划 %d 次（滚动周期 K=%d）｜规则版本 %s" % (replans, a.K, planner.RULE_VERSION))
    print()
    print("%-10s %-8s %-14s %-12s %-10s" % ("作业", "类型", "指派平台", "步区间", "协同"))
    print("-" * 78)
    seen = {}
    for tr in all_events:
        pass
    for t in snap.tasks:
        # 从证据里找这台任务实际被派过的平台与时段
        srcs = sorted({e.source for e in rec.get(t.tid) if e.kind == "presence"})
        ats = [e.at for e in rec.get(t.tid) if e.kind == "presence"]
        span = ("[%d,%d]" % (min(ats), max(ats))) if ats else "—"
        print("%-10s %-8s %-14s %-12s %-10s"
              % (t.tid, CN[t.ttype], ",".join(srcs) or "—", span, "crew>=%d" % t.crew))
    print("> 注意：指派平台是从**执行证据**里反查的，不是从某一版计划里读的——"
          "滚动时域下计划会被反复重排，证据才是事实。")

    # 计划合法性（不变量 #1）：判据层管不了这个，必须单独查
    ovs = find_overlaps(plan.assignments) if plan else []
    if ovs:
        print()
        print("⚠ 计划存在问题：%d 处同平台同时段重叠（不变量 #1 被破坏）" % len(ovs))
        for o in ovs:
            print("    %s：%s 与 %s 在 [%d,%d] 重叠 %d 步"
                  % (o["pid"], o["a"], o["b"], o["span"][0], o["span"][1], o["steps"]))
        print("  成因：--sustain 是**事后延长 end**，没有重新排程。"
              "真实修法是让 planner 在排程阶段就知道持续型要占住到窗口结束。")
        print("  它不影响下面的判据结论，但这份计划**不能直接下发**。")

    # ---------------- 3 判定 ----------------
    print()
    print("=" * 78)
    print("三、判定：criteria 五类各自判据（吃全过程证据，不是最后一帧）")
    print("=" * 78)
    crits = build_criteria(snap, first_start, a.steps, a.legs, a.cells,
                           a.patrol_factor, a.recon_ratio)
    print("%-10s %-8s %-10s %-10s %s" % ("作业", "类型", "判定", "旧口径", "理由"))
    print("-" * 78)
    verdicts = {}
    for t in snap.tasks:
        v = criteria.judge(t.ttype, crits[t.tid], rec.get(t.tid), a.steps)
        verdicts[t.tid] = v
        old = "done" if t.status == "done" else t.status
        print("%-10s %-8s %-10s %-10s %s"
              % (t.tid, CN[t.ttype], v.status, old, v.reason[:44]))
    print()
    print("证据统计（每条都带时刻与来源，可事后复算）：")
    print("%-10s %-8s %-8s %-8s %-8s %-8s %-8s"
          % ("作业", "类型", "在位", "访问", "覆盖", "事件", "结果/回传"))
    print("-" * 78)
    for t in snap.tasks:
        print("%-10s %-8s %-8d %-8d %-8d %-8d %-8d"
              % (t.tid, CN[t.ttype],
                 len({e.at for e in rec.get(t.tid) if e.kind == "presence"}),
                 rec.count(t.tid, "visit"),
                 rec.count(t.tid, "observation"),
                 rec.count(t.tid, "event"),
                 rec.count(t.tid, "result") + rec.count(t.tid, "relay")))

    # ---------------- 4 输出 ----------------
    print()
    print("=" * 78)
    print("四、输出")
    print("=" * 78)
    print("1) 下发件 Assignment：子任务(tid) / 平台(pids) / 时序(start,seq) / "
          "时间窗(end) / 协同(coord)")
    print("2) 证据序列 Evidence：对象-时间-门槛-证据-缺失处理 五要素齐全，可重放复算")
    print("3) 判定 Verdict：%s"
          % "、".join(sorted({v.status for v in verdicts.values()})))
    print()
    n_done = sum(1 for v in verdicts.values() if v.status == criteria.SUCCESS)
    print("新口径成功 %d/5 ｜ 旧口径(progress>=work) 完成 %d/5"
          % (n_done, sum(1 for t in snap.tasks if t.status == "done")))
    print("> 两个数不一样是正常的，而且**正是重点**：旧口径只看'工作量干完'，"
          "新口径看'约定的条件是否全程满足'。")
    print()
    print("未接线提醒：`bridge.py`（目标点→Twist 闭环）未接入本演示——"
          "本演示的下游仍是替身执行器。")


if __name__ == "__main__":
    main()
