# -*- coding: utf-8 -*-
"""同一输入、同一审计口径下比较 unified / 基座 planner_v2 / M2。

审计只看可比的硬指标：
  * 任务落实数、未分配数、makespan；
  * 时间窗、平台时段重叠、能力、目标禁入区、路径穿禁入区、依赖；
  * 协同组开始时刻是否对齐（单列，不混进硬违规）。

不做的事：不比较能耗/风险绝对值（两边系数不同）、不把运行耗时当任务
完成时长、不拿不同输入的历史结果互相对照。
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from .geometry import path_enters_polygon, point_in_polygon
from .message import target_points
from .model import Scenario
from .scheduler import Planner

BACKENDS = ("unified", "base_v2", "m2")


# ----------------------------------------------------------------------
def _task_map(scenario: Scenario) -> Dict[str, Any]:
    return {t.task_id: t for t in scenario.tasks}


def _scaled_polygon(item: Dict[str, Any], scale: float):
    area = item.get("area")
    polygon = area.get("polygon") if isinstance(area, dict) else area
    if not polygon:
        return None
    return [(float(p[0]) * scale, float(p[1]) * scale) for p in polygon]


def audit(scenario: Scenario, rows: List[Dict[str, Any]],
          backend: str, objective: str, runtime_ms: float,
          unassigned: Optional[List[Dict[str, Any]]] = None,
          extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tasks = _task_map(scenario)
    platforms = scenario.platform_map
    scale = scenario.cell_size_m
    violations = []
    capability_gaps = []

    for row in rows:
        task = tasks.get(row["parent_task_id"])
        platform = platforms.get(row["unit_id"])
        if task is None or platform is None:
            violations.append(dict(type="IDENTITY", detail="未知任务或平台",
                                   subtask_id=row.get("subtask_id")))
            continue
        for code, level in task.required_capabilities.items():
            if int(platform.capabilities.get(code, 0)) < int(level):
                # 基座 middle-demo/v2 契约没有能力编码，只有 payload/sensor/
                # altitude；这条单列为“契约缺口”，不混进算法违规排名。
                capability_gaps.append(dict(
                    type="CAPABILITY_GAP", subtask_id=row.get("subtask_id"),
                    detail="%s 的 %s=%s < %s"
                           % (row["unit_id"], code,
                              platform.capabilities.get(code, 0), level)))
        if (row["start_s"] < row["window_start_s"] - 1e-6
                or row["end_s"] > row["window_end_s"] + 1e-6):
            violations.append(dict(
                type="WINDOW", subtask_id=row.get("subtask_id"),
                detail="%.1f–%.1f 超出 %.1f–%.1f" % (
                    row["start_s"], row["end_s"],
                    row["window_start_s"], row["window_end_s"])))
        for point in target_points(task.target):
            for item in scenario.constraints:
                if item.get("type") != "no_go":
                    continue
                polygon = _scaled_polygon(item, scale)
                if polygon and point_in_polygon(
                        (float(point[0]) * scale, float(point[1]) * scale), polygon):
                    violations.append(dict(
                        type="NO_GO_TARGET", subtask_id=row.get("subtask_id"),
                        detail="目标点在禁入区 %s"
                               % item.get("constraint_id", item.get("source"))))
                    break
        if row.get("path") and not platform.is_air:
            for item in scenario.constraints:
                if item.get("type") != "no_go":
                    continue
                if item.get("applies_to", "ground") not in ("ground", "all"):
                    continue
                polygon = _scaled_polygon(item, scale)
                if polygon and path_enters_polygon(row["path"], polygon):
                    violations.append(dict(
                        type="PATH_NO_GO", subtask_id=row.get("subtask_id"),
                        detail="路径穿过 %s"
                               % item.get("constraint_id", item.get("source"))))
                    break

    # 同机器人时段重叠（含去程）
    by_unit: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_unit.setdefault(row["unit_id"], []).append(row)
    for unit_id, items in by_unit.items():
        items = sorted(items, key=lambda r: (r["start_s"] - r.get("travel_s", 0.0),
                                             r["end_s"]))
        for prev, curr in zip(items, items[1:]):
            if prev["end_s"] > curr["start_s"] - curr.get("travel_s", 0.0) + 1e-6:
                violations.append(dict(
                    type="OVERLAP", subtask_id=curr.get("subtask_id"),
                    detail="%s: %s 与 %s 重叠" % (unit_id,
                                                  prev.get("subtask_id"),
                                                  curr.get("subtask_id"))))

    # 依赖：前置任务全部结束（含在途）后才能开始
    by_task: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_task.setdefault(row["parent_task_id"], []).append(row)
    for task in scenario.tasks:
        for dep_id in task.depends_on:
            dep_rows = by_task.get(dep_id, [])
            if not dep_rows:
                continue
            dep_end = max(r["end_s"] for r in dep_rows)
            for row in by_task.get(task.task_id, []):
                if dep_end > row["start_s"] + 1e-6:
                    violations.append(dict(
                        type="DEPENDENCY", subtask_id=row.get("subtask_id"),
                        detail="前置 %s 结束 %.1f 晚于本任务开始 %.1f"
                               % (dep_id, dep_end, row["start_s"])))

    # 兵力上限：同一任务使用的不同平台数不能超过 4.1 的 max_units
    for task in scenario.tasks:
        if task.max_units is None:
            continue
        units = {r["unit_id"] for r in by_task.get(task.task_id, [])}
        if len(units) > int(task.max_units):
            violations.append(dict(
                type="FORCE_LIMIT", subtask_id=task.task_id,
                detail="任务 %s 用了 %d 台，超过 max_units=%d"
                       % (task.task_id, len(units), int(task.max_units))))

    # 协同组开始时刻（单列）
    unaligned = 0
    for task in scenario.tasks:
        coordination = (task.params or {}).get("coordination") or []
        if isinstance(coordination, str):
            coordination = [coordination]
        if "simultaneous_arrival" not in coordination:
            continue
        group = by_task.get(task.task_id, [])
        starts = [r["start_s"] for r in group]
        if len(starts) > 1 and max(starts) - min(starts) > 1e-3:
            unaligned += 1

    assigned_tasks = len({r["parent_task_id"] for r in rows})
    makespan = max([r["end_s"] for r in rows] or [0.0])
    travel = sum((r.get("path_length_m") or 0.0) for r in rows)
    routes = any(r.get("path") for r in rows)
    result = dict(
        backend=backend,
        objective=objective,
        tasks_total=len(scenario.tasks),
        tasks_assigned=assigned_tasks,
        rows=len(rows),
        makespan_s=round(makespan, 3),
        travel_m=round(travel, 1),
        routes_available=routes,
        unassigned_count=len(unassigned or []),
        unassigned=list(unassigned or []),
        violations=violations,
        violation_count=len(violations),
        capability_gaps=capability_gaps,
        capability_gap_count=len(capability_gaps),
        coordination_unaligned_groups=unaligned,
        runtime_ms=round(runtime_ms, 1),
    )
    if extra:
        result.update(extra)
    return result


# ----------------------------------------------------------------------
def _unified_rows(plan) -> List[Dict[str, Any]]:
    rows = []
    for a in plan.assignments:
        rows.append(dict(
            unit_id=a.unit_id,
            robot_id=a.robot_id,
            parent_task_id=a.parent_task_id,
            subtask_id=a.subtask_id,
            task_type=a.task_type,
            start_s=a.start_s,
            end_s=a.end_s,
            travel_s=a.travel_s,
            path_length_m=a.path_length_m,
            path=list(a.path),
            target=dict(a.target),
            window_start_s=a.window_start_s,
            window_end_s=a.window_end_s,
            status=a.status,
            coordination=list(a.coordination),
        ))
    return rows


def run_backend(scenario: Scenario, backend: str, objective: str) -> Dict[str, Any]:
    if backend == "unified":
        started = time.perf_counter()
        plan = Planner(scenario, objective=objective).plan()
        elapsed = (time.perf_counter() - started) * 1000.0
        rows = _unified_rows(plan)
        return dict(backend="unified", rows=rows,
                    unassigned=[dict(u) for u in plan.unassigned],
                    runtime_ms=elapsed, raw=plan,
                    objective_metrics=dict(plan.objective_metrics or {}),
                    note="interop 统一层：协同组统一开始时刻，路径含避障")
    if backend == "base_v2":
        from .adapters import base_v2
        return base_v2.run(scenario, objective=objective)
    if backend == "m2":
        from .adapters import m2
        return m2.run(scenario, objective=objective)
    raise ValueError("未知后端: %r" % backend)


def compare_scenario(scenario: Scenario, objectives=("timeliness", "energy"),
                     backends=BACKENDS) -> Dict[str, Any]:
    results = []
    for objective in objectives:
        for backend in backends:
            try:
                raw = run_backend(scenario, backend, objective)
                result = audit(scenario, raw["rows"], backend, objective,
                               raw["runtime_ms"], raw.get("unassigned"),
                               extra=dict(note=raw.get("note", ""),
                                          comparison_scope=raw.get("comparison_scope", "offline_planning"),
                                          normalization=raw.get("normalization", {}),
                                          backend_tasks_assigned=raw.get(
                                              "tasks_assigned")))
                metrics = raw.get("objective_metrics") or {}
                result["model_risk"] = metrics.get("total_risk")
                result["model_energy"] = metrics.get("total_energy")
            except Exception as exc:
                result = dict(backend=backend, objective=objective,
                              error="%s: %s" % (type(exc).__name__, exc),
                              tasks_total=len(scenario.tasks),
                              tasks_assigned=0, rows=0, makespan_s=0.0,
                              travel_m=0.0, violation_count=0,
                              violations=[], unassigned_count=0,
                              coordination_unaligned_groups=0,
                              runtime_ms=0.0)
            results.append(result)
    return dict(
        formation_id=scenario.formation_id,
        tasks=len(scenario.tasks),
        platforms=len(scenario.platforms),
        objectives=list(objectives),
        backends=list(backends),
        results=results,
    )


def summarize(comparison: Dict[str, Any]) -> Dict[str, Any]:
    """给出每个 (objective, backend) 的硬指标汇总与同目标排名依据。"""
    best = {}
    for item in comparison["results"]:
        if "error" in item:
            continue
        key = item["objective"]
        rank = (item["violation_count"],
                item.get("capability_gap_count", 0),
                item["tasks_total"] - item["tasks_assigned"],
                item["unassigned_count"],
                item["makespan_s"])
        current = best.get(key)
        if current is None or rank < current[0]:
            best[key] = (rank, item["backend"])
    return {k: v[1] for k, v in best.items()}


def build_markdown(comparisons: List[Dict[str, Any]]) -> str:
    lines = ["# 同输入对比：unified / 基座 planner_v2 / M2", ""]
    lines.append("审计口径：时间窗、平台时段重叠、能力、目标禁入区、路径穿禁入区、"
                 "依赖；协同对齐单列。能耗/风险绝对值不跨后端比较。")
    lines.append("基座结果是调整过电量、效率和工作量的离线对比实验；"
                 "排名仅适用于本表实验设定，不代表同参数运行验证或外部执行。")
    lines.append("")
    for comparison in comparisons:
        lines.append("## %s（%d 平台 / %d 任务）"
                     % (comparison.get("name", comparison["formation_id"]),
                        comparison["platforms"], comparison["tasks"]))
        lines.append("")
        lines.append("| 目标 | 后端 | 落实任务 | 行数 | 未分配 | makespan / s "
                     "| 里程 / m | 模型风险 | 模型能耗 | 硬违规 | 能力缺口 "
                     "| 协同未对齐 | 路径几何 | 规划耗时 / ms |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: "
                     "| ---: | ---: | ---: | ---: | --- | ---: |")
        for item in comparison["results"]:
            if "error" in item:
                lines.append("| %s | %s | - | - | - | - | - | - | - | - | - "
                             "| - | - | - |" % (item["objective"], item["backend"]))
                lines.append("")
                lines.append("> %s：%s" % (item["backend"], item["error"]))
                lines.append("")
                continue
            travel = ("%.0f" % item["travel_m"]) if item.get("routes_available") else "—"
            risk = ("%.2f" % item["model_risk"]
                    if item.get("model_risk") is not None else "—")
            energy = ("%.1f" % item["model_energy"]
                      if item.get("model_energy") is not None else "—")
            lines.append("| %s | %s | %d/%d | %d | %d | %.1f | %s | %s | %s "
                         "| %d | %d | %d | %s | %.0f |"
                         % (item["objective"], item["backend"],
                            item["tasks_assigned"], item["tasks_total"],
                            item["rows"], item["unassigned_count"],
                            item["makespan_s"], travel, risk, energy,
                            item["violation_count"],
                            item.get("capability_gap_count", 0),
                            item["coordination_unaligned_groups"],
                            "有" if item["routes_available"] else "无",
                            item["runtime_ms"]))
        lines.append("")
        for item in comparison["results"]:
            if item.get("normalization"):
                lines.append("- %s / %s：%s" % (item["backend"], item["objective"], item.get("note", "")))
        lines.append("")
        for item in comparison["results"]:
            if item.get("violations"):
                lines.append("<details><summary>%s / %s 的违规明细</summary>"
                             % (item["backend"], item["objective"]))
                lines.append("")
                for violation in item["violations"][:12]:
                    lines.append("- %s：%s" % (violation["type"],
                                               violation["detail"]))
                lines.append("")
                lines.append("</details>")
                lines.append("")
        lines.append("")
    lines.append("## 本轮反复出现的差异（源码可见）")
    lines.append("")
    lines.append("| 后端 | 现象 | 依据 |")
    lines.append("| --- | --- | --- |")
    lines.append("| 基座 planner_v2 | 不读 4.1 的 required_capabilities，"
                 "只看 payload/sensor/altitude | `contracts_v2.check_scenario_v2` "
                 "的平台只允许 robot_no/pos；`planner_v2.feasible` 无能力编码 |")
    lines.append("| 基座 planner_v2 | 排程检查完工截止，但不检查窗口下界 | "
                 "`planner_v2.plan` 只判 `e > window[1]`；对比中出现 112 s 先于 "
                 "120 s 窗口开工 |")
    lines.append("| 基座 planner_v2 | 计划层不含路径几何，无法静态验证避障 | "
                 "`Assignment` 只有 start/end/travel/dur |")
    lines.append("| M2 | 区域/路线拆分段数不受 `max_units` 约束 | "
                 "`templates._decompose_rcn/_decompose_ptl` 只按可拆平台数切分 |")
    lines.append("| M2 | `simultaneous_arrival` 只保证同组不同平台，不保证同时开始 | "
                 "M2 README 的边界自述；对比中协同未对齐组数 > 0 |")
    lines.append("| unified | 严格 schema 0.3、能力闸门、max_units 上限、"
                 "协同组统一开始、路径穿障碍审计 | `interop` 实现 |")
    lines.append("")
    lines.append("## 读法")
    lines.append("")
    lines.append("- 硬违规优先于 makespan：一个更快的计划如果穿建筑/超窗口，不认为更好。")
    lines.append("- 基座计划层没有路径几何，`路径几何=无` 表示无法静态验证避障、"
                 "里程记 `—`；这不是“零里程”，也不能据此判它更省。")
    lines.append("- `能力缺口` 单列：基座 middle-demo/v2 契约没有 4.1 的能力编码，"
                 "只有 payload/sensor/altitude，这一列反映契约差异，不是算法违规。")
    lines.append("- M2 的 `simultaneous_arrival` 只保证同组不同平台，不保证同时开始；"
                 "统一层把开始时刻对齐，所以这一列会不同。")
    lines.append("- 任务拆分超过 `max_units` 计入硬违规（M2 的区域/路线拆分不读该上限）。")
    lines.append("- 能耗/风险是各自模型值，不能跨后端排名；表中的模型风险/能耗"
                 "只用于同一后端切换目标时对照。")
    lines.append("- `compare.json` 里的 best 排序是：硬违规 → 能力缺口 → 未落实任务 "
                 "→ 未分配 → makespan。也就是“先满足 4.1 契约，再比快慢”；"
                 "只看 makespan 的结论会不同，报告里同时给出了原始列。")
    lines.append("")
    return "\n".join(lines)
