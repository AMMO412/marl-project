# -*- coding: utf-8 -*-
"""统一规划内核：分解 → 能力闸门 → 协同组匈牙利 → 排程 → 事后校验。

六步与 M2 对齐，但修了两处：
  1. ``simultaneous_arrival`` 不再只是标签：协同组内各平台统一到同一个
     开始时刻（同时到达），而不是各自“最早可达”就出发。
  2. 协同组选中的平台在组内全部落实前被预留，别的任务不能抢走，
     否则会出现“匹配成功但执行时平台已被占用”的隐性失败。

输出保持 4.2 的两层：assignments（计划层）与 commands（执行层）。
"""

import heapq
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .assignment import hungarian
from .cost import CostModel
from .errors import PlanningError
from .execution import build_commands
from .gate import gate_platform, reason_to_conflict_type, target_inside_no_go
from .message import target_point, target_points
from .model import (Assignment, Conflict, Metrics, Plan, Platform, Scenario,
                    Subtask)
from .motion import simulate_path
from .routing import NoRouteError, Router
from .templates import decompose
from .validate import validate_plan

EPS = 1e-6
BIG_COST = 1e9
Point = Tuple[float, float]


@dataclass
class _PlatformState:
    platform: Platform
    free_s: float = 0.0
    position: Point = field(default_factory=lambda: (0.0, 0.0))
    used_s: float = 0.0
    heading_rad: float = 0.0
    altitude_m: float = 0.0


def _target_start_units(target: Dict[str, Any]) -> Point:
    if "route" in target:
        return tuple(float(v) for v in target["route"][0])
    if "target_list" in target:
        return tuple(float(v) for v in target["target_list"][0])
    return target_point(target)


def _target_end_units(target: Dict[str, Any]) -> Point:
    if "route" in target:
        return tuple(float(v) for v in target["route"][-1])
    if "target_list" in target:
        return tuple(float(v) for v in target["target_list"][-1])
    return target_point(target)


