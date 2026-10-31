# -*- coding: utf-8 -*-
"""计划的事后校验：依赖、重叠、时间窗、续航、能力、禁入区、路径穿障碍、
协同组是否真的同时开始。

与 M2 相比补了两项：
  * 路径穿禁入区（M2 只在 A* 里绕，事后不查；基座 planner_v2 完全不建图）；
  * ``simultaneous_arrival`` 的开始时刻对齐（M2 只检查“同组不同平台”，
    不检查时间是否一致）。
"""

from typing import Dict, List

from .geometry import path_enters_polygon
from .gate import has_capabilities, target_inside_no_go
from .model import Assignment, Conflict, Scenario, Subtask

EPS = 1e-6


class _ConflictIds(object):
    def __init__(self):
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return "CF-V-%03d" % self.n


def _conflict(ids, ctype, subtask_ids, reason, detected_at_s=0.0):
    return Conflict(
        conflict_id=ids.next(),
        type=ctype,
        subtask_ids=list(subtask_ids),
        detected_at_s=float(detected_at_s),
        action="REPORT_UNRESOLVED",
        resolved=False,
        reason=reason,
    )


def validate_plan(assignments: List[Assignment], scenario: Scenario,
                  subtasks: List[Subtask]) -> List[Conflict]:
    ids = _ConflictIds()
    conflicts = []
    platforms = scenario.platform_map
    subtask_map = {s.subtask_id: s for s in subtasks}
    assignment_map = {a.subtask_id: a for a in assignments}

    for a in assignments:
        platform = platforms.get(a.unit_id)
        if platform is None:
            conflicts.append(_conflict(ids, "CAPABILITY", [a.subtask_id],
                                       "平台 %s 不存在" % a.unit_id))
            continue
        subtask = subtask_map.get(a.subtask_id)
        if subtask is None:
            conflicts.append(_conflict(ids, "DEPENDENCY", [a.subtask_id],
                                       "子任务 %s 不在分解结果中" % a.subtask_id))
            continue
        if not has_capabilities(platform, subtask.required_capabilities):
            conflicts.append(_conflict(
                ids, "CAPABILITY", [a.subtask_id],
                "平台 %s 能力不满足 %s" % (a.unit_id,
                                           subtask.required_capabilities)))
        if a.start_s < a.window_start_s - EPS or a.end_s > a.window_end_s + EPS:
            conflicts.append(_conflict(
                ids, "WINDOW", [a.subtask_id],
                "子任务时间 %.1f-%.1f 超出窗口 %.1f-%.1f"
                % (a.start_s, a.end_s, a.window_start_s, a.window_end_s)))
        for dep_id in a.depends_on:
            dep = assignment_map.get(dep_id)
            if dep is None:
                conflicts.append(_conflict(ids, "DEPENDENCY",
                                           [a.subtask_id, dep_id],
                                           "前置子任务 %s 未分配" % dep_id))
            elif dep.end_s > a.start_s + EPS:
                conflicts.append(_conflict(
                    ids, "DEPENDENCY", [a.subtask_id, dep_id],
                    "前置 %s 结束 %.1f 晚于后继开始 %.1f"
                    % (dep_id, dep.end_s, a.start_s)))
        if target_inside_no_go(subtask.target, scenario.constraints):
            conflicts.append(_conflict(ids, "CONSTRAINT", [a.subtask_id],
                                       "任务目标位于禁入区"))
        # 路径穿禁入区：只对地面平台检查（空中按直线航路，不做地面绕行）
        if not platform.is_air and a.path:
            for item in scenario.constraints:
                if item.get("type") != "no_go":
                    continue
                if item.get("applies_to", "ground") not in ("ground", "all"):
                    continue
                area = item.get("area")
                polygon = area.get("polygon") if isinstance(area, dict) else area
                if not polygon:
                    continue
                scaled = [(float(p[0]) * scenario.cell_size_m,
                           float(p[1]) * scenario.cell_size_m) for p in polygon]
                if path_enters_polygon(a.path, scaled):
                    conflicts.append(_conflict(
                        ids, "CONSTRAINT", [a.subtask_id],
                        "路径穿过禁入区 %s" % item.get("constraint_id",
                                                      item.get("source", "no_go"))))
                    break

    # 同一平台的时间占用重叠（含去程）
    by_unit = {}  # type: Dict[str, List[Assignment]]
    for a in assignments:
        by_unit.setdefault(a.unit_id, []).append(a)
    for unit_id, items in by_unit.items():
        items = sorted(items, key=lambda x: (x.start_s - x.travel_s, x.end_s))
        for prev, curr in zip(items, items[1:]):
            if prev.end_s > curr.start_s - curr.travel_s + EPS:
                conflicts.append(_conflict(
                    ids, "RESOURCE_OVERLAP",
                    [prev.subtask_id, curr.subtask_id],
                    "平台 %s 的 %s 与 %s 时段重叠"
                    % (unit_id, prev.subtask_id, curr.subtask_id),
                    detected_at_s=curr.start_s - curr.travel_s))

    # 协同组：必须不同平台，且开始时刻对齐（同时到达）
    sim_groups = {}
    for a in assignments:
        if "simultaneous_arrival" in a.coordination:
            sim_groups.setdefault(a.parent_task_id, []).append(a)
    for parent_id, items in sim_groups.items():
        units = [a.unit_id for a in items]
        if len(units) != len(set(units)):
            conflicts.append(_conflict(
                ids, "COORDINATION", [a.subtask_id for a in items],
                "协同组 %s 出现同一平台承担多个子任务" % parent_id))
        starts = [a.start_s for a in items]
        if starts and max(starts) - min(starts) > 1e-3:
            conflicts.append(_conflict(
                ids, "COORDINATION", [a.subtask_id for a in items],
                "协同组 %s 未对齐开始时刻：%.2f–%.2f"
                % (parent_id, min(starts), max(starts))))

    used = {}
    for a in assignments:
        used[a.unit_id] = (used.get(a.unit_id, 0.0) + a.travel_s
                           + (a.end_s - a.start_s))
    for unit_id, total in used.items():
        platform = platforms.get(unit_id)
        if platform is not None and total > platform.endurance_s + EPS:
            conflicts.append(_conflict(
                ids, "ENDURANCE", [],
                "平台 %s 累计用时 %.1fs 超过续航 %.1fs"
                % (unit_id, total, platform.endurance_s)))
    return conflicts
