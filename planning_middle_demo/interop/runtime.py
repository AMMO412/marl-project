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
  * T-ASL 由本层分配侦察/突击/评估席位与出发时刻，打击动作、弹药和效果
    判定仍由基座 `behaviors.py` 与评估接口执行；
  * 基座 job 的 work/work_rate 进度模型保持不变，统一层只负责“谁、何时、
    从哪条路去”；T-ASL 的进度按行为阶段计，不改写 work。
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
                 "energy": "energy", "exposure": "exposure",
                 "dispersion": "exposure",
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
        battery=float(params["battery"]), work_rate=1.0,
        move_cost=float(profile["move_cost"]),
        work_cost=float(profile["work_cost"]),
    )


def _asl_task_from_v2_job(job) -> Task:
    """基座 assault 作业 → 4.1 T-ASL 任务（供 interop 规划快照使用）。

    基座 `_behavior` 是执行层的权威参数；这里只抽取规划层需要的部分：
    目标点、兵力、效果参数、侦察/评估席位、几何与时序。打击与判定仍由
    执行层按 `_behavior` 运行。
    """
    bh = dict(getattr(job, "behavior", None) or {})
    job_id = job.job_id if hasattr(job, "job_id") else job["job_id"]
    pos = job.pos if hasattr(job, "pos") else job["pos"]
    window = job.window if hasattr(job, "window") else job["window"]
    crew = max(1, int(job.crew if hasattr(job, "crew") else job["crew"]))
    scout_pid = bh.get("scout_pid")
    assessor_pid = bh.get("assessor_pid")
    execute_deadline = bh.get("execute_deadline")
    execute_deadline = (float(execute_deadline)
                        if execute_deadline is not None
                        and float(execute_deadline) > 0 else None)
    params = dict(
        effect=bh.get("effect_kind") or bh.get("effect") or "damage",
        required_level=float(bh.get("required_level", 6.0)),
        required_duration=float(bh.get("required_duration", 10.0)),
        required_control_s=float(bh.get("required_control_s", 10.0)),
        payload_required=float((bh.get("role_payload") or {}).get(
            "assault", bh.get("assault_payload_required", 4.0))),
        duration_s=float(bh.get("duration_s", 140.0)),
        attack_window=list(bh.get("attack_window") or window),
        scout={"count": 1 if scout_pid else 0,
               "capabilities": {"RCN": 2}, "unit": scout_pid},
        assessor={"count": 1 if assessor_pid else 0,
                  "capabilities": {"RCN": 1}, "unit": assessor_pid},
        staging_center=bh.get("staging_center"),
        objective_radius=float(bh.get("objective_radius", 14.0)),
        observe_radius=float(bh.get("observe_radius", 25.0)),
        observe_angle=float(bh.get("observe_angle", 0.0)),
        assessment_post=bh.get("assessment_post"),
        assessment_delay=float(bh.get("assessment_delay", 0.0)),
        confirmation_deadline=float(bh.get("confirmation_deadline", 120.0)),
        execute_deadline=execute_deadline,
        withdraw=bool(bh.get("withdraw", False)),
        withdraw_point=bh.get("withdraw_point"),
        withdraw_ring=float(bh.get("withdraw_ring", 2.0)),
        withdraw_deadline=float(bh.get("withdraw_deadline", 0.0)),
        target_id=bh.get("target_id") or job_id,
        roe=bh.get("roe"),
        collateral_limit=bh.get("collateral_limit"),
        waves=int(bh.get("waves", 1)),
    )
    params["assault_units"] = max(1, crew - params["scout"]["count"]
                                  - params["assessor"]["count"])
    return Task(
        task_id=job_id, task_type="T-ASL", priority=1,
        target={"point": [float(pos[0]), float(pos[1])]},
        window_start_s=float(window[0]), window_end_s=float(window[1]),
        required_capabilities={}, min_units=crew, max_units=crew,
        params=params, description="由基座 assault 作业映射",
    )


def _task_from_v2_job(job) -> Task:
    jtype = job.jtype if hasattr(job, "jtype") else job.get("jtype")
    if jtype in ASSAULT_JOB_TYPES:
        return _asl_task_from_v2_job(job)
    task_type = V2_JOB_TO_TASK.get(jtype)
    if task_type is None:
        raise UnsupportedFeature("无法把基座作业类型 %r 映射到 4.1 任务" % jtype)
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
    没有时按 job.type 映射；assault 映射为 T-ASL（只取规划需要的参数），
    其余类型映射为对应的中性任务。
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
                "warn_range_m", "warning_response_s", "retreat_clearance_m",
                "intercept_standoff_m", "intercept_post",
                "reserve_post", "intruders", "target_start_mode", "max_leak_rate", "rotation_s",
                "occupancy_tolerance_s", "boundary_sample_m",
                "air_altitude_m", "air_orbit_radius_m", "air_orbit_period_s",
                "air_speed_mps", "air_capabilities", "air_unit"):
        if key in params:
            out[key] = params[key]
    out["roles"] = params.get("roles") or {}
    out["duration_s"] = float(params.get(
        "hold_duration_s", params.get("duration_s", 600.0)))
    out["site"] = list(target_point(task.target))
    return out