class Planner(object):
    def __init__(self, scenario: Scenario, objective: str = "timeliness",
                 weights: Optional[Tuple[float, float, float]] = None,
                 assignment_mode: str = "hungarian"):
        if assignment_mode not in ("greedy", "hungarian"):
            raise ValueError("assignment_mode 必须是 greedy 或 hungarian")
        self.scenario = scenario
        self.assignment_mode = assignment_mode
        self.cost_model = CostModel(scenario, objective, weights)
        self.states = {
            p.unit_id: _PlatformState(platform=p, position=p.position,
                                      heading_rad=p.heading_rad,
                                      altitude_m=p.altitude_m,
                                      free_s=float(getattr(p, "busy_until_s", 0.0)))
            for p in scenario.platforms
        }
        self.subtasks = decompose(scenario)
        # 父任务目标本身落在禁入区：整组槽位直接拒绝，不能因为拆分后的
        # 子目标恰好可用就放行。
        self.invalid_tasks = {
            task.task_id for task in scenario.tasks
            if target_inside_no_go(task.target, scenario.constraints)
        }
        self.assignments = []  # type: List[Assignment]
        self.conflicts = []  # type: List[Conflict]
        self.unassigned = []  # type: List[Dict[str, Any]]
        self.explain = []  # type: List[str]
        self.group_start = {}  # type: Dict[str, float]
        self.group_solved = set()
        self.group_assign = {}  # type: Dict[str, Tuple[str, float]]
        self.reserved = {}  # type: Dict[str, str]
        self.processed = set()  # type: set
        self.router = Router(scenario, self.subtasks,
                             risk_weight=self.cost_model.weights[1])

    # ------------------------------------------------------------------
    def plan(self) -> Plan:
        started = _time.perf_counter()
        assigned_by_subtask = {}
        for subtask in self._topological_order():
            if subtask.parent_task_id in self.invalid_tasks:
                self._unassign(subtask, "NO_GO", "父任务目标位于禁入区")
                self._mark_processed(subtask)
                continue
            missing = [d for d in subtask.depends_on
                       if d not in assigned_by_subtask]
            if missing:
                self._unassign(subtask, "DEPENDENCY",
                               "前置子任务未分配: %s" % ", ".join(missing))
                self._mark_processed(subtask)
                continue
            dep_ready = 0.0
            if subtask.depends_on:
                dep_ready = max(assigned_by_subtask[d].end_s
                                for d in subtask.depends_on)

            if (self.assignment_mode == "hungarian"
                    and "simultaneous_arrival" in subtask.coordination
                    and subtask.parent_task_id not in self.group_solved):
                self._solve_group(subtask.parent_task_id, dep_ready)

            best = None
            rejects = {}
            forced = self.group_assign.get(subtask.subtask_id)
            if forced is not None:
                unit_id, group_start = forced
                platform = self._platform(unit_id)
                if platform is not None:
                    candidate, reject = self._evaluate_platform(
                        subtask, platform, dep_ready, start_override=group_start)
                    if candidate is not None:
                        best = candidate
                    else:
                        rejects[unit_id] = reject
            if best is None:
                candidate, extra = self._evaluate_candidates(subtask, dep_ready)
                rejects.update(extra)
                best = candidate

            if best is None:
                reason, detail = self._aggregate_rejections(rejects)
                self._unassign(subtask, reason, detail)
                self._mark_processed(subtask)
                continue

            (cost, unit_id, platform, state, travel_m, travel_s, start_s,
             end_s, route, motion, risk, energy) = best
            assignment = Assignment(
                unit_id=unit_id,
                subtask_id=subtask.subtask_id,
                parent_task_id=subtask.parent_task_id,
                task_type=subtask.task_type,
                target=subtask.target,
                start_s=start_s,
                end_s=end_s,
                window_start_s=subtask.window_start_s,
                window_end_s=subtask.window_end_s,
                depends_on=list(subtask.depends_on),
                coordination=list(subtask.coordination),
                travel_s=travel_s,
                robot_id=platform.robot_id,
                topic=platform.topic,
                path=list(route.path),
                path_length_m=travel_m,
                heading_start=state.heading_rad,
                heading_end=motion.final_heading,
                energy=energy,
                risk=risk,
                altitude_m=state.altitude_m,
            )
            self.assignments.append(assignment)
            assigned_by_subtask[subtask.subtask_id] = assignment
            subtask.status = "ASSIGNED"

            state.free_s = end_s
            state.position = _target_end_units(subtask.target)
            state.heading_rad = motion.final_heading
            state.used_s += travel_s + subtask.duration_s

            self._mark_processed(subtask)
            self.explain.append(
                "%s -> %s: %.1f-%.1f s（移动 %.1fs，%.1f m），风险 %.2f，"
                "能耗 %.2f，代价 %.4f"
                % (subtask.subtask_id, unit_id, start_s, end_s, travel_s,
                   travel_m, risk, energy, cost))

        self.conflicts.extend(
            validate_plan(self.assignments, self.scenario, self.subtasks))
        makespan = max([a.end_s for a in self.assignments] or [0.0])
        detected = len(self.conflicts)
        resolved = sum(1 for c in self.conflicts if c.resolved)
        tasks_total = len(self.scenario.tasks)
        fully = 0
        for task in self.scenario.tasks:
            items = [s for s in self.subtasks
                     if s.parent_task_id == task.task_id]
            if items and all(s.status == "ASSIGNED" for s in items):
                fully += 1
        metrics = Metrics(
            makespan_s=makespan,
            assigned_subtasks=len(self.assignments),
            unassigned_subtasks=len(self.unassigned),
            conflicts_detected=detected,
            conflicts_resolved=resolved,
            resolution_rate=(float(resolved) / detected) if detected else 1.0,
            plan_latency_ms=(_time.perf_counter() - started) * 1000.0,
            tasks_total=tasks_total,
            tasks_fully_assigned=fully,
        )
        generated_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        commands = build_commands(self.assignments, self.scenario)
        return Plan(
            plan_id=self.scenario.plan_id,
            plan_version=1,
            generated_at=generated_at,
            assignments=list(self.assignments),
            commands=commands,
            conflicts=list(self.conflicts),
            unassigned=list(self.unassigned),
            metrics=metrics,
            explain=list(self.explain),
            objective=self.cost_model.objective,
            weights=dict(zip(("time", "risk", "energy"),
                             self.cost_model.weights)),
            objective_metrics=self.cost_model.metrics(self.assignments),
            source_message=self.scenario.message,
            result_status="PLAN_ONLY",
            evidence_source="NO_EXECUTION_EVIDENCE",
            backend="unified",
        )

    # ------------------------------------------------------------------
    def _platform(self, unit_id: str) -> Optional[Platform]:
        return self.scenario.platform_map.get(unit_id)

    def _solve_group(self, parent_id: str, dep_ready: float) -> None:
        group = [s for s in self.subtasks
                 if s.parent_task_id == parent_id
                 and "simultaneous_arrival" in s.coordination]
        self.group_solved.add(parent_id)
        if len(group) <= 1:
            return
        platforms = [p for p in self.scenario.platforms
                     if p.status == "READY"]
        if not platforms:
            return
        matrix = []
        for subtask in group:
            row = []
            for platform in platforms:
                candidate, _ = self._evaluate_platform(
                    subtask, platform, dep_ready)
                row.append(candidate[0] if candidate is not None else BIG_COST)
            matrix.append(row)
        pairs = hungarian(matrix)
        chosen = []
        for row, col in pairs:
            if matrix[row][col] >= BIG_COST:
                continue
            subtask = group[row]
            platform = platforms[col]
            candidate, _ = self._evaluate_platform(subtask, platform, dep_ready)
            chosen.append((subtask, platform, candidate))
        if not chosen:
            self.explain.append("协同组 %s：没有可行的槽位-平台组合" % parent_id)
            return
        # 同时到达：所有槽位统一到最晚的“可开工时刻”
        group_start = max(max(state.free_s + travel_s, dep_ready,
                              subtask.window_start_s)
                          for subtask, _p, (cost, _u, _pl, state, _tm,
                                            travel_s, _s, _e, _r, _mo,
                                            _rk, _en) in chosen)
        for subtask, platform, _candidate in chosen:
            self.group_assign[subtask.subtask_id] = (platform.unit_id, group_start)
            self.reserved[platform.unit_id] = subtask.subtask_id
        self.group_start[parent_id] = group_start
        self.explain.append(
            "协同组 %s：匈牙利匹配 %d/%d 个槽位，统一开始 %.1f s"
            % (parent_id, len(chosen), len(group), group_start))

    def _mark_processed(self, subtask: Subtask) -> None:
        """一个槽位处理完（分配或未分配）就登记；整组处理完再释放预留。

        只在“全部落实”时释放会让某个槽位失败后把平台永久占住，后续任务
        再也用不了；这里按“处理完”而不是“分配成功”释放。
        """
        self.processed.add(subtask.subtask_id)
        parent_id = subtask.parent_task_id
        group = [s for s in self.subtasks if s.parent_task_id == parent_id]
        if not all(s.subtask_id in self.processed for s in group):
            return
        for unit_id in list(self.reserved):
            if self.reserved[unit_id].startswith(parent_id + "-"):
                del self.reserved[unit_id]

    def _evaluate_platform(self, subtask: Subtask, platform: Platform,
                           dep_ready: float,
                           start_override: Optional[float] = None):
        ok, reason, detail = gate_platform(platform, subtask, self.scenario)
        if not ok:
            return None, (reason, detail)

        state = self.states[platform.unit_id]
        scale = self.scenario.cell_size_m
        target_start = _target_start_units(subtask.target)
        target_end = _target_end_units(subtask.target)
        start_m = (state.position[0] * scale, state.position[1] * scale)
        goal_m = (target_start[0] * scale, target_start[1] * scale)
        try:
            route = self.router.route(start_m, goal_m, platform.is_air)
            motion = simulate_path(route.path, platform, state.heading_rad,
                                   max(platform.speed_mps, 0.1))
        except NoRouteError as exc:
            return None, ("NO_ROUTE", str(exc))

        travel_m = route.length_m
        travel_s = motion.duration_s
        start_s = max(state.free_s + travel_s, dep_ready,
                      subtask.window_start_s)
        if start_override is not None:
            start_s = max(start_override, state.free_s + travel_s,
                          subtask.window_start_s)
        end_s = start_s + subtask.duration_s

        if end_s > subtask.window_end_s + EPS:
            return None, ("WINDOW", "结束 %.1fs 超过窗口 %.1fs"
                          % (end_s, subtask.window_end_s))
        if state.used_s + travel_s + subtask.duration_s > platform.endurance_s + EPS:
            return None, ("ENDURANCE", "累计 %.1fs 超过续航 %.1fs"
                          % (state.used_s + travel_s + subtask.duration_s,
                             platform.endurance_s))

        risk = self.cost_model.path_risk(
            platform, route.path, platform.speed_mps, subtask.duration_s,
            (target_start[0] * scale, target_start[1] * scale))
        energy = self.cost_model.energy(platform, travel_m, subtask.duration_s)
        cost = self.cost_model.candidate_cost(end_s, risk, energy)
        return (
            cost, platform.unit_id, platform, state, travel_m, travel_s,
            start_s, end_s, route, motion, risk, energy,
        ), ("OK", "")

    def _evaluate_candidates(self, subtask: Subtask, dep_ready: float):
        best = None
        rejects = {}
        used_units = set()
        if "simultaneous_arrival" in subtask.coordination:
            used_units = {a.unit_id for a in self.assignments
                          if a.parent_task_id == subtask.parent_task_id}
        for platform in self.scenario.platforms:
            owner = self.reserved.get(platform.unit_id)
            if owner is not None and owner != subtask.subtask_id:
                rejects[platform.unit_id] = ("COORDINATION",
                                             "平台已被协同组预留")
                continue
            if platform.unit_id in used_units:
                rejects[platform.unit_id] = ("COORDINATION",
                                             "同一协同组已使用该平台")
                continue
            candidate, reject = self._evaluate_platform(
                subtask, platform, dep_ready)
            if candidate is None:
                rejects[platform.unit_id] = reject
                continue
            if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
                best = candidate
        return best, rejects

    def _aggregate_rejections(self, rejects: Dict[str, Tuple[str, str]]):
        if not rejects:
            return "NO_CAPABILITY", "没有可用平台"
        counts = {}
        for reason, _ in rejects.values():
            counts[reason] = counts.get(reason, 0) + 1
        scheduling = [r for r in ("WINDOW", "ENDURANCE", "COORDINATION")
                      if r in counts]
        if scheduling:
            chosen = scheduling[0]
        else:
            chosen = None
            for reason in ("NO_CAPABILITY", "STATUS", "NO_GO", "NO_ROUTE"):
                if reason in counts:
                    chosen = reason
                    break
            if chosen is None:
                chosen = max(counts, key=counts.get)
        details = []
        for unit_id in sorted(rejects):
            reason, detail = rejects[unit_id]
            if reason == chosen:
                details.append("%s: %s" % (unit_id, detail))
        return chosen, "; ".join(details[:3])

    def _unassign(self, subtask: Subtask, reason: str, detail: str) -> None:
        self.unassigned.append({
            "subtask_id": subtask.subtask_id,
            "parent_task_id": subtask.parent_task_id,
            "task_type": subtask.task_type,
            "reason": reason,
            "detail": detail,
        })
        self.conflicts.append(Conflict(
            conflict_id="CF-%03d" % (len(self.conflicts) + 1),
            type=reason_to_conflict_type(reason),
            subtask_ids=[subtask.subtask_id],
            detected_at_s=0.0,
            action="REPORT_UNRESOLVED",
            resolved=False,
            reason=detail,
        ))
        self.explain.append("%s 未分配: %s (%s)"
                            % (subtask.subtask_id, reason, detail))

    def _topological_order(self) -> List[Subtask]:
        subtask_map = {s.subtask_id: s for s in self.subtasks}
        indegree = {}
        successors = {s.subtask_id: [] for s in self.subtasks}
        for subtask in self.subtasks:
            deps = [d for d in subtask.depends_on if d in subtask_map]
            indegree[subtask.subtask_id] = len(deps)
            for dep_id in deps:
                successors[dep_id].append(subtask.subtask_id)
        heap = []
        for subtask in self.subtasks:
            if indegree[subtask.subtask_id] == 0:
                heapq.heappush(heap, (subtask.priority, subtask.window_end_s,
                                      subtask.subtask_id))
        order = []
        while heap:
            _, _, subtask_id = heapq.heappop(heap)
            order.append(subtask_map[subtask_id])
            for nxt in successors[subtask_id]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    item = subtask_map[nxt]
                    heapq.heappush(heap, (item.priority, item.window_end_s,
                                          item.subtask_id))
        if len(order) != len(self.subtasks):
            remaining = sorted(sid for sid, deg in indegree.items() if deg > 0)
            raise PlanningError("子任务依赖存在环: %s" % ", ".join(remaining))
        return order
