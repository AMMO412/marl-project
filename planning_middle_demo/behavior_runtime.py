# -*- coding: utf-8 -*-
"""behavior_runtime.py —— 把行为状态机接到运动层（逐拍 Twist + A* 路径）。

分层：
  behaviors.py     只决定"下一目标点/阶段/事件"（纯决策，可单测）
  city_nav.py      只负责"目标点 → 绕障路径 → 逐拍速度"（纯几何）
  本文件           把两者接起来：每 1 个仿真步执行一次行为决策，步内用
                   10 拍 × 0.1 s 的闭环跟随把平台开到目标点，记录轨迹。

里程与时间口径：1 个仿真步 = 1 s（与 planning_middle_demo 的整数步一致），
步内控制周期 0.1 s。平台速度为场景单位/步，换算成每拍就是 speed × 0.1。
"""
import math
from dataclasses import dataclass, field

import city_nav
from city_nav import PathFollower, distance
from motion import AirLoiter, Pose
from vehicle_kinematics import approach, clamp_angle, limits_for, turn_radius_for


@dataclass
class AgentState:
    pid: str
    x: float
    y: float
    yaw: float = 0.0
    speed: float = 0.8
    z: float = 0.0              # 当前高度（场景单位/米）
    altitude: float = 0.0       # 巡航高度：0 = 地面平台
    can_climb: bool = False
    kind: str = ''
    path: list = field(default_factory=list)
    index: int = 0
    follow: object = None
    target: list = None
    loiter: object = None
    path_meta: dict = None
    odometer: float = 0.0      # 累计行程（场景单位），供能耗记账
    air_v: float = 0.0
    target_moving: bool = False
    target_vel: tuple = (0.0, 0.0)
    target_time: float = 0.0
    target_moving_until: float = 0.0
    loiter_target: tuple = None
    loiter_requested_radius: float = None
    heading_initialized: bool = False
    threat_exit_target: list = None
    last_route_plan_t: float = -1e9

    @property
    def pose(self):
        return (self.x, self.y, self.yaw)


