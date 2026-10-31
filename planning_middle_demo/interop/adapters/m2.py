# -*- coding: utf-8 -*-
"""M2 编队规划器适配器：只读导入对方工程，跑同一份统一 Scenario。

M2 是独立工程，不在本仓库内；默认从环境变量 ``M2_ROOT`` 读取，
缺省 ``D:/Desktop/M2``。本适配器不修改 M2 源码，只把统一 Scenario
翻译成 M2 的 Platform/Task/Scenario 对象，再把结果转回统一行格式。
"""

import importlib
import os
import sys
import time
from typing import Any, Dict, List, Optional

DEFAULT_M2_ROOT = os.environ.get("M2_ROOT", r"D:/Desktop/M2")


class M2AdapterError(RuntimeError):
    pass


def _load_modules(root: Optional[str] = None):
    root = root or DEFAULT_M2_ROOT
    if not os.path.isdir(os.path.join(root, "formation_planner")):
        raise M2AdapterError("找不到 M2 工程: %s（可用环境变量 M2_ROOT 指定）" % root)
    inserted = False
    if root not in sys.path:
        sys.path.insert(0, root)
        inserted = True
    try:
        model = importlib.import_module("formation_planner.model")
        scheduler = importlib.import_module("formation_planner.scheduler")
    except Exception as exc:
        raise M2AdapterError("无法导入 M2 formation_planner: %s" % exc)
    finally:
        if inserted:
            sys.path.pop(0)
    return model, scheduler


def run(scenario, objective: str = "timeliness",
        root: Optional[str] = None) -> Dict[str, Any]:
    model, scheduler = _load_modules(root)

    platforms = []
    for item in scenario.platforms:
        platforms.append(model.Platform(
            unit_id=item.unit_id,
            platform_type=item.platform_type or item.platform_class,
            capabilities=dict(item.capabilities),
            position=tuple(item.position),
            speed_mps=float(item.speed_mps),
            endurance_s=float(item.endurance_s),
            status=item.status,
            platform_class=item.platform_class,
            robot_id=item.robot_id,
            heading_rad=float(item.heading_rad),
            altitude_m=float(item.altitude_m),
            vertical_speed_mps=float(item.vertical_speed_mps),
        ))

    tasks = []
    for task in scenario.tasks:
        tasks.append(model.Task(
            task_id=task.task_id,
            task_type=task.task_type,
            priority=int(task.priority),
            target=dict(task.target),
            window_start_s=float(task.window_start_s),
            window_end_s=float(task.window_end_s),
            depends_on=list(task.depends_on),
            params=dict(task.params),
            required_capabilities=dict(task.required_capabilities),
            min_units=int(task.min_units),
            max_units=(None if task.max_units is None else int(task.max_units)),
            allow_split=bool(task.allow_split),
            description=task.description,
        ))

    m2_scenario = model.Scenario(
        formation_id=scenario.formation_id,
        platforms=platforms,
        groups=list(scenario.groups),
        constraints=[dict(item) for item in scenario.constraints],
        tasks=tasks,
        cell_size_m=float(scenario.cell_size_m),
        plan_id=scenario.plan_id,
        schema_version="0.3",
        meta=dict(scenario.meta),
        message=dict(scenario.message or {}),
    )

    started = time.perf_counter()
    try:
        plan = scheduler.Planner(m2_scenario, objective=objective).plan()
    except Exception as exc:
        raise M2AdapterError("M2 规划失败: %s" % exc)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    scale = float(scenario.cell_size_m)
    rows = []
    for assignment in plan.assignments:
        rows.append(dict(
            unit_id=assignment.unit_id,
            robot_id=assignment.robot_id,
            parent_task_id=assignment.parent_task_id,
            subtask_id=assignment.subtask_id,
            task_type=assignment.task_type,
            start_s=float(assignment.start_s),
            end_s=float(assignment.end_s),
            travel_s=float(assignment.travel_s),
            path_length_m=float(assignment.path_length_m),
            path=[(float(x) * scale, float(y) * scale)
                  for x, y in assignment.path],
            target=dict(assignment.target or {}),
            window_start_s=float(assignment.window_start_s),
            window_end_s=float(assignment.window_end_s),
            status=assignment.status,
            coordination=list(assignment.coordination or []),
        ))

    tasks_total = len(tasks)
    tasks_assigned = len({r["parent_task_id"] for r in rows})
    return dict(
        backend="m2",
        objective=objective,
        rows=rows,
        tasks_total=tasks_total,
        tasks_assigned=tasks_assigned,
        unassigned=[dict(item) for item in plan.unassigned],
        makespan_s=float(plan.metrics.makespan_s),
        runtime_ms=elapsed_ms,
        objective_metrics=dict(plan.objective_metrics or {}),
        note=("M2 formation_planner：路径按 A*（地面）/直线（空中），"
              "travel 含转向耗时；simultaneous_arrival 只保证同组不同平台，"
              "不强制开始时刻对齐"),
        raw=plan,
    )
