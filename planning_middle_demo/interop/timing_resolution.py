# -*- coding: utf-8 -*-
"""动态场景下子任务时序冲突的跨回合消解统计（指标 2.2(3)）。

指标原文：动态场景下 20 回合内子任务时序冲突消解率 ≥ 95%。

本模块不重复规划器的时序逻辑，只做三件事：
  1. 把“正在执行 + 已排待执行 + 因依赖/事件被阻塞”的子任务统一成
     ``TimingSlot`` 快照；
  2. 用独立的约束检查器识别四类时序冲突：同平台占用重叠、前后依赖、
     时间窗、协同开始；
  3. 跨回合跟踪每条冲突的首次发现回合、处理动作、复核结果和消解回合，
     输出 ``resolution_rate_20``。

回合按完整调度周期计（默认取协调器的滚动周期 K）；动态事件后的状态
作为该冲突的第 0 回合，之后每 K 步推进一回合。即使某回合没有重规划，
回合也照常推进。
"""
from dataclasses import dataclass, field
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

EPS = 1e-6

TIMING_TYPES = ("RESOURCE_OVERLAP", "DEPENDENCY", "WINDOW", "COORDINATION")
TYPE_LABELS = {
    "RESOURCE_OVERLAP": "同平台占用重叠",
    "DEPENDENCY": "前后依赖冲突",
    "WINDOW": "时间窗冲突",
    "COORDINATION": "协同时间冲突",
}


@dataclass
class TimingSlot:
    """一个子任务在某一时刻的时序事实。

    ``state``：
      * RUNNING  —— 已有在途指令，start 固定，end 用预计完成时刻；
      * PLANNED  —— 已排进当前计划、尚未下发；
      * BLOCKED  —— 因依赖/事件尚未排入计划，用最早可行时间估算。
    """
    subtask_id: str
    parent_task_id: str
    task_type: str
    target: Dict
    start_s: float
    end_s: float
    window_start_s: float
    window_end_s: float
    depends_on: List[str] = field(default_factory=list)
    coordination: List[str] = field(default_factory=list)
    unit_id: Optional[str] = None
    state: str = "PLANNED"
    role: str = ""
    travel_s: float = 0.0
    command_id: Optional[str] = None
    assigned: bool = True

    @property
    def interval_start(self) -> float:
        return float(self.start_s) - float(self.travel_s or 0.0)


@dataclass(frozen=True)
class ConflictHit:
    key: Tuple
    type: str
    subtask_ids: Tuple[str, ...]
    reason: str
    detected_at_s: float
    detail: Tuple[Tuple[str, object], ...] = ()

    def info(self) -> Dict:
        return dict(self.detail)


def _slot_map(slots: Sequence[TimingSlot]) -> Dict[str, TimingSlot]:
    return {slot.subtask_id: slot for slot in slots}