class BehaviorRunner:
    def __init__(self, nav, behavior, starts, speeds=None, dt=0.1,
                 ticks_per_step=10, caps=None, air_nav=None):
        self.nav = nav
        self.air_nav = air_nav
        self.behavior = behavior
        self.continuous = getattr(behavior, 'continuous', False)
        self.dt = dt
        self.ticks_per_step = ticks_per_step
        speeds = speeds or {}
        caps = caps or {}
        air_alt = (behavior.params.get('air_altitude') or {})
        self.agents = {}
        for pid, start in starts.items():
            cap = caps.get(pid) or {}
            can_climb = bool(cap.get('can_climb'))
            base_z = float(cap.get('start_z') or 0.0)
            altitude = (max(base_z, float(air_alt.get(pid, base_z)))
                        if can_climb else 0.0)
            self.agents[pid] = AgentState(
                pid=pid, x=float(start[0]), y=float(start[1]),
                yaw=float(start[2]) if len(start) > 2 else 0.0,
                speed=float(speeds.get(pid, 0.8)),
                z=base_z, altitude=altitude, can_climb=can_climb,
                kind=str(cap.get('kind') or ''),
                air_v=(0.75 * float(speeds.get(pid, 0.8))
                       if can_climb and altitude > 0 else 0.0),
                heading_initialized=bool(
                    cap.get('heading_initialized', False)))
        self.time = 0.0
        self.samples = []
        self.events = []
        self.routes = []
        self._follower = PathFollower()
        # 每台平台一个跟随器：``PathFollower.max_linear`` 是"场景单位/秒"，
        # 若所有平台共用默认 0.8，就会把 4.1 编成表里的 8 m/s 地面平台、
        # 30 m/s 飞机全部压成 0.8 m/s——小场景看不出来，几百米的封控区里
        # 拦截组永远追不上目标。默认值只留作未登记速度时的兜底。
        self._followers = {}
        # 同一架飞机可能连续多拍收到同一逻辑航点；只在投影首次变化时
        # 记一次事件，避免把诊断信息刷满事件列表。
        self._last_safe_targets = {}
        # Cross-job ground coordination is supplied by MockFleet once per
        # simulation step.  Each job owns a separate runner, so without this
        # snapshot two tasks can route different platforms through the same
        # street at the same time and visually stack them.
        self.peer_ground_positions = {}
        # 行为层给出的"限速系数"（默认 1.0 = 平台全速）
        self._speed_scale = {}
        # 空中平台的盘旋限速单独放一张表：地面跟随器读 _speed_scale，
        # 空中直飞读这张，互不干扰（封控/坚守的既有速度不受影响）。
        self._air_speed_scale = {}
        # A moving target can change by tens of centimetres on every 0.1 s
        # control tick.  Re-running a full A* search at that cadence makes the
        # software look frozen and produces a dense fan of path segments.  The
        # route remains valid between updates; force=True and explicit
        # planned_routes still bypass this throttle when safety requires it.
        self.dynamic_replan_interval_s = 1.0
        self.behavior.speeds = speeds
        self._last_phase = None
        self._job = behavior.job_id
        self._site = list(behavior.site)
        self._inside = False
        self.behavior.station_holds = self._station_holds

    def _station_holds(self, pid, target, tolerance=0.35):
        agent = self.agents.get(pid)
        return bool(agent and agent.can_climb and agent.z > 0
                    and agent.loiter
                    and (agent.loiter.matches(target, tolerance)
                         or (agent.loiter_target is not None
                             and distance(target, agent.loiter_target)
                             <= tolerance))
                    and distance((agent.x, agent.y), agent.loiter.center)
                    <= agent.loiter.radius + 0.5)

    def _set_air_loiter(self, agent, target, radius=None):
        target = [float(target[0]), float(target[1])]
        default_radius = getattr(
            self.behavior, 'air_orbit_radius_effective_m', None)
        if self.behavior.phase == '撤离':
            # Withdrawal targets are destinations, not observation stations.
            # Reusing the 45+ m observation orbit here made aircraft circle far
            # outside the withdrawal point until the deadline expired.
            default_radius = self.behavior.params.get(
                'withdraw_air_orbit_radius_m', 8.0)
        elif default_radius is None:
            default_radius = self.behavior.params.get(
                'air_orbit_radius_m', 3.0)
        # ``air_orbit_radius_m=0`` means "derive the orbit from the configured
        # station speed and bank angle" in the task behaviours.  Passing that
        # zero straight to AirLoiter used to collapse the circle to its 0.5 m
        # safety floor.  A 30 m/s fixed wing then had to obey the yaw-rate
        # limit, slowing to 0.95 * 0.35 * 0.5 = 0.166 m/s and taking about a
        # minute to reach a station only a few metres away.  Resolve the
        # automatic radius here, before AirLoiter applies its kinematic limit.
        configured_radius = float(default_radius or 0.0)
        if radius is not None:
            radius = float(radius)
        elif configured_radius > 0.0:
            radius = configured_radius
        else:
            orbit_speed = max(0.2, float(
                self.behavior.params.get(
                    'air_orbit_speed_mps', min(6.0, agent.speed))))
            bank = math.radians(max(5.0, min(45.0, float(
                self.behavior.params.get('air_bank_deg', 15.0)))))
            radius = min(
                80.0,
                max(10.0, orbit_speed * orbit_speed
                    / (9.8 * math.tan(bank))))
        radius = (float(radius)
                  if radius is not None else
                  float(default_radius))
        agent.loiter_requested_radius = radius
        center = list(target)
        threat_map = (getattr(self.nav, 'air_threat_map', None)
                      or self.air_nav)

        def clear(candidate, orbit_radius):
            if threat_map is None:
                return True
            samples = max(24, int(math.ceil(
                2.0 * math.pi * orbit_radius / 1.0)))
            for index in range(samples):
                angle = 2.0 * math.pi * index / samples
                point = (candidate[0] + orbit_radius * math.cos(angle),
                         candidate[1] + orbit_radius * math.sin(angle))
                if not threat_map.free(point):
                    return False
            return True

        if not clear(center, radius):
            logical = getattr(agent, '_requested_target', target)
            dx, dy = center[0] - logical[0], center[1] - logical[1]
            norm = math.hypot(dx, dy)
            if norm <= 1e-9:
                dx, dy, norm = 1.0, 0.0, 1.0
            for offset in (0.5 * index for index in range(1, 61)):
                candidate = [
                    center[0] + dx / norm * offset,
                    center[1] + dy / norm * offset]
                if clear(candidate, radius):
                    center = candidate
                    break
            else:
                for trial in (1.5, 1.0, 0.5):
                    if clear(center, trial):
                        radius = trial
                        break
        safe_transition = (
            threat_map.segment_free if threat_map is not None else None)
        agent.loiter = AirLoiter(
            center, agent.speed, radius=radius,
            max_yaw_rate=self.behavior.params.get(
                'air_max_yaw_rate', 0.35),
            max_yaw_accel=self.behavior.params.get(
                'air_max_yaw_accel', 0.45),
            safe_transition=safe_transition)
        agent.loiter_target = tuple(target)

    def _align_initial_air_heading(self, agent, path):
        """Align a newly launched aircraft once, before its first translation."""
        if (not agent.can_climb or agent.altitude <= 0
                or agent.odometer > 1e-6
                or agent.heading_initialized):
            return
        start = (agent.x, agent.y)
        for point in (path or [])[1:]:
            dx, dy = float(point[0]) - start[0], float(point[1]) - start[1]
            if math.hypot(dx, dy) > 0.1:
                agent.yaw = math.atan2(dy, dx)
                agent.air_turn_rate = 0.0
                agent.heading_initialized = True
                return

    # ---- 目标点 → 路径 ----
    def replace_agent(self, old_pid, new_pid, start, speed, caps=None):
        """编成内改派：把行为状态机里的一个席位换到新平台。

        新平台从自己的当前位姿开始（不是旧平台的位姿），行为层随后按原
        角色/扇区/检查点给它派活；旧平台的跟随器、限速与盘旋状态清掉。
        """
        self.agents.pop(old_pid, None)
        self.behavior._effective_targets.pop(old_pid, None)
        cap = caps or {}
        can_climb = bool(cap.get('can_climb'))
        base_z = float(cap.get('start_z') or 0.0)
        air_alt = (self.behavior.params.get('air_altitude') or {})
        altitude = (max(base_z, float(air_alt.get(new_pid, base_z)))
                    if can_climb else 0.0)
        self.agents[new_pid] = AgentState(
            pid=new_pid, x=float(start[0]), y=float(start[1]),
            yaw=float(start[2]) if len(start) > 2 else 0.0,
            speed=float(speed), z=base_z, altitude=altitude,
            can_climb=can_climb, kind=str(cap.get('kind') or ''),
            air_v=cap.get('air_v', 0.0))
        self._followers.pop(old_pid, None)
        self._speed_scale.pop(old_pid, None)
        self._air_speed_scale.pop(old_pid, None)
        if hasattr(self.behavior, 'speeds'):
            self.behavior.speeds[new_pid] = float(speed)
        if hasattr(self.behavior, 'platform_caps'):
            self.behavior.platform_caps.pop(old_pid, None)
            self.behavior.platform_caps[new_pid] = dict(cap)
        if hasattr(self.behavior, 'replace_agent'):
            self.behavior.replace_agent(old_pid, new_pid, can_climb)
        return self.agents[new_pid]


    def _climb_rate(self):
        """爬升率（场景单位/步）；参数可调，缺省 8，约 0.8/拍。"""
        try:
            return max(1.0, float((self.behavior.params or {}).get('climb_rate', 8.0)))
        except (TypeError, ValueError):
            return 8.0

    def _log_route_failed(self, agent, target, reason):
        key = (agent.pid, round(target[0], 2), round(target[1], 2), reason)
        if key != getattr(self, '_last_fail', None):
            self._last_fail = key
            self.events.append(dict(t=round(self.time, 2), kind='route_failed',
                                    job_id=self._job, pid=agent.pid,
                                    reason=reason, target=target))

    def _plan_leg(self, agent, target):
        """规划一段路。出发点落在膨胀障碍里时吸附到最近可通行点再试。

        替身模式时代由 approach 路线的 nearest_free 兜底（mock_fleet 同款）；
        行为层改为从原始位姿直接起跑后必须自己兜：simple_city 的 J6 巡逻
        曾因 rover_01 出生点在膨胀圈内，start_in_obstacle 后永久 0 进度，
        该平台一直占着不放，连带 J5 每轮都因"成员忙"派不出去。吸附位移
        用 start_snapped 事件显式记录，不悄悄挪点、不计里程。
        """
        threat_plan = self._plan_threat_aware(agent, target, is_air=False)
        if threat_plan is not None:
            return threat_plan
        if getattr(self.nav, 'prefer_scoped_router', False):
            # Dense imported maps contain hundreds of real footprints.  The
            # unified 5 m risk router shares its grid cache with planning and
            # is materially faster than rebuilding a 1 m city NavMap for every
            # behavior leg.  Fall through to NavMap only if this route fails.
            scoped = self._plan_scoped_route(
                agent, target, is_air=False)
            if scoped is not None and len(scoped.get('path') or []) >= 2:
                return scoped
        # 连续巡逻与侦察用平滑后的折点，避免密集短航点在高速转向时诱发绕点。
        options = dict(densify=0 if self.continuous else 0.5,
                       corner_radius=turn_radius_for(agent.kind or 'UGV', agent.speed))
        try:
            return self.nav.plan((agent.x, agent.y), target, **options)
        except city_nav.NavError as exc:
            if str(exc) != 'start_in_obstacle':
                self._log_route_failed(agent, target, str(exc))
                return None
            try:
                snapped, offset = self.nav.nearest_free(
                    (agent.x, agent.y), max_radius=6.0)
            except city_nav.NavError:
                self._log_route_failed(agent, target, str(exc))
                return None
            self.events.append(dict(
                t=round(self.time, 2), kind='start_snapped',
                job_id=self._job, pid=agent.pid,
                from_pose=[round(agent.x, 2), round(agent.y, 2)],
                to=[round(snapped[0], 2), round(snapped[1], 2)],
                offset=round(offset, 2),
                note='出生/当前点在膨胀障碍内，吸附到最近可通行点'))
            agent.x, agent.y = float(snapped[0]), float(snapped[1])
            try:
                return self.nav.plan((agent.x, agent.y), target, **options)
            except city_nav.NavError as exc2:
                self._log_route_failed(agent, target, str(exc2))
                return None

    def _plan_air_leg(self, agent, target):
        """规划空中平台到下一行为目标的避威胁折线。

        空地共用的 NavMap 不能直接复用：对空威胁不应阻塞地面平台，
        对地威胁也不应改变飞行路线。这里只使用 air/all 作用域的威胁图。
        """
        scoped_plan = self._plan_scoped_route(
            agent, target, is_air=True)
        if scoped_plan is not None:
            return scoped_plan
        if self.air_nav is None:
            return None
        try:
            return self.air_nav.plan((agent.x, agent.y), target, densify=0)
        except city_nav.NavError as exc:
            self._log_route_failed(agent, target, str(exc))
            return None

    def _plan_scoped_route(self, agent, target, is_air):
        """按地面/空中和巡航高度规划硬障碍与威胁航段。"""
        avoid_threats = bool(getattr(self.nav, 'avoid_threats', False))
        router = (getattr(self.nav, 'threat_router', None)
                  if avoid_threats
                  else getattr(self.nav, 'route_router', None))
        if router is None:
            return None
        start = (agent.x, agent.y)
        goal = (float(target[0]), float(target[1]))
        try:
            route = router.route(
                start, goal, is_air=bool(is_air),
                altitude_m=agent.altitude if is_air else None)
        except ValueError as exc:
            self._log_route_failed(agent, target, 'threat_route:%s' % exc)
            # 暴露度模式没有安全路径时停在当前位置。退回直飞/直走会把
            # 已确认的风险规避重新变成穿区路线。
            return dict(
                path=[[agent.x, agent.y]],
                length=0.0,
                straight_length=distance(start, goal),
                straight_line_ok=False,
                min_clearance=None,
                mode='threat_route_blocked',
                route_source='threat_aware_route')
        return dict(
            path=[[float(p[0]), float(p[1])] for p in route.path],
            length=route.length_m,
            straight_length=distance(start, goal),
            straight_line_ok=bool(len(route.path) == 2),
            min_clearance=router.threat_clearance_m,
            mode=(('air_threat_astar' if avoid_threats else 'air_scope_route')
                  if is_air else 'ground_threat_astar'),
            route_source=('threat_aware_route' if avoid_threats
                          else 'scoped_route'))

    def _plan_threat_aware(self, agent, target, is_air):
        """暴露度目标仍使用带安全间隔的威胁路由器。"""
        if not getattr(self.nav, 'avoid_threats', False):
            return None
        return self._plan_scoped_route(agent, target, is_air)

    def _safe_air_target(self, agent, target):
        """把空中行为目标投影到 air/all 威胁区外。

        盘旋、环绕观察等行为可能在威胁区内生成下一拍目标。若直接交给
        ``NavMap.plan``，规划会以 ``goal_in_obstacle`` 失败，调用方随后
        退回直飞，飞机就会从威胁区中间穿过去。
        """
        threat_map = (
            getattr(self.nav, 'air_threat_map', None)
            or self.air_nav)
        if (target is None or threat_map is None
                or not agent.can_climb or agent.altitude <= 0):
            return target
        try:
            # A point projected only a few centimetres outside an inflated
            # threat boundary is technically safe but impossible for a
            # rate-limited fixed-wing aircraft to hold.  Keep a goal margin
            # that leaves enough room to turn and establish a stable orbit.
            # The value can be tuned by the scenario without changing the
            # threat semantics.
            goal_margin = max(
                0.0, float((self.behavior.params or {}).get(
                    'air_goal_clearance_m', 3.0)))
            safe_radius = max(
                float(getattr(threat_map, 'radius', 0.0) or 0.0),
                float(getattr(threat_map, 'radius', 0.0) or 0.0)
                + goal_margin)
            if threat_map.free(target, radius=safe_radius):
                return target
            x0, y0, x1, y1 = threat_map.bounds
            span = max(float(x1) - float(x0), float(y1) - float(y0))
            safe, _ = threat_map.nearest_free(
                target, max_radius=max(8.0, span), step=0.25,
                radius=safe_radius)
            return safe
        except city_nav.NavError as exc:
            self._log_route_failed(agent, target, 'safe_air_goal:%s' % exc)
            # 找不到安全目标时停在当前位置，不能为追赶不合法目标而主动
            # 飞入适用威胁区。
            return [agent.x, agent.y]

    def _follower_for(self, pid):
        follower = self._followers.get(pid)
        if follower is None:
            agent = self.agents.get(pid)
            speed = float(getattr(agent, 'speed', 0.8) or 0.8)
            # 跟随器参数要跟速度同量级：一拍走 ``speed*dt`` 米，若航点容差
            # 只有 0.35 m，高速平台会"一步跨过航点"，前瞻点落到身后，于是
            # 原地打转。容差/前瞻按每拍位移放大，小场景（0.8 m/s）保持原值。
            limits = limits_for(agent.kind or "UGV", speed)
            step_move = max(speed * self.dt, 1e-3)
            follower = PathFollower(
                max_linear=max(0.2, speed),
                max_angular=limits.max_yaw_rate,
                max_linear_accel=limits.max_accel,
                max_linear_decel=limits.max_decel,
                max_angular_accel=limits.max_yaw_accel,
                max_lateral_accel=limits.max_lateral_accel,
                lookahead=max(1.0, 3.0 * step_move),
                waypoint_tol=max(0.35, 1.6 * step_move))
            self._followers[pid] = follower
        # 行为层可以给"限速系数"：区域封控的占位/门哨在岗时按巡逻速度走，
        # 前出拦阻恢复全速。跟随器缓存复用，这里每步刷新上限即可。
        agent = self.agents.get(pid)
        if agent is not None:
            scale = float(self._speed_scale.get(pid, 1.0))
            follower.max_linear = max(0.2, float(agent.speed) * scale)
        return follower

    def _ground_separation_scale(self, agent):
        """Ease a trailing ground platform when it closes on its leader.

        Static A* paths only avoid map obstacles, so several platforms routed
        through the same corridor can share almost the same centre line.  The
        planner's staging slots are distinct, but the bodies still overlap for
        tens of seconds while catching up.  Compare remaining target distance
        and yield to the platform already ahead along the route.  This is a
        small longitudinal speed guard: it keeps the convoy separated without
        changing the planned target or adding another artificial wait.
        """
        if agent.can_climb and agent.altitude > 0 or agent.target is None:
            return 1.0
        ground = [
            other for other in self.agents.values()
            if other.pid != agent.pid
            and not (other.can_climb and other.altitude > 0)
        ]
        if not ground and not self.peer_ground_positions:
            return 1.0
        nav_radius = max(0.0, float(getattr(self.nav, 'radius', 0.0) or 0.0))
        safe_gap = max(3.0, nav_radius * 2.8)
        stop_gap = max(1.6, nav_radius * 1.5)
        own_remaining = distance((agent.x, agent.y), agent.target)
        scale = 1.0
        for other in ground:
            gap = distance((agent.x, agent.y), (other.x, other.y))
            if gap >= safe_gap:
                continue
            if other.target is None:
                other_ahead = other.pid < agent.pid
            else:
                other_remaining = distance((other.x, other.y), other.target)
                # A platform already parked on its own distinct staging slot is
                # an endpoint, not a moving convoy leader.  Let the arriving
                # platform pass it; otherwise dense ring slots deadlock at the
                # boundary while one parker "owns" the corridor forever.
                if other_remaining <= 0.45:
                    continue
                # The platform closer to its assigned slot has right of way.
                # Use platform id to break a near tie deterministically so two
                # platforms never both stop at the same separation boundary.
                other_ahead = (
                    other_remaining + 0.2 < own_remaining
                    or (abs(other_remaining - own_remaining) <= 0.2
                        and other.pid < agent.pid))
            if not other_ahead:
                continue
            local = ((gap - stop_gap) / max(safe_gap - stop_gap, 1e-6))
            scale = min(scale, max(0.0, min(1.0, local)))
        # Other jobs share the same map but have their own runners.  The list
        # is refreshed by MockFleet before every behaviour step.  A stable
        # platform-id priority breaks the otherwise mutual "both stop" case:
        # the higher id yields until the lower-id platform clears the shared
        # corridor.  This is a temporary speed reduction, not a teleport.
        peer_safe_gap = max(4.5, safe_gap)
        peer_stop_gap = max(2.4, stop_gap)
        for pid, point in sorted(self.peer_ground_positions.items()):
            if pid >= agent.pid or len(point) < 2:
                continue
            gap = distance((agent.x, agent.y), (point[0], point[1]))
            if gap >= peer_safe_gap:
                continue
            local = ((gap - peer_stop_gap)
                     / max(peer_safe_gap - peer_stop_gap, 1e-6))
            scale = min(scale, max(0.0, min(1.0, local)))
        return scale

    def _set_target(self, agent, target, force=False,
                    planned_route=None, pursuit=False, now=None):
        """设定目标点并规划路径；``force`` 用于安全投影触发重规划时强制重算。

        原先重规划分支调用 ``_set_target(agent, agent.target)`` 会因"目标没变"
        直接返回，跟随器拿着旧路径每拍再触发一次安全投影，形成原地打转
        （仿真 300 拍仍停在原地，占位永远凑不齐）。
        """
        source_target = ([float(target[0]), float(target[1])]
                         if target is not None else None)
        target = self._safe_air_target(agent, target)
        if target is None:
            return
        target = [float(target[0]), float(target[1])]
        agent._requested_target = list(source_target or target)
        now = float(self.time if now is None else now)
        if source_target is not None and agent.can_climb and agent.altitude > 0:
            # 行为层保留原始航点，到点判定认安全投影点。否则飞机到达
            # 威胁区边界后会停在原地，状态机却永远等待区内的原坐标。
            if hasattr(self.behavior, 'set_effective_target'):
                self.behavior.set_effective_target(
                    agent.pid, source_target, target)
            key = (agent.pid,
                   round(source_target[0], 2), round(source_target[1], 2),
                   round(target[0], 2), round(target[1], 2))
            if (distance(source_target, target) > 0.05
                    and key != self._last_safe_targets.get(agent.pid)):
                self._last_safe_targets[agent.pid] = key
                self.events.append(dict(
                    t=round(self.time, 2), kind='waypoint_safe_projection',
                    job_id=self._job, pid=agent.pid,
                    logical_target=[round(v, 2) for v in source_target],
                    effective_target=[round(v, 2) for v in target],
                    reason='air_threat_avoidance'))
        moved = (0.0 if agent.target is None
                 else distance(target, agent.target))
        if agent.target is not None:
            if moved > 1e-6:
                dt = max(0.05, now - agent.target_time)
                agent.target_vel = (
                    (target[0] - agent.target[0]) / dt,
                    (target[1] - agent.target[1]) / dt)
                agent.target_time = now
                hold = 10.0 if math.hypot(*agent.target_vel) > 0.5 else 2.0
                agent.target_moving_until = now + hold
                agent.loiter = None
            if not force and moved < 0.35:
                agent.target_moving = now < agent.target_moving_until
                return
        else:
            agent.target_time = now
            agent.target_vel = (0.0, 0.0)
        agent.target_moving = now < agent.target_moving_until
        dynamic_target = (agent.target is not None and moved >= 0.35
                          and (pursuit or agent.target_moving))
        if (dynamic_target and not force and planned_route is None
                and agent.path
                and now - agent.last_route_plan_t
                < self.dynamic_replan_interval_s):
            # Keep following the last validated route until its update
            # deadline.  Crucially, do not overwrite agent.target: the next
            # tick must still see the accumulated target displacement and
            # eventually trigger a real replan.
            return
        agent.last_route_plan_t = now
        if planned_route is not None:
            plan = dict(planned_route)
            plan.setdefault('route_source', 'planned_threat_route')
            agent.target = target
            agent.path = plan['path']
            previous = agent.follow
            agent.follow = self._follower_for(agent.pid).reset()
            if (pursuit and previous is not None
                    and not previous.replan
                    and hasattr(previous, "v")
                    and hasattr(previous, "w")):
                agent.follow.v, agent.follow.w = previous.v, previous.w
            agent.path_meta = plan
            self._align_initial_air_heading(agent, agent.path)
            self.routes.append(dict(pid=agent.pid, job_id=self._job,
                                    t=round(self.time, 2),
                                    from_pose=[round(agent.x, 2), round(agent.y, 2),
                                               round(agent.z, 2)],
                                    to=target, path=[[round(p[0], 2), round(p[1], 2)]
                                                     for p in plan['path']],
                                    length=plan['length'],
                                    straight=plan['straight_length'],
                                    straight_line_ok=plan['straight_line_ok'],
                                    min_clearance=plan['min_clearance'],
                                    mode='planned_threat_route'))
            return
        air_plan = (self._plan_air_leg(agent, target)
                    if agent.can_climb and agent.altitude > 0 else None)
        if air_plan is not None:
            agent.target = target
            agent.path = air_plan['path']
            previous = agent.follow
            agent.follow = self._follower_for(agent.pid).reset()
            if (pursuit and previous is not None
                    and not previous.replan
                    and hasattr(previous, "v")
                    and hasattr(previous, "w")):
                agent.follow.v, agent.follow.w = previous.v, previous.w
            agent.path_meta = dict(
                air_plan, mode=air_plan.get('mode', 'air_threat_astar'),
                route_source=air_plan.get('route_source',
                                          'planned_threat_route'),
                altitude=agent.altitude)
            self._align_initial_air_heading(agent, agent.path)
            self.routes.append(dict(
                pid=agent.pid, job_id=self._job, t=round(self.time, 2),
                from_pose=[round(agent.x, 2), round(agent.y, 2),
                           round(agent.z, 2)],
                to=target,
                path=[[round(p[0], 2), round(p[1], 2)]
                      for p in air_plan['path']],
                length=air_plan['length'],
                straight=air_plan['straight_length'],
                straight_line_ok=air_plan['straight_line_ok'],
                min_clearance=air_plan['min_clearance'],
                mode=air_plan.get('mode', 'air_threat_astar'),
                altitude=agent.altitude))
            return
        if agent.can_climb and agent.altitude > 0:
            # 空中平台越障直飞：已知静态建筑高度低于巡航高度，2D 地图上的
            # 膨胀障碍不适用。航路仍记录直线长度，便于核对"直飞 vs 绕行"。
            # 注意：只有配了巡航高度（air_altitude）的空中平台才直飞；
            # 没配高度的飞机仍按地面 A* 处理，避免"z=0 却穿楼"。
            straight = distance((agent.x, agent.y), target)
            agent.target = target
            agent.path = [[agent.x, agent.y], [target[0], target[1]]]
            agent.follow = self._follower_for(agent.pid).reset()
            agent.path_meta = dict(length=straight, straight_length=straight,
                                   straight_line_ok=True, min_clearance=None,
                                   mode='air_direct', altitude=agent.altitude)
            self._align_initial_air_heading(agent, agent.path)
            self.routes.append(dict(pid=agent.pid, job_id=self._job,
                                    t=round(self.time, 2),
                                    from_pose=[round(agent.x, 2), round(agent.y, 2),
                                               round(agent.z, 2)],
                                    to=target,
                                    path=[p[:] for p in agent.path],
                                    length=straight, straight=straight,
                                    straight_line_ok=True, min_clearance=None,
                                    mode='air_direct', altitude=agent.altitude))
            return
        planning_target = target
        if pursuit and math.hypot(*agent.target_vel) > 0.2:
            # Aim ahead of a moving station so reaching last tick's point
            # does not repeatedly stop the acceleration-limited follower.
            horizon = min(0.8, 4.0 / max(math.hypot(*agent.target_vel), 1e-6))
            predicted = [target[0] + agent.target_vel[0] * horizon,
                         target[1] + agent.target_vel[1] * horizon]
            if self.nav.segment_free(target, predicted):
                planning_target = predicted
        plan = self._plan_leg(agent, planning_target)
        if plan is None:
            return
        agent.target = target
        agent.path = plan['path']
        previous = agent.follow
        agent.follow = self._follower_for(agent.pid).reset()
        if (pursuit and previous is not None
                and not previous.replan
                and hasattr(previous, "v")
                and hasattr(previous, "w")):
            agent.follow.v, agent.follow.w = previous.v, previous.w
        agent.path_meta = plan
        self.routes.append(dict(pid=agent.pid, job_id=self._job,
                                t=round(self.time, 2),
                                from_pose=[round(agent.x, 2), round(agent.y, 2),
                                           round(agent.z, 2)],
                                to=target, path=[[round(p[0], 2), round(p[1], 2)]
                                                 for p in plan['path']],
                                length=plan['length'],
                                straight=plan['straight_length'],
                                straight_line_ok=plan['straight_line_ok'],
                                min_clearance=plan['min_clearance'],
                                mode=plan.get('mode', 'ground_astar')))

    # ---- 单步 ----
    def _advance_polyline(self, agent, speed_scale=1.0):
        """按规划折线逐段移动，不能只瞄准最后一个航点。

        统一规划器可能为了绕开“对空/空地”威胁区给出多个中间航点。
        旧实现每一步都直接朝 ``path[-1]`` 移动，等于把绕行折线压回
        起终点直线，平台因此会重新穿过本应规避的威胁区。执行安全航路
        时严格沿折线走，避免前瞻跟随器用曲线切掉威胁区角的保护余量。
        """
        if not agent.path:
            return
        state = agent.follow
        if state is None:
            state = self._follower_for(agent.pid).reset()
            agent.follow = state
        while (state.index < len(agent.path) - 1
               and distance((agent.x, agent.y),
                            agent.path[state.index]) <= 0.35):
            state.index += 1
        target = agent.path[min(state.index, len(agent.path) - 1)]
        dx, dy = target[0] - agent.x, target[1] - agent.y
        remaining = math.hypot(dx, dy)
        if remaining <= 1e-9:
            if state.index >= len(agent.path) - 1:
                state.done = True
            else:
                state.index += 1
            return
        agent.yaw = math.atan2(dy, dx)
        speed = (agent.speed * float(speed_scale)
                 * self._ground_separation_scale(agent))
        step = min(speed * self.dt, remaining)
        agent.x += dx / remaining * step
        agent.y += dy / remaining * step
        agent.odometer += step
        if remaining <= step + 0.35:
            agent.x, agent.y = float(target[0]), float(target[1])
            if state.index >= len(agent.path) - 1:
                state.done = True
            else:
                state.index += 1

    def _air_safe_radius(self, threat_map):
        base = float(getattr(threat_map, 'radius', 0.0) or 0.0)
        margin = max(
            0.0, float((self.behavior.params or {}).get(
                'air_goal_clearance_m', 3.0)))
        return base + margin

    def _advance_air_out_of_threat(self, agent, threat_map):
        """Leave an initial/current threat overlap under kinematic limits.

        Threat regions are soft constraints.  If a platform is already inside
        one, a strict ``segment_free`` check would reject every forward move
        and trap the aircraft permanently.  Navigate to the nearest point
        outside the threat envelope first; once clear, normal route avoidance
        resumes.
        """
        limit = limits_for(agent, agent.speed)
        current = (agent.x, agent.y)
        exit_target = agent.threat_exit_target
        if exit_target is None or distance(current, exit_target) <= 0.35:
            x0, y0, x1, y1 = threat_map.bounds
            span = max(float(x1) - float(x0), float(y1) - float(y0))
            try:
                exit_target, _ = threat_map.nearest_free(
                    current, max_radius=max(8.0, span), step=0.75,
                    radius=self._air_safe_radius(threat_map))
            except city_nav.NavError:
                return False
            agent.threat_exit_target = [
                float(exit_target[0]), float(exit_target[1])]
            self.events.append(dict(
                t=round(self.time, 2), kind='air_threat_escape',
                job_id=self._job, pid=agent.pid,
                from_pose=[round(current[0], 2), round(current[1], 2)],
                exit_target=[round(exit_target[0], 2),
                             round(exit_target[1], 2)],
                reason='initial_threat_overlap'))
        exit_target = agent.threat_exit_target
        dx, dy = exit_target[0] - agent.x, exit_target[1] - agent.y
        remaining = math.hypot(dx, dy)
        if remaining <= 1e-9:
            agent.threat_exit_target = None
            return False

        desired_yaw = math.atan2(dy, dx)
        heading_error = clamp_angle(desired_yaw - agent.yaw)
        yaw_command = max(
            -limit.max_yaw_rate,
            min(limit.max_yaw_rate, 2.2 * heading_error))
        agent.air_turn_rate = approach(
            float(getattr(agent, 'air_turn_rate', 0.0)),
            yaw_command, limit.max_yaw_accel * self.dt)
        agent.air_turn_rate = max(
            -limit.max_yaw_rate,
            min(limit.max_yaw_rate, agent.air_turn_rate))
        agent.yaw = clamp_angle(
            agent.yaw + agent.air_turn_rate * self.dt)

        max_speed = max(
            0.05,
            float(agent.speed)
            * float(self._air_speed_scale.get(agent.pid, 1.0)))
        alignment = max(0.0, math.cos(heading_error))
        desired_speed = max_speed * max(0.18, alignment)
        if abs(heading_error) > math.pi / 2:
            desired_speed = max_speed * 0.18
        agent.air_v = approach(
            float(agent.air_v), desired_speed,
            max(1.5, limit.max_accel) * self.dt
            if desired_speed >= agent.air_v
            else max(2.0, limit.max_decel) * self.dt)
        step = agent.air_v * self.dt
        candidate = (
            agent.x + step * math.cos(agent.yaw),
            agent.y + step * math.sin(agent.yaw))
        # While inside the region any forward move that reduces the remaining
        # exit distance is valid; movement that heads deeper is held until the
        # bounded turn brings the aircraft onto the exit bearing.
        if distance(candidate, exit_target) <= remaining + 1e-9:
            agent.x, agent.y = candidate
            agent.odometer += step
        else:
            agent.air_v = max(
                0.0, agent.air_v
                - max(2.0, limit.max_decel) * self.dt)
        if threat_map.free((agent.x, agent.y)):
            agent.threat_exit_target = None
        return True

    def _advance_air(self, agent):
        """Advance a fixed-wing aircraft with bounded speed and yaw changes.

        A route is a sequence of desired positions, not a sequence of teleports.
        The old implementation copied each segment bearing straight into
        ``agent.yaw`` and then moved in the new direction during the same
        0.1 s tick.  In replay this looked like instant pivots, backwards
        motion, and tangled sweep lines even though the stored waypoints were
        valid.  Here the aircraft keeps a forward speed, limits yaw and yaw
        acceleration, slows for sharp turns, and always moves along its actual
        heading.
        """
        if not agent.path:
            agent.air_v = max(
                0.0, agent.air_v - limits_for(agent, agent.speed).max_decel * self.dt)
            return
        threat_map = (getattr(self.nav, 'air_threat_map', None)
                      or self.air_nav)
        if (threat_map is not None
                and not threat_map.free((agent.x, agent.y))
                and self._advance_air_out_of_threat(agent, threat_map)):
            return
        state = agent.follow
        if state is None:
            state = self._follower_for(agent.pid).reset()
            agent.follow = state
        effective_speed = max(
            0.05,
            float(agent.speed)
            * float(self._air_speed_scale.get(agent.pid, 1.0)))
        # Turn geometry must use the speed the aircraft is actually allowed
        # to fly.  Using the platform's raw 25--30 m/s envelope after a patrol
        # speed scale had already reduced it to 3 m/s produced a 50--60 m
        # corner-pass radius inside a 40 m task area, so the aircraft skipped
        # waypoints and wandered away from the assigned boundary.
        limits = limits_for(agent, effective_speed)

        # A route starts at the current pose; consume coincident waypoints and
        # any vertex already passed.  Fixed-wing aircraft also advance before
        # coinciding with an intermediate corner: their minimum turn radius is
        # larger than a planner vertex tolerance, so waiting for 0.5 m makes
        # them orbit the same corner forever.  The next segment is still flown
        # under the bounded-yaw and threat/footprint checks below.
        turn_radius = max(2.0, float(limits.min_turn_radius))
        planned_threat_route = (
            ((getattr(agent, 'path_meta', None) or {}).get('route_source')
             in ('planned_threat_route', 'threat_aware_route',
                 'scoped_route')))
        # A globally planned threat-avoidance polyline owns its clearance.
        # Switching to the next leg one turn-radius early can cut across the
        # protected side of a corner even though the planned centreline was
        # safe.  Patrol/direct air legs still use the larger pass radius so a
        # fixed wing does not circle a transient station forever.
        corner_pass_radius = min(30.0, 0.85 * turn_radius)
        if planned_threat_route:
            # The global route already carries the safety margin.  Consume a
            # planned corner only just before it is crossed; a full turn-radius
            # look-ahead is useful for transient patrol points but would shift
            # the arc into the protected side of the planned corner.
            corner_pass_radius = min(corner_pass_radius, 4.0)
        while state.index < len(agent.path) - 1:
            current = agent.path[state.index]
            following = agent.path[state.index + 1]
            current_distance = distance((agent.x, agent.y), current)
            following_distance = distance((agent.x, agent.y), following)
            early_corner_switch = current_distance <= corner_pass_radius
            if planned_threat_route and early_corner_switch and threat_map is not None:
                # Releasing a corner early is what keeps a fixed wing from
                # orbiting it forever.  For a threat-avoidance route, that is
                # only allowed when the direct chord to the next waypoint is
                # still clear; otherwise the cut-corner arc can cross the very
                # risk area the saved polyline was meant to avoid.
                early_corner_switch = threat_map.segment_free(
                    (agent.x, agent.y), following)
            if (current_distance <= 0.5
                    or early_corner_switch
                    or following_distance + 1e-9 < current_distance):
                state.index += 1
                continue
            break

        target = agent.path[min(state.index, len(agent.path) - 1)]
        dx, dy = float(target[0]) - agent.x, float(target[1]) - agent.y
        remaining = math.hypot(dx, dy)
        # Behaviour checkpoints use a 0.35 m "reached" tolerance.  Declaring
        # route completion earlier leaves scan/patrol logic waiting at outside
        # its own threshold while the fixed-wing has already stopped.
        if remaining <= 0.35:
            if state.index >= len(agent.path) - 1:
                state.done = True
                agent.air_v = max(
                    0.0, agent.air_v
                    - limits_for(agent, agent.speed).max_decel * self.dt)
                return
            state.index += 1
            target = agent.path[state.index]
            dx, dy = float(target[0]) - agent.x, float(target[1]) - agent.y
            remaining = math.hypot(dx, dy)
        if remaining <= 1e-9:
            state.done = state.index >= len(agent.path) - 1
            return

        max_speed = effective_speed
        desired_yaw = math.atan2(dy, dx)
        heading_error = clamp_angle(desired_yaw - agent.yaw)

        # Bound both angular rate and angular acceleration.  The first turn
        # from a parked/formation heading cannot be written directly into yaw.
        old_yaw = agent.yaw
        old_turn_rate = float(getattr(agent, 'air_turn_rate', 0.0))
        yaw_command = max(
            -limits.max_yaw_rate,
            min(limits.max_yaw_rate, 2.2 * heading_error))
        yaw_rate = old_turn_rate
        yaw_rate = approach(
            yaw_rate, yaw_command, limits.max_yaw_accel * self.dt)
        yaw_rate = max(-limits.max_yaw_rate,
                       min(limits.max_yaw_rate, yaw_rate))
        agent.air_turn_rate = yaw_rate
        agent.yaw = clamp_angle(old_yaw + yaw_rate * self.dt)

        # Slow down for large heading errors and sharp upcoming corners.
        alignment = max(0.0, math.cos(heading_error))
        desired_speed = max_speed * max(0.18, alignment)
        if abs(heading_error) > math.pi / 2:
            desired_speed = max_speed * 0.18
        if state.index < len(agent.path) - 1 and remaining < max(
                3.0, 0.65 * max_speed):
            next_point = agent.path[state.index + 1]
            turn = abs(clamp_angle(
                math.atan2(next_point[1] - target[1],
                           next_point[0] - target[0])
                - desired_yaw))
            if turn > math.radians(30):
                desired_speed = max(max_speed * 0.16,
                                    desired_speed * (1.0 - turn / math.pi))

        # High-level aircraft acceleration is deliberately stronger than the
        # conservative table base (which is retained for reporting): the table
        # value makes a 30 m/s aircraft need roughly a minute to accelerate,
        # pushing otherwise valid task windows past their deadlines.
        acceleration = (max(1.5, limits.max_accel)
                        if desired_speed >= agent.air_v
                        else max(2.0, limits.max_decel))
        agent.air_v = approach(
            float(agent.air_v), desired_speed, acceleration * self.dt)
        agent.air_v = max(0.0, min(max_speed, agent.air_v))

        step = agent.air_v * self.dt
        candidate = (
            (float(target[0]), float(target[1]))
            if remaining <= step and abs(heading_error) <= math.pi / 3
            else (agent.x + step * math.cos(agent.yaw),
                  agent.y + step * math.sin(agent.yaw)))
        old_position = (agent.x, agent.y)
        if (threat_map is not None
                and not threat_map.segment_free(old_position, candidate)):
            # A bounded turn can still produce a short arc across an inflated
            # threat boundary.  Try equally bounded steering alternatives.  If
            # none is safe, hold position for this control tick while the
            # heading continues to turn; direct waypoint teleportation would
            # violate the aircraft's rate limits and caused the tangled paths.
            accel_step = limits.max_yaw_accel * self.dt
            rate_low = max(
                -limits.max_yaw_rate, old_turn_rate - accel_step)
            rate_high = min(
                limits.max_yaw_rate, old_turn_rate + accel_step)
            rate_candidates = sorted(
                {yaw_rate, old_turn_rate, rate_low, rate_high},
                key=lambda rate: abs(rate - yaw_command))
            chosen = None
            for candidate_rate in rate_candidates:
                candidate_yaw = clamp_angle(
                    old_yaw + candidate_rate * self.dt)
                for fraction in (1.0, 0.5, 0.25):
                    candidate_step = step * fraction
                    candidate_position = (
                        old_position[0]
                        + candidate_step * math.cos(candidate_yaw),
                        old_position[1]
                        + candidate_step * math.sin(candidate_yaw))
                    if threat_map.segment_free(
                            old_position, candidate_position):
                        chosen = (
                            candidate_rate, candidate_yaw,
                            candidate_position, candidate_step)
                        break
                if chosen is not None:
                    break
            if chosen is None:
                agent.air_turn_rate = yaw_rate
                agent.air_v = max(
                    0.0, agent.air_v
                    - max(2.0, limits.max_decel) * self.dt)
                # If the planned global polyline was reached at an awkward
                # heading, the rate-limited aircraft can no longer find a
                # safe forward tangent.  Rebuild the short leg from the real
                # current pose instead of waiting forever at the boundary.
                # The local route still starts at the current point, so this
                # is a planning update, never a positional teleport.
                local_goal = (
                    [float(agent.target[0]), float(agent.target[1])]
                    if agent.target is not None
                    else [float(target[0]), float(target[1])])
                try:
                    local = threat_map.plan(
                        old_position, local_goal, densify=0)
                except city_nav.NavError:
                    return
                agent.path = [
                    [float(point[0]), float(point[1])]
                    for point in local['path']]
                agent.follow = self._follower_for(agent.pid).reset()
                key = (
                    agent.pid, round(old_position[0], 1),
                    round(old_position[1], 1), round(target[0], 1),
                    round(target[1], 1))
                if key != getattr(self, '_last_air_local_replan', None):
                    self._last_air_local_replan = key
                    self.events.append(dict(
                        t=round(self.time, 2), kind='air_local_replan',
                        job_id=self._job, pid=agent.pid,
                        from_pose=[round(old_position[0], 2),
                                   round(old_position[1], 2)],
                        target=[round(local_goal[0], 2),
                                round(local_goal[1], 2)],
                        reason='rate_limited_safe_tangent'))
                return
            agent.air_turn_rate, agent.yaw, candidate, step = chosen
        if remaining <= step and abs(
                clamp_angle(math.atan2(dy, dx) - agent.yaw)
                ) <= math.pi / 3:
            agent.x, agent.y = candidate
            step = remaining
        else:
            agent.x, agent.y = candidate
        agent.odometer += step
        if remaining <= step + 0.35:
            if state.index >= len(agent.path) - 1:
                state.done = True
            else:
                state.index += 1

    def _advance_behavior(self, t, dt):
        poses = {pid: (a.x, a.y, a.yaw) for pid, a in self.agents.items()}
        out = self.behavior.step(poses, t, dt)
        self._speed_scale = out.get('speed_scale') or {}
        self._air_speed_scale = out.get('air_speed_scale') or {}
        debug = self.behavior.debug() if hasattr(self.behavior, 'debug') else {}
        targets = out.get('targets') or {}
        phase = out.get('phase') or self.behavior.phase
        if phase != self._last_phase:
            self._last_phase = phase
            self.events.append(dict(t=round(t, 2), kind='phase',
                                    job_id=self._job, phase=phase))
        routes = out.get('planned_routes') if isinstance(out, dict) else None
        pursuit_pids = set(out.get('pursuit_pids') or ())
        for pid, agent in self.agents.items():
            target = targets.get(pid)
            radius = (out.get('loiter_radius') or {}).get(pid)
            if radius is not None and agent.altitude > 0 and target is not None:
                if (agent.loiter is None
                        or agent.loiter_target is None
                        or distance(agent.loiter_target, target) > 0.35
                        or agent.loiter_requested_radius != float(radius)):
                    self._set_air_loiter(agent, target, radius)
                continue
            # _set_target owns orbit exit when the target actually changes.
            # Clearing a stationary orbit every control tick makes the aircraft
            # alternate between an old approach segment and a fresh orbit.
            if target is None and agent.loiter is not None:
                agent.loiter = None
            self._set_target(agent, target,
                             planned_route=(routes or {}).get(pid),
                             pursuit=pid in pursuit_pids, now=t)
        return out, phase, debug

    def step(self, record_motion=None):
        out, phase, debug = self._advance_behavior(
            self.time, self.dt if self.continuous else 1.0)
        if (not self._inside and self.behavior.kind != 'assault'
                and distance((self.agents[self.behavior.pids[0]].x,
                              self.agents[self.behavior.pids[0]].y),
                             self._site) < max(4.0, getattr(
                                 self.behavior, 'params', {}).get(
                                 'ring_radius', 4.0))):
            self._inside = True
            self.events.append(dict(t=round(self.time, 2), kind='arrived_area',
                                    job_id=self._job))
        # 步内 10 拍闭环跟随
        for k in range(self.ticks_per_step):
            if k and self.continuous and not out.get('done'):
                out, phase, debug = self._advance_behavior(self.time + k * self.dt, self.dt)
            if self.continuous and out.get('done'):
                break
            before_poses = {pid:(a.x,a.y,a.z,a.yaw) for pid,a in self.agents.items()} if record_motion else {}
            for agent in self.agents.values():
                if agent.can_climb and agent.altitude > 0:
                    if agent.loiter is not None:
                        pose, moved = agent.loiter.step(
                            Pose(agent.x, agent.y, agent.z, agent.yaw),
                            self.dt)
                        agent.x, agent.y = pose.x, pose.y
                        agent.yaw = pose.yaw
                        agent.odometer += moved
                    else:
                        # 空中平台同样按完整规划折线飞行；普通直飞路径只有
                        # 起点和终点，效果与原有空中直飞一致。
                        self._advance_air(agent)
                        if (agent.target is not None
                                # Moving waypoints already describe a flight
                                # path; reaching one must not start another
                                # circle around that transient waypoint.
                                and not agent.target_moving
                                # Recon/patrol routes are discrete scan or
                                # checkpoint targets; orbiting before reaching
                                # them prevents their own progress logic.
                                and not self.continuous
                                and distance((agent.x, agent.y),
                                             agent.target) <= max(
                                                 0.8, min(
                                                     12.0,
                                                     agent.speed * 0.45))):
                            # Fixed-wing aircraft normally enter a station
                            # holding pattern before reaching the exact target
                            # point.  Waiting for a sub-metre point capture
                            # makes a high-speed aircraft overshoot and circle
                            # forever because its minimum turn radius is much
                            # larger than the arrival tolerance.
                            self._set_air_loiter(agent, agent.target)
                    climb = self._climb_rate() * self.dt
                    if agent.z < agent.altitude:
                        agent.z = min(agent.altitude, agent.z + climb)
                    elif agent.z > agent.altitude:
                        agent.z = max(agent.altitude, agent.z - climb)
                    continue
                if ((getattr(agent, 'path_meta', None) or {}).get(
                        'route_source') in (
                            'planned_threat_route', 'threat_aware_route',
                            'scoped_route')):
                    # 威胁规避航路按折线逐段结算；普通道路仍由闭环跟随器
                    # 负责转向和平滑。这样计划线之外不会再出现曲线切角。
                    self._advance_polyline(
                        agent, self._speed_scale.get(agent.pid, 1.0))
                    continue
                if not agent.path or agent.follow is None:
                    continue
                # 风险规避路线由统一规划器同时检查了障碍与威胁；执行层
                # 再交给本地 NavMap 时，会把威胁区又当作硬障碍投影，
                # 在角点持续转向却不前进。
                follower_nav = (
                    None if ((getattr(agent, 'path_meta', None) or {}).get(
                        'route_source') == 'planned_threat_route')
                    else self.nav)
                v, w, state = self._follower_for(agent.pid).step(
                    agent.pose, agent.path, agent.follow, follower_nav, self.dt)
                agent.follow = state
                if state.replan:
                    state.replan = False
                    # 只转向不前进：把车头摆向可通行方向，下一拍重新判断。
                    # 若直接 continue，平台会原地卡死（既不动也不转）。
                    agent.yaw += w * self.dt
                    # 同一次卡住的连续重规划之间留 1 s 冷却，避免每拍都跑 A*。
                    last = getattr(agent, '_replan_at', -9.0)
                    if self.time - last >= 1.0:
                        agent._replan_at = self.time
                        # 威胁区是可穿越的风险区，不是撞墙。若安全投影因
                        # 风险区角点触发，而当前路径本身按规划规避威胁，
                        # 强制用本地 NavMap 重算反而会退回同一条贴角路径；
                        # 从当前位置接上原风险规避路线的剩余航点，交给
                        # 下一个航点解除卡位；若这一小段确实撞实体障碍，
                        # 再回退到本地硬障碍重规划。
                        if ((getattr(agent, 'path_meta', None) or {}).get(
                                'route_source')
                                == 'planned_threat_route'):
                            remaining = list(agent.path[state.index:])
                            if remaining and self.nav.segment_free(
                                    (agent.x, agent.y), remaining[0]):
                                agent.path = [[agent.x, agent.y]] + remaining
                                agent.follow = self._follower_for(
                                    agent.pid).reset()
                            else:
                                self._set_target(agent, agent.target,
                                                 force=True)
                        else:
                            self._set_target(agent, agent.target, force=True)
                    continue
                v *= self._ground_separation_scale(agent)
                agent.yaw += w * self.dt
                agent.x += v * math.cos(agent.yaw) * self.dt
                agent.y += v * math.sin(agent.yaw) * self.dt
                agent.odometer += abs(v) * self.dt
            # 每个内部控制拍都留位姿。回放若只保存"每秒端点"，一条先横移、
            # 再转向的绕角折线会被画成斜穿威胁区的直线，暴露统计也会误判。
            # 这里记录实际闭环位置，mock_fleet 再按步增量写入审计。
            if record_motion:
                for pid,a in self.agents.items():
                    action = "loiter" if a.loiter and a.z>0 else phase
                    record_motion(pid,k*self.dt,self.dt,action,before_poses[pid],(a.x,a.y,a.z,a.yaw))
            self.samples.append(dict(
                t=round(self.time + k * self.dt, 2), job=self._job,
                phase=phase,
                agents={pid: [round(a.x, 3), round(a.y, 3), round(a.yaw, 3),
                              round(a.z, 3)]
                        for pid, a in self.agents.items()},
                debug=debug))
        self.events.extend(self.behavior.drain())
        self.time += 1.0
        return out.get('done', False)

    def run(self, max_steps=260):
        for _ in range(max_steps):
            if self.step():
                break
        return self.result()

    def result(self):
        return dict(job_id=self._job, kind=self.behavior.kind,
                    label=self.behavior.label, site=[round(v, 2) for v in self._site],
                    phase=self.behavior.phase,
                    samples=self.samples, events=self.events,
                    routes=self.routes, metrics=self.behavior.metrics,
                    duration=round(self.time, 2))
