# -*- coding: utf-8 -*-
"""基座 planner_v2 适配器：把统一 Scenario 转成基座对象并跑一次规划。

保留基座语义：
  * 平台能力参数从编成表读取（速度/载荷/传感器/续航画像）；
  * 作业按 ``work`` 与 ``work_rate`` 换算时长；本适配器把 work_rate 固定
    为 1.0、work 取任务 duration_s，使两边的“作业时长”同口径；
  * 电池设为很大的值，只让时间窗/能力/高度/协同约束起作用（基座 battery
    是电量单位，与统一层的 endurance_s 不是同一个量，硬套会得出错误结论）。

已知差异（对比时必须在报告里写明）：
  * 基座计划层不含路径几何，无法做“路径穿障碍”静态校验；
  * 基座目标只有 makespan/energy/dispersion，没有 risk/balanced；
  * 基座是滚动时域规划器，这里用 now=0、足够大的 H 跑单次全量计划。
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

BASE_OBJECTIVES = {"timeliness": "makespan", "energy": "energy"}


class BaseAdapterError(RuntimeError):
    pass


def _first_point(task_target: Dict[str, Any]) -> List[float]:
    from interop.templates import as_point
    if "route" in task_target:
        return list(as_point(task_target["route"][0]))
    if "target_list" in task_target:
        return list(as_point(task_target["target_list"][0]))
    if "point" in task_target:
        return list(as_point(task_target["point"]))
    if "key_point" in task_target:
        return list(as_point(task_target["key_point"]))
    from interop.message import target_point
    return list(target_point(task_target))


def run(scenario, objective: str = "timeliness",
        motion: str = "real") -> Dict[str, Any]:
    if objective not in BASE_OBJECTIVES:
        raise BaseAdapterError(
            "基座 planner_v2 不支持 objective=%r（只有 makespan/energy/dispersion）"
            % objective)
    try:
        import contracts_v2
        import planner_v2
        import fleet
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可读错误
        raise BaseAdapterError("无法导入基座规划器: %s" % exc)

    platforms = []
    for item in scenario.platforms:
        platforms.append(contracts_v2.Platform(
            pid=fleet.pid_of(item.robot_id),
            kind=item.platform_class,
            robot_no=item.robot_id,
            pos=tuple(item.position),
            speed=float(item.speed_mps),
            work_rate=1.0,
            battery=1.0e6,
            payload=float(item.payload),
            sensor=item.sensor,
            can_climb=item.is_air,
            move_cost=float(item.move_cost),
            work_cost=float(item.work_cost),
            ammo=0,
            alive=True,
            pos_topic=fleet.pose_topic_of(item.robot_id),
            yaw=float(item.heading_rad),
        ))

    jobs = []
    for task in scenario.tasks:
        duration = float(task.params.get("duration_s",
                                         task.params.get("hold_duration_s", 120.0)))
        jobs.append(contracts_v2.Job(
            job_id=task.task_id,
            jtype=task.task_type,
            pos=tuple(_first_point(task.target)),
            # 基座按 work/work_rate/crew 折算工期；这里让 crew 台合作时
            # 墙上时间仍等于任务的 duration_s，避免把“人多干得快”的模型
            # 差异混进对比。
            work=duration * max(1, int(task.min_units)),
            window=(int(round(task.window_start_s)), int(round(task.window_end_s))),
            crew=int(task.min_units),
            need_payload=float(task.params.get("payload", 0.0)),
            need_sensor=task.params.get("sensor"),
            altitude=float(task.params.get("altitude_m", 0.0)),
            behavior={},
        ))

    horizon = int(max([t.window_end_s for t in scenario.tasks] + [1.0])) + 10
    started = time.perf_counter()
    plan, events = planner_v2.plan(platforms, jobs, now=0, H=horizon, plan_id=1,
                                   objective=BASE_OBJECTIVES[objective],
                                   motion=motion)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    rows = []
    task_rows = {}
    by_robot = {item.robot_id: item.unit_id for item in scenario.platforms}
    for assignment in plan.assignments:
        job = next((j for j in jobs if j.job_id == assignment.job_id), None)
        task_start = assignment.start
        if motion == "real":
            # real 语义下 assignment.start 是出发时刻，作业开工要加在途
            task_start = assignment.start + assignment.travel
        for pid in assignment.pids:
            platform = next((p for p in platforms if p.pid == pid), None)
            if platform is None:
                continue
            unit_id = by_robot.get(platform.robot_no, platform.pid)
            task_rows.setdefault(assignment.job_id, 0)
            task_rows[assignment.job_id] += 1
            rows.append(dict(
                unit_id=unit_id,
                robot_id=platform.robot_no,
                parent_task_id=assignment.job_id,
                subtask_id="%s#%s" % (assignment.job_id, unit_id),
                task_type=job.jtype if job else "",
                start_s=float(task_start),
                end_s=float(assignment.end),
                travel_s=float(assignment.travel),
                # 基座计划层没有路径几何；用 travel_s×speed 会把转向/加减速
                # 时间当成里程，系统性偏大，所以这里不伪造里程。
                path_length_m=None,
                path=[],
                target={},
                window_start_s=float(job.window[0]) if job else 0.0,
                window_end_s=float(job.window[1]) if job else 0.0,
                status="ASSIGNED",
                coordination=[],
            ))

    unassigned = []
    for job in jobs:
        if task_rows.get(job.job_id, 0) < job.crew:
            reasons = [r for r in plan.rejected if r.get("job_id") == job.job_id]
            unassigned.append(dict(
                subtask_id=job.job_id,
                parent_task_id=job.job_id,
                reason="UNASSIGNED",
                detail="需要 %d 台，实际 %d 台；拒绝样例: %s"
                       % (job.crew, task_rows.get(job.job_id, 0),
                          reasons[0]["reason"] if reasons else "未知"),
            ))

    makespan = max([r["end_s"] for r in rows] or [0.0])
    return dict(
        backend="base_v2",
        objective=objective,
        rows=rows,
        tasks_total=len(jobs),
        tasks_assigned=len({r["parent_task_id"] for r in rows}),
        unassigned=unassigned,
        makespan_s=makespan,
        runtime_ms=elapsed_ms,
        comparison_scope="normalized_planning_experiment",
        normalization={"work_rate": 1.0, "battery": 1.0e6,
                       "work": "duration_s * min_units",
                       "runtime_equivalent": False},
        note=("基座 planner_v2：motion=%s；计划层不含路径几何，"
              "不提供里程；对比实验固定work_rate=1、电量=1000000、"
              "work=duration×crew。此归一化实验不等同于to-v2实际运行，"
              "不能据此宣称运行参数已对齐或执行成功" % motion),
        raw=plan,
        events=events,
    )