def detect_timing_conflicts(slots: Sequence[TimingSlot],
                            coordination_tol_s: float = 1.0) -> List[ConflictHit]:
    """独立约束检查器：只返回四类时序冲突，不做任何“已经重规划过”的推断。"""
    hits: List[ConflictHit] = []
    by_id = _slot_map(slots)

    # 1) 同平台占用重叠：按平台把有指派的时间段排序，前一任务结束晚于
    #    后一任务“开始 - 转场时间”即冲突。
    by_unit: Dict[str, List[TimingSlot]] = {}
    for slot in slots:
        if slot.unit_id and slot.assigned and slot.state in ("RUNNING", "PLANNED"):
            by_unit.setdefault(slot.unit_id, []).append(slot)
    for unit_id, items in by_unit.items():
        items = sorted(items, key=lambda s: (s.interval_start, s.end_s,
                                             s.subtask_id))
        for prev, curr in zip(items, items[1:]):
            if prev.end_s > curr.interval_start + EPS:
                hits.append(ConflictHit(
                    key=("RESOURCE_OVERLAP", unit_id, prev.subtask_id,
                         curr.subtask_id),
                    type="RESOURCE_OVERLAP",
                    subtask_ids=tuple(sorted((prev.subtask_id, curr.subtask_id))),
                    reason=("平台 %s 的 %s 结束 %.1f 晚于 %s 的最早开始 %.1f"
                            % (unit_id, prev.subtask_id, prev.end_s,
                               curr.subtask_id, curr.interval_start)),
                    detected_at_s=float(curr.interval_start),
                    detail=(("unit_id", unit_id),
                            ("prev", prev.subtask_id),
                            ("curr", curr.subtask_id),
                            ("prev_end", round(float(prev.end_s), 3)),
                            ("curr_start", round(float(curr.start_s), 3)),
                            ("travel_s", round(float(curr.travel_s or 0.0), 3)))))

    # 2) 前后依赖：后继开始早于前置结束即冲突。前置不在快照里时，
    #    若它已被标记未分配/删除，由跟踪器按“不可用”处理。
    for slot in slots:
        for dep_id in slot.depends_on or []:
            dep = by_id.get(dep_id)
            if dep is None:
                hits.append(ConflictHit(
                    key=("DEPENDENCY", slot.subtask_id, dep_id),
                    type="DEPENDENCY",
                    subtask_ids=tuple(sorted((slot.subtask_id, dep_id))),
                    reason="前置子任务 %s 未分配，后继 %s 无法按时序开工"
                           % (dep_id, slot.subtask_id),
                    detected_at_s=float(slot.start_s),
                    detail=(("child", slot.subtask_id), ("dep", dep_id),
                            ("dep_missing", True))))
            elif dep.end_s > slot.start_s + EPS:
                hits.append(ConflictHit(
                    key=("DEPENDENCY", slot.subtask_id, dep_id),
                    type="DEPENDENCY",
                    subtask_ids=tuple(sorted((slot.subtask_id, dep_id))),
                    reason=("前置 %s 结束 %.1f 晚于后继 %s 开始 %.1f"
                            % (dep_id, dep.end_s, slot.subtask_id, slot.start_s)),
                    detected_at_s=float(slot.start_s),
                    detail=(("child", slot.subtask_id), ("dep", dep_id),
                            ("dep_end", round(float(dep.end_s), 3)),
                            ("child_start", round(float(slot.start_s), 3)))))

    # 3) 时间窗：开始早于窗口或预计结束晚于窗口。
    for slot in slots:
        if slot.start_s < slot.window_start_s - EPS:
            hits.append(ConflictHit(
                key=("WINDOW", slot.subtask_id),
                type="WINDOW",
                subtask_ids=(slot.subtask_id,),
                reason=("子任务 %s 开始 %.1f 早于窗口 %.1f"
                        % (slot.subtask_id, slot.start_s, slot.window_start_s)),
                detected_at_s=float(slot.start_s),
                detail=(("subtask_id", slot.subtask_id),
                        ("window", [round(float(slot.window_start_s), 3),
                                    round(float(slot.window_end_s), 3)]),
                        ("start_s", round(float(slot.start_s), 3)),
                        ("end_s", round(float(slot.end_s), 3)))))
        elif slot.end_s > slot.window_end_s + EPS:
            hits.append(ConflictHit(
                key=("WINDOW", slot.subtask_id),
                type="WINDOW",
                subtask_ids=(slot.subtask_id,),
                reason=("子任务 %s 预计结束 %.1f 晚于窗口 %.1f"
                        % (slot.subtask_id, slot.end_s, slot.window_end_s)),
                detected_at_s=float(slot.start_s),
                detail=(("subtask_id", slot.subtask_id),
                        ("window", [round(float(slot.window_start_s), 3),
                                    round(float(slot.window_end_s), 3)]),
                        ("start_s", round(float(slot.start_s), 3)),
                        ("end_s", round(float(slot.end_s), 3)))))

    # 4) 协同开始：同一父任务下要求 simultaneous_arrival 的成员，
    #    计划/在途开始时刻差超过约定容差。
    groups: Dict[str, List[TimingSlot]] = {}
    for slot in slots:
        if ("simultaneous_arrival" in (slot.coordination or [])
                and slot.assigned and slot.state in ("RUNNING", "PLANNED")):
            groups.setdefault(slot.parent_task_id, []).append(slot)
    for parent_id, items in groups.items():
        starts = [float(slot.start_s) for slot in items]
        if len(starts) > 1 and max(starts) - min(starts) > coordination_tol_s + EPS:
            hits.append(ConflictHit(
                key=("COORDINATION", parent_id),
                type="COORDINATION",
                subtask_ids=tuple(sorted(slot.subtask_id for slot in items)),
                reason=("协同组 %s 开始时刻差 %.2f 超过容差 %.2f"
                        % (parent_id, max(starts) - min(starts),
                           coordination_tol_s)),
                detected_at_s=float(min(starts)),
                detail=(("parent_task_id", parent_id),
                        ("starts", [round(v, 3) for v in starts]),
                        ("tolerance_s", coordination_tol_s))))
    return hits


