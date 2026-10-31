# -*- coding: utf-8 -*-
"""把统一规划层接到基座运行链：4.1 输入驱动 CoordinatorV2。

对接方式不是把 4.2 的 cmd_vel 硬塞进协调器，而是**换规划引擎、不换运行
语义**：

  CoordinatorV2._replan()
       ├─ 默认：planner_v2.plan()        （基座原规划器）
       └─ 本模块：InteropPlanner(...)    （统一层，4.1/4.2 契约）

InteropPlanner 每次滚动规划时：
  1. 用协调器的当前平台位姿/存活状态、待派作业和剩余工作量，快照一份
     interop Scenario；
  2. 调 interop.scheduler.Planner（能力闸门 + 协同匈牙利 + 风险 A* + 三目标）；
  3. 把“槽位分配”折回基座的 job 级 Assignment（pids/start/end/travel/dur），
     交给 CoordinatorV2 下发、投影、收反馈。

职责边界：
  * 只接管**规划**；指令下发、反馈核对、取消/重试、工作台仍是基座的；
  * 含 T-ASL/突击/效果判定的场景会被明确拒绝（`UnsupportedFeature`），
    不降级、不猜语义；
  * 基座 job 的 work/work_rate 进度模型保持不变，统一层只负责“谁、何时、
    从哪条路去”。
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from .errors import UnsupportedFeature, WireError
from .message import (CLASS_BASE_PROFILE, CLASS_CAPABILITIES, parse_message,
                      parse_formation)
from .model import Platform, Scenario, Task
from .scheduler import Planner

# 基座 job 类型 → 4.1 任务类型
V2_JOB_TO_TASK = {
    "patrol": "T-PTL",
    "recon": "T-RCN",
    "blockade": "T-SEC",
    "hold": "T-HLD",
}
ASSAULT_JOB_TYPES = {"assault"}
OBJECTIVE_MAP = {"makespan": "timeliness", "timeliness": "timeliness",
                 "energy": "energy", "dispersion": "balanced",
                 "risk": "risk", "balanced": "balanced"}


class InteropPlannerError(RuntimeError):
    pass


def _v2_job_duration(job) -> float:
    """把基座工作量折算成单次作业时长（秒/步）。

    基座 work 是工作量单位；本适配器约定 1 台平台 1 步贡献 1 工作量
    （与 to-v2 的 work=duration×crew 对应），所以时长 = 剩余工作量 / crew。
    """
    crew = max(1, int(getattr(job, "crew", 1)))
    remain = max(0.0, float(job.work) - float(getattr(job, "progress", 0.0)))
    return max(1.0, math.ceil(remain / crew))


def _platform_from_v2(item) -> Platform:
    import fleet
    if isinstance(item, dict):
        robot_no = int(item["robot_no"])
        pos = item.get("pos") or [0.0, 0.0]
    else:
        robot_no = int(item.robot_no)
        pos = item.pos or [0.0, 0.0]
    kind = fleet.kind_of(robot_no)
    params = fleet.PLANNING_PARAMS[kind]
    profile = CLASS_BASE_PROFILE[kind]
    caps = dict(CLASS_CAPABILITIES[kind])
    altitude = 0.0
    heading = 0.0
    return Platform(
        unit_id=fleet.pid_of(robot_no), robot_id=robot_no, platform_class=kind,
        position=(float(pos[0]), float(pos[1])),
        speed_mps=float(params["speed"]), endurance_s=1.0e9,
        capabilities=caps, status="READY",
        # v2 场景里没有“平台类参数”，只能按编成表暂定值；
        # 统一层的速度/续航闸门对这类导出的场景不作强约束。
        platform_type=kind.lower(), heading_rad=heading, altitude_m=altitude,
        vertical_speed_mps=3.0 if kind in ("PLANE", "WING") else 0.0,
        payload=float(params["payload"]), sensor=str(params["sensor"]),
        battery=1.0e9, work_rate=1.0,
        move_cost=float(profile["move_cost"]),
        work_cost=float(profile["work_cost"]),
    )


def _task_from_v2_job(job) -> Task:
    jtype = job.jtype if hasattr(job, "jtype") else job.get("jtype")
    if jtype in ASSAULT_JOB_TYPES:
        raise UnsupportedFeature(
            "基座作业 %s 是 assault（机动突击/效果判定），统一层不含 T-ASL、"
            "攻击阵位与 fires；请继续用 base 规划器，或改用中性任务场景。"
            % (job.job_id if hasattr(job, "job_id") else job.get("job_id")))
    task_type = V2_JOB_TO_TASK.get(jtype)
    if task_type is None:
        raise UnsupportedFeature("无法把基座作业类型 %r 映射到 4.1 中性任务" % jtype)
    job_id = job.job_id if hasattr(job, "job_id") else job["job_id"]
    pos = job.pos if hasattr(job, "pos") else job["pos"]
    window = job.window if hasattr(job, "window") else job["window"]
    crew = max(1, int(job.crew if hasattr(job, "crew") else job["crew"]))
    duration = _v2_job_duration(job)
    target = {"target_list": [[float(pos[0]), float(pos[1])]]} \
        if task_type == "T-RCN" else {"point": [float(pos[0]), float(pos[1])]}
    return Task(
        task_id=job_id, task_type=task_type, priority=1, target=target,
        window_start_s=float(window[0]), window_end_s=float(window[1]),
        required_capabilities={}, min_units=crew, max_units=crew,
        params=dict(duration_s=duration, hold_duration_s=duration,
                    slots=crew,
                    coordination=(["simultaneous_arrival"] if crew > 1 else [])),
        description="由基座 middle-demo/v2 作业映射",
    )


def scenario_from_v2(data: Dict[str, Any]) -> Scenario:
    """把 middle-demo/v2 场景转成统一 Scenario。

    优先读 `_meta.interop`（由 `to-v2` 写入的原始 4.1 消息/编成表）；
    没有时按 job.type 做中性映射，遇到 assault 直接拒绝。
    """
    meta = data.get("_meta") or {}
    bundle = meta.get("interop") if isinstance(meta, dict) else None
    if isinstance(bundle, dict) and bundle.get("message") and bundle.get("formation"):
        return parse_message(bundle["message"], bundle["formation"])

    from contracts_v2 import build_jobs, build_platforms
    platforms = [_platform_from_v2(p) for p in build_platforms(data)]
    tasks = [_task_from_v2_job(j) for j in build_jobs(data)]
    return Scenario(
        formation_id="V2-%s" % (meta.get("source") if isinstance(meta, dict)
                                else "SCENARIO"),
        platforms=platforms, tasks=tasks,
        constraints=list(meta.get("constraints") or [])
        if isinstance(meta, dict) else [],
        meta={"cell_size_m": 1.0, "plan_id": "PLAN-INTEROP-V2",
              "grid_cell_m": 2.0, "grid_margin_m": 1.0},
        message={"schema_version": "0.3", "message_id": "MSG-FROM-V2",
                 "issued_at": "1970-01-01T00:00:00Z", "source": "UPPER"},
        cell_size_m=1.0, plan_id="PLAN-INTEROP-V2",
    )


def _sec_behavior_params(task: Task) -> Optional[Dict[str, Any]]:
    """T-SEC → 基座行为层参数（区域封控语义，1028 §2.2）。

    统一层负责"谁守哪段、谁当门哨、谁当机动组"；执行层要复现同一条边界，
    因此把区域、通道、控制等级、交战授权和目标时间线显式交给行为层，
    不让它自己猜。缺 area 的旧样例不注入，行为层保持原样。
    """
    if task.task_type != "T-SEC":
        return None
    from .message import target_point
    area = None
    for key in ("area", "defense_area", "sector"):
        if key in task.target:
            area = task.target[key]
            break
    if area is None:
        return None
    params = task.params
    out = dict(area=area)
    for key in ("gates", "control_level", "engagement_authority",
                "control_objective", "sensor_radius_m", "standoff_m",
                "warn_range_m", "intercept_standoff_m", "intercept_post",
                "reserve_post", "intruders", "max_leak_rate", "rotation_s",
                "occupancy_tolerance_s", "boundary_sample_m"):
        if key in params:
            out[key] = params[key]
    out["roles"] = params.get("roles") or {}
    out["duration_s"] = float(params.get(
        "hold_duration_s", params.get("duration_s", 600.0)))
    out["site"] = list(target_point(task.target))
    return out


def to_v2_dict(scenario: Scenario, raw_message: Optional[Dict[str, Any]] = None,
               raw_formation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一 Scenario → 基座可执行的 middle-demo/v2 场景。

    `_meta.interop` 保留原始 4.1 消息与编成表，运行时可原样还原能力、
    障碍和任务语义，不再靠猜。
    """
    jobs = []
    for task in scenario.tasks:
        from .message import target_point
        duration = float(task.params.get("duration_s",
                                         task.params.get("hold_duration_s", 120.0)))
        job = dict(
            job_id=task.task_id,
            pos=list(target_point(task.target)),
            work=duration * max(1, int(task.min_units)),
            window=[int(round(task.window_start_s)),
                    int(round(task.window_end_s))],
            crew=int(task.min_units),
            need_payload=float(task.params.get("payload", 0.0)),
            need_sensor=task.params.get("sensor"),
            altitude=float(task.params.get("altitude_m", 0.0)),
            _task_type=task.task_type,
            _target=task.target,
        )
        behavior = _sec_behavior_params(task)
        if behavior is not None:
            # 运行视图的作业参数（非 4.1 契约字段，只给基座行为层读）。
            job["_behavior"] = behavior
        jobs.append(job)
    horizon = int(max([t.window_end_s for t in scenario.tasks] + [1.0])) + 10
    interop_meta = {"schema_version": "0.3", "authoritative": False,
                    "role": "runtime-view", "note":
                    "v2 字段是运行替身视图；能力/障碍/阵位语义以 bundle 内"
                    "原始 4.1 消息与编成表为准"}
    if raw_message is not None:
        interop_meta["message"] = raw_message
    if raw_formation is not None:
        interop_meta["formation"] = raw_formation
    return {
        "protocol": "middle-demo/v2",
        "objective": "makespan",
        "H": horizon,
        "K": 8,
        "_meta": {
            "source": "interop 4.1 运行视图（不是无损旧场景转换）",
            "message": dict(scenario.message or {}),
            "cell_size_m": scenario.cell_size_m,
            "formula": "job.work=duration_s×crew；统一层负责规划，基座负责运行",
            "interop": interop_meta,
        },
        "platforms": [dict(robot_no=p.robot_id,
                           pos=[p.position[0], p.position[1]],
                           _platform_class=p.platform_class)
                      for p in scenario.platforms],
        "jobs": jobs,
    }


