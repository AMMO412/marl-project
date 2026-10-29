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
                 ticks_per_step=10):
        self.nav = nav
        self.behavior = behavior
        self.dt = dt
        self.ticks_per_step = ticks_per_step
        speeds = speeds or {}
        self.agents = {}
        for pid, start in starts.items():
            self.agents[pid] = AgentState(
                pid=pid, x=float(start[0]), y=float(start[1]),
                yaw=float(start[2]) if len(start) > 2 else 0.0,
                speed=float(speeds.get(pid, 0.8)))
        self.time = 0.0
        self.samples = []
        self.events = []
        self.routes = []
        self._follower = PathFollower()
        self.behavior.speeds = speeds
        self._last_phase = None
        self._job = behavior.job_id
        self._site = list(behavior.site)
        self._inside = False

    # ---- 目标点 → 路径 ----
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

    def _set_target(self, agent, target):
        if target is None:
            return
        target = [float(target[0]), float(target[1])]
        if agent.target is not None and distance(target, agent.target) < 0.35:
            return
        plan = self._plan_leg(agent, target)
        if plan is None:
            return
        agent.target = target
        agent.path = plan['path']
        agent.follow = self._follower.reset()
        agent.path_meta = plan
        self.routes.append(dict(pid=agent.pid, job_id=self._job,
                                t=round(self.time, 2),
                                from_pose=[round(agent.x, 2), round(agent.y, 2)],
                                to=target, path=[[round(p[0], 2), round(p[1], 2)]
                                                 for p in plan['path']],
                                length=plan['length'],
                                straight=plan['straight_length'],
                                straight_line_ok=plan['straight_line_ok'],
                                min_clearance=plan['min_clearance']))

    # ---- 单步 ----
    def step(self):
        poses = {pid: (a.x, a.y, a.yaw) for pid, a in self.agents.items()}
        speeds = {pid: a.speed for pid, a in self.agents.items()}
        out = self.behavior.step(poses, self.time, 1.0)
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
                if not agent.path or agent.follow is None:
                    continue
                v, w, state = self._follower.step(agent.pose, agent.path,
                                                  agent.follow, self.nav)
                agent.follow = state
                if state.replan:
                    state.replan = False
                    self._set_target(agent, agent.target)
                    continue
                agent.yaw += w * self.dt
                agent.x += v * math.cos(agent.yaw) * self.dt
                agent.y += v * math.sin(agent.yaw) * self.dt
                agent.odometer += abs(v) * self.dt
            if k % 2 == 0 or k == self.ticks_per_step - 1:
                self.samples.append(dict(
                    t=round(self.time + k * self.dt, 2), job=self._job,
                    phase=phase,
                    agents={pid: [round(a.x, 3), round(a.y, 3), round(a.yaw, 3)]
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