def _hld_behavior_params(task: Task) -> Optional[Dict[str, Any]]:
    """T-HLD → 基座行为层参数（要点坚守语义，1028 §2.5）。

    统一层回答"谁去哪个阵位、谁当预备队"；执行层要复现同一组阵位点、朝向与
    观察口径，因此把要点、阵位、威胁方向、轮换/增援/撤离规则显式交下去，
    不让执行层自己按作业点摆一圈。效果类字段（``effect`` / ``counter_attack``）
    只作为**抽象效果**参数透传，判定仍由 ``assessment.Adjudicator`` 完成。

    白名单之外的字段不下发：4.1 的 ``params`` 是自由字段，透传未知字段会让
    "行为层读了什么"变得不可核对。
    """
    if task.task_type != "T-HLD":
        return None
    from .templates import hld_key_point, hld_positions, hld_stations
    key_point = hld_key_point(task)
    positions = hld_positions(task)
    if key_point is None or not positions:
        return None
    params = task.params
    out = dict(
        key_point=[float(key_point[0]), float(key_point[1])],
        positions=[dict(item) for item in positions],
        stations=hld_stations(task, key_point, positions),
        threats=[dict(item) for item in (params.get("threat_directions") or [])],
        role_counts=dict(params.get("roles") or {}),
        duration_s=float(params.get("hold_duration_s",
                                   params.get("duration_s", 600.0))),
        site=[float(key_point[0]), float(key_point[1])],
    )
    for key in ("hold_criteria", "min_on_post", "observation_gap_max_s",
                "observation_ring_m", "observation_samples", "sensor_radius_m",
                "relief", "reinforce", "withdraw", "enemy_events",
                "counter_attack", "effect", "assembly_point",
                "post_tolerance_m", "patrol_enabled", "patrol_radius_m",
                "patrol_speed_mps", "patrol_period_s",
                "air_altitude_m", "air_orbit_radius_m", "air_orbit_period_s",
                "air_speed_mps", "air_capabilities", "air_unit",
                "min_key_point_coverage", "max_steps"):
        if key in params:
            out[key] = params[key]
    return out


def _unit_pid(scenario: Scenario, unit_id: Optional[str]) -> Optional[str]:
    if not unit_id:
        return None
    import fleet
    for platform in scenario.platforms:
        if platform.unit_id == unit_id:
            return fleet.pid_of(int(platform.robot_id))
    return None


def _asl_job(task: Task, scenario: Scenario) -> Dict[str, Any]:
    """4.1 T-ASL 任务 → 基座 assault 作业（含执行层 `_behavior`）。

    规划层只提供目标、兵力、角色席位、效果参数与几何；打击动作、弹药和
    效果判定由基座行为层与评估接口执行。
    """
    from .message import target_point
    import fleet
    params = task.params
    site = list(target_point(task.target))
    scout_pid = _unit_pid(scenario, params.get("scout_unit"))
    assessor_pid = _unit_pid(scenario, params.get("assessor_unit"))
    payload_required = float(params.get("payload_required", 4.0))
    air_altitude = {fleet.pid_of(int(p.robot_id)): float(p.altitude_m)
                    for p in scenario.platforms
                    if p.is_air and float(p.altitude_m) > 0}
    execute_deadline = params.get("execute_deadline")
    execute_deadline = (float(execute_deadline)
                        if execute_deadline is not None
                        and float(execute_deadline) > 0 else None)
    behavior = dict(
        staging_center=params.get("staging_center"),
        staging_radius=float(params.get("staging_radius", 6.0)),
        objective_radius=float(params.get("objective_radius", 14.0)),
        confirm_radius=float(params.get("confirm_radius", 18.0)),
        arrive_tol=float(params.get("arrive_tol", 0.8)),
        sync_tol=float(params.get("sync_tol", 14.0)),
        # 探测半径：只给工作台画"智能体探测范围"，不参与规划与判定
        sensor_radius_m=float(params.get("sensor_radius_m", 35.0)),
        scout_pid=scout_pid,
        observe_radius=float(params.get("observe_radius", 25.0)),
        observe_angle=float(params.get("observe_angle", 0.0)),
        assessor_pid=assessor_pid,
        assessment_post=params.get("assessment_post"),
        attack_window=list(params.get("attack_window") or []),
        assessment_delay=float(params.get("assessment_delay", 0.0)),
        confirmation_deadline=float(params.get("confirmation_deadline", 120.0)),
        execute_deadline=execute_deadline,
        effect_kind=params.get("effect", "damage"),
        required_level=float(params.get("required_level", 6.0)),
        required_duration=float(params.get("required_duration", 10.0)),
        required_control_s=float(params.get("required_control_s", 10.0)),
        damage_per_hit=1.0,
        fire_interval=float(params.get("fire_interval", 3.0)),
        rounds_per_salvo=int(params.get("rounds_per_salvo", 1)),
        counterattack_interval=float(params.get("counterattack_interval", 0.0)),
        target_id=params.get("target_id") or task.task_id,
        object_label=params.get("object_label"),
        roe=params.get("roe"),
        collateral_limit=params.get("collateral_limit"),
        positive_id_required=bool(params.get("positive_id_required", False)),
        waves=int(params.get("waves", 1)),
        role_payload={"assault": payload_required, "support": 0.5},
        assault_payload_required=payload_required,
        withdraw=bool(params.get("withdraw", False)),
        withdraw_point=params.get("withdraw_point"),
        withdraw_ring=float(params.get("withdraw_ring", 2.0)),
        withdraw_deadline=float(params.get("withdraw_deadline", 0.0)),
        timeout_s=float(params.get("timeout_s", 900.0)),
    )
    if air_altitude:
        behavior["air_altitude"] = air_altitude
    return dict(
        job_id=task.task_id, type="assault", pos=site,
        window=[int(round(task.window_start_s)),
                int(round(task.window_end_s))],
        crew=int(task.min_units),
        _task_type="T-ASL",
        _target=dict(task.target),
        _behavior=behavior,
    )