def nav_from_scenario(scenario: Scenario, margin: float = 40.0,
                      radius: float = 1.5, resolution: float = 1.0):
    """用 4.1 编成表的 no_go 约束构造基座静态地图（NavMap）。

    融合层的中性样例不写 ``_meta.sdf``，基座 ``city_nav.build_nav`` 会退到
    simple_city 的世界坐标，等于用错地图。这里改为**只用权威输入**：
    平台与任务几何定边界，编成表的 ``no_go`` 约束当障碍，不解析 SDF、
    不猜坐标。范围只包住本次作业区，A* 栅格因此保持 1 m 级而不爆内存。
    """
    import city_nav

    points = [tuple(p.position) for p in scenario.platforms]
    for task in scenario.tasks:
        for key in ("area", "defense_area", "sector", "patrol_area"):
            value = task.target.get(key)
            if value is None:
                continue
            polygon = value.get("polygon") if isinstance(value, dict) else value
            try:
                points.extend((float(p[0]), float(p[1])) for p in polygon)
            except (TypeError, ValueError, IndexError):
                pass
        for key in ("gates", "intruders", "entry_points", "defense_positions",
                    "posts", "intercept_post", "reserve_post"):
            values = task.params.get(key) or []
            if isinstance(values, dict):
                values = [values]
            for item in values if isinstance(values, (list, tuple)) else []:
                if isinstance(item, dict):
                    for field in ("point", "start", "goal"):
                        if field in item:
                            try:
                                points.append((float(item[field][0]),
                                               float(item[field][1])))
                            except (TypeError, ValueError, IndexError):
                                pass
                else:
                    try:
                        points.append((float(item[0]), float(item[1])))
                    except (TypeError, ValueError, IndexError):
                        pass
        try:
            from .message import target_points
            points.extend(target_points(task.target))
        except Exception:      # 几何不可解析时不影响地图构造
            pass
    if not points:
        raise ValueError("场景里没有可用于确定封控地图的点")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bounds = [min(xs) - margin, min(ys) - margin,
              max(xs) + margin, max(ys) + margin]
    obstacles = []
    for item in scenario.constraints:
        if item.get("type") != "no_go":
            continue
        area = item.get("area") or {}
        polygon = area.get("polygon") if isinstance(area, dict) else area
        if not polygon:
            continue
        obstacles.append(dict(id=item.get("constraint_id"),
                              polygon=[(float(p[0]), float(p[1])) for p in polygon]))
    return city_nav.NavMap(bounds, obstacles, radius=radius,
                           resolution=resolution)