class TimingResolutionTracker(object):
    """跨回合冲突账本。

    一条冲突的身份 = 冲突类型 + 约束范围（平台/父子/协同组）。同一冲突
    连续出现多轮只保留一条记录；解决后再次出现视为新一代冲突。
    """

    def __init__(self, budget: int = 20, round_steps: int = 1):
        self.budget = max(1, int(budget))
        self.round_steps = max(1, int(round_steps))
        self.records: Dict[Tuple, Dict] = {}   # (冲突身份, 代次) -> 记录
        self.active: Dict[Tuple, Tuple] = {}   # 冲突身份 -> 当前代次记录键
        self.generations: Dict[Tuple, int] = {}
        self.compute_ms = 0.0
        self.observations = 0
        self.last_repair_round = -1
        self.last_round = 0
        self.history: List[Dict] = []

    # ------------------------------------------------------------------
    def round_of(self, now: int) -> int:
        self.last_round = max(0, int(now)) // self.round_steps
        return self.last_round

    def has_open(self) -> bool:
        return any(rec["status"] == "open"
                   and rec.get("candidate_round") is None
                   for rec in self.records.values())

    def open_keys(self) -> List[Tuple]:
        return [key for key, rec in self.records.items()
                if rec["status"] == "open"]

    # ------------------------------------------------------------------
    def observe(self, slots: Sequence[TimingSlot], now: int, *,
                unassigned: Iterable[str] = (), deleted: Iterable[str] = (),
                phase: str = "detect", repaired: bool = False) -> None:
        started = time.perf_counter()
        self.observations += 1
        round_idx = self.round_of(now)
        hits = detect_timing_conflicts(slots)
        current = {hit.key: hit for hit in hits}
        present = {slot.subtask_id for slot in slots if slot.assigned}
        parent_of = {slot.subtask_id: slot.parent_task_id for slot in slots}
        unassigned = set(unassigned)
        deleted = set(deleted)

        for key, hit in current.items():
            composite = self.active.get(key)
            rec = self.records.get(composite) if composite else None
            if rec is None or rec["status"] in ("resolved", "expired"):
                generation = self.generations.get(key, 0) + 1
                self.generations[key] = generation
                composite = (key, generation)
                self.active[key] = composite
                parents = sorted({parent_of.get(sid) for sid in hit.subtask_ids
                                  if parent_of.get(sid)})
                self.records[composite] = dict(
                    key=key, type=hit.type, subtask_ids=list(hit.subtask_ids),
                    parent_ids=parents, generation=generation,
                    first_round=round_idx, first_s=int(now),
                    last_round=round_idx, last_s=int(now),
                    status="open", resolution_round=None, resolution_s=None,
                    candidate_round=None, candidate_s=None,
                    reason=hit.reason, detail=hit.info(), attempts=0,
                    history=[dict(round=round_idx, at_s=int(now),
                                  action="detected", reason=hit.reason)],
                )
            else:
                if rec.get("candidate_round") is not None:
                    rec["candidate_round"] = None
                    rec["candidate_s"] = None
                    rec["history"].append(dict(round=round_idx, at_s=int(now),
                                               action="candidate_revoked",
                                               reason=hit.reason))
                rec["last_round"] = round_idx
                rec["last_s"] = int(now)
                rec["reason"] = hit.reason
                rec["detail"] = hit.info()

        current_composites = {self.active[key] for key in current}
        for composite, rec in list(self.records.items()):
            if rec["status"] != "open" or composite in current_composites:
                continue
            ids = set(rec["subtask_ids"])
            parents = set(rec.get("parent_ids") or ())
            if ids & deleted or parents & deleted:
                self._close(rec, round_idx, now, "abandoned",
                            "任务被删除，不计为消解")
                continue
            if ids & unassigned or parents & unassigned:
                self._close(rec, round_idx, now, "infeasible",
                            "相关子任务未分配或仅上报，不计为消解")
                continue
            if rec.get("candidate_round") is not None:
                # 候选修复已保持到下一回合：确认消解，消解时刻记首次
                # 通过独立校验的那一回合，而不是确认回合。
                if round_idx > rec["candidate_round"] and ids & present:
                    rec["status"] = "resolved"
                    rec["resolution_round"] = rec["candidate_round"]
                    rec["resolution_s"] = rec.get("candidate_s")
                    rec["close_reason"] = "新时序通过独立校验并已进入调度状态"
                    rec["history"].append(dict(
                        round=round_idx, at_s=int(now), action="resolved",
                        reason=rec["close_reason"]))
                else:
                    self._close(rec, round_idx, now, "abandoned",
                                "相关子任务已不在可执行时序中，不计为消解")
                continue
            if phase == "verify" and repaired and ids & present:
                rec["candidate_round"] = round_idx
                rec["candidate_s"] = int(now)
                rec["history"].append(dict(round=round_idx, at_s=int(now),
                                           action="candidate",
                                           reason="候选方案通过独立校验，待确认"))

        for rec in self.records.values():
            if (rec["status"] == "open"
                    and rec.get("candidate_round") is None
                    and round_idx - rec["first_round"] > self.budget):
                self._close(rec, round_idx, now, "expired",
                            "超过 %d 回合预算仍未消解" % self.budget)
        self.compute_ms += (time.perf_counter() - started) * 1000.0

    def _close(self, rec: Dict, round_idx: int, now: int, status: str,
               reason: str) -> None:
        rec["status"] = status
        rec["closed_round"] = round_idx
        rec["closed_s"] = int(now)
        rec["close_reason"] = reason
        if status == "resolved":
            rec["resolution_round"] = round_idx
            rec["resolution_s"] = int(now)
        rec["history"].append(dict(round=round_idx, at_s=int(now),
                                   action=status, reason=reason))

    # ------------------------------------------------------------------
    def result(self, now: int) -> Dict:
        round_idx = self.round_of(now)
        records = list(self.records.values())
        # 预算判定：已在 20 回合内消解的冲突直接计入（有完整消解证据）；
        # 尚未解决的冲突必须已观察满 20 回合，才进入验收分母；不足窗口的
        # 单独报告，避免“运行提前结束”被算成未消解。
        eligible = []
        insufficient = []
        for rec in records:
            resolved_in_budget = (
                rec["status"] == "resolved"
                and rec["resolution_round"] is not None
                and rec["resolution_round"] - rec["first_round"] <= self.budget)
            observed = round_idx - rec["first_round"] >= self.budget
            if resolved_in_budget or observed:
                eligible.append(rec)
            else:
                insufficient.append(rec)

        def done_round(rec):
            if rec["status"] == "resolved":
                return rec["resolution_round"]
            if rec["status"] == "open" and rec.get("candidate_round") is not None:
                return rec["candidate_round"]
            return None

        resolved = []
        for rec in eligible:
            round_done = done_round(rec)
            if round_done is not None and round_done - rec["first_round"] <= self.budget:
                resolved.append(rec)
        expired = [rec for rec in eligible if rec["status"] == "expired"]
        abandoned = [rec for rec in eligible
                     if rec["status"] in ("abandoned", "infeasible")]
        total = len(eligible)
        rate = (len(resolved) / float(total)) if total else None
        by_round = {}
        for probe in (1, 5, 10, 20):
            count = sum(1 for rec in eligible
                        if done_round(rec) is not None
                        and done_round(rec) - rec["first_round"] <= probe)
            by_round[str(probe)] = (count / float(total)) if total else None
        by_type = {}
        for kind in TIMING_TYPES:
            items = [rec for rec in eligible if rec["type"] == kind]
            done = [rec for rec in items
                    if done_round(rec) is not None
                    and done_round(rec) - rec["first_round"] <= self.budget]
            by_type[kind] = dict(label=TYPE_LABELS[kind], total=len(items),
                                 resolved=len(done))
        conflicts = []
        for rec in records:
            round_done = done_round(rec)
            status = rec["status"]
            if status == "open" and round_done is not None:
                status = "resolved"
            conflicts.append(dict(
                type=rec["type"], label=TYPE_LABELS.get(rec["type"], rec["type"]),
                subtask_ids=list(rec["subtask_ids"]),
                generation=rec.get("generation", 1),
                first_round=rec["first_round"], first_s=rec["first_s"],
                status=status,
                resolution_round=round_done,
                rounds_used=(None if round_done is None
                             else round_done - rec["first_round"]),
                reason=(rec.get("close_reason") or rec["reason"]),
                action=("resolved" if status == "resolved" else status),
            ))
        return dict(
            metric="resolution_rate_20",
            rate=None if rate is None else round(rate, 4),
            rate_percent=None if rate is None else round(rate * 100.0, 2),
            resolved=len(resolved), total=total,
            no_conflict=not records,
            budget_rounds=self.budget, round_steps=self.round_steps,
            rounds_observed=round_idx,
            by_round=by_round, by_type=by_type,
            expired=len(expired), abandoned=len(abandoned),
            insufficient_window=[rec["key"][0] + ":" + ",".join(rec["subtask_ids"])
                                 for rec in insufficient[:20]],
            compute_ms=round(self.compute_ms, 3),
            observations=self.observations,
            conflicts=conflicts,
        )
