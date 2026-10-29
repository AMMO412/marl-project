# -*- coding: utf-8 -*-
"""
evidence.py —— 证据层（L5，最小实现）

判据层 `criteria.py` 吃的是 **Evidence 序列**，不是当前值。
本层负责把执行过程变成 Evidence。没有这一层，判据层就是空转。

> [!warning] 三条派生规则是**我方暂定**，写在明处，不要当成真实观测
> 1. **巡逻**：下游与我们都没有"检查点序列"的概念。这里把作业的 `work` 均分成
>    `PATROL_LEGS` 段，**每完成一段记一次有效访问**。这样从真实进度派生出访问序列，
>    不是伪造时间戳——但"一段=一次有效访问"这个等价关系是我方暂定。
> 2. **侦察**：`Task` 只有点、没有面。这里把待覆盖总量离散成 `RECON_CELLS` 个单元，
>    按进度比例标记已覆盖。**覆盖几何是派生的，不是真实传感覆盖。**
> 3. **封控/坚守**：每步在位记一条 `presence`。这个不派生，就是执行事实。

真实传感覆盖、真实检查点、真实事件流到位后，只需替换本文件的派生函数，
`criteria.py` **不用改**。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from criteria import Evidence

# ---- 派生参数（我方暂定）----
PATROL_LEGS = 3        # 巡逻：work 切成几段 = 几次有效访问
RECON_CELLS = 20       # 侦察：待覆盖区域离散成几个单元


@dataclass
class Recorder:
    """按任务收集证据。每条都带时刻、来源与有效性。"""
    logs: Dict[str, List[Evidence]] = field(default_factory=dict)
    rule_version: str = ""
    state: Dict[str, object] = field(default_factory=dict)   # 派生用的小状态（如巡逻当前段）

    def bind(self, tids: Sequence[str], rule_version: str = "") -> None:
        self.rule_version = rule_version
        for t in tids:
            self.logs.setdefault(t, [])

    def add(self, tid: str, kind: str, at: int, source: str,
            obj: Optional[str] = None, value: Optional[float] = None,
            valid: bool = True, note: str = "") -> None:
        self.logs.setdefault(tid, []).append(
            Evidence(kind=kind, at=at, source=source, obj=obj,
                     value=value, valid=valid, note=note))

    def get(self, tid: str) -> List[Evidence]:
        return self.logs.get(tid, [])

    def count(self, tid: str, kind: str) -> int:
        return sum(1 for e in self.get(tid) if e.kind == kind)


# ------------------------------------------------------------------
# 从执行过程派生证据
# ------------------------------------------------------------------

def observe_step(rec: Recorder, plan, snapshot, now: int,
                 patrol_legs: int = PATROL_LEGS,
                 recon_cells: int = RECON_CELLS) -> None:
    """每个执行步调一次：把当前发生的事记成证据。"""
    tmap = {t.tid: t for t in snapshot.tasks}
    active = {a.tid: a for a in plan.assignments if a.start <= now < a.end}

    for tid, a in active.items():
        t = tmap.get(tid)
        if t is None or t.status == "failed":
            # 注意：**不因 status == "done" 就停止记录**。持续型任务（封控/坚守）
            # 要求"维持到窗口结束"，而旧口径一干完工作量就置 done；
            # 若在 done 时停止记录，判据层就永远看不到维持过程——那等于把
            # "持续型被做成瞬时型"这个缺陷藏起来了。这里照实记，让判据去判。
            continue

        # ---- 在位：所有类型都记（封控/坚守要靠它做全过程检查）----
        for pid in a.pids:
            rec.add(tid, "presence", now, pid, value=1.0 if _alive(snapshot, pid) else 0.0,
                    valid=_alive(snapshot, pid),
                    note="在位" if _alive(snapshot, pid) else "离位")

        # ---- 巡逻：进度跨过一段 = 一次有效访问 ----
        # 注意：同一段在**不同圈**要各记一次（L0 会被反复访问），
        # 所以这里记的是"刚刚完成的那一段"，不去重。
        if t.ttype == "patrol":
            leg = _leg_index(t, patrol_legs)
            prev = rec.state.get(tid + "_leg")
            if leg is not None and prev is not None and leg != prev:
                rec.add(tid, "visit", now, ",".join(a.pids), obj="L%d" % prev,
                        value=1.0, valid=True, note="完成第%d段" % (prev + 1))
            if leg is not None:
                rec.state[tid + "_leg"] = leg

        # ---- 侦察：按进度标记覆盖单元 ----
        if t.ttype == "recon":
            covered = int(t.progress / max(t.work, 1e-6) * recon_cells)
            for c in range(covered):
                obj = "c%02d" % c
                if not _already(rec, tid, "observation", obj=obj):
                    rec.add(tid, "observation", now, ",".join(a.pids),
                            obj=obj, value=1.0, valid=True, note="覆盖单元")

        # ---- 突击：执行环节记录（指令已发送 ≠ 已执行，这里只记真实推进）----
        if t.ttype == "assault" and t.progress > 0:
            if not _already(rec, tid, "event", obj="strike"):
                rec.add(tid, "event", now, ",".join(a.pids), obj="strike",
                        value=1.0, valid=True, note="突击动作执行")

        # ---- 封控：控制状态（在位即视为控制建立，注意这不是"处置成功"）----
        if t.ttype == "blockade":
            rec.add(tid, "control", now, ",".join(a.pids), value=1.0, valid=True,
                    note="控制状态")


def _alive(snapshot, pid: str) -> bool:
    for p in snapshot.platforms:
        if p.pid == pid:
            return p.alive
    return False


def _already(rec: Recorder, tid: str, kind: str, obj: Optional[str] = None) -> bool:
    return any(e.kind == kind and e.obj == obj for e in rec.get(tid))


def _leg_index(t, legs: int) -> Optional[int]:
    """进度落在第几段（0-based）。未完成任何一段时返回 None。"""
    if legs <= 0:
        return None
    frac = t.progress / max(t.work, 1e-6)
    idx = int(frac * legs)
    return idx if 0 <= idx < legs else None


def relay(rec: Recorder, tid: str, at: int, source: str = "rx") -> None:
    """回传确认（侦察交付条件的证据）。真实系统由接收方产生。"""
    rec.add(tid, "relay", at, source, value=1.0, valid=True, note="接收方确认")


def result(rec: Recorder, tid: str, at: int, obj: str, source: str = "evaluator",
           ok: bool = True) -> None:
    """结果确认（突击/封控的处置结果）。真实系统由评估模块产生。"""
    rec.add(tid, "result", at, source, obj=obj, value=1.0 if ok else 0.0,
            valid=ok, note="评估结果")