def to_v2_dict(scenario: Scenario, raw_message: Optional[Dict[str, Any]] = None,
               raw_formation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一 Scenario → 基座可执行的 middle-demo/v2 场景。

    `_meta.interop` 保留原始 4.1 消息与编成表，运行时可原样还原能力、
    障碍和任务语义，不再靠猜。
    """
    jobs = []
    for task in scenario.tasks:
        if task.task_type == "T-ASL":
            jobs.append(_asl_job(task, scenario))
            continue
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
        behavior = _sec_behavior_params(task) or _hld_behavior_params(task)
        if task.task_type == "T-RCN":
            from fleet import pid_of
            from .templates import recon_start_points, task_polygon
            area = task_polygon(task, ("area",))
            if area is not None:
                behavior = dict(
                    area=area,
                    air_altitude={
                        pid_of(p.robot_id): float(
                            task.params.get('air_altitude_m',
                                            p.altitude_m or 25.0))
                        for p in scenario.platforms if p.is_air},
                    search_deadline_s=min(
                        task.window_end_s,
                        float(task.params.get("search_deadline_s",
                                              task.window_end_s))),
                )
                if any(key in task.params
                       for key in ("search_starts", "search_points")):
                    starts = recon_start_points(task)
                    assigned_starts = {
                        unit: point for unit, point in starts if unit}
                    behavior.update(
                        search_starts={
                            pid_of(p.robot_id):
                                assigned_starts[p.unit_id]
                            for p in scenario.platforms
                            if p.unit_id in assigned_starts},
                        search_points_by_role={
                            'search:%d' % index: point
                            for index, (_, point) in enumerate(starts, 1)},
                    )
                else:
                    # 四点区域输入没有显式起点时，执行层仍必须使用区域
                    # 覆盖模型。实际成员位姿由 MockFleet 在派发时补齐为
                    # 初始扇区，避免退回旧的“中心点 9 米小圆”模型。
                    behavior["auto_search_sectors"] = True
                for key in ("cell", "coverage_target", "sensor_radius_m",
                            "tracking_target", "search_limit_s",
                            "air_search_speed_mps", "air_max_yaw_rate",
                            "air_max_yaw_accel"):
                    if key in task.params:
                        behavior[key] = task.params[key]
                behavior['air_orbit_radius_m'] = task.params.get(
                    'air_orbit_radius_m', 3.0)
                behavior['air_max_yaw_rate'] = task.params.get(
                    'air_max_yaw_rate', 0.35)
                behavior['takeoff_before_translation'] = task.params.get(
                    'takeoff_before_translation', False)
        if task.task_type == "T-PTL":
            from fleet import pid_of
            from .templates import patrol_has_loop, patrol_loop
            if patrol_has_loop(task):
                area, checkpoints, cycles = patrol_loop(task)
                behavior = dict(area=area, waypoints=checkpoints, cycles=cycles,
                                air_altitude={pid_of(p.robot_id): p.altitude_m
                                              for p in scenario.platforms if p.is_air})
                if task.params.get("follow_boundary"):
                    behavior["corner_lookahead_m"] = 3.0
            if behavior is None and any(key in task.params for key in
                                        ("sensor_radius_m", "observation_target", "_workbench_patrol")):
                behavior = {}
            if behavior is not None:
                if scenario.cell_size_m != 1:
                    behavior["cell_size_m"] = scenario.cell_size_m
                for key in ("sensor_radius_m", "observation_target", "_workbench_patrol"):
                    if key in task.params:
                        behavior[key] = task.params[key]
        if behavior is not None:
            if task.params.get('_workbench_task'):
                behavior['_workbench_task'] = True
            # 运行视图的作业参数（非 4.1 契约字段，只给基座行为层读）。
            job["_behavior"] = behavior
            if task.task_type in ("T-SEC", "T-HLD") and task.params.get("relay_verdict"):
                behavior["relay_verdict"] = True
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
    meta = {
        "source": "interop 4.1 运行视图（不是无损旧场景转换）",
        "message": dict(scenario.message or {}),
        "cell_size_m": scenario.cell_size_m,
        "formula": "job.work=duration_s×crew；统一层负责规划，基座负责运行",
        "interop": interop_meta,
    }
    for task in scenario.tasks:
        relay = task.params.get("relay_target")
        if relay:
            spec = relay if isinstance(relay, dict) else task.params["observation_target"]
            meta["relay_target"] = dict(spec, source_job_id=task.task_id)
            break
    if any(task.task_type == "T-ASL" for task in scenario.tasks):
        # 独立 T-ASL 样例可以声明自己的 SDF；导入地图则完全以编成表内的
        # no_go/threat 约束为权威，绝不把 container_00 的 SDF 和固定包围盒
        # 套到任意场景坐标上。运行适配器会从原始 4.1 bundle 构造同一张地图。
        formation_meta = dict(scenario.meta or {})
        source_sdf = formation_meta.get("source_sdf")
        imported_map = (formation_meta.get("map_geometry_authority")
                        == "planning_and_display" and formation_meta.get("map_id"))
        if source_sdf and not imported_map:
            scene_bounds = formation_meta.get("scene_bounds")
            meta.update({
                "sdf": source_sdf,
                "models": "资料/接口说明/models",
                "scale": 1.0, "offset_x": 0.0, "offset_y": 0.0,
                "radius": float(formation_meta.get("runtime_radius_m", 1.75)),
                "resolution": float(formation_meta.get("runtime_resolution_m", 0.5)),
            })
            if scene_bounds:
                meta["bounds"] = [float(v) for v in scene_bounds]
    return {
        "protocol": "middle-demo/v2",
        "objective": "makespan",
        "H": horizon,
        "K": int((scenario.meta or {}).get("runtime_replan_period_s", 8)),
        "_meta": meta,
        "platforms": [dict(robot_no=p.robot_id,
                           pos=[p.position[0], p.position[1]],
                           _platform_class=p.platform_class,
                           _payload_kg=p.payload_kg, _sensor=dict(p.sensor_spec),
                           _motion=dict(p.motion_spec), _endurance_s=p.endurance_s)
                      for p in scenario.platforms],
        "jobs": jobs,
    }


def nav_from_scenario(scenario: Scenario, margin: float = 40.0,
                      radius: float = 1.5, resolution: float = 1.0,
                      avoid_threats: bool = False):
    """用 4.1 编成表的 no_go 约束构造基座静态地图（NavMap）。

    融合层的中性样例不写 ``_meta.sdf``，基座 ``city_nav.build_nav`` 会退到
    simple_city 的世界坐标，等于用错地图。这里改为**只用权威输入**：
    平台与任务几何定边界，编成表的 ``no_go`` 约束当障碍，不解析 SDF、
    不猜坐标。范围只包住本次作业区，A* 栅格因此保持 1 m 级而不爆内存。

    threat 是软风险区，不能进入作为硬障碍的 ``NavMap``。否则平台一旦
    出生在威胁区内，执行层就会报 ``start_in_obstacle`` 并反复规划，永远
    无法起步。威胁代价由统一规划器计算；空中航点的安全投影单独使用
    ``air_threat_map``。``avoid_threats`` 保留用于兼容旧调用，不再改变
    硬障碍语义。
    """
    import city_nav

    points = [tuple(p.position) for p in scenario.platforms]
    map_bounds = (scenario.meta or {}).get("map_scene_bounds")
    if (isinstance(map_bounds, (list, tuple))
            and len(map_bounds) == 4):
        x0, y0, x1, y1 = map(float, map_bounds)
        points.extend(((x0, y0), (x1, y1)))
        # Imported city maps are used as a secondary fallback behind the
        # scoped router.  A 2 m fallback grid keeps that diagnostic path
        # responsive while the route itself remains governed by the 5 m
        # cached risk grid.
        resolution = max(float(resolution), 2.0)
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
        for key in ("gates", "intruders", "tracking_target", "entry_points", "defense_positions",
                    "posts", "intercept_post", "reserve_post", "positions",
                    "reserve_point", "support_points", "relay_point",
                    "threat_directions"):
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
    for item in scenario.constraints:
        area = item.get("area") or {}
        polygon = area.get("polygon") if isinstance(area, dict) else area
        for point in polygon or []:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError, IndexError):
                pass
    if not points:
        raise ValueError("场景里没有可用于确定封控地图的点")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bounds = [min(xs) - margin, min(ys) - margin,
              max(xs) + margin, max(ys) + margin]
    ground_obstacles = []
    air_obstacles = []
    ground_threats = []
    air_threats = []
    for item in scenario.constraints:
        kind = item.get("type")
        if kind not in ("no_go", "threat"):
            continue
        area = item.get("area") or {}
        polygon = area.get("polygon") if isinstance(area, dict) else area
        if not polygon:
            continue
        obstacle = dict(
            id=item.get("constraint_id"),
            polygon=[(float(p[0]), float(p[1])) for p in polygon])
        applies = str(item.get("applies_to", "ground"))
        if kind == "no_go":
            if applies in ("ground", "all"):
                ground_obstacles.append(obstacle)
            # 空中静态 NavMap 无法按每个平台高度选障碍。显式对空禁飞区，
            # 以及缺少物高而必须保守处理的全域 no_go 先放入固定图；
            # air/all + height_m 由下面带 altitude_m 的统一路由器按巡航
            # 高度判定，避免建筑二维投影被误当成整柱空域墙。
            if (applies == "air"
                    or (applies == "all"
                        and item.get("height_m") is None)):
                air_obstacles.append(obstacle)
        else:
            if applies in ("ground", "all"):
                ground_threats.append(obstacle)
            if applies in ("air", "all"):
                air_threats.append(obstacle)
    nav = city_nav.NavMap(bounds, ground_obstacles, radius=radius,
                          resolution=resolution)
    # 地面与空中共享平面坐标，但硬障碍和威胁作用域不同：
    # * air_threat_nav 只负责可通行几何，不能把威胁重新变成墙；
    # * *._threat_map 只用于安全航点投影和可视化/诊断。
    nav.air_threat_nav = (
        city_nav.NavMap(bounds, air_obstacles, radius=radius,
                        resolution=resolution)
        if air_obstacles else None)
    nav.ground_threat_map = (
        city_nav.NavMap(bounds, ground_threats, radius=radius,
                        resolution=resolution)
        if ground_threats else None)
    nav.air_threat_map = (
        city_nav.NavMap(bounds, air_threats, radius=radius,
                        resolution=resolution)
        if air_threats else None)
    # 行为层执行期间还会根据集结位、观察位和动态航点重新规划。只把
    # 避威胁标志留给首次分配规划不够，那些本地航段仍会直穿风险区。
    # 暴露度模式因此保留一个带安全间隔的软风险路由器，供执行层复用。
    from .routing import Router
    from .templates import decompose
    nav.route_router = Router(
        scenario, decompose(scenario),
        risk_weight=1.0 if avoid_threats else 0.0)
    nav.prefer_scoped_router = bool(
        (scenario.meta or {}).get("map_scene_bounds")
    )
    nav.threat_router = nav.route_router if avoid_threats else None
    nav.avoid_threats = bool(avoid_threats)
    return nav


class InteropPlanner(object):
    """CoordinatorV2 的可插拔规划器：返回 (planner_v2.Plan, events)。"""

    name = "interop"

    def __init__(self, scenario: Scenario, objective: str = "makespan",
                 data: Optional[Dict[str, Any]] = None):
        self.scenario = scenario
        self.data = data or {}
        self.objective = OBJECTIVE_MAP.get(objective, "timeliness")
        map_bounds = (scenario.meta or {}).get("map_scene_bounds")
        if isinstance(map_bounds, (list, tuple)) and len(map_bounds) == 4:
            self._grid_bounds_m = [
                float(map_bounds[0]) - 20.0,
                float(map_bounds[1]) - 20.0,
                float(map_bounds[2]) + 20.0,
                float(map_bounds[3]) + 20.0,
            ]
        else:
            # Keep the router domain fixed for the life of this planner.
            # Deriving it from live positions made the grid bounds move every
            # few simulation steps, invalidating the expensive obstacle grid.
            points = [tuple(p.position) for p in scenario.platforms]
            from .message import target_points
            for task in scenario.tasks:
                try:
                    points.extend(target_points(task.target))
                except Exception:
                    pass
            for item in scenario.constraints:
                area = item.get("area") or {}
                polygon = area.get("polygon") if isinstance(area, dict) else area
                for point in polygon or []:
                    try:
                        points.append((float(point[0]), float(point[1])))
                    except (TypeError, ValueError, IndexError):
                        pass
            if points:
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                self._grid_bounds_m = [
                    min(xs) - 40.0,
                    min(ys) - 40.0,
                    max(xs) + 40.0,
                    max(ys) + 40.0,
                ]
            else:
                self._grid_bounds_m = None
        self.last_plan = None
        self.last_snapshot = None
        self.initial_plan = None
        self.refresh_subtasks()
        self.plan_history = []
        self._cached_interop_plan = None
        self.activation_rules = {task.task_id: task.params["after_event"]
                                 for task in scenario.tasks if "after_event" in task.params}
        task_ids = {task.task_id for task in scenario.tasks}
        for job_id, rule in self.activation_rules.items():
            if (not isinstance(rule, dict) or not isinstance(rule.get("task_id"), str)
                    or rule["task_id"] not in task_ids - {job_id}
                    or not isinstance(rule.get("kind"), str) or not rule["kind"]):
                raise InteropPlannerError("%s 的 after_event 须指定另一项任务和事件类型" % job_id)

    def refresh_subtasks(self) -> None:
        """缓存槽位规格，供运行中的子任务改派使用。

        ``decompose`` 是确定性的：同一份输入每次给出同样的 subtask_id。
        工作台在暂停时刻改任务后会重建本对象，或在同一个对象上替换
        scenario，因此这里也允许显式刷新。
        """
        from .templates import decompose
        self.__dict__.pop("_return_candidates", None)
        try:
            self._subtask_specs = {slot.subtask_id: slot
                                   for slot in decompose(self.scenario)}
        except ValueError:
            # 历史/不完整场景可能在构造期还分解不出来；先留空，
            # 真正规划时仍按原有错误路径报告，不让编辑/加载直接崩。
            self._subtask_specs = {}

    def replacement_for(self, coord, job_id: str, subtask_id: str, now: int,
                        exclude_pids=()) -> Optional[Tuple[Platform, float]]:
        """在编成表内为一个失败/超时子任务找替补平台。

        只做“能不能接”的硬过滤（能力/状态/载荷/时间窗/续航/禁入区）和
        粗略到达时间比较；真正的路径、转向与避障仍由执行层负责。返回
        ``(platform, travel_s)``，没有候选时返回 ``None``。
        """
        from dataclasses import replace as dc_replace
        import fleet
        from .gate import gate_platform
        from .message import target_point
        slot = self._subtask_specs.get(subtask_id)
        if slot is None:
            return None
        excluded = set(exclude_pids)
        job = coord.jobs.get(job_id)
        used = set(getattr(job, "_interop_subtasks", {}) or {}) - excluded
        try:
            goal = target_point(slot.target)
        except WireError:
            return None
        best = None
        for platform in self.scenario.platforms:
            pid = fleet.pid_of(platform.robot_id)
            if pid in excluded or pid in used or pid in getattr(coord, "returning_home", ()):
                continue
            live = coord.platforms.get(pid)
            if live is None or not getattr(live, "alive", True):
                continue
            if coord.platform_cmd.get(pid):
                continue
            candidate = dc_replace(slot, pinned_unit="")
            ok, _, _ = gate_platform(platform, candidate, self.scenario)
            if not ok:
                continue
            # 已在当前计划里排给别家的平台不抢，避免改派和待派任务互相踩。
            if coord.plan is not None:
                busy_plan = any(
                    a.job_id != job_id and pid in a.pids
                    and (coord.jobs.get(a.job_id) is None
                         or coord.jobs[a.job_id].status == "pending")
                    for a in coord.plan.assignments)
                if busy_plan:
                    continue
            pos = getattr(live, "pos", platform.position)
            travel = math.hypot(float(pos[0]) - goal[0],
                                float(pos[1]) - goal[1]) / max(platform.speed_mps, 1e-6)
            if now + travel >= slot.window_end_s:
                continue
            if best is None or travel < best[1]:
                best = (platform, travel)
        return best

    def timing_slots(self, coord):
        """当前“在途 + 已排 + 被阻塞”的子任务时序快照。

        动态时序指标（2.2(3)）只看事实，不改变规划：
          * RUNNING：协调器 active 中的在途指令，结束时间取计划、动态
            延期与剩余工作量三者的最大值；
          * PLANNED：最近一次槽位计划里尚未下发的分配；
          * BLOCKED：因依赖/事件尚未排入计划的子任务，用最早可行时间
            估算，用于把在途延期传递给后续任务。
        """
        import fleet
        from .timing_resolution import TimingSlot
        specs = dict(self._subtask_specs)
        slots = []
        running_ids = set()
        running_by_id = {}
        for command_id, command in list(coord.active.items()):
            if command.action != "start":
                continue
            job = coord.jobs.get(command.job_id)
            if job is None:
                continue
            meta = (getattr(job, "_interop_subtasks", {}) or {}).get(
                command.worker_id)
            if not meta:
                continue
            spec = specs.get(meta.get("subtask_id"))
            if spec is None:
                continue
            frac = 0.0
            try:
                frac = min(1.0, max(0.0, float(job.progress) / max(float(job.work), 1e-9)))
            except (TypeError, ValueError):
                frac = 0.0
            remaining = max(0.0, float(spec.duration_s) * (1.0 - frac))
            end = max(float(command.expected_end_sim_s),
                      float(coord.now) + remaining)
            slot = TimingSlot(
                subtask_id=spec.subtask_id,
                parent_task_id=spec.parent_task_id,
                task_type=spec.task_type,
                target=dict(spec.target),
                start_s=float(command.start_sim_s),
                end_s=end,
                window_start_s=float(spec.window_start_s),
                window_end_s=float(spec.window_end_s),
                depends_on=list(spec.depends_on),
                coordination=list(spec.coordination),
                unit_id=command.worker_id,
                state="RUNNING",
                role=getattr(spec, "role", ""),
                travel_s=0.0,
                command_id=command_id,
                assigned=True,
            )
            slots.append(slot)
            running_ids.add(spec.subtask_id)
            running_by_id[spec.subtask_id] = slot

        planned = {}
        if self.last_plan is not None:
            for item in self.last_plan.assignments:
                job = coord.jobs.get(item.parent_task_id)
                if job is None or job.status != "pending":
                    continue
                if item.subtask_id in running_ids:
                    continue
                spec = specs.get(item.subtask_id)
                if spec is None:
                    continue
                slot = TimingSlot(
                    subtask_id=item.subtask_id,
                    parent_task_id=item.parent_task_id,
                    task_type=item.task_type,
                    target=dict(item.target),
                    start_s=float(item.start_s),
                    end_s=float(item.end_s),
                    window_start_s=float(item.window_start_s),
                    window_end_s=float(item.window_end_s),
                    depends_on=list(item.depends_on),
                    coordination=list(item.coordination),
                    unit_id=(fleet.pid_of(int(item.robot_id))
                             if getattr(item, "robot_id", None) is not None
                             else item.unit_id),
                    state="PLANNED",
                    role=getattr(item, "role", ""),
                    travel_s=float(item.travel_s),
                    assigned=True,
                )
                slots.append(slot)
                planned[item.subtask_id] = slot

        placed = running_by_id | planned
        states = getattr(coord, "subtask_states", {}) or {}
        succeeded_at = getattr(coord, "succeeded_at", {}) or {}
        blocked = {}

        def _active(spec):
            job = coord.jobs.get(spec.parent_task_id)
            if job is None or job.status not in ("pending", "assigned", "running"):
                return False
            state = states.get(spec.subtask_id)
            if state is not None and state.get("status") in ("succeeded",
                                                             "cancelled"):
                return False
            return True

        def _done_time(job_id):
            value = succeeded_at.get(job_id)
            return float(value) if value is not None else float(coord.now)

        def _blocked_slot(spec, stack):
            """被依赖阻塞的槽位：按依赖链推算最早可开工时刻。

            依赖也可能是被阻塞的槽位（链式任务），必须按依赖顺序回推，
            否则会把"还没排进计划的合法前置"误报成"前置未分配"。
            """
            sid = spec.subtask_id
            if sid in blocked:
                return blocked[sid]
            if sid in stack or sid in placed or not _active(spec):
                return None
            dep_end = 0.0
            for dep_id in spec.depends_on or []:
                dep = running_by_id.get(dep_id) or planned.get(dep_id)
                if dep is None:
                    dep_spec = specs.get(dep_id)
                    if dep_spec is not None:
                        dep_job = coord.jobs.get(dep_spec.parent_task_id)
                        if dep_job is not None and dep_job.status == "succeeded":
                            dep_end = max(dep_end,
                                          _done_time(dep_job.job_id))
                        else:
                            dep = _blocked_slot(dep_spec, stack | {sid})
                if dep is not None:
                    dep_end = max(dep_end, float(dep.end_s))
            start = max(float(coord.now), float(spec.window_start_s), dep_end)
            slot = TimingSlot(
                subtask_id=sid,
                parent_task_id=spec.parent_task_id,
                task_type=spec.task_type,
                target=dict(spec.target),
                start_s=start,
                end_s=start + float(spec.duration_s),
                window_start_s=float(spec.window_start_s),
                window_end_s=float(spec.window_end_s),
                depends_on=list(spec.depends_on),
                coordination=list(spec.coordination),
                unit_id=None,
                state="BLOCKED",
                role=getattr(spec, "role", ""),
                travel_s=0.0,
                assigned=False,
            )
            blocked[sid] = slot
            return slot

        for spec in specs.values():
            slot = _blocked_slot(spec, set())
            if slot is not None:
                slots.append(slot)

        # 已完成的前置子任务作为"已满足"的占位加入快照，避免独立检查器
        # 把已成功但已退出在途表的依赖误报成"前置未分配"。
        referenced = {dep_id for spec in specs.values()
                      for dep_id in (spec.depends_on or [])}
        for dep_id in referenced:
            if (dep_id in running_by_id or dep_id in planned
                    or dep_id in blocked):
                continue
            dep_spec = specs.get(dep_id)
            if dep_spec is None:
                continue
            dep_job = coord.jobs.get(dep_spec.parent_task_id)
            if dep_job is None or dep_job.status != "succeeded":
                continue
            done = _done_time(dep_job.job_id)
            slots.append(TimingSlot(
                subtask_id=dep_id,
                parent_task_id=dep_spec.parent_task_id,
                task_type=dep_spec.task_type,
                target=dict(dep_spec.target),
                start_s=done,
                end_s=done,
                window_start_s=0.0,
                window_end_s=max(done, 0.0),
                depends_on=[],
                coordination=[],
                unit_id=None,
                state="DONE",
                role=getattr(dep_spec, "role", ""),
                travel_s=0.0,
                assigned=True,
            ))
        return slots

    def timing_exclusions(self, coord):
        """返回 (unassigned, deleted) 标识集合，供消解判定排除“删/未分配”。"""
        unassigned = set()
        if self.last_plan is not None:
            for item in self.last_plan.unassigned:
                if isinstance(item, dict):
                    for key in ("subtask_id", "parent_task_id"):
                        if isinstance(item.get(key), str):
                            unassigned.add(item[key])
            for item in self.last_plan.rejected:
                if isinstance(item, dict) and isinstance(item.get("job_id"), str):
                    unassigned.add(item["job_id"])
        deleted = set(getattr(coord, "deleted_job_ids", set()) or ())
        known = {task.task_id for task in self.scenario.tasks}
        for job_id in list(getattr(coord, "jobs", {})):
            if job_id not in known:
                deleted.add(job_id)
        return unassigned, deleted

    def observe_behavior_event(self, coord, row):
        event = row["event"]
        for job_id, rule in self.activation_rules.items():
            if (event.get("job_id") != rule["task_id"] or event.get("kind") != rule["kind"]
                    or any(event.get(key) != rule[key]
                           for key in ("target_id", "verdict", "overall") if key in rule)):
                continue
            activated = getattr(coord, "_interop_handoffs", None)
            if activated is None:
                coord._interop_handoffs = activated = {}
            if job_id in activated:
                continue
            activated[job_id] = row["sim_s"]
            handoff = dict(kind="relay_handoff", job_id=job_id,
                           from_job_id=rule["task_id"], source_event=event["kind"])
            for key in ("target_id", "pid", "pos", "verdict"):
                if key in event:
                    handoff[key] = event[key]
            coord.audit.append(dict(kind="behavior_event", sim_s=row["sim_s"], event=handoff))
            coord.pending.append(("handoff", "%s → %s" % (rule["task_id"], job_id)))

    def reserve_unplanned(self, job_ids):
        """等待依赖或事件的作业仍保留可执行其席位的成员。"""
        from fleet import pid_of
        from .gate import gate_platform
        from .templates import decompose
        if not hasattr(self, "_return_candidates"):
            self._return_candidates = {}
            for slot in decompose(self.scenario):
                candidates = self._return_candidates.setdefault(slot.parent_task_id, set())
                for platform in self.scenario.platforms:
                    if gate_platform(platform, slot, self.scenario)[0]:
                        candidates.add(pid_of(platform.robot_id))
        return set().union(*(self._return_candidates.get(jid, set()) for jid in job_ids))

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
                platform.status = (item.status if item.status in ('OFFLINE', 'DAMAGED', 'LOST')
                                   else "READY") if getattr(live, "alive", True) else "LOST"
                # 4.1 编成表是速度/续航的权威来源；基座 v2 场景只带 robot_no，
                # build_platforms 会退回 fleet 默认速度（0.8 m/s 等），和 4.1 的
                # 8/25/30 m/s 不一致。运行适配器把权威参数同步给协调器，逐步
                # 运动的到达时刻才与计划同源。
                live.speed = float(item.speed_mps)
                live.work_rate = float(item.work_rate)
                # 载荷/传感器也以 4.1 编成表为准：基座行为层的“突击组载荷
                # 下限”读的是指令投递块，不改这两项会出现“计划按编成表、
                # 执行按 fleet 默认”的两套参数。
                live.payload = float(item.payload)
                live.sensor = str(item.sensor)
                live.payload_kg = item.payload_kg
                live.sensor_spec = dict(item.sensor_spec)
                live.motion_spec = dict(item.motion_spec)
                live.endurance_s = item.endurance_s
                # 电量以 4.1 编成表为准，不再人为抬到 1e6；否则界面和续航
                # 判定都会显示成“几乎满电”。真实电量不足时由基座记
                # energy_depleted 事件，规划层的续航校验另行拦截。
                live.battery = float(item.battery)
                live.can_climb = bool(item.is_air)
            # 在途指令把平台占到 expected_end；重规划必须把它当“最早可用时刻”，
            # 否则会把新作业排给正在执行旧作业的平台，下发时又被协调器挡回。
            command_id = coord.platform_cmd.get(fleet.pid_of(item.robot_id))
            command = coord.active.get(command_id) if command_id else None
            platform.busy_until_s = max(float(command.expected_end_sim_s) if command is not None else 0.0,
                float(coord.dynamic_ends.get(command_id, 0.0)) if command_id else 0.0)
            platforms.append(platform)

        tasks = []
        for task in self.scenario.tasks:
            job = coord.jobs.get(task.task_id)
            if job is None or job.status != "pending":
                continue   # 已在途/已完成/已失败的作业不在本层重排
            if (task.task_id in self.activation_rules
                    and task.task_id not in getattr(coord, "_interop_handoffs", {})):
                continue
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
            if task.task_type != "T-ASL":
                # 行为任务（T-ASL）的执行时长由行为状态机决定，不按剩余
                # 工作量折减；其余任务沿用槽位时长口径。
                for key in ("duration_s", "hold_duration_s"):
                    if key in params:
                        params[key] = max(1.0, float(params[key]) * scale)
            # 基座作业是“一台次 crew 同时干一个活”，没有“同一作业拆成多段
            # 串行槽位”的表达。运行适配器因此把所有槽位对齐为同时开始：
            # 分组后的 start/end 才是一个真实作业区间，而不是把先后几段
            # 拼成一段超长作业。T-ASL 的同时到达由模板只作用于突击席，
            # 这里不再给整任务加协同标记。
            if task.task_type != "T-ASL":
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
        snapshot_meta = dict(self.scenario.meta)
        if self._grid_bounds_m is not None:
            snapshot_meta["grid_bounds_m"] = list(self._grid_bounds_m)
        return Scenario(
            formation_id=self.scenario.formation_id, platforms=platforms,
            tasks=tasks,
            constraints=[dict(c) for c in self.scenario.constraints],
            groups=list(self.scenario.groups), meta=snapshot_meta,
            message=dict(self.scenario.message or {}),
            cell_size_m=self.scenario.cell_size_m,
            plan_id=self.scenario.plan_id, schema_version="0.3",
        )

    # ------------------------------------------------------------------
    def __call__(self, coord, now):
        import fleet
        import planner_v2
        snapshot = self._snapshot(coord)
        can_reuse = (
            self._cached_interop_plan is not None
            and bool((self.scenario.meta or {}).get("reuse_stable_plan"))
            and bool(coord.pending)
            and all(source == "periodic" for source, _detail in coord.pending)
        )
        if can_reuse:
            plan = self._cached_interop_plan
        else:
            plan = Planner(snapshot, objective=self.objective).plan()
            self._cached_interop_plan = plan
        if self.initial_plan is None:
            # The first rolling-planning snapshot is the plan that produced
            # the initial dispatch. Keep that object for the 4.2 export;
            # planning again after execution completes can select different
            # units because the live snapshot no longer contains finished or
            # in-flight work.
            self.initial_plan = plan
        self.last_plan = plan
        self.last_snapshot = snapshot
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
                reason = (reasons[0] if reasons else "NO_ASSIGNMENT")
                rejected.append(dict(
                    job_id=task.task_id,
                    reason="融合层未凑齐兵力(%d/%d)%s"
                           % (len(pids), job.crew,
                              ("：" + reason) if reasons else "")))
                # A static plan that cannot form the required crew on this
                # complete planning snapshot will not become feasible merely
                # by waiting.  Leaving the job pending made deadline tests spin
                # to max_ticks and the native window appear frozen.  Record an
                # explicit terminal failure so the run can settle and explain
                # whether the cause was a time window, no route, or capacity.
                if job.status == "pending":
                    job.status = "failed"
                    coord.record(
                        "job_failed",
                        job_id=task.task_id,
                        cause="interop_unassigned",
                        reason=reason,
                    )
                continue
            orig_start = min(item.start_s for item in items)
            is_asl = task.task_type == "T-ASL"
            if is_asl:
                # 突击作业的时长取执行段参数（默认 140 s），不从槽位跨度
                # 反推；侦察/评估席的 10 s 机动不能把整个作业压缩成 10 s。
                duration = float(task.params.get("duration_s", 140.0))
            else:
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
            if is_asl:
                # T-ASL 进度按行为阶段计（progress_frac），改写 work 会让
                # 进度与阶段脱节；只登记本层总量，保持基座 work 不变。
                job._interop_total = max(1.0, float(job.work))
            else:
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
            # 子任务影子账本：一个平台一个槽位。运行层只按 (job_id, pid)
            # 关联反馈，不改变 4.2 指令/反馈协议的既有字段。
            subtasks = {}
            for item in items:
                pid = fleet.pid_of(robot_of[item.unit_id])
                subtasks[pid] = dict(
                    subtask_id=item.subtask_id,
                    parent_task_id=task.task_id,
                    unit_id=item.unit_id,
                    role=getattr(item, "role", ""),
                    task_type=task.task_type,
                    target=dict(item.target),
                    start_s=float(item.start_s),
                    end_s=float(item.end_s),
                    window_start_s=float(item.window_start_s),
                    window_end_s=float(item.window_end_s),
                    duration_s=max(0.0, float(item.end_s) - float(item.start_s)),
                )
            if subtasks:
                job._interop_subtasks = subtasks
                job._interop_local_replace = task.task_type in ("T-RCN", "T-PTL")
            # 把 4.2 计划路线随任务下发给行为层：只是路线证据，目标与
            # 行为判定不变。暴露度/风险目标的地面路线会绕开威胁区，可防止
            # 行为层本地重规划把路径又拉回威胁区角点。
            paths_by_pid = {}
            for item in by_task.get(task.task_id) or []:
                pid = fleet.pid_of(robot_of[item.unit_id])
                if item.path:
                    paths_by_pid[pid] = [list(map(float, point))
                                         for point in item.path]
            if paths_by_pid:
                job._interop_paths = paths_by_pid
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
        # Capture the exact dynamic snapshot used for this coordinator version.
        # Future rollovers must not replace evidence used by an earlier dispatch.
        self.plan_history.append(dict(runtime_plan_id=coord.plan_id,
            generated_at_s=now, plan=plan.to_dict(),
            runtime_assignments=[dict(job_id=a.job_id, pids=list(a.pids),
                                      start=a.start, end=a.end, travel=a.travel)
                                 for a in assignments]))
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
