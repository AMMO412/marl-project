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
    path_meta: dict = None
    odometer: float = 0.0      # 累计行程（场景单位），供能耗记账

    @property
    def pose(self):
        return (self.x, self.y, self.yaw)


class BehaviorRunner:
    def __init__(self, nav, behavior, starts, speeds=None, dt=0.1,
                 ticks_per_step=10, caps=None):
        self.nav = nav
        self.behavior = behavior
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
                kind=str(cap.get('kind') or ''))
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
        # 行为层给出的"限速系数"（默认 1.0 = 平台全速）
        self._speed_scale = {}
        # 空中平台的盘旋限速单独放一张表：地面跟随器读 _speed_scale，
        # 空中直飞读这张，互不干扰（封控/坚守的既有速度不受影响）。
        self._air_speed_scale = {}
        self.behavior.speeds = speeds
        self._last_phase = None
        self._job = behavior.job_id
        self._site = list(behavior.site)
        self._inside = False

    # ---- 目标点 → 路径 ----
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
        try:
            return self.nav.plan((agent.x, agent.y), target)
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
                return self.nav.plan((agent.x, agent.y), target)
            except city_nav.NavError as exc2:
                self._log_route_failed(agent, target, str(exc2))
                return None

    def _follower_for(self, pid):
        follower = self._followers.get(pid)
        if follower is None:
            agent = self.agents.get(pid)
            speed = float(getattr(agent, 'speed', 0.8) or 0.8)
            # 跟随器参数要跟速度同量级：一拍走 ``speed*dt`` 米，若航点容差
            # 只有 0.35 m，高速平台会"一步跨过航点"，前瞻点落到身后，于是
            # 原地打转。容差/前瞻按每拍位移放大，小场景（0.8 m/s）保持原值。
            step_move = max(speed * self.dt, 1e-3)
            follower = PathFollower(
                max_linear=max(0.2, speed),
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

    def _set_target(self, agent, target, force=False):
        """设定目标点并规划路径；``force`` 用于安全投影触发重规划时强制重算。

        原先重规划分支调用 ``_set_target(agent, agent.target)`` 会因"目标没变"
        直接返回，跟随器拿着旧路径每拍再触发一次安全投影，形成原地打转
        （仿真 300 拍仍停在原地，占位永远凑不齐）。
        """
        if target is None:
            return
        target = [float(target[0]), float(target[1])]
        if (not force and agent.target is not None
                and distance(target, agent.target) < 0.35):
            return
        if agent.can_climb and agent.altitude > 0:
            # 空中平台越障直飞：已知静态建筑高度低于巡航高度，2D 地图上的
            # 膨胀障碍不适用。航路仍记录直线长度，便于核对"直飞 vs 绕行"。
            # 注意：只有配了巡航高度（air_altitude）的空中平台才直飞；
            # 没配高度的飞机仍按地面 A* 处理，避免"z=0 却穿楼"。
            straight = distance((agent.x, agent.y), target)
            agent.target = target
            agent.path = [[agent.x, agent.y], [target[0], target[1]]]
            agent.follow = None
            agent.path_meta = dict(length=straight, straight_length=straight,
                                   straight_line_ok=True, min_clearance=None,
                                   mode='air_direct', altitude=agent.altitude)
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
        plan = self._plan_leg(agent, target)
        if plan is None:
            return
        agent.target = target
        agent.path = plan['path']
        agent.follow = self._follower_for(agent.pid).reset()
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
                                mode='ground_astar'))

    # ---- 单步 ----
    def step(self):
        poses = {pid: (a.x, a.y, a.yaw) for pid, a in self.agents.items()}
        speeds = {pid: a.speed for pid, a in self.agents.items()}
        out = self.behavior.step(poses, self.time, 1.0)
        self._speed_scale = out.get('speed_scale') or {}
        self._air_speed_scale = out.get('air_speed_scale') or {}
        debug = self.behavior.debug() if hasattr(self.behavior, 'debug') else {}
        targets = out.get('targets') or {}
        phase = out.get('phase') or self.behavior.phase
        if phase != self._last_phase:
            self._last_phase = phase
            self.events.append(dict(t=round(self.time, 2), kind='phase',
                                    job_id=self._job, phase=phase))
        for pid, agent in self.agents.items():
            self._set_target(agent, targets.get(pid))
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
            for agent in self.agents.values():
                if agent.can_climb and agent.altitude > 0:
                    # 空中直飞：两点线段按速度推进；高度按爬升率趋近巡航高
                    if agent.path and len(agent.path) >= 2:
                        tx, ty = agent.path[-1]
                        dx, dy = tx - agent.x, ty - agent.y
                        d = math.hypot(dx, dy)
                        if d > 1e-9:
                            agent.yaw = math.atan2(dy, dx)
                            speed = agent.speed * float(
                                self._air_speed_scale.get(agent.pid, 1.0))
                            step = min(speed * self.dt, d)
                            agent.x += dx / d * step
                            agent.y += dy / d * step
                            agent.odometer += step
                    climb = self._climb_rate() * self.dt
                    if agent.z < agent.altitude:
                        agent.z = min(agent.altitude, agent.z + climb)
                    elif agent.z > agent.altitude:
                        agent.z = max(agent.altitude, agent.z - climb)
                    continue
                if not agent.path or agent.follow is None:
                    continue
                v, w, state = self._follower_for(agent.pid).step(
                    agent.pose, agent.path, agent.follow, self.nav)
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
                        self._set_target(agent, agent.target, force=True)
                    continue
                agent.yaw += w * self.dt
                agent.x += v * math.cos(agent.yaw) * self.dt
                agent.y += v * math.sin(agent.yaw) * self.dt
                agent.odometer += abs(v) * self.dt
            if k % 2 == 0 or k == self.ticks_per_step - 1:
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