class InteropPlanner(object):
    """CoordinatorV2 的可插拔规划器：返回 (planner_v2.Plan, events)。"""

    name = "interop"

    def __init__(self, scenario: Scenario, objective: str = "makespan",
                 data: Optional[Dict[str, Any]] = None):
        self.scenario = scenario
        self.data = data or {}
        self.objective = OBJECTIVE_MAP.get(objective, "timeliness")

    # ------------------------------------------------------------------
    def _snapshot(self, coord) -> Scenario:
        """用协调器的运行时状态做一份规划快照。"""
        import fleet
        platforms = []
        for item in self.scenario.platforms:
            live = coord.platforms.get(fleet.pid_of(item.robot_id))
            platform = Platform(**{**item.__dict__})
            if live is not None:
                platform.position = (float(live.pos[0]), float(live.pos[1]))
                platform.heading_rad = float(getattr(live, "yaw", 0.0))
                platform.status = "READY" if getattr(live, "alive", True) else "LOST"
                # 4.1 编成表是速度/续航的权威来源；基座 v2 场景只带 robot_no，
                # build_platforms 会退回 fleet 默认速度（0.8 m/s 等），和 4.1 的
                # 8/25/30 m/s 不一致。运行适配器把权威参数同步给协调器，逐步
                # 运动的到达时刻才与计划同源。
                live.speed = float(item.speed_mps)
                live.work_rate = float(item.work_rate)
                live.battery = max(float(live.battery), 1.0e6)
                live.can_climb = bool(item.is_air)
            # 在途指令把平台占到 expected_end；重规划必须把它当“最早可用时刻”，
            # 否则会把新作业排给正在执行旧作业的平台，下发时又被协调器挡回。
            command_id = coord.platform_cmd.get(fleet.pid_of(item.robot_id))
            command = coord.active.get(command_id) if command_id else None
            platform.busy_until_s = (float(command.expected_end_sim_s)
                                     if command is not None else 0.0)
            platforms.append(platform)

        tasks = []
        for task in self.scenario.tasks:
            job = coord.jobs.get(task.task_id)
            if job is None or job.status != "pending":
                continue   # 已在途/已完成/已失败的作业不在本层重排
            # 依赖未完成：本轮跳过，等前置作业成功后的下一次滚动再排。
            if any(coord.jobs.get(d) is None
                   or coord.jobs[d].status != "succeeded"
                   for d in task.depends_on):
                continue
            remain = max(0.0, float(job.work) - float(job.progress))
            if remain <= 0:
                continue
            # 使用“统一层上一次给这个作业定的总量”，避免基座 work 被按
            # 参与台数改写后，滚动重规划把剩余时长越算越大。
            total = float(getattr(job, "_interop_total", job.work)) or 1.0
            scale = max(0.0, min(1.0, (total - float(job.progress)) / total))
            params = dict(task.params)
            for key in ("duration_s", "hold_duration_s"):
                if key in params:
                    params[key] = max(1.0, float(params[key]) * scale)
            # 基座作业是“一台次 crew 同时干一个活”，没有“同一作业拆成多段
            # 串行槽位”的表达。运行适配器因此把所有槽位对齐为同时开始：
            # 分组后的 start/end 才是一个真实作业区间，而不是把先后几段
            # 拼成一段超长作业。
            coordination = params.get("coordination") or []
            if isinstance(coordination, str):
                coordination = [coordination]
            params["coordination"] = list(dict.fromkeys(
                list(coordination) + ["simultaneous_arrival"]))
            tasks.append(Task(
                task_id=task.task_id, task_type=task.task_type,
                priority=task.priority, target=task.target,
                window_start_s=max(task.window_start_s, float(coord.now)),
                window_end_s=task.window_end_s,
                required_capabilities=dict(task.required_capabilities),
                min_units=task.min_units, max_units=task.max_units,
                depends_on=[], params=params,
                allow_split=task.allow_split,
                description=task.description,
            ))
        return Scenario(
            formation_id=self.scenario.formation_id, platforms=platforms,
            tasks=tasks,
            constraints=[dict(c) for c in self.scenario.constraints],
            groups=list(self.scenario.groups), meta=dict(self.scenario.meta),
            message=dict(self.scenario.message or {}),
            cell_size_m=self.scenario.cell_size_m,
            plan_id=self.scenario.plan_id, schema_version="0.3",
        )

    # ------------------------------------------------------------------
    def __call__(self, coord, now):
        import fleet
        import planner_v2
        snapshot = self._snapshot(coord)
        plan = Planner(snapshot, objective=self.objective).plan()
        robot_of = {p.unit_id: p.robot_id for p in snapshot.platforms}
        assignments = []
        rejected = []
        by_task = {}
        for item in plan.assignments:
            by_task.setdefault(item.parent_task_id, []).append(item)
        for task in snapshot.tasks:
            job = coord.jobs[task.task_id]
            items = by_task.get(task.task_id, [])
            pids = []
            roles = {}
            for item in sorted(items, key=lambda a: a.start_s):
                pid = fleet.pid_of(robot_of[item.unit_id])
                if pid not in pids:
                    pids.append(pid)
                if getattr(item, "role", ""):
                    roles[pid] = item.role
            if not items or len(pids) < int(job.crew):
                reasons = [u["reason"] for u in plan.unassigned
                           if u["parent_task_id"] == task.task_id]
                rejected.append(dict(
                    job_id=task.task_id,
                    reason="融合层未凑齐兵力(%d/%d)%s"
                           % (len(pids), job.crew,
                              ("：" + reasons[0]) if reasons else "")))
                continue
            orig_start = min(item.start_s for item in items)
            duration = max(item.end_s for item in items) - orig_start
            travel = max(item.travel_s for item in items)
            start_task = max(float(coord.now), orig_start)
            if coord.motion == "real":
                # 基座 real 语义：start 是出发时刻；到 now 才发令出发
                start_task = max(start_task, float(coord.now) + travel)
                start = start_task - travel
            else:
                start = start_task
            end = start_task + duration
            # 基座的进度模型按“每台成员每步 work_rate 工作量”累计；统一层按
            # 槽位时长排程。让 work = 时长 × 成员 work_rate 之和，运行时进度
            # 速度与计划时长同口径，不会出现“计划 150 s、实际 75 s 完成”或
            # 偏差检测反复触发重规划。
            rate = sum(float(coord.platforms[pid].work_rate) for pid in pids)
            job._interop_total = max(1.0, duration * max(rate, 1e-6))
            job.work = max(float(job.progress) + 1e-6, job._interop_total)
            # 计划角色随指令下发到执行层（边界段/门哨/机动组），使"守哪一段"
            # 在计划与执行两份数据里对得上；执行层只把角色当建议，仍按在位
            # 几何自行复核。
            if roles:
                job._interop_roles = dict(roles)
            assignments.append(planner_v2.Assignment(
                job_id=task.task_id, pids=pids, start=int(round(max(0.0, start))),
                end=int(round(end)), travel=int(round(travel)),
                dur=int(round(end - start_task)), seq=int(round(start_task)),
                coord="interop"))
        for task in snapshot.tasks:
            if task.task_id not in by_task and not any(
                    r["job_id"] == task.task_id for r in rejected):
                rejected.append(dict(job_id=task.task_id, reason="融合层未分配"))
        base_plan = planner_v2.Plan(
            plan_id=coord.plan_id, created_at=now, horizon=coord.H,
            objective=coord.objective, rule_version="interop-1.0",
            assignments=assignments, rejected=rejected)
        events = [dict(kind="interop_plan", n=len(assignments),
                       makespan=round(plan.metrics.makespan_s, 1),
                       unassigned=plan.metrics.unassigned_subtasks,
                       objective=self.objective)]
        # 让基座报告把“结构性凑不齐兵力”标成 need_report，而不是只留一条
        # 每轮重复的 rejected 文本。
        for item in rejected:
            events.append(dict(kind="resolved", job_id=item["job_id"],
                               by="report", need_report=True,
                               note=item["reason"]))
        return base_plan, events


def planner_from_v2(data: Dict[str, Any], objective: Optional[str] = None):
    """给 run_demo_v2 / 工作台用的工厂。"""
    scenario = scenario_from_v2(data)
    return InteropPlanner(scenario, objective=objective
                          or data.get("objective", "makespan"), data=data)
