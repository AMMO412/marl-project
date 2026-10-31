# -*- coding: utf-8 -*-
"""behaviors.py —— 到位之后的"作业动作"状态机（五类任务）。

规划层只回答"谁去哪个作业点"；到了点上做什么，原来在演示里只有一句
"每步贡献 work_rate"。本文件把五类任务的动作补成可执行的规则：

  patrol   巡逻警戒：绕作业区一圈的闭合环路，按检查点计数，记录每个
           检查点的重访间隔（对应巡逻复查示意）。
  blockade 区域封控：封控圈上按弧段占位；外圈出现入侵者时，最近的在位
           平台解算拦截点前出，其余保持封控（对应区域拦截示意）。
  recon    协同侦察：共享占据栅格，各自奔向"已知区旁边的未知格"（前沿），
           到达后按传感器半径并入共享地图，覆盖率达标后回传（对应协同
           探索示意）。
  assault  机动突击：机动 → 到位（全员齐）→ 执行（收拢到目标环）→
           结果确认（前出观察点确认），阶段推进带全员同步（对应突击阶段）。
  hold     要点坚守：在位/待命轮换，接替者到位才撤，统计"零人在位"缺口
           （对应接替示意）。

这一层是**纯决策**：每次 step 只返回每台平台的下一目标点、当前阶段和
事件，不直接改位姿；运动由 city_nav.PathFollower 执行。这样状态机可以
脱开运动学单独测试（见 tests/test_behaviors.py）。

所有几何都在场景坐标（与 simple_city.json 一致），作业点若落在建筑内，
统一先吸附到最近可通行点（NavMap.nearest_free），吸附距离记在 metrics 里。
"""
import math

from assessment import EFFECT_KINDS, StubAdjudicator, normalize_effect_kind
from city_nav import NavError, distance
import containment_geom as geom


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (1.0, 0.0)


def _polar(center, radius, angle):
    return [center[0] + radius * math.cos(angle),
            center[1] + radius * math.sin(angle)]


def _wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class Behavior:
    kind = 'base'
    label = '作业'
    DEFAULTS = {}

    def __init__(self, job, nav, pids, params=None, site=None):
        self.job_id = job.get('job_id', 'J?')
        self.nav = nav
        self.pids = list(pids)
        self.params = dict(self.DEFAULTS)
        self.params.update({k: v for k, v in (params or {}).items()
                            if not str(k).startswith('_')})
        raw_site = site or job.get('pos')
        self.site, offset = nav.nearest_free(raw_site)
        self.site_snap = round(offset, 3)
        self.phase = '待命'
        self.done = False
        self.t = 0.0
        self._events = []
        self.history = []          # 全量事件（drain 不清空，供测试/复盘）
        self.platform_caps = {}    # 平台画像（类目/爬升/载荷），第二道能力闸门用
        self.metrics = dict(site=[round(v, 2) for v in self.site],
                            site_snap_offset=self.site_snap)

    # ---- 工具 ----
    def emit(self, kind, **fields):
        event = dict(t=round(self.t, 3), job_id=self.job_id,
                     kind=kind, **fields)
        self._events.append(event)
        self.history.append(event)

    def drain(self):
        out, self._events = self._events, []
        return out

    def set_platform_caps(self, caps):
        """注入平台画像（类目/爬升/载荷/速度）。

        规划器已按角色核过载荷，但"能力约束必须在下发后也有闸门"是本层
        的既定纪律：真实对接时指令可能被上层改写，行为层仍要能自己拒绝
        "让侦察无人机去扛 4 吨弹药"这种不合理编成。默认只登记、不改决策，
        子类（突击）据此做角色校核。
        """
        self.platform_caps = {k: dict(v) for k, v in (caps or {}).items()}
        self.metrics['platform_caps'] = {
            pid: dict(cap) for pid, cap in self.platform_caps.items()}

    def set_phase(self, phase):
        if phase != self.phase:
            self.phase = phase
            self.emit('phase', phase=phase)

    def occupy(self, poses, targets, tol=0.6):
        return all(distance(poses[pid], targets[i]) <= tol
                   for i, pid in enumerate(self.pids[:len(targets)]))

    def step(self, poses, t, dt):
        self.t = t
        return dict(targets={pid: poses[pid] for pid in self.pids},
                    phase=self.phase, done=self.done)

    def debug(self):
        """给可视化用的动态量；不参与决策。"""
        return {}

    def progress_frac(self):
        """归一化推进度 [0,1]：把"行为推进"映射回作业级进度。

        主链（mock_fleet）在行为模式下用它把行为阶段/圈数/覆盖率换算成
        coordinator 能消费的 progress；done 时恒为 1.0。默认只区分
        完成与否，各子类给出更细的中间进度。
        """
        return 1.0 if self.done else 0.0

    def _finish(self, reason):
        if not self.done:
            self.done = True
            self.emit('behavior_complete', reason=reason)
            self.set_phase('完成')


# ------------------------------------------------------------------
# 1. 巡逻警戒：闭环 + 检查点 + 重访间隔
# ------------------------------------------------------------------
class PatrolBehavior(Behavior):
    kind = 'patrol'
    label = '巡逻警戒'
    DEFAULTS = dict(radius=2.4, checkpoints=6, cycles=3,
                    arrive_tol=0.7, center_shift=0.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loop = self._build_loop()
        self.metrics['radius'] = round(self.params['radius'], 2)
        self.metrics['checkpoints'] = len(self.loop)
        self.metrics['loop'] = [[round(v, 2) for v in q] for q in self.loop]
        self.idx = {}
        self.cycles = {pid: 0 for pid in self.pids}
        self.last_cycle_t = {pid: 0.0 for pid in self.pids}
        self.visits = {pid: [] for pid in self.pids}
        # 多机沿环路均匀错开，避免挤在同一个检查点
        for k, pid in enumerate(self.pids):
            self.idx[pid] = (k * len(self.loop) // max(1, len(self.pids))) % len(self.loop)
        self.set_phase('机动')

    def _build_loop(self):
        p = self.params
        n = max(3, int(p['checkpoints']))
        for shrink in range(8):
            radius = p['radius'] * (1 - 0.08 * shrink)
            loop = []
            for i in range(n):
                a = 2 * math.pi * i / n
                point, _ = self.nav.nearest_free(
                    _polar(self.site, radius, a), radius=self.nav.radius + 0.25)
                loop.append(point)
            ok = all(self.nav.segment_free(a, b) for a, b in
                     zip(loop, loop[1:] + loop[:1]))
            if ok:
                return loop
        # 环路被建筑切断时退化为"可用检查点序列"，仍保证段段可通行
        loop = []
        for i in range(n):
            point, _ = self.nav.nearest_free(
                _polar(self.site, p['radius'] * 0.5, 2 * math.pi * i / n),
                radius=self.nav.radius + 0.25)
            if not loop or self.nav.segment_free(loop[-1], point):
                loop.append(point)
        return loop or [self.site]

    def step(self, poses, t, dt):
        self.t = t
        targets = {}
        n = len(self.loop)
        if (self.phase == '机动'
                and distance(poses[self.pids[0]], self.site)
                <= self.params['radius'] + 1.0):
            self.set_phase('巡逻')
        for pid in self.pids:
            i = self.idx[pid]
            target = self.loop[(i + 1) % n]
            targets[pid] = target
            if distance(poses[pid], target) <= self.params['arrive_tol']:
                self.idx[pid] = (i + 1) % n
                self.visits[pid].append(dict(index=(i + 1) % n, t=round(t, 2)))
                self.emit('checkpoint_visited', pid=pid,
                          index=(i + 1) % n, cycle=self.cycles[pid])
                if self.idx[pid] == 0:
                    self.cycles[pid] += 1
                    interval = t - self.last_cycle_t[pid]
                    self.last_cycle_t[pid] = t
                    self.emit('cycle_completed', pid=pid,
                              cycle=self.cycles[pid],
                              revisit_s=round(interval, 2))
                    if self.cycles[pid] >= int(self.params['cycles']):
                        self.metrics['revisit_s'] = round(interval, 2)
        if all(self.cycles[pid] >= int(self.params['cycles']) for pid in self.pids):
            self._finish('patrol_cycles_done')
        return dict(targets=targets, phase=self.phase, done=self.done)

    def progress_frac(self):
        if self.done:
            return 1.0
        total = max(1, len(self.pids) * int(self.params['cycles']))
        return min(1.0, sum(self.cycles.values()) / total)

    def debug(self):
        return dict(idx={k: v for k, v in self.idx.items()},
                    cycles=dict(self.cycles))


# ------------------------------------------------------------------
# 2. 区域封控：环形占位 + 入侵拦截
# ------------------------------------------------------------------
class BlockadeBehavior(Behavior):
    kind = 'blockade'
    label = '区域封控'
    DEFAULTS = dict(ring_radius=3.2, outer_radius=5.2, arc_span=2.0,
                    intruder_speed=0.22, max_steps=90,
                    intruder_start=None, occupy_tol=0.8, intercept_tol=0.9)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.params
        self.occupied = False
        self.triggered = False
        self.intercepted = False
        self.intruder_stopped = False
        self.interceptor = None
        self.release_t = None
        self.intruder_history = []
        # 入侵方向：未指定时取离作业点最近的边界方向（从外向内）
        if p.get('intruder_start'):
            self.intruder_start = list(p['intruder_start'])
        else:
            x0, y0, x1, y1 = self.nav.bounds
            edges = [[x0, self.site[1]], [x1, self.site[1]],
                     [self.site[0], y0], [self.site[0], y1]]
            nearest = min(edges, key=lambda e: distance(self.site, e))
            direction = _unit(self.site, nearest)
            self.intruder_start = _polar(self.site, p['outer_radius'] + 6.0,
                                         math.atan2(direction[1], direction[0]))
        self.bearing = math.atan2(self.intruder_start[1] - self.site[1],
                                  self.intruder_start[0] - self.site[0])
        self.intruder = list(self.intruder_start)
        self.posts = self._build_posts()
        self.metrics.update(posts=[[round(v, 2) for v in q] for q in self.posts],
                            intruder_start=[round(v, 2) for v in self.intruder_start],
                            ring_radius=p['ring_radius'],
                            outer_radius=p['outer_radius'])
        self.set_phase('占位')

    def _build_posts(self):
        p = self.params
        posts = []
        span = p['arc_span']
        n = max(2, len(self.pids))
        for i in range(n):
            a = self.bearing + span * (0.5 - i / max(1, n - 1)) if n > 1 else self.bearing
            point, _ = self.nav.nearest_free(_polar(self.site, p['ring_radius'], a))
            posts.append(point)
        return posts

    def _advance_intruder(self, dt):
        if self.intruder_stopped:
            return
        dx, dy = self.site[0] - self.intruder[0], self.site[1] - self.intruder[1]
        d = math.hypot(dx, dy)
        if d < 0.4:
            self.intruder_stopped = True
            self.emit('breach', pos=[round(v, 2) for v in self.intruder])
            return
        step = min(d, self.params['intruder_speed'] * dt)
        self.intruder = [self.intruder[0] + dx / d * step,
                         self.intruder[1] + dy / d * step]
        self.intruder_history.append([round(v, 2) for v in self.intruder])

    def _intercept_point(self, pose, speed):
        """沿入侵者未来轨迹找最早可截住的点（简单前向搜索）。"""
        p = self.params
        x, y = self.intruder
        dx, dy = self.site[0] - x, self.site[1] - y
        d = max(1e-6, math.hypot(dx, dy))
        vx, vy = dx / d * p['intruder_speed'], dy / d * p['intruder_speed']
        best = None
        for k in range(1, 60):
            fx, fy = x + vx * k, y + vy * k
            t_intruder = k * 0.5
            t_agent = distance(pose, (fx, fy)) / max(speed, 1e-6)
            if t_agent <= t_intruder:
                best = [fx, fy]
                break
        point = best or [x + vx * 10, y + vy * 10]
        # 拦截点可能落在边界外（入侵者从图外进来）：夹回可通行区域
        x0, y0, x1, y1 = self.nav.bounds
        inset = self.nav.radius + 0.2
        point = [min(max(point[0], x0 + inset), x1 - inset),
                 min(max(point[1], y0 + inset), y1 - inset)]
        snapped, _ = self.nav.nearest_free(point)
        return snapped

    def step(self, poses, t, dt):
        self.t = t
        speeds = getattr(self, 'speeds', None) or {pid: 0.8 for pid in self.pids}
        p = self.params
        targets = {}
        self._advance_intruder(dt)
        if not self.occupied and self.occupy(poses, self.posts, p['occupy_tol']):
            self.occupied = True
            self.emit('posts_occupied',
                      posts=[[round(v, 2) for v in q] for q in self.posts])
            self.set_phase('封控在位')
        if not self.triggered and distance(self.intruder, self.site) <= p['outer_radius']:
            self.triggered = True
            self.emit('intrusion_detected',
                      pos=[round(v, 2) for v in self.intruder],
                      range=round(distance(self.intruder, self.site), 2))
            self.set_phase('拦截')
        if self.triggered and not self.intercepted:
            if self.interceptor is None:
                self.interceptor = min(
                    self.pids,
                    key=lambda pid: distance(poses[pid], self.intruder))
                self.emit('interceptor_assigned', pid=self.interceptor)
            point = self._intercept_point(poses[self.interceptor],
                                          speeds.get(self.interceptor, 0.8))
            for i, pid in enumerate(self.pids):
                targets[pid] = (point if pid == self.interceptor
                                else self.posts[min(i, len(self.posts) - 1)])
            if distance(poses[self.interceptor], self.intruder) <= p['intercept_tol']:
                self.intercepted = True
                self.intruder_stopped = True
                self.release_t = t
                self.metrics['intercept_t'] = round(t, 2)
                self.metrics['intercept_from'] = [
                    round(v, 2) for v in poses[self.interceptor]]
                self.emit('intercepted', pid=self.interceptor,
                          pos=[round(v, 2) for v in self.intruder])
                self.set_phase('处置完毕')
        elif self.intercepted:
            for i, pid in enumerate(self.pids):
                targets[pid] = self.posts[min(i, len(self.posts) - 1)]
            if self.release_t is not None and t - self.release_t > 6:
                self._finish('intercept_handled')
        else:
            for i, pid in enumerate(self.pids):
                targets[pid] = self.posts[min(i, len(self.posts) - 1)]
        if t > p['max_steps']:
            self._finish('timeout')
        return dict(targets=targets, phase=self.phase, done=self.done)

    def progress_frac(self):
        if self.done:
            return 1.0
        frac = 0.25 if self.occupied else 0.05
        if self.triggered:
            frac = max(frac, 0.55)
        if self.intercepted:
            frac = max(frac, 0.9)
        return frac

    def debug(self):
        return dict(intruder=[round(v, 2) for v in self.intruder],
                    interceptor=self.interceptor,
                    stopped=self.intruder_stopped)


# ------------------------------------------------------------------
# 2b. 区域封控（1028 §2.2）：边界段占位 + 通道哨位 + 警告→拦阻
# ------------------------------------------------------------------
CN_LEVELS = ("monitor", "warn", "block")
CN_LEVEL_LABELS = {"monitor": "监视", "warn": "警告", "block": "拦阻"}
CN_AUTHORITY = ("none", "self_defense", "on_order")
CN_AUTHORITY_LABELS = {"none": "无火力授权", "self_defense": "仅自卫",
                       "on_order": "按令"}
CN_OBJECTIVES = ("deny_entry", "control_passage", "monitor_channel", "intercept")
CN_STATE_WAIT = "待出现"
CN_STATE_WATCH = "监视"
CN_STATE_WARNED = "已警告"
CN_STATE_INTERCEPT = "拦截中"
CN_STATE_HELD = "已拦阻"
CN_STATE_BREACH = "未授权进入"
CN_STATE_WITHDRAWN = "已撤离"
CN_STATE_PASSED = "已放行"


class _ContainmentTarget:
    """一个被监视/被处置的目标（未授权或已授权），只做匀速直线运动。

    真实识别、敌我属性判定属外部情报/传感器模块；本层按输入给定的
    ``authorized`` 标记复核，不臆造识别过程（见 docs/区域封控任务.md）。
    """

    def __init__(self, spec, center):
        self.id = str(spec.get("target_id") or spec.get("id") or "T?")
        self.authorized = bool(spec.get("authorized", False))
        self.compliance = bool(spec.get("compliance", False))
        self.speed = float(spec.get("speed_mps", 2.0))
        self.t_start = float(spec.get("t_start_s", 0.0))
        self.start = [float(v) for v in (spec.get("start") or center)]
        self.goal = [float(v) for v in (spec.get("goal") or center)]
        self.pos = list(self.start)
        self.state = CN_STATE_WAIT
        self.appeared = False
        self.detected_t = None
        self.warned_t = None
        self.intercept_t = None
        self.resolved_t = None
        self.breach_t = None
        self.interceptor = None
        self.track = []
        self.version = 1

    def velocity(self, retreat=False):
        tx, ty = (self.start if retreat else self.goal)
        dx, dy = tx - self.pos[0], ty - self.pos[1]
        d = math.hypot(dx, dy)
        if d <= 1e-9:
            return (0.0, 0.0), 0.0
        return (dx / d * self.speed, dy / d * self.speed), d

    def move(self, dt, retreat=False):
        (vx, vy), d = self.velocity(retreat)
        step = min(d, self.speed * dt)
        if d > 1e-9:
            self.pos = [self.pos[0] + vx / self.speed * step,
                        self.pos[1] + vy / self.speed * step]
        return step

    def snapshot(self):
        return dict(target_id=self.id, authorized=self.authorized,
                    compliance=self.compliance, speed_mps=self.speed,
                    start=[round(v, 2) for v in self.start],
                    goal=[round(v, 2) for v in self.goal],
                    pos=[round(v, 2) for v in self.pos], state=self.state,
                    detected_at_s=self.detected_t, warned_at_s=self.warned_t,
                    intercepted_at_s=self.intercept_t,
                    resolved_at_s=self.resolved_t, breach_at_s=self.breach_t,
                    interceptor=self.interceptor)


class ContainmentBehavior(Behavior):
    """区域封控：按 1028 §2.2 的控制等级与交战授权执行"监视→警告→拦阻"。

    与 ``BlockadeBehavior``（小场景环形占位演示）的分工：
      * BlockadeBehavior 保留给历史场景，几何是"作业点外一圈"；
      * 本类只在输入给出 ``area`` 多边形时启用，几何是**真实封控边界**：
        边界按弧长均分为若干段，每段一个占位点；通道口一个哨位；
        另有机动拦截组与预备队。
    本层不含火力、毁伤与效果判定：控制等级最高到"拦阻"，交战授权只影响
    是否允许前出拦阻，不改变任何武器语义。
    """

    kind = 'blockade'
    label = '区域封控'
    DEFAULTS = dict(
        area=None,
        gates=(),
        roles=None,
        standoff_m=12.0,
        gate_standoff_m=6.0,
        sensor_radius_m=35.0,
        warn_range_m=None,
        intercept_standoff_m=10.0,
        intercept_post=None,
        reserve_post=None,
        control_level="block",
        engagement_authority="on_order",
        control_objective="deny_entry",
        max_leak_rate=0.0,
        min_coverage=0.5,
        min_intercept_rate=0.8,
        max_response_s=15.0,
        intruders=(),
        duration_s=180.0,
        boundary_sample_m=5.0,
        occupy_tol=3.0,
        intercept_tol=4.0,
        occupancy_tolerance_s=5.0,
        # 在岗不等于钉在原地：占位组沿负责的边界段巡视、门哨在通道口横向
        # 游走、机动组在待机点小圈待机。周期给慢一点，看起来是"踱步"不是冲锋。
        patrol_enabled=True,
        patrol_speed_mps=2.0,
        patrol_period_s=120.0,
        gate_patrol_period_s=45.0,
        standby_loop_radius_m=8.0,
        # 空中监视：绕封控区上方盘旋，按高度层提供覆盖（2D 画面按投影绘制）
        air_altitude_m=60.0,
        air_orbit_radius_m=55.0,
        air_orbit_period_s=90.0,
        air_speed_mps=14.0,
        max_steps=600,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.params
        self.polygon = geom.as_polygon(p.get('area'))
        self.perimeter_m = geom.perimeter(self.polygon)
        self.samples = geom.boundary_samples(self.polygon,
                                             p['boundary_sample_m'])
        self.center = geom.polygon_center(self.polygon)
        self.site = [round(v, 3) for v in self.center]
        self.gates = [dict(g) for g in (p.get('gates') or [])]
        self.control_level = str(p.get('control_level') or 'block')
        self.authority = str(p.get('engagement_authority') or 'on_order')
        if self.control_level not in CN_LEVELS:
            raise ValueError("control_level 必须是 %s" % "/".join(CN_LEVELS))
        if self.authority not in CN_AUTHORITY:
            raise ValueError("engagement_authority 必须是 %s"
                             % "/".join(CN_AUTHORITY))
        self.objective = str(p.get('control_objective') or 'deny_entry')
        self.starts = {}
        self.lost_pids = set()
        self._assign_roles()
        self._on_post = {}
        # 巡视相位按平台错开，避免所有哨位同手同脚一起走。
        self.patrol_phase = {pid: (index * 1.7) % (2 * math.pi)
                             for index, pid in enumerate(sorted(self.posts))}
        # 空中监视的高度层：BehaviorRunner 用 params['air_altitude'] 决定
        # 巡航高度（键是 pid），没配高度的飞机仍按地面 A* 走，不会穿楼。
        if self.air_pids:
            self.params['air_altitude'] = {
                pid: float(self.params['air_altitude_m'])
                for pid in self.air_pids}
        self.targets = [_ContainmentTarget(spec, self.center)
                        for spec in (p.get('intruders') or [])]
        self.control_established_at = None
        self.control_released_at = None
        self.coverage_sum = 0.0
        self.coverage_t = 0.0
        self.occupancy_sum = 0.0
        self.vacancy_started = {}
        self.interrupted_pids = set()
        self.interruptions = []
        self.intercept_tasks = {}     # pid -> target_id
        self.timeline = []
        self.counts = dict(unauthorized=0, authorized=0, warned=0,
                           warning_effective=0, intercept_attempts=0,
                           intercepted=0, breach=0, passed=0, false_intercept=0)
        self.response_times = []
        self.warn_latencies = []
        self.verdict = None
        self.metrics.update(
            perimeter_m=round(self.perimeter_m, 1),
            boundary_samples=len(self.samples),
            control_level=self.control_level,
            control_level_label=CN_LEVEL_LABELS[self.control_level],
            engagement_authority=self.authority,
            engagement_authority_label=CN_AUTHORITY_LABELS[self.authority],
            control_objective=self.objective,
            sensor_radius_m=p['sensor_radius_m'],
            air_units=len(self.air_pids),
            air_altitude_m=(float(p['air_altitude_m']) if self.air_pids else None),
            policy=dict(area=[[round(x, 2), round(y, 2)] for x, y in self.polygon],
                        gates=[dict(g) for g in self.gates],
                        posts=[dict(p) for p in self.post_list],
                        roles=dict(self.roles)),
        )
        self.set_phase('机动')

    # ---------------- 分工与占位 ----------------
    def _assign_roles(self):
        """把平台分到 边界段 / 通道哨位 / 机动拦截 / 预备队。

        优先用计划下发的角色（``roles[pid]``），只有当角色缺失/不覆盖全部
        平台时才按几何补位——执行层不把计划的角色当唯一真值，但也不擅自
        把"守东段"改成"守西段"。
        """
        pids = list(self.pids)
        declared = {pid: str(role) for pid, role in
                    (self.params.get('roles') or {}).items() if pid in pids}
        boundary_roles = {}
        gate_roles = {}
        intercept_pids = []
        reserve_pids = []
        air_pids = []
        for pid in pids:
            role = declared.get(pid, '')
            kind, _, detail = role.partition(':')
            if kind == 'boundary' and detail:
                try:
                    boundary_roles[pid] = int(detail.split('/')[0])
                except ValueError:
                    boundary_roles[pid] = 0
            elif kind == 'gate':
                gate_roles[pid] = detail or (self.gates[0].get('gate_id')
                                             if self.gates else 'G1')
            elif kind == 'intercept':
                intercept_pids.append(pid)
            elif kind == 'reserve':
                reserve_pids.append(pid)
            elif kind == 'air':
                air_pids.append(pid)
        unassigned = [pid for pid in pids
                      if pid not in boundary_roles and pid not in gate_roles
                      and pid not in intercept_pids and pid not in reserve_pids
                      and pid not in air_pids]

        # 补位：先满足入口哨位，再给一个机动组，其余做边界段。
        gate_ids = [str(g.get('gate_id')) for g in self.gates]
        for gate_id in gate_ids:
            if gate_id in gate_roles.values():
                continue
            if not unassigned:
                break
            gate_roles[unassigned.pop(0)] = gate_id
        for pid in list(unassigned):
            if not intercept_pids:
                intercept_pids.append(pid)
                unassigned.remove(pid)
        for pid in list(unassigned):
            boundary_roles[pid] = 0
            unassigned.remove(pid)

        boundary_pids = [pid for pid in pids if pid in boundary_roles]
        sector_count = len(boundary_pids)
        posts = (geom.sector_posts(self.polygon, sector_count,
                                   standoff=float(self.params['standoff_m']))
                 if sector_count else [])
        # 按声明的段号排序；未声明段号的排在后面、按平台编号，保证可复现。
        order = sorted(boundary_pids,
                       key=lambda pid: (boundary_roles.get(pid) or 999, pid))
        self.posts = {}
        self.sectors = {}
        self.roles = {}
        self.post_list = []
        for index, pid in enumerate(order):
            post = posts[index] if index < len(posts) else posts[-1]
            self.posts[pid] = list(post['post'])
            self.sectors[pid] = (post['s0'], post['s1'])
            self.roles[pid] = 'boundary:%d/%d' % (post['index'], sector_count)
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(post['post']),
                                       mid=list(post['mid']),
                                       sector=[post['s0'], post['s1']],
                                       index=post['index']))

        for pid, gate_id in gate_roles.items():
            gate = next((g for g in self.gates
                         if str(g.get('gate_id')) == str(gate_id)),
                        self.gates[0] if self.gates else None)
            point = (gate or {}).get('point') or [self.center[0], self.center[1]]
            arc = geom.arc_of_point(self.polygon, point)['s']
            inward, _ = geom.point_at(self.polygon, arc,
                                      float(self.params['gate_standoff_m']))
            self.posts[pid] = [round(inward[0], 3), round(inward[1], 3)]
            self.sectors[pid] = None
            self.roles[pid] = 'gate:%s' % gate_id
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(self.posts[pid]),
                                       mid=[round(v, 3) for v in point],
                                       sector=None, gate=str(gate_id)))

        standby = self.params.get('intercept_post') or [
            self.center[0], self.center[1]]
        reserve = self.params.get('reserve_post') or [
            self.center[0], self.center[1] - float(self.params['standoff_m'])]
        for pid in intercept_pids:
            self.posts[pid] = [float(v) for v in standby]
            self.sectors[pid] = None
            self.roles[pid] = 'intercept:standby'
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(self.posts[pid]),
                                       mid=list(self.posts[pid]), sector=None))
        for pid in reserve_pids:
            self.posts[pid] = [float(v) for v in reserve]
            self.sectors[pid] = None
            self.roles[pid] = 'reserve:standby'
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(self.posts[pid]),
                                       mid=list(self.posts[pid]), sector=None))
        for pid in air_pids:
            self.posts[pid] = [float(v) for v in self.center]
            self.sectors[pid] = None
            self.roles[pid] = 'air:watch'
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(self.posts[pid]),
                                       mid=list(self.posts[pid]), sector=None,
                                       air=True,
                                       altitude_m=float(self.params['air_altitude_m']),
                                       orbit_radius_m=float(self.params['air_orbit_radius_m'])))
        self.interceptors = list(intercept_pids) + [
            pid for pid in gate_roles if pid not in intercept_pids]
        self.reserve_pids = list(reserve_pids)
        self.air_pids = list(air_pids)

    def _role_label(self, pid):
        return self.roles.get(pid, '未分工')

    # ---------------- 事件与时间线 ----------------
    def _log(self, t, event, **fields):
        row = dict(t=round(t, 2), event=event, **fields)
        self.timeline.append(row)
        return row

    def report_loss(self, pid, t):
        """执行期成员失联：不再计在位，并显式记一条控制中断。"""
        if pid in self.lost_pids:
            return
        self.lost_pids.add(pid)
        self.metrics['our_losses'] = len(self.lost_pids)
        self._log(t, 'member_lost', pid=pid, role=self._role_label(pid))
        self.emit('member_lost', pid=pid, role=self._role_label(pid))

    # ---------------- 主循环 ----------------
    def step(self, poses, t, dt):
        self.t = t
        p = self.params
        warn_range = float(p['warn_range_m'] or p['sensor_radius_m'])
        targets_out = dict(self.posts)
        self._on_post = {}
        for pid, post in self.posts.items():
            if pid in self.lost_pids:
                continue
            self._on_post[pid] = self._is_on_post(pid, poses[pid])

        # 处置结束后回到"封控在位"：阶段名反映当前实际状态，一次警告/拦阻
        # 不是整个封控时段的终态。这一步在推进目标之前判断，"处置完毕"
        # 至少能显示一拍，不会同拍被覆盖。
        if (self.control_established_at is not None
                and not self.intercept_tasks
                and self.phase in ('警告', '拦阻', '处置完毕')
                and not any(x.state in (CN_STATE_WARNED, CN_STATE_INTERCEPT)
                            for x in self.targets)):
            self.set_phase('封控在位')

        for spec in self.targets:
            self._update_target(spec, poses, t, dt, warn_range)

        self._track_control(poses, t, dt)

        for pid, post in self.posts.items():
            if pid in self.lost_pids:
                continue
            if pid in self.intercept_tasks:
                target = self._target_of(pid)
                if target is not None and target.state == CN_STATE_INTERCEPT:
                    point = geom.lead_intercept(
                        tuple(poses[pid])[:2],
                        target.pos,
                        (target.velocity()[0][0], target.velocity()[0][1]),
                        self._speed_of(pid))
                    targets_out[pid] = self._free_point(point)
                continue
            # 在岗不等于钉在原地：沿负责的边界段来回巡视（门哨在通道口横向
            # 游走、机动组在待机点小圈待机），监视扇面随时间扫过，比站着
            # 不动更接近"持续监视/占位"，也能看出覆盖缺口。
            targets_out[pid] = self._patrol_target(pid, t) or post

        if self.control_established_at is not None and not self.done:
            if t - self.control_established_at >= float(p['duration_s']):
                self._finalize(t)
        if t > float(p['max_steps']):
            self._finalize(t, timeout=True)
        # 巡视/待机时把平台限速到巡逻速度：跟随器按"距离越近越慢"走，
        # 全速追一个 2 m/s 的慢移目标会一顿一顿地超调，看起来像抽搐。
        speed_scale = {}
        if p.get('patrol_enabled', True):
            patrol_speed = max(0.2, float(p['patrol_speed_mps']))
            for pid in self.posts:
                if pid in self.intercept_tasks:
                    continue                  # 前出拦阻按全速，不按巡逻速度
                kind = str(self.roles.get(pid, '')).split(':')[0]
                if kind in ('intercept', 'reserve'):
                    on_station = True          # 待机点本来就是小圈
                elif kind == 'air':
                    # 空中盘旋按自己的巡航速度，不受地面巡视限速影响
                    speed_scale[pid] = min(
                        1.0, max(0.1, float(p['air_speed_mps']))
                        / max(self._speed_of(pid), 0.1))
                    continue
                elif kind in ('boundary', 'gate'):
                    # 只有已经进入自己那段/口才开始踱步；否则先全速到位。
                    on_station = bool(self._on_post.get(pid))
                else:
                    continue
                if on_station:
                    speed_scale[pid] = min(
                        1.0, patrol_speed / max(self._speed_of(pid), 0.1))
        return dict(targets=targets_out, phase=self.phase, done=self.done,
                    speed_scale=speed_scale)

    def _speed_of(self, pid):
        return float((getattr(self, 'speeds', None) or {}).get(pid, 8.0) or 8.0)

    def _gate_of(self, pid):
        role = str(self.roles.get(pid, ''))
        if not role.startswith('gate:'):
            return None
        gate_id = role.split(':', 1)[1]
        return next((g for g in self.gates
                     if str(g.get('gate_id')) == gate_id),
                    self.gates[0] if self.gates else None)

    def _is_on_post(self, pid, pose):
        """是否在"自己负责的那段"上：看段内/口内，不看是否精确踩点。

        平台会沿段巡视，用"离指定点 ≤ occupy_tol"判定会把正常巡视误记成
        离岗；这里按职责范围判：边界段看弧长与带内距离，门哨看通道口范围。
        """
        p = self.params
        role = str(self.roles.get(pid, ''))
        kind = role.split(':')[0]
        point = tuple(pose)[:2]
        if kind == 'boundary':
            sector = self.sectors.get(pid)
            if not sector:
                return False
            arc = geom.arc_of_point(self.polygon, point)
            s0, s1 = sector
            inside = (s0 - 1e-6) <= arc['s'] <= (s1 + 1e-6)
            band = float(p['standoff_m']) + 25.0
            return bool(inside and arc['distance'] <= band)
        if kind == 'gate':
            gate = self._gate_of(pid)
            if gate is None:
                return False
            radius = float(gate.get('width', 12.0)) / 2.0 + 20.0
            return distance(point, tuple(gate['point'])) <= radius
        if kind == 'air':
            radius = float(p['air_orbit_radius_m']) * 1.5
            return distance(point, tuple(self.center)) <= radius
        return distance(point, self.posts.get(pid, point)) <= float(p['occupy_tol'])

    def _patrol_target(self, pid, t):
        """在岗时的巡逻目标：边界段来回巡视、通道口横向游走、待机点小圈。"""
        if not self.params.get('patrol_enabled', True):
            return None
        p = self.params
        role = str(self.roles.get(pid, ''))
        kind = role.split(':')[0]
        phase = self.patrol_phase.get(pid, 0.0)
        if kind == 'boundary':
            sector = self.sectors.get(pid)
            if not sector:
                return None
            s0, s1 = sector
            span = max(1e-6, s1 - s0)
            period = max(20.0, float(p['patrol_period_s']))
            # 振幅同时受"段长"和"巡视速度"约束：正弦扫掠的峰值线速度是
            # amp·2π/period，不封顶会出现 100 m 段上 5 m/s 的"飞奔"。
            amp = min(span / 2.0 - 10.0,
                      float(p['patrol_speed_mps']) * period / (2 * math.pi))
            amp = max(0.0, amp)
            s = (s0 + s1) / 2.0 + amp * math.sin(2 * math.pi * t / period + phase)
            point, _ = geom.point_at(self.polygon, s, float(p['standoff_m']))
            return [round(point[0], 3), round(point[1], 3)]
        if kind == 'gate':
            gate = self._gate_of(pid)
            if gate is None:
                return None
            angle = math.atan2(gate['direction'][1], gate['direction'][0])
            nx, ny = -math.sin(angle), math.cos(angle)
            period = max(10.0, float(p['gate_patrol_period_s']))
            amp = min(max(1.0, float(gate.get('width', 12.0)) / 2.0 - 1.5),
                      float(p['patrol_speed_mps']) * period / (2 * math.pi))
            off = amp * math.sin(2 * math.pi * t / period + phase)
            arc = geom.arc_of_point(self.polygon, tuple(gate['point']))['s']
            base, _ = geom.point_at(self.polygon, arc,
                                    float(p['gate_standoff_m']))
            return [round(base[0] + nx * off, 3), round(base[1] + ny * off, 3)]
        if kind in ('intercept', 'reserve'):
            center = self.posts.get(pid)
            if not center:
                return None
            radius = float(p['standby_loop_radius_m']) * (0.75 if kind == 'reserve' else 1.0)
            period = max(20.0, float(p['patrol_period_s']))
            theta = 2 * math.pi * t / period + phase
            return [round(center[0] + radius * math.cos(theta), 3),
                    round(center[1] + radius * math.sin(theta), 3)]
        if kind == 'air':
            # 空中监视：绕封控区上方定高盘旋（2D 画面按投影画）
            radius = float(p['air_orbit_radius_m'])
            period = max(20.0, float(p['air_orbit_period_s']))
            theta = 2 * math.pi * t / period + phase
            return [round(self.center[0] + radius * math.cos(theta), 3),
                    round(self.center[1] + radius * math.sin(theta), 3)]
        return None

    def _free_point(self, point, max_radius=6.0):
        """前出点若落在静态障碍里，吸附到最近可通行点（不悄悄穿过花坛）。"""
        nav = getattr(self, 'nav', None)
        if nav is None:
            return list(point)
        try:
            snapped, _ = nav.nearest_free((point[0], point[1]),
                                          max_radius=max_radius)
            return [float(snapped[0]), float(snapped[1])]
        except Exception:      # noqa: BLE001  吸附失败就用原点，交回按原样执行
            return list(point)

    def _target_of(self, pid):
        target_id = self.intercept_tasks.get(pid)
        return next((x for x in self.targets if x.id == target_id), None)

    # ---------------- 目标推进与处置 ----------------
    def _update_target(self, target, poses, t, dt, warn_range):
        p = self.params
        if target.state in (CN_STATE_HELD, CN_STATE_BREACH,
                            CN_STATE_WITHDRAWN, CN_STATE_PASSED):
            return
        if not target.appeared:
            if t < target.t_start:
                return
            target.appeared = True
            self.counts['unauthorized' if not target.authorized
                        else 'authorized'] += 1
            self.emit('target_appeared', target_id=target.id,
                      authorized=target.authorized,
                      pos=[round(v, 2) for v in target.pos])
            self._log(t, 'target_appeared', target=target.id,
                      authorized=target.authorized)
        retreat = target.state == CN_STATE_WARNED and target.compliance
        target.move(dt, retreat=retreat)
        target.track.append([round(t, 1), round(target.pos[0], 2),
                             round(target.pos[1], 2)])

        if target.detected_t is None:
            observer = self._nearest_observer(poses, target.pos,
                                              float(p['sensor_radius_m']))
            if observer is None:
                return
            target.detected_t = round(t, 2)
            target.state = CN_STATE_WATCH
            self.emit('target_detected', target_id=target.id, pid=observer,
                      authorized=target.authorized,
                      range=round(distance(poses[observer], target.pos), 2))
            self._log(t, 'target_detected', target=target.id, pid=observer,
                      authorized=target.authorized)
            if target.authorized:
                self.emit('target_authorized', target_id=target.id)
                self._log(t, 'target_authorized', target=target.id)
            else:
                self.emit('target_unauthorized', target_id=target.id)
                self._log(t, 'target_unauthorized', target=target.id)

        if target.authorized:
            if geom.inside(self.polygon, target.pos):
                target.state = CN_STATE_PASSED
                target.resolved_t = round(t, 2)
                self.counts['passed'] += 1
                self.emit('authorized_pass', target_id=target.id,
                          pos=[round(v, 2) for v in target.pos])
                self._log(t, 'authorized_pass', target=target.id)
            return

        if target.state == CN_STATE_WATCH:
            if geom.inside(self.polygon, target.pos):
                # 只监视/无授权时目标自己走进来，也属于"未授权进入"。
                self._mark_breach(target, t)
                return
            if self.control_level == 'monitor':
                return
            near = self._nearest_observer(poses, target.pos, warn_range)
            if near is None:
                return
            target.state = CN_STATE_WARNED
            target.warned_t = round(t, 2)
            self.counts['warned'] += 1
            if target.detected_t is not None:
                self.warn_latencies.append(round(t - target.detected_t, 2))
            self.emit('warning_issued', target_id=target.id, pid=near,
                      level=CN_LEVEL_LABELS[self.control_level])
            self._log(t, 'warning_issued', target=target.id, pid=near)
            self.set_phase('警告')
            return

        if target.state == CN_STATE_WARNED:
            if target.compliance:
                if distance(target.pos, target.start) <= 3.0:
                    target.state = CN_STATE_WITHDRAWN
                    target.resolved_t = round(t, 2)
                    self.counts['warning_effective'] += 1
                    self.emit('warning_effective', target_id=target.id)
                    self._log(t, 'warning_effective', target=target.id)
                return
            if geom.inside(self.polygon, target.pos):
                # 警告无效且已进入：无论有没有拦阻，都按"未授权进入"记账。
                self._mark_breach(target, t)
                return
            if self.control_level != 'block':
                return
            if self.authority == 'none':
                # 无火力授权：只能警告与报告，不实施拦阻；如实记"未处置"。
                if not getattr(target, '_no_authority_logged', False):
                    target._no_authority_logged = True
                    self.emit('intercept_denied', target_id=target.id,
                              reason='无火力授权')
                    self._log(t, 'intercept_denied', target=target.id)
                return
            pid = self._pick_interceptor(poses, target)
            if pid is None:
                return
            target.state = CN_STATE_INTERCEPT
            target.intercept_t = round(t, 2)
            target.interceptor = pid
            self.intercept_tasks[pid] = target.id
            self.counts['intercept_attempts'] += 1
            if target.detected_t is not None:
                self.response_times.append(round(t - target.detected_t, 2))
            self.emit('intercept_assigned', target_id=target.id, pid=pid,
                      role=self._role_label(pid))
            self._log(t, 'intercept_assigned', target=target.id, pid=pid,
                      role=self._role_label(pid))
            self.set_phase('拦阻')
            return

        if target.state == CN_STATE_INTERCEPT:
            pid = target.interceptor
            if pid is None or pid in self.lost_pids:
                self.intercept_tasks.pop(pid, None)
                target.state = CN_STATE_WARNED
                target.interceptor = None
                return
            if distance(poses[pid], target.pos) <= float(p['intercept_tol']):
                target.state = CN_STATE_HELD
                target.resolved_t = round(t, 2)
                self.counts['intercepted'] += 1
                self.intercept_tasks.pop(pid, None)
                self.emit('intercepted', target_id=target.id, pid=pid,
                          pos=[round(v, 2) for v in target.pos])
                self._log(t, 'intercepted', target=target.id, pid=pid)
                self.set_phase('处置完毕')
                return
            if geom.inside(self.polygon, target.pos):
                self._mark_breach(target, t, pid=pid)
            return

    def _mark_breach(self, target, t, pid=None):
        """记一次未授权进入（漏控）并闭掉该目标；只记一次。"""
        if target.state == CN_STATE_BREACH:
            return
        target.state = CN_STATE_BREACH
        target.breach_t = round(t, 2)
        target.resolved_t = round(t, 2)
        self.counts['breach'] += 1
        self.intercept_tasks.pop(target.interceptor, None)
        target.interceptor = None
        self.emit('breach', target_id=target.id, pid=pid,
                  pos=[round(v, 2) for v in target.pos])
        self._log(t, 'breach', target=target.id, pid=pid)

    def _nearest_observer(self, poses, point, radius):
        best, best_d = None, radius
        for pid in self.posts:
            if pid in self.lost_pids:
                continue
            if not self._on_post.get(pid) and self.control_established_at is not None:
                continue      # 离位平台不算在监视范围内
            d = distance(poses[pid], point)
            if d <= best_d:
                best, best_d = pid, d
        return best

    def _pick_interceptor(self, poses, target):
        """机动组优先；机动组忙时再由通道哨位前出支援（处置完回岗）。

        1028 §2.2.3 的兵力组成里，"占位组"与"机动拦截组"是两拨人：让门哨
        习惯性脱岗追击，会同时把通道监视和边界覆盖率打空，图上看起来
        "有人去了"，实际封控已经漏了。
        """
        busy = set(self.intercept_tasks)
        mobile = [pid for pid in self.interceptors
                  if self.roles.get(pid, '').startswith('intercept')
                  and pid not in busy and pid not in self.lost_pids]
        support = [pid for pid in self.interceptors
                   if not self.roles.get(pid, '').startswith('intercept')
                   and pid not in busy and pid not in self.lost_pids]
        for pool in (mobile, support):
            if pool:
                return min(pool, key=lambda pid: distance(poses[pid], target.pos))
        return None

    # ---------------- 控制状态时间线 ----------------
    def _track_control(self, poses, t, dt):
        p = self.params
        # 只把"占位/门哨"算进在位与边界监视：机动组本来就要前出，
        # 把它离岗记成控制中断会把"履职"误报成"漏控"。
        tracked = [pid for pid in self.posts
                   if self.roles.get(pid, '').startswith(('boundary', 'gate'))]
        manned = [pid for pid in tracked
                  if pid not in self.lost_pids and self._on_post.get(pid)]
        observers = [tuple(poses[pid])[:2] for pid in manned]
        # 空中监视也算观察者：它在封控区上方盘旋，探测圈覆盖整片区域。
        for pid in getattr(self, 'air_pids', []):
            if pid not in self.lost_pids:
                observers.append(tuple(poses[pid])[:2])
        coverage = geom.coverage_ratio(self.samples, observers,
                                       float(p['sensor_radius_m']))
        self.coverage_sum += coverage * dt
        self.coverage_t += dt
        post_count = max(1, len([pid for pid in tracked
                                 if pid not in self.lost_pids]))
        self.occupancy_sum += len(manned) / float(post_count) * dt
        self._last_coverage = coverage

        all_manned = len(manned) == post_count
        if self.control_established_at is None:
            if all_manned:
                self.control_established_at = round(t, 2)
                self.set_phase('封控在位')
                self.emit('control_established', posts=post_count,
                          coverage=round(coverage, 3))
                self._log(t, 'control_established', coverage=round(coverage, 3))
        else:
            # 离位容忍：超阈值记一次中断；回岗记一次恢复。同一次离位不重复刷，
            # 历史也不因恢复而抹掉（1028 §1.4 全过程核验）。
            for pid in tracked:
                if pid in self.lost_pids:
                    continue
                if pid in manned:
                    self.vacancy_started.pop(pid, None)
                    if pid in self.interrupted_pids:
                        self.interrupted_pids.discard(pid)
                        self.emit('control_restored', pid=pid,
                                  role=self._role_label(pid))
                        self._log(t, 'control_restored', pid=pid,
                                  role=self._role_label(pid))
                    continue
                since = self.vacancy_started.setdefault(pid, t)
                if (t - since >= float(p['occupancy_tolerance_s'])
                        and pid not in self.interrupted_pids):
                    self.interrupted_pids.add(pid)
                    self.interruptions.append(dict(t=round(t, 2), pid=pid,
                                                   role=self._role_label(pid),
                                                   reason='离位超过容忍时长'))
                    self.emit('control_interrupted', pid=pid,
                              role=self._role_label(pid))
                    self._log(t, 'control_interrupted', pid=pid,
                              role=self._role_label(pid))

    # ---------------- 结算 ----------------
    def _finalize(self, t, timeout=False):
        if self.done:
            return
        self._last_coverage = getattr(self, '_last_coverage', 0.0)
        self.control_released_at = round(t, 2)
        metrics = dict(
            perimeter_m=round(self.perimeter_m, 1),
            control_level=self.control_level,
            control_level_label=CN_LEVEL_LABELS[self.control_level],
            engagement_authority=self.authority,
            boundary_coverage=round(self.coverage_sum / max(self.coverage_t, 1e-9), 4),
            occupancy_ratio=round(self.occupancy_sum / max(self.coverage_t, 1e-9), 4),
            air_units=len(getattr(self, 'air_pids', [])),
            air_altitude_m=(float(self.params['air_altitude_m'])
                            if getattr(self, 'air_pids', []) else None),
            unauthorized_approaches=self.counts['unauthorized'],
            authorized_approaches=self.counts['authorized'],
            unauthorized_entries=self.counts['breach'],
            leak_rate=round(self.counts['breach']
                            / max(1, self.counts['unauthorized']), 4),
            intercept_attempts=self.counts['intercept_attempts'],
            intercepted=self.counts['intercepted'],
            intercept_rate=round(self.counts['intercepted']
                                 / max(1, self.counts['intercept_attempts']), 4),
            warned=self.counts['warned'],
            warning_effective=self.counts['warning_effective'],
            warning_effective_rate=round(self.counts['warning_effective']
                                         / max(1, self.counts['warned']), 4),
            authorized_passes=self.counts['passed'],
            false_intercepts=self.counts['false_intercept'],
            mean_response_s=(round(sum(self.response_times)
                                   / len(self.response_times), 2)
                             if self.response_times else None),
            mean_warning_latency_s=(round(sum(self.warn_latencies)
                                          / len(self.warn_latencies), 2)
                                    if self.warn_latencies else None),
            control_established_at_s=self.control_established_at,
            control_released_at_s=self.control_released_at,
            interruptions=len(self.interruptions),
            targets=[x.snapshot() for x in self.targets],
            timeline=[dict(row) for row in self.timeline],
        )
        result = self._verdict(metrics, timeout=timeout)
        metrics['verdict'] = result
        self.metrics.update(metrics)
        self.verdict = result
        self._log(t, 'containment_result',
                  verdict=result['verdict'], reason=result['reason'])
        # 事件里带一份"可回放"的完整过程数据：指标数字、逐目标轨迹与控制
        # 时间线。工作台的区域封控页只读这一条事件 + 结构事件，不再二次推算。
        summary = {k: v for k, v in metrics.items()
                   if k not in ('targets', 'timeline')}
        self.emit('containment_result', verdict=result['verdict'],
                  reason=result['reason'], items=result['items'],
                  metrics=summary,
                  targets=[dict(x.snapshot(), track=[list(p) for p in x.track])
                           for x in self.targets],
                  timeline=[dict(row) for row in self.timeline])
        self._finish('containment_timeout' if timeout else 'containment_done')

    def _verdict(self, metrics, timeout=False):
        """按 1028 §2.2.2 的控制目标逐项判定；缺证据时记"待确认"。

        本层只判"控制目标是否达成"：执行走完不等于任务成功，目标未达成也
        不因此重跑作业（重试属于指挥层决策）。
        """
        p = self.params
        items = []
        objective = self.objective
        if objective == 'deny_entry':
            limit = float(p['max_leak_rate'])
            ok = metrics['unauthorized_entries'] == 0
            items.append(dict(id='unauthorized_entries', label='未授权进入事件数',
                              value=metrics['unauthorized_entries'], target=0,
                              ok=ok, required=True))
            items.append(dict(id='leak_rate', label='漏控率',
                              value=metrics['leak_rate'], target=limit,
                              ok=metrics['leak_rate'] <= limit + 1e-9,
                              required=True))
            items.append(dict(id='intercept_rate', label='拦截成功率',
                              value=metrics['intercept_rate'],
                              target=float(p['min_intercept_rate']), required=False,
                              ok=metrics['intercept_rate'] >= float(p['min_intercept_rate'])
                              or metrics['intercept_attempts'] == 0))
        elif objective == 'control_passage':
            items.append(dict(id='unauthorized_cross', label='未授权穿越数',
                              value=metrics['unauthorized_entries'], target=0,
                              ok=metrics['unauthorized_entries'] == 0,
                              required=True))
            items.append(dict(id='authorized_pass', label='授权放行率',
                              value=(1.0 if metrics['authorized_approaches'] == 0
                                     else round(metrics['authorized_passes']
                                                / max(1, metrics['authorized_approaches']), 4)),
                              target=1.0,
                              ok=metrics['authorized_approaches'] == 0
                              or metrics['authorized_passes'] == metrics['authorized_approaches'],
                              required=True))
        elif objective == 'monitor_channel':
            target = float(p['min_coverage'])
            items.append(dict(id='boundary_coverage', label='边界监视覆盖率',
                              value=metrics['boundary_coverage'], target=target,
                              ok=metrics['boundary_coverage'] >= target,
                              required=True))
            items.append(dict(id='occupancy_ratio', label='持续占位率',
                              value=metrics['occupancy_ratio'], target=target,
                              ok=metrics['occupancy_ratio'] >= target,
                              required=True))
        else:   # intercept
            items.append(dict(id='intercept_rate', label='拦截成功率',
                              value=metrics['intercept_rate'],
                              target=float(p['min_intercept_rate']),
                              ok=metrics['intercept_rate'] >= float(p['min_intercept_rate']),
                              required=True))
            response = metrics['mean_response_s']
            items.append(dict(id='mean_response', label='平均响应时间(s)',
                              value=response, target=float(p['max_response_s']),
                              ok=response is not None
                              and response <= float(p['max_response_s']),
                              required=True))

        failed = [x for x in items if x['required'] and not x['ok']]
        if timeout:
            verdict, reason = 'failed', '封控时段结束时仍有目标未闭合'
        elif metrics['unauthorized_approaches'] == 0 and objective in (
                'deny_entry', 'intercept'):
            verdict = 'pending'
            reason = '本次未触发未授权接近事件：只支持"状态维持"结论，不证明处置能力'
        elif failed:
            verdict = 'failed'
            reason = '；'.join('%s=%s（要求 %s）' % (x['label'], x['value'], x['target'])
                              for x in failed)
        else:
            verdict = 'succeeded'
            reason = '全部必需判据有证据满足（封控 %s s，控制等级%s，交战授权%s）' % (
                int(float(p['duration_s'])), CN_LEVEL_LABELS[self.control_level],
                CN_AUTHORITY_LABELS[self.authority])
        return dict(verdict=verdict, reason=reason, items=items,
                    objective=objective,
                    evidence='本地行为状态机 + 4.1 输入仿真的过程记录',
                    closure=[x.snapshot() for x in self.targets])

    # ---------------- 展示 ----------------
    def progress_frac(self):
        if self.done:
            return 1.0
        if self.control_established_at is None:
            return 0.12 * min(1.0, self.t / 30.0)
        elapsed = self.t - self.control_established_at
        return min(0.98, 0.12 + 0.88 * elapsed
                   / max(float(self.params['duration_s']), 1.0))

    def debug(self):
        return dict(
            control_level=self.control_level,
            coverage=round(getattr(self, '_last_coverage', 0.0), 3),
            on_post={pid: bool(self._on_post.get(pid)) for pid in self.posts},
            targets=[dict(target_id=x.id, state=x.state,
                          pos=[round(v, 2) for v in x.pos],
                          interceptor=x.interceptor) for x in self.targets],
            interceptor_active=dict(self.intercept_tasks),
        )


# ------------------------------------------------------------------
# 3. 协同侦察：共享地图 + 前沿覆盖
# ------------------------------------------------------------------
class ReconBehavior(Behavior):
    kind = 'recon'
    label = '协同侦察'
    DEFAULTS = dict(area_radius=9.0, cell=1.2, sensor_radius=2.6,
                    coverage_target=0.9, frontier_tol=0.9,
                    claim_radius=1.6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.params
        cell = p['cell']
        x0, y0, x1, y1 = self.nav.bounds
        cx, cy = self.site
        r = p['area_radius']
        self.cells = []
        nx = int(2 * r / cell)
        for i in range(nx + 1):
            for j in range(nx + 1):
                q = [cx - r + i * cell, cy - r + j * cell]
                if not (x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                    continue
                if self.nav.clearance(q) < 0.2:
                    continue
                self.cells.append((round(q[0], 2), round(q[1], 2)))
        self.unknown = set(self.cells)
        self.explored = set()
        self.claimed = {}
        self.phase = '展开'
        self.report_sent = False
        self.last_coverage_emit = 0.0
        self.metrics.update(cells=len(self.cells),
                            sensor_radius=p['sensor_radius'],
                            area_radius=p['area_radius'])

    def _mark(self, point):
        r = self.params['sensor_radius']
        newly = [c for c in self.unknown if distance(c, point) <= r]
        for c in newly:
            self.unknown.discard(c)
            self.explored.add(c)
        return len(newly)

    def coverage(self):
        return 1 - len(self.unknown) / max(1, len(self.cells))

    def _frontier(self, pose, pid):
        p = self.params
        best, best_d = None, math.inf
        for cell in self.unknown:
            # 前沿 = 未知格，且 2 格内有已探索/已感知区域
            known = any(distance(cell, c) <= p['cell'] * 1.8
                        for c in self.explored)
            if not known:
                continue
            if any(distance(cell, q) < p['claim_radius']
                   for other, q in self.claimed.items() if other != pid):
                continue
            d = distance(pose, cell)
            if d < best_d:
                best, best_d = cell, d
        return best

    def step(self, poses, t, dt):
        self.t = t
        p = self.params
        targets = {}
        if not getattr(self, '_primed', False):
            # 出发位附近的区域视为"已探索"，从它往外找前沿
            for pid in self.pids:
                self._mark(poses[pid])
            self._primed = True
            self.emit('map_initialised', explored=len(self.explored),
                      coverage=round(self.coverage(), 3))
        if self.phase == '展开':
            self.set_phase('探索')
        reach = p['coverage_target']
        if self.phase == '探索' and self.coverage() >= reach:
            self.set_phase('回传')
            self.emit('coverage_reached',
                      coverage=round(self.coverage(), 3))
        if self.phase == '回传':
            rally = _polar(self.site, 1.5, 0.0)
            for pid in self.pids:
                targets[pid] = rally
            if self.occupy(poses, [rally] * len(self.pids), 1.0):
                if not self.report_sent:
                    self.report_sent = True
                    self.metrics['coverage'] = round(self.coverage(), 3)
                    self.emit('report_sent', coverage=round(self.coverage(), 3),
                              cells=len(self.cells))
                self._finish('map_shared')
            return dict(targets=targets, phase=self.phase, done=self.done)
        for pid in self.pids:
            pose = poses[pid]
            target = self.claimed.get(pid)
            if target is None or distance(pose, target) <= p['frontier_tol']:
                if target is not None:
                    gained = self._mark(target)
                    cov = self.coverage()
                    self.emit('frontier_mapped', pid=pid,
                              pos=[round(v, 2) for v in target],
                              newly=gained, coverage=round(cov, 3))
                    if cov - self.last_coverage_emit >= 0.2:
                        self.last_coverage_emit = cov
                        self.emit('map_shared', coverage=round(cov, 3),
                                  explored=len(self.explored))
                target = self._frontier(pose, pid)
                self.claimed[pid] = target
            targets[pid] = target if target is not None else poses[pid]
        if all(self.claimed.get(pid) is None for pid in self.pids):
            # 没有可达前沿了：要么覆盖够了，要么剩余未知区被建筑隔断
            self.set_phase('回传')
            self.emit('coverage_reached', coverage=round(self.coverage(), 3),
                      reason='no_frontier')
        return dict(targets=targets, phase=self.phase, done=self.done)

    def progress_frac(self):
        if self.done:
            return 1.0
        return min(1.0, self.coverage() / max(self.params['coverage_target'], 1e-6))

    def debug(self):
        return dict(coverage=round(self.coverage(), 3),
                    explored=len(self.explored),
                    targets={k: v for k, v in self.claimed.items() if v})


# ------------------------------------------------------------------
# 4. 机动突击：T-ASL
#    指令 → 机动（集结）→ 侦察指示 → 占位 → 打击 → 结果待确认 →
#    外部评估 → 成功/失败 → 撤离
#
# 口径对齐《无人集群编队五类任务定义》2.4：
#   * 集结区、攻击阵位、观察/评估点、撤离点分开记录，不再把集结环
#     默认套在目标上（需显式给 staging_center）。
#   * 指令发送、平台到位、动作结束、效果达成是不同事实，分别出事件。
#   * 效果只由外部评估接口判定；评估未回时记“结果待确认”，不默认成功。
#   * 攻击窗口、打击时长、评估时延、撤离时限、确认期限都留时间戳。
# 兼容旧场景：不给 staging_center / scout_pid / result_items 时，行为与
# 原来一致（集结环在目标附近，首位平台前出确认点，阶段名不变）。
# ------------------------------------------------------------------
class AssaultBehavior(Behavior):
    kind = 'assault'
    label = '机动突击'
    DEFAULTS = dict(
        # 几何
        staging_center=None, staging_radius=4.2, objective_radius=1.4,
        confirm_radius=3.0, arrive_tol=0.7, sync_tol=1.0,
        # 侦察/指示组（信息保障单元）
        scout_pid=None, observe_radius=25.0, observe_angle=-math.pi / 2,
        # 评估组（独立评估单元）：随队机动，执行期前出评估观察位
        assessor_pid=None, assessment_post=None,
        # 时序与评估
        attack_window=None, confirm_dwell=2.0,
        assessment_delay=0.0, confirmation_deadline=None,
        # 效果三分类（damage/suppress/seize，也接受中文标签）
        effect_kind='damage', effect=None,
        required_level=3.0, damage_per_hit=1.0, fire_interval=2.0,
        rounds_per_salvo=1, ammo_per_platform=1,
        required_duration=10.0, recovery_gap=3.0,
        required_control_s=10.0, min_occupants=2, hold_required_s=10.0,
        # 辅助指标的可仿真部分：敌方反击（夺占期按周期发生）、角色载荷下限
        counterattack_interval=0.0, counterattack_break_s=0.0,
        assault_payload_required=0.0,
        # 空中分队高度（pid → 巡航高度）与爬升率；未列出的空中平台用初始高度
        air_altitude=None, climb_rate=8.0,
        # 终止条件（弹药耗尽/执行截止；目标消失/被迫撤离仅预留接口字段）
        execute_deadline=None, target_vanish=False, forced_withdraw=False,
        # 任务输入（2.4.8）：交战规则、附带损伤、正识别、波次、作用对象
        roe='仅打击经指示的指定目标', collateral_limit=None,
        positive_id_required=False, waves=1,
        object_label=None, target_id=None, rule_version='T-ASL/2026-10-29',
        # 撤离
        withdraw=False, withdraw_point=None, withdraw_ring=2.0,
        withdraw_deadline=None, timeout_s=240.0)

    # 结果项标签（规范 §5：必需项逐项结算，信息项不计成败）
    RESULT_LABELS = {
        'effect': {'damage': '毁伤等级不低于规定值',
                   'suppress': '目标连续压制不低于规定时长',
                   'seize': '控制权保持不低于规定时长'},
        'window': '效果在规定时间窗内达成',
        'confirmation': '结果确认（评估回传）',
        'hold_after_handover': '移交后持续坚守',
    }
    # 进入评估证据的事件子集（evidence.events）
    EVIDENCE_EVENTS = ('command_received', 'all_staged', 'assault_started',
                       'all_in_position', 'effect_started', 'salvo_fired',
                       'restrike_needed', 'effect_achieved', 'handover',
                       'control_established', 'control_lost',
                       'suppression_gap', 'assessment_requested')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.params
        # 可插拔评估接口：params 可注入同协议 Adjudicator（对象不入 JSON 事件）
        self.adjudicator = p.pop('adjudicator', None) or StubAdjudicator()
        job = args[0] if args and isinstance(args[0], dict) else {}
        # 评估结果绑定：本任务 + 本对象 + 当前执行版本（attempt）
        self.attempt = int(job.get('attempt') or 1)
        self.scout = p.get('scout_pid') if p.get('scout_pid') in self.pids else None
        self.assessor = (p.get('assessor_pid')
                         if p.get('assessor_pid') in self.pids
                         and p.get('assessor_pid') != self.scout else None)
        self.assault_pids = ([x for x in self.pids
                              if x not in (self.scout, self.assessor)]
                             or list(self.pids))
        self.effect_kind = normalize_effect_kind(
            p.get('effect_kind') or p.get('effect'))
        self.effect_label = EFFECT_KINDS[self.effect_kind]
        self.target_id = str(p.get('target_id') or p.get('object_label')
                             or self.job_id)
        self._assessor_slot = (self.pids.index(self.assessor)
                               if self.assessor else 0)
        n = max(2, len(self.assault_pids))
        center = p.get('staging_center') or self.site
        self.staging_center = [float(center[0]), float(center[1])]
        self.staging = [self._reachable_ring_point(
            self.staging_center, p['staging_radius'],
            2 * math.pi * i / n) for i in range(n)]
        self.objective = [self._reachable_ring_point(
            self.site, p['objective_radius'],
            2 * math.pi * i / n) for i in range(n)]
        self.observation = (self._reachable_ring_point(
            self.site, p['observe_radius'], p['observe_angle'])
            if self.scout else None)
        # 评估观察位：显式配置时吸附到可通行点；缺省在观察环上错开侦察位
        self.assessment_post = None
        if self.assessor:
            if p.get('assessment_post'):
                post, offset = self.nav.nearest_free(
                    [float(p['assessment_post'][0]),
                     float(p['assessment_post'][1])])
                self.assessment_post = post
                self.assessment_post_snap = round(offset, 3)
            else:
                self.assessment_post = self._reachable_ring_point(
                    self.site, p['observe_radius'],
                    p['observe_angle'] + 0.7)
        self.withdraw_point = ([float(p['withdraw_point'][0]),
                                float(p['withdraw_point'][1])]
                               if p.get('withdraw_point') else None)
        self.withdraw_targets = ([self._reachable_ring_point(
            self.withdraw_point, p['withdraw_ring'],
            2 * math.pi * i / n) for i in range(n)]
            if p.get('withdraw') and self.withdraw_point else [])

        self.roles = {pid: '突击组' for pid in self.assault_pids}
        if self.scout:
            self.roles[self.scout] = '侦察指示组'
        if self.assessor:
            self.roles[self.assessor] = '评估组'
        self.window = ([float(v) for v in p['attack_window']]
                       if p.get('attack_window') else None)

        # ---- 效果引擎状态（证据来源，评估只读不改） ----
        self.ammo = {pid: max(0, int(p['ammo_per_platform']))
                     for pid in self.assault_pids}
        self.fire_log = []              # [{t, pids, rounds, hits, ...}]
        self.damage_level = 0.0
        self.shots_fired = 0
        self.shots_hit = 0
        self.restrikes = 0
        self.suppression_gaps = 0
        self.coverage_intervals = []    # 压制覆盖区间 [[t0, t1], ...]
        self.control_intervals = []     # 控制区间 [[t0, t1], ...]
        self.longest_suppression_s = 0.0
        self.longest_control_s = 0.0
        self._run_start_t = None        # 当前压制连续段起点
        self._last_fire_t = None
        self._next_salvo_t = None
        self._control_on = False
        self._control_start = None
        self.hold_start_t = None
        self.hold_s = 0.0
        self.handover_t = None
        self.effect_achieved_t = None
        self.termination = None
        self.assess_requested = False
        self.confirm_deadline_t = None
        self.execute_start_t = None
        self.execute_deadline_t = None
        self.result = None
        self._last_adjudicator = None
        self._last_verified = None

        self.stage_enter_t = 0.0
        self.effect_t = None
        self.confirmed_t = None
        self.assessment_t = None
        self.deadline_t = None
        self.phase_times = []
        self.arrivals = {pid: {} for pid in self.pids}
        self.position_reported = False
        self.designated = False
        self.assessed = False
        self.speeds = {}
        self.release_at = {}
        self.withdraw_started_t = None
        self.status = '执行中'
        # ---- 辅助指标状态（规范 2.4.3：逐项可核验，不拿过程量冒充结果） ----
        self.losses = []             # 执行期我方损失（pid + 时刻）
        self.lost_pids = set()
        self.role_violations = []    # 角色载荷校核未通过项
        self.role_blocked = False
        self.counterattacks = []     # 夺占期敌方反击（时刻）
        self.control_interruptions = 0
        self._next_counter_t = None
        self.recovery_s = None       # 压制结束后到任务结束的实测恢复时延
        self.max_gap_s = 0.0         # 实测最大压制中断
        self._build_result_items()
        self.metrics.update(
            staging=[[round(v, 2) for v in q] for q in self.staging],
            staging_center=[round(v, 2) for v in self.staging_center],
            objective=[[round(v, 2) for v in q] for q in self.objective],
            observation=([round(v, 2) for v in self.observation]
                         if self.observation else None),
            assessment_post=([round(v, 2) for v in self.assessment_post]
                             if self.assessment_post else None),
            confirm_radius=p['confirm_radius'], roles=dict(self.roles),
            attack_window=self.window,
            effect_kind=self.effect_kind, effect=self.effect_label,
            target_id=self.target_id, attempt=self.attempt,
            assessment_delay=p['assessment_delay'],
            assessment_source=self.adjudicator.name,
            assessment_source_class=(
                '构造数据（演示桩，未接入评估接口）'
                if not getattr(self.adjudicator, 'verified', False)
                else '外部评估接口'),
            result_items=[dict(x) for x in self.result_items],
            ammo=dict(self.ammo),
            inputs=dict(effect=self.effect_label,
                        effect_kind=self.effect_kind,
                        object=p['object_label'] or
                        [round(v, 2) for v in self.site],
                        target_id=self.target_id,
                        roe=p['roe'], collateral_limit=p['collateral_limit'],
                        positive_id_required=bool(p['positive_id_required']),
                        waves=p['waves'], ammo_per_platform=p['ammo_per_platform'],
                        rule_version=p['rule_version']),
            overall_status=self.status, status=self.status)
        self.emit('command_received', target=[[round(v, 2) for v in self.site]],
                  roles=dict(self.roles), attack_window=self.window,
                  effect_kind=self.effect_kind, effect=self.effect_label,
                  target_id=self.target_id, attempt=self.attempt,
                  ammo=dict(self.ammo), ammo_per_platform=p['ammo_per_platform'],
                  adjudicator=self.adjudicator.name,
                  roe=p['roe'], collateral_limit=p['collateral_limit'],
                  positive_id_required=bool(p['positive_id_required']),
                  waves=p['waves'], source='planner')
        self.phase_times.append(dict(phase='机动', t=round(getattr(self, 't', 0.0), 2)))
        self.set_phase('机动')

    # ---- 弹药与效果引擎 ----
    def set_platform_caps(self, caps):
        """角色级能力校核（第二道闸门）：突击组必须扛得动战斗载荷。

        规划器已按 role_payload 做过一次过滤；这里再核一次，因为行为层
        收到的成员可能来自旧方案或人工改写。支援组（侦察/评估）只带传感器，
        不参与这条校核。
        """
        super().set_platform_caps(caps)
        required = float(self.params.get('assault_payload_required') or 0.0)
        self.role_violations = []
        if required > 0:
            for pid in self.assault_pids:
                payload = (caps.get(pid) or {}).get('payload')
                if payload is not None and float(payload) < required:
                    self.role_violations.append(
                        dict(pid=pid, role=self.roles.get(pid, '突击组'),
                             payload=round(float(payload), 2),
                             required=required))
        self.metrics['role_check'] = dict(
            required=required, ok=not self.role_violations,
            violations=[dict(x) for x in self.role_violations],
            note='突击组载荷下限；支援组只带传感器，不参与该下限')
        if self.role_violations:
            self.role_blocked = True
            self.emit('role_check_failed', required=required,
                      violations=[dict(x) for x in self.role_violations])

    def report_loss(self, pid, t):
        """记录执行期我方损失；损失成员不再计入在位/开火/控制人数。"""
        if pid in self.lost_pids:
            return
        self.lost_pids.add(pid)
        self.losses.append(dict(pid=pid, t=round(t, 2),
                                role=self.roles.get(pid, '突击组')))
        self.metrics['our_losses'] = len(self.losses)
        self.emit('loss', pid=pid, role=self.roles.get(pid, '突击组'),
                  at=round(t, 2), total=len(self.losses))

    def _alive(self, pid):
        return pid not in self.lost_pids

    def set_platform_ammo(self, values):
        """注入平台级弹药基数（编成参数 PLANNING_PARAMS.ammo，经替身透传）。"""
        for pid in self.assault_pids:
            if values.get(pid) is not None:
                self.ammo[pid] = max(0, int(values[pid]))
        self.metrics['ammo'] = dict(self.ammo)

    def _in_objective(self, pose):
        radius = float(self.params['objective_radius'])
        return distance(pose, self.site) <= radius + self.params['arrive_tol'] + 0.05

    def _step_effect(self, poses, t):
        """执行期效果推进：毁伤按齐射累计等级，压制按覆盖区间，夺占按控制区间。"""
        if self.effect_kind == 'seize':
            self._step_seize(poses, t)
        elif self._next_salvo_t is None or t >= self._next_salvo_t:
            self._fire_salvo(poses, t)

    def _fire_salvo(self, poses, t):
        """一轮齐射：在目标环内且有弹的平台各发 rounds_per_salvo 发。

        演示口径（桩判定）：占位在 objective_radius 内且弹药>0 即视为命中。
        """
        p = self.params
        rounds = max(1, int(p['rounds_per_salvo']))
        fired, hits = [], 0
        for pid in self.assault_pids:
            if (self._alive(pid)
                    and self.ammo.get(pid, 0) >= rounds
                    and self._in_objective(poses[pid])):
                self.ammo[pid] -= rounds
                fired.append(pid)
                hits += rounds
        if not fired:
            return                      # 本拍无人可开火（不在位 / 无弹）
        self._next_salvo_t = t + float(p['fire_interval'])
        self.shots_fired += rounds * len(fired)
        self.shots_hit += hits
        salvo = dict(t=round(t, 2), pids=list(fired), rounds=rounds, hits=hits)
        self.fire_log.append(salvo)
        if self.effect_kind == 'damage':
            self.damage_level += hits * float(p['damage_per_hit'])
            salvo['damage_level'] = round(self.damage_level, 2)
        self.emit('salvo_fired', pids=fired, rounds=rounds, hits=hits,
                  damage_level=round(self.damage_level, 2),
                  ammo_left={pid: self.ammo[pid] for pid in fired})
        for pid in fired:
            if self.ammo[pid] <= 0:
                self.emit('ammo_depleted', pid=pid, note='平台弹药耗尽')
        if self.effect_kind == 'damage':
            if self.damage_level >= float(p['required_level']):
                self._effect_achieved(t)
            elif self.effect_achieved_t is None:
                self.restrikes += 1
                self.emit('restrike_needed',
                          level=round(self.damage_level, 2),
                          required=float(p['required_level']))
        else:
            self._step_suppress_coverage(t)

    def _step_suppress_coverage(self, t):
        """压制覆盖记账：无人开火超过 recovery_gap → 覆盖断开、连续时长重计。"""
        p = self.params
        if (self._last_fire_t is not None
                and t - self._last_fire_t > float(p['recovery_gap'])):
            self.max_gap_s = max(self.max_gap_s, t - self._last_fire_t)
            self._close_coverage()
            self.suppression_gaps += 1
            self.emit('suppression_gap',
                      gap_s=round(t - self._last_fire_t, 2),
                      continuous_s=round(self.longest_suppression_s, 2))
        if self._run_start_t is None:
            self._run_start_t = t
        self._last_fire_t = t
        run = t - self._run_start_t
        self.longest_suppression_s = max(self.longest_suppression_s, run)
        if run >= float(p['required_duration']):
            self._effect_achieved(t)

    def _close_coverage(self):
        if self._run_start_t is not None:
            end = self._last_fire_t if self._last_fire_t is not None else self._run_start_t
            self.coverage_intervals.append(
                [round(self._run_start_t, 2), round(end, 2)])
            self._run_start_t = None

    def _step_seize(self, poses, t):
        """夺占：≥min_occupants 在目标环内 → 控制建立；跌破 → 控制丢失。

        敌方反击（辅助指标"敌方反击次数"）：控制期内按 `counterattack_interval`
        周期发生，默认被在位兵力击退、不打断连续控制；若配置
        `counterattack_break_s`，则每次反击造成该时长的控制中断（连续控制
        计时重计，用于演示"反击确实能打断夺占"）。
        """
        p = self.params
        occupants = [pid for pid in self.assault_pids
                     if self._alive(pid) and self._in_objective(poses[pid])]
        if not self._control_on:
            pause_until = getattr(self, '_control_pause_until', None)
            if pause_until is not None and t < pause_until:
                return                      # 反击造成的中断尚未解除
            if len(occupants) >= int(p['min_occupants']):
                self._control_on = True
                self._control_start = t
                self._control_pause_until = None
                interval = float(p.get('counterattack_interval') or 0.0)
                self._next_counter_t = (t + interval) if interval > 0 else None
                self.emit('control_established', occupants=occupants,
                          min_occupants=int(p['min_occupants']))
            return
        run = t - self._control_start
        self.longest_control_s = max(self.longest_control_s, run)
        if len(occupants) < int(p['min_occupants']):
            self._control_on = False
            self.control_intervals.append(
                [round(self._control_start, 2), round(t, 2)])
            self.emit('control_lost', held_s=round(run, 2),
                      occupants=len(occupants))
            return
        if (self.effect_achieved_t is None
                and run >= float(p['required_control_s'])):
            self.control_intervals.append(
                [round(self._control_start, 2), round(t, 2)])
            self._effect_achieved(t)
            return
        # 敌方反击（只记事实；是否打断控制由参数决定）
        if self._next_counter_t is not None and t >= self._next_counter_t:
            interval = max(0.1, float(p.get('counterattack_interval') or 0.0))
            self._next_counter_t = t + interval
            self.counterattacks.append(round(t, 2))
            break_s = max(0.0, float(p.get('counterattack_break_s') or 0.0))
            self.emit('counterattack', n=len(self.counterattacks),
                      held_s=round(run, 2), occupants=len(occupants),
                      repelled=break_s <= 0)
            if break_s > 0:
                self.control_intervals.append(
                    [round(self._control_start, 2), round(t, 2)])
                self.control_interruptions += 1
                self._control_on = False
                self._control_pause_until = t + break_s
                self.emit('control_interrupted',
                          break_s=round(break_s, 2),
                          n=self.control_interruptions)

    def _step_hold(self, poses, t):
        """移交后坚守：独立于夺占单独结算，夺占成功不自动使坚守成功。"""
        p = self.params
        occupants = [pid for pid in self.assault_pids
                     if self._in_objective(poses[pid])]
        self.hold_s = t - self.hold_start_t
        if len(occupants) < int(p['min_occupants']):
            self.emit('control_lost', held_s=round(self.hold_s, 2),
                      occupants=len(occupants), phase='坚守')
            self._action_complete(t)
        elif self.hold_s >= float(p['hold_required_s']):
            self._action_complete(t)

    def _effect_achieved(self, t):
        """效果达成事实（与动作结束、结果确认分列；结果项由评估接口判定）。"""
        self.effect_achieved_t = t
        self.metrics['effect_achieved_t'] = round(t, 2)
        if self.effect_kind == 'damage':
            fields = dict(damage_level=round(self.damage_level, 2))
        elif self.effect_kind == 'suppress':
            fields = dict(suppression_s=round(self.longest_suppression_s, 2))
        else:
            fields = dict(control_s=round(self.longest_control_s, 2))
        self.emit('effect_achieved', effect_kind=self.effect_kind,
                  at=round(t, 2), **fields)
        if self.effect_kind == 'seize':
            # 夺占与移交后坚守分别结算：达成即移交，坚守独立计时
            self.handover_t = t
            self.hold_start_t = t
            self.emit('handover', at=round(t, 2),
                      hold_required_s=float(self.params['hold_required_s']))
            self.set_phase('坚守')
            self.phase_times.append(dict(phase='坚守', t=round(t, 2)))
        else:
            self._close_coverage()
            self._action_complete(t)

    def _action_complete(self, t):
        """动作结束事实（effect_applied）：进入结果确认，两类截止分别核验。"""
        p = self.params
        self.metrics['ammo_used'] = self.shots_fired
        self._fill_info_items()
        self.emit('effect_applied',
                  strike_s=round(t - (self.effect_t if self.effect_t is not None
                                      else t), 2),
                  ammo_used=self.shots_fired, waves=p['waves'],
                  effect_kind=self.effect_kind)
        self._set_status('结果待确认')
        self.set_phase('结果确认')
        self.stage_enter_t = t
        if p.get('confirmation_deadline') is not None:
            self.confirm_deadline_t = t + float(p['confirmation_deadline'])
            self.deadline_t = self.confirm_deadline_t
            self.metrics['confirmation_deadline_t'] = round(
                self.confirm_deadline_t, 2)
        self.phase_times.append(dict(phase='结果确认', t=round(t, 2)))
        self.emit('result_pending', source=self.adjudicator.name,
                  deadline_t=round(self.confirm_deadline_t, 2)
                  if self.confirm_deadline_t is not None else None,
                  items=[dict(x) for x in self.result_items],
                  missing=[x['id'] for x in self.result_items
                           if x.get('required')])

    # ---- 逐项结算（规范 §5） ----
    def _build_result_items(self):
        self.result_items = [dict(
            id='effect', label=self.RESULT_LABELS['effect'][self.effect_kind],
            required=True, status='pending', t=None, evidence=None, metric=None)]
        if self.window:
            self.result_items.append(dict(
                id='window', label=self.RESULT_LABELS['window'],
                required=True, status='pending', t=None, evidence=None,
                metric=None))
        self.result_items.append(dict(
            id='confirmation', label=self.RESULT_LABELS['confirmation'],
            required=True, status='pending', t=None, evidence=None,
            metric=None))
        if self.effect_kind == 'seize':
            self.result_items.append(dict(
                id='hold_after_handover',
                label=self.RESULT_LABELS['hold_after_handover'],
                required=True, status='pending', t=None, evidence=None,
                metric=None))
        auxiliary_labels = {
            'damage': '命中率 / 弹药消耗 / 二次打击需求',
            'suppress': '火力覆盖时间 / 目标恢复时间 / 我方损失',
            'seize': '控制时长 / 敌方反击次数 / 移交时间'}
        self.result_items.extend([
            dict(id='ammo_used', label='弹药消耗', required=False,
                 status='info', t=None, evidence=None, metric=None),
            dict(id='effect_metric',
                 label=auxiliary_labels[self.effect_kind], required=False,
                 status='info', t=None, evidence=None, metric=None),
            dict(id='restrikes', label='二次打击次数', required=False,
                 status='info', t=None, evidence=None, metric=None)])

    def _item(self, item_id):
        return next((x for x in self.result_items if x['id'] == item_id), None)

    def _set_item(self, item_id, status, t=None, evidence=None, metric=None):
        item = self._item(item_id)
        if item is None or status is None:
            return
        item['status'] = status
        if t is not None:
            item['t'] = round(float(t), 2)
        if evidence is not None:
            item['evidence'] = evidence
        if metric is not None:
            item['metric'] = metric

    def _overall(self):
        required = [x for x in self.result_items if x.get('required')]
        if any(x['status'] == 'failed' for x in required):
            return 'failed'
        if required and all(x['status'] == 'achieved' for x in required):
            return 'succeeded'
        return 'pending'

    def _auxiliary(self, total_suppression):
        """辅助指标（规范 §7 表格里的"辅助指标"列）。

        口径：只报**本次运行记录到的事实**；没建模的量明确标注"仅登记"，
        不写成已测量。判定口径写在 verdict 里，供工作台逐项显示。
        """
        our_losses = len(self.losses)
        rows = []
        if self.effect_kind == 'damage':
            rate = (self.shots_hit / self.shots_fired
                    if self.shots_fired else None)
            rows = [
                dict(key='hit_rate', label='命中率',
                     value=(round(rate, 2) if rate is not None else None),
                     unit='', verdict=('达标' if rate is not None and rate >= 0.8
                                       else '未达标' if rate is not None else '未开始'),
                     note='命中/发射（桩判定：在目标环内且有弹即命中）'),
                dict(key='ammo_used', label='弹药消耗',
                     value=self.shots_fired, unit='发',
                     verdict='已记录', note='逐发记录，含各平台余弹'),
                dict(key='restrikes', label='二次打击需求',
                     value=self.restrikes, unit='次',
                     verdict=('需要' if self.restrikes else '不需要'),
                     note='未达规定等级时的补射次数'),
                dict(key='our_losses', label='我方损失',
                     value=our_losses, unit='台',
                     verdict=('有损失' if our_losses else '无损失'),
                     note='执行期失联/被击毁的平台数（本层只统计失联注入）'),
            ]
        elif self.effect_kind == 'suppress':
            gap_model = float(self.params.get('recovery_gap') or 0.0)
            rows = [
                dict(key='coverage_total', label='火力覆盖时间',
                     value=round(total_suppression, 2), unit='s',
                     verdict=('达标' if total_suppression >= float(
                         self.params.get('required_duration') or 0) else '未达标'),
                     note='各覆盖区间累计；中断后重新计时'),
                dict(key='coverage_longest', label='最长连续压制',
                     value=round(self.longest_suppression_s, 2), unit='s',
                     verdict=('达标' if self.longest_suppression_s >= float(
                         self.params.get('required_duration') or 0) else '未达标'),
                     note='连续段最长值，决定效果是否达成'),
                dict(key='recovery_gap', label='目标恢复时间',
                     value=round(gap_model, 2), unit='s',
                     verdict='模型参数',
                     note='无人开火超过该时长即视为目标恢复行动能力'),
                dict(key='gaps', label='压制中断',
                     value=self.suppression_gaps, unit='次',
                     verdict=('有中断' if self.suppression_gaps else '无中断'),
                     note='实测最大中断 %.1f s' % self.max_gap_s),
                dict(key='our_losses', label='我方损失',
                     value=our_losses, unit='台',
                     verdict=('有损失' if our_losses else '无损失'),
                     note='执行期失联平台数'),
            ]
        else:
            rows = [
                dict(key='control_longest', label='控制时长',
                     value=round(self.longest_control_s, 2), unit='s',
                     verdict=('达标' if self.longest_control_s >= float(
                         self.params.get('required_control_s') or 0) else '未达标'),
                     note='连续控制最长区间；中断后重新计时'),
                dict(key='control_intervals', label='控制区间',
                     value=len(self.control_intervals), unit='段',
                     verdict='已记录', note=str(self.control_intervals)),
                dict(key='counterattacks', label='敌方反击次数',
                     value=len(self.counterattacks), unit='次',
                     verdict=('已击退' if self.counterattacks else '未发生'),
                     note='反击时刻 %s；打断控制 %d 次' % (
                         self.counterattacks or '—', self.control_interruptions)),
                dict(key='handover_t', label='移交时间',
                     value=(round(self.handover_t, 2)
                            if self.handover_t is not None else None),
                     unit='s',
                     verdict=('已移交' if self.handover_t is not None else '未移交'),
                     note='控制达成即移交，之后单独结算坚守'),
                dict(key='hold_s', label='移交后坚守',
                     value=round(self.hold_s, 2), unit='s',
                     verdict=('达标' if self.hold_s >= float(
                         self.params.get('hold_required_s') or 0) else '未达标'),
                     note='与夺占分开结算'),
                dict(key='our_losses', label='我方损失',
                     value=our_losses, unit='台',
                     verdict=('有损失' if our_losses else '无损失'),
                     note='执行期失联平台数'),
            ]
        self.auxiliary = rows
        return rows

    def _fill_info_items(self):
        total = sum(b - a for a, b in self.coverage_intervals)
        if self._run_start_t is not None and self._last_fire_t is not None:
            total += max(0.0, self._last_fire_t - self._run_start_t)
        rows = self._auxiliary(total)
        if self.effect_kind == 'damage':
            metric = dict(hit_rate=next((r['value'] for r in rows
                                         if r['key'] == 'hit_rate'), None),
                          shots_fired=self.shots_fired,
                          shots_hit=self.shots_hit,
                          damage_level=round(self.damage_level, 2))
        elif self.effect_kind == 'suppress':
            metric = dict(longest_suppression_s=round(self.longest_suppression_s, 2),
                          total_suppression_s=round(total, 2),
                          suppression_gaps=self.suppression_gaps,
                          max_gap_s=round(self.max_gap_s, 2))
        else:
            metric = dict(longest_control_s=round(self.longest_control_s, 2),
                          hold_s=round(self.hold_s, 2),
                          enemy_counterattacks=len(self.counterattacks),
                          control_interruptions=self.control_interruptions,
                          handover_t=(round(self.handover_t, 2)
                                      if self.handover_t is not None else None))
        metric['our_losses'] = len(self.losses)
        metric['auxiliary'] = rows
        self._set_item('ammo_used', 'info',
                       metric=dict(shots_fired=self.shots_fired,
                                   ammo_left=dict(self.ammo)),
                       evidence='fire_log')
        self._set_item('effect_metric', 'info', metric=metric,
                       evidence='fire_log / coverage / control 区间 / 损失与反击记录')
        self._set_item('restrikes', 'info',
                       metric=dict(restrikes=self.restrikes),
                       evidence='restrike_needed 事件计数')
        self.metrics['auxiliary'] = rows
        self.metrics['our_losses'] = len(self.losses)

    def _ammo_exhausted(self):
        """全体可开火成员弹药=0 且效果未达成 → 终止（夺占不消耗弹药）。

        已损失成员不再计入：都打光了还留着它的弹药份额，会让作业一直
        拖到执行截止，而不是按"弹药耗尽"如实终止。
        """
        if self.effect_kind == 'seize':
            return False
        alive = [pid for pid in self.assault_pids if self._alive(pid)]
        if not alive:
            return True
        return all(self.ammo.get(pid, 0) <= 0 for pid in alive)

    def _settle_items_by_fact(self, t, reason):
        """终止/确认截止时按已发生事实结算各必需项（规范 §5）。

        效果达成是独立事实：effect_achieved 已发生则该项记 achieved
        （证据注明"未经评估确认"）；未发生则 failed。其余 pending 项
        一律 failed——确认截止后仍 pending 按未达成处理，不冒充。
        """
        if self.effect_achieved_t is not None:
            self._set_item(
                'effect', 'achieved', t=self.effect_achieved_t,
                evidence='effect_achieved 事件（终止前已达成，未经评估确认）')
            if self.window:
                ok = self._window_ok(self.effect_achieved_t)
                self._set_item(
                    'window', 'achieved' if ok else 'failed',
                    t=self.effect_achieved_t,
                    evidence='effect_achieved@%.1f，window=%s' % (
                        self.effect_achieved_t, self.window))
            if (self.effect_kind == 'seize'
                    and self.handover_t is not None):
                need = float(self.params['hold_required_s'])
                self._set_item(
                    'hold_after_handover',
                    'achieved' if self.hold_s >= need else 'failed', t=t,
                    evidence='坚守%.1fs / 要求%.1fs（移交@%.1f）' % (
                        self.hold_s, need, self.handover_t))
        self._set_item('confirmation', 'failed', t=t,
                       evidence='terminate:%s（评估未回传）' % reason)
        for item in self.result_items:
            if item.get('required') and item['status'] == 'pending':
                item.update(status='failed', t=round(t, 2),
                            evidence='terminate:%s' % reason)

    def _terminate(self, t, reason, status='失败'):
        """终止：只有达到规定效果才计成功；结果项按事实逐项结算。"""
        self.termination = reason
        self._fill_info_items()
        self._settle_items_by_fact(t, reason)
        self._set_status(status)
        if reason == 'ammo_exhausted':
            self.emit('ammo_exhausted', ammo_left=dict(self.ammo),
                      effect=self.effect_kind,
                      damage_level=round(self.damage_level, 2))
        elif reason == 'deadline_exceeded':
            self.emit('deadline_exceeded',
                      deadline_s=float(self.params['execute_deadline'] or 0.0),
                      effect_achieved=False)
        self.emit('terminate', reason=reason,
                  items=[dict(x) for x in self.result_items])
        self._finish(reason)

    def _confirm_timeout(self, t):
        """确认截止：效果达成但评估未回传 → 确认项未达成，整体不计成功。"""
        self.termination = 'confirmation_timeout'
        self._fill_info_items()
        self._settle_items_by_fact(t, 'confirmation_timeout')
        self._set_item('confirmation', 'failed', t=t,
                       evidence='confirmation_timeout:评估未在确认截止前回传')
        self.emit('confirmation_timeout',
                  deadline_t=round(self.confirm_deadline_t, 2))
        self.emit('terminate', reason='confirmation_timeout',
                  items=[dict(x) for x in self.result_items])
        self._set_status('超时')
        self._finish('confirmation_timeout')

    # ---- 记录“平台到位”这一独立事实 ----
    def _record_arrival(self, poses, pid, where, target, tol):
        if pid is None or where in self.arrivals[pid]:
            return
        if distance(poses[pid], target) <= tol:
            self.arrivals[pid][where] = round(self.t, 2)
            self.emit('arrived', pid=pid, where=where,
                      role=self.roles.get(pid, '突击组'),
                      pos=[round(v, 2) for v in poses[pid]])

    def _set_status(self, status):
        if status != self.status:
            self.status = status
            self.metrics['status'] = status
            self.metrics['overall_status'] = status
            self.emit('status', status=status)

    def _window_ok(self, t):
        return self.window is None or self.window[0] <= t <= self.window[1]

    def _finish(self, reason):
        self.metrics['phases'] = self.phase_times
        self.metrics['arrival_times'] = {pid: dict(v)
                                         for pid, v in self.arrivals.items()}
        self.metrics['result_items'] = [dict(x) for x in self.result_items]
        self.metrics['overall_status'] = self.status
        self.metrics['losses'] = [dict(x) for x in self.losses]
        self.metrics['counterattacks'] = list(self.counterattacks)
        self.metrics['control_interruptions'] = self.control_interruptions
        overall = self._overall()
        if overall == 'pending':
            overall = 'failed'      # 结束态不允许 pending（确认截止/终止已核验）
        self.metrics['result'] = dict(
            job_id=self.job_id, target_id=self.target_id,
            attempt=self.attempt, effect_kind=self.effect_kind,
            items=[dict(x) for x in self.result_items],
            auxiliary=[dict(x) for x in getattr(self, 'auxiliary', [])],
            losses=[dict(x) for x in self.losses],
            counterattacks=list(self.counterattacks),
            control_interruptions=self.control_interruptions,
            role_check=self.metrics.get('role_check'),
            overall=overall, termination=self.termination,
            adjudicator=self._last_adjudicator or self.adjudicator.name,
            verified=self._last_verified,
            status=self.status, reason=reason)
        self.result = dict(self.metrics['result'])
        super()._finish(reason)

    def _schedule_release(self, t):
        """按最慢一台的预计行程给出发时刻，实现“同时到达”。

        用 A* 路径长度而不是直线距离，转弯绕行也算进去；速度取
        BehaviorRunner 注入的 self.speeds（缺省 1.0 场景单位/步）。
        """
        ests = {}
        for i, pid in enumerate(self.assault_pids):
            start = self.staging[min(i, len(self.staging) - 1)]
            target = self.objective[min(i, len(self.objective) - 1)]
            speed = max(float(self.speeds.get(pid, 1.0)), 0.1)
            try:
                length = self.nav.plan(start, target)['length']
            except NavError:
                length = distance(start, target)
            ests[pid] = length / speed
        slowest = max(ests.values())
        self.release_at = {pid: round(t + slowest - e, 2) for pid, e in ests.items()}
        self.metrics['release_offsets'] = {
            pid: round(slowest - e, 2) for pid, e in ests.items()}
        self.metrics['eta_s'] = {pid: round(e, 2) for pid, e in ests.items()}

    def _reachable_ring_point(self, center, radius, angle):
        """环上一点，保证从 center 有较直路径可达（否则沿径向回缩）。

        assault 的 staging/objective 若落在建筑另一侧，平台要绕很远、
        甚至卡在墙角（PathFollower 局部重规划）。这里若直连不可行就
        沿 center→点 方向回缩到最近的可直连点；若中心本身已紧贴建筑
        （clearance 很小，无法展开环），直接退回中心。
        """
        if self.nav.clearance(center) < self.nav.radius + 0.35:
            return [center[0], center[1]]
        q, _ = self.nav.nearest_free(_polar(center, radius, angle))
        for frac in (1.0, 0.7, 0.45, 0.25):
            cand, _ = self.nav.nearest_free(_polar(center, radius * frac, angle))
            if self.nav.segment_free(center, cand):
                return cand
        return q

    # ---- 目标分配 ----
    def _targets_at(self, points):
        out = {}
        if self.scout:
            out[self.scout] = self.observation
        for i, pid in enumerate(self.assault_pids):
            out[pid] = points[min(i, len(points) - 1)]
        return out

    def _all_arrived(self, where):
        return all(where in self.arrivals[pid] for pid in self.assault_pids)

    # ---- 评估回传与结算（可插拔接口，规范 §3/§5） ----
    def _evidence(self):
        total = sum(b - a for a, b in self.coverage_intervals)
        if self._run_start_t is not None and self._last_fire_t is not None:
            total += max(0.0, self._last_fire_t - self._run_start_t)
        members = []
        for pid in self.pids:
            pose = (self._poses or {}).get(pid)
            members.append(dict(
                pid=pid, role=self.roles.get(pid, '突击组'),
                pos=([round(pose[0], 2), round(pose[1], 2)]
                     if pose else None),
                ammo_left=self.ammo.get(pid)))
        return dict(
            job_id=self.job_id, target_id=self.target_id,
            attempt=self.attempt, window=self.window,
            effect_achieved_t=(round(self.effect_achieved_t, 2)
                               if self.effect_achieved_t is not None else None),
            fire_log=[dict(x) for x in self.fire_log],
            damage_level=round(self.damage_level, 2),
            shots_fired=self.shots_fired, shots_hit=self.shots_hit,
            coverage_intervals=[[round(a, 2), round(b, 2)]
                                for a, b in self.coverage_intervals],
            control_intervals=[[round(a, 2), round(b, 2)]
                               for a, b in self.control_intervals],
            longest_suppression_s=round(self.longest_suppression_s, 2),
            total_suppression_s=round(total, 2),
            longest_control_s=round(self.longest_control_s, 2),
            hold_s=round(self.hold_s, 2),
            handover_t=(round(self.handover_t, 2)
                        if self.handover_t is not None else None),
            restrikes=self.restrikes,
            suppression_gaps=self.suppression_gaps,
            max_gap_s=round(self.max_gap_s, 2),
            losses=[dict(x) for x in self.losses],
            counterattacks=list(self.counterattacks),
            control_interruptions=self.control_interruptions,
            role_check=self.metrics.get('role_check'),
            members=members,
            events=[dict(kind=e['kind'], t=e['t'])
                    for e in self.history
                    if e['kind'] in self.EVIDENCE_EVENTS])

    def _assess(self, t):
        """评估回传：经可插拔评估接口出逐项判定，绑定本任务/本对象/本版本。"""
        p = self.params
        task_ref = dict(job_id=self.job_id, target_id=self.target_id,
                        attempt=self.attempt, effect_kind=self.effect_kind,
                        params={k: p.get(k) for k in (
                            'required_level', 'required_duration',
                            'recovery_gap', 'required_control_s',
                            'hold_required_s')})
        adj = self.adjudicator.adjudicate(task_ref, self._evidence())
        self._last_adjudicator = adj.get('adjudicator', self.adjudicator.name)
        self._last_verified = bool(adj.get('verified'))
        for adj_item in adj.get('items', []):
            self._set_item(adj_item.get('id'), adj_item.get('status'),
                           t=t, evidence='评估接口:%s' % self._last_adjudicator,
                           metric=adj_item.get('metric'))
        self._set_item('confirmation', 'achieved', t=t,
                       evidence='assessment_received:评估已回传')
        self._fill_info_items()
        self.assessed = True
        self.metrics['result_items'] = [dict(x) for x in self.result_items]
        self.metrics['assessment_latency_s'] = round(t - (self.stage_enter_t or t), 2)
        if self.effect_achieved_t is not None:
            self.metrics['attack_window_ok'] = self._window_ok(self.effect_achieved_t)
        overall = self._overall()
        self.metrics['evaluation'] = dict(
            effect_kind=self.effect_kind, overall=overall,
            adjudicator=self._last_adjudicator,
            verified=self._last_verified, note=adj.get('note'),
            ammo_used=self.shots_fired,
            not_modeled=['我方损失实测', '敌方反击', '目标机动/消失（预留接口）'],
            note_extra='桩判定按开火/占位日志确定性规则，不冒充实测')
        self.emit('assessment_received', source=self._last_adjudicator,
                  verified=self._last_verified, overall=overall,
                  items=[dict(x) for x in self.result_items],
                  latency_s=round(t - (self.stage_enter_t or t), 2),
                  note=adj.get('note'))
        lead = self.assault_pids[0]
        if overall == 'succeeded':
            self.confirmed_t = t
            self.metrics['confirmed_t'] = round(t, 2)
            self._set_status('成功')
            self.emit('confirmed', lead=lead,
                      source=self._last_adjudicator,
                      verified=self._last_verified,
                      items=[dict(x) for x in self.result_items],
                      pos=[round(v, 2) for v in self._poses[lead]])
            if p['withdraw'] and self.withdraw_targets:
                self.set_phase('撤离')
                self.withdraw_started_t = t
                self.phase_times.append(dict(phase='撤离', t=round(t, 2)))
                self.metrics['withdraw_started_t'] = round(t, 2)
                self.metrics['withdraw_deadline_s'] = p['withdraw_deadline'] or 60.0
                self.emit('withdraw_started', point=self.withdraw_point,
                          deadline_s=p['withdraw_deadline'] or 60.0)
            else:
                self._finish('result_confirmed')
        else:
            self._set_status('失败')
            self.emit('result_failed', items=[dict(x) for x in self.result_items],
                      reason='评估未达成全部必需结果项（部分达成不冒充全部成功）')
            self._finish('result_failed')

    def step(self, poses, t, dt):
        self.t = t
        self._poses = poses
        p = self.params
        # 第二道角色闸门：突击组载荷不达标时，不接受"让无人机扛弹"的编成。
        if self.role_blocked and not self.done:
            self._terminate(t, 'role_infeasible', status='失败')
            return dict(targets={}, phase=self.phase, done=True)
        tol = p['arrive_tol']
        targets = {}
        if self.phase == '机动':
            targets = self._targets_at(self.staging)
            if self.assessor:
                targets[self.assessor] = self.staging[
                    min(self._assessor_slot, len(self.staging) - 1)]
                self._record_arrival(
                    poses, self.assessor, 'staging',
                    self.staging[min(self._assessor_slot,
                                     len(self.staging) - 1)], tol)
            for i, pid in enumerate(self.assault_pids):
                self._record_arrival(poses, pid, 'staging',
                                     self.staging[min(i, len(self.staging) - 1)], tol)
            if self.scout:
                targets[self.scout] = self.observation
                self._record_arrival(poses, self.scout, 'observation',
                                     self.observation, tol)
                if not self.designated and 'observation' in self.arrivals[self.scout]:
                    self.designated = True
                    self.metrics['target_designated_t'] = round(t, 2)
                    self.metrics['positive_id'] = '已指示'
                    self.emit('target_designated', source=self.scout,
                              target=[round(v, 2) for v in self.site],
                              confidence=p.get('designation_confidence', 0.9))
            staged = self._all_arrived('staging') and (
                self.assessor is None
                or 'staging' in self.arrivals[self.assessor])
            if staged and (self.scout is None or self.designated):
                self.emit('all_staged', staging=self.staging,
                          pids=list(self.assault_pids))
                self.set_phase('到位')
                self.stage_enter_t = t
                self.phase_times.append(dict(phase='到位', t=round(t, 2)))
        elif self.phase == '到位':
            targets = self._targets_at(self.staging)
            if self.assessor:
                targets[self.assessor] = self.staging[
                    min(self._assessor_slot, len(self.staging) - 1)]
            if t - self.stage_enter_t >= 1.0:
                self._schedule_release(t)
                self.set_phase('执行')
                self.execute_start_t = t
                if p.get('execute_deadline') is not None:
                    self.execute_deadline_t = t + float(p['execute_deadline'])
                    self.metrics['execute_deadline_t'] = round(
                        self.execute_deadline_t, 2)
                self.emit('assault_started', objective=[round(v, 2) for v in self.site],
                          release_offsets=dict(self.metrics.get('release_offsets', {})))
                self.stage_enter_t = t
                self.phase_times.append(dict(phase='执行', t=round(t, 2)))
        elif self.phase == '执行':
            # 未到各自出发时刻的平台仍在集结位待机，避免先到先打
            targets = {}
            for i, pid in enumerate(self.assault_pids):
                if t < self.release_at.get(pid, 0.0):
                    targets[pid] = self.staging[min(i, len(self.staging) - 1)]
                else:
                    targets[pid] = self.objective[min(i, len(self.objective) - 1)]
            if self.scout:
                targets[self.scout] = self.observation
            if self.assessor:
                # 评估组前出评估观察位（在位后才有资格发起评估）
                targets[self.assessor] = self.assessment_post
                self._record_arrival(poses, self.assessor, 'assessment_post',
                                     self.assessment_post, tol)
            for i, pid in enumerate(self.assault_pids):
                self._record_arrival(poses, pid, 'objective',
                                     self.objective[min(i, len(self.objective) - 1)], tol)
            if not self.position_reported and self._all_arrived('objective'):
                times = [self.arrivals[pid]['objective'] for pid in self.assault_pids]
                spread = max(times) - min(times)
                self.position_reported = True
                self.metrics['arrival_spread_s'] = round(spread, 2)
                self.metrics['simultaneous_ok'] = bool(spread <= p['sync_tol'])
                self.emit('all_in_position', pids=list(self.assault_pids),
                          arrival_times={pid: self.arrivals[pid]['objective']
                                         for pid in self.assault_pids},
                          spread_s=round(spread, 2),
                          simultaneous=bool(spread <= p['sync_tol']))
            if self.position_reported and self.effect_t is None:
                if self.window and t < self.window[0]:
                    pass                      # 已到位，等攻击窗口开启
                elif not self._window_ok(t):
                    self.metrics['attack_window_ok'] = False
                    self.emit('attack_window_missed', window=self.window, t=round(t, 2))
                    self._terminate(t, 'attack_window_missed')
                else:
                    self.effect_t = t
                    self._next_salvo_t = t
                    self.metrics['effect_t'] = round(t, 2)
                    self.metrics['attack_window_ok'] = True
                    self.emit('effect_started', window=self.window)
            if (not self.done and self.effect_t is not None
                    and self.phase == '执行'):
                self._step_effect(poses, t)
                # 终止条件（执行期内分别核验：弹药耗尽 / 执行截止）
                if (not self.done and self.effect_achieved_t is None):
                    if self._ammo_exhausted():
                        self._terminate(t, 'ammo_exhausted')
                    elif (self.execute_deadline_t is not None
                          and t > self.execute_deadline_t):
                        self._terminate(t, 'deadline_exceeded', status='超时')
        elif self.phase == '坚守':
            targets = self._targets_at(self.objective)
            if self.assessor:
                targets[self.assessor] = self.assessment_post
            self._step_hold(poses, t)
        elif self.phase == '结果确认':
            targets = self._targets_at(self.objective)
            if self.assessor:
                # 评估组在评估观察位发起评估；无评估组时由突击组长发起（桩）
                targets[self.assessor] = self.assessment_post
                self._record_arrival(poses, self.assessor, 'assessment_post',
                                     self.assessment_post, tol)
            if not self.assess_requested:
                ready = (self.assessor is None
                         or 'assessment_post' in self.arrivals[self.assessor])
                if ready:
                    self.assess_requested = True
                    self.assessment_t = t + max(0.0, float(p['assessment_delay']))
                    self.emit('assessment_requested',
                              by=self.assessor or self.assault_pids[0],
                              post=([round(v, 2) for v in self.assessment_post]
                                    if self.assessment_post else None),
                              source=self.adjudicator.name,
                              delay_s=max(0.0, float(p['assessment_delay'])))
            if not self.assessed:
                if (self.confirm_deadline_t is not None
                        and t > self.confirm_deadline_t):
                    self._confirm_timeout(t)
                elif (self.assess_requested
                      and t >= (self.assessment_t or 0)):
                    self._assess(t)
        elif self.phase == '撤离':
            targets = {}
            if self.scout:
                targets[self.scout] = self.observation
            for i, pid in enumerate(self.assault_pids):
                targets[pid] = self.withdraw_targets[min(i, len(self.withdraw_targets) - 1)]
            if self.assessor:
                slot = min(self._assessor_slot, len(self.withdraw_targets) - 1)
                targets[self.assessor] = self.withdraw_targets[slot]
                self._record_arrival(poses, self.assessor, 'withdraw',
                                     self.withdraw_targets[slot], tol)
            for i, pid in enumerate(self.assault_pids):
                self._record_arrival(poses, pid, 'withdraw',
                                     self.withdraw_targets[min(i, len(self.withdraw_targets) - 1)], tol)
            withdrawn = self._all_arrived('withdraw') and (
                self.assessor is None
                or 'withdraw' in self.arrivals[self.assessor])
            if withdrawn:
                taken = t - (self.withdraw_started_t or t)
                limit = float(p['withdraw_deadline'] or 60.0)
                self.metrics['withdraw_t'] = round(t, 2)
                self.metrics['withdraw_s'] = round(taken, 2)
                self.metrics['withdraw_ok'] = bool(taken <= limit)
                self.emit('withdrawn', withdraw_s=round(taken, 2),
                          deadline_s=limit, within_deadline=bool(taken <= limit))
                self._finish('withdrawn')
            elif (self.withdraw_started_t is not None
                  and t - self.withdraw_started_t > float(p['withdraw_deadline'] or 60.0)):
                self.metrics['withdraw_ok'] = False
                self.emit('withdraw_timeout',
                          deadline_s=float(p['withdraw_deadline'] or 60.0))
                self._finish('withdraw_timeout')
        if not self.done and t > float(p['timeout_s']):
            self._set_status('超时')
            self.emit('task_timeout', timeout_s=p['timeout_s'])
            self._terminate(t, 'timeout', status='超时')
        return dict(targets=targets, phase=self.phase, done=self.done)

    def progress_frac(self):
        if self.done:
            return 1.0
        stages = {'机动': 0.12, '到位': 0.35, '执行': 0.72, '坚守': 0.85,
                  '结果确认': 0.9, '撤离': 0.96}
        return stages.get(self.phase, 0.05)

    def debug(self):
        return dict(effect_started=self.effect_t is not None,
                    effect_achieved=self.effect_achieved_t is not None,
                    status=self.status, assessed=self.assessed,
                    designated=self.designated,
                    ammo=dict(self.ammo),
                    damage_level=round(self.damage_level, 2),
                    suppression_s=round(self.longest_suppression_s, 2),
                    control_s=round(self.longest_control_s, 2),
                    hold_s=round(self.hold_s, 2),
                    counterattacks=len(self.counterattacks),
                    losses=len(self.losses))


# ------------------------------------------------------------------
# 5. 要点坚守：在位/待命轮换，接替者到位才撤
# ------------------------------------------------------------------
class HoldBehavior(Behavior):
    kind = 'hold'
    label = '要点坚守'
    DEFAULTS = dict(post_radius=1.6, standby_radius=3.4, shift_s=12.0,
                    handover_tol=0.6, presence_radius=2.2, relief_cycles=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.params
        self.posts = [self.nav.nearest_free(_polar(self.site, p['post_radius'], a))[0]
                      for a in (0.0, math.pi)]
        self.standbys = [self.nav.nearest_free(_polar(self.site, p['standby_radius'], a))[0]
                         for a in (0.0, math.pi)]
        self.primary = self.pids[0]
        self.secondary = self.pids[1] if len(self.pids) > 1 else self.pids[0]
        self.solo = len(self.pids) < 2
        self.shift_end = p['shift_s']
        self.handovers = 0
        self.gap_s = 0.0
        self.min_present = len(self.pids)
        self.swapping = False
        self.occupied_once = False
        self.phase = '机动'
        self.metrics.update(posts=[[round(v, 2) for v in q] for q in self.posts],
                            shift_s=p['shift_s'])

    def step(self, poses, t, dt):
        self.t = t
        p = self.params
        present = [pid for pid in self.pids
                   if distance(poses[pid], self.site) <= p['presence_radius']]
        if (not self.occupied_once
                and distance(poses[self.primary], self.posts[0]) <= 0.8):
            # 主班真正站上岗位才建立基线：赶路/路过都不算"在位"
            self.occupied_once = True
            self.set_phase('在位')
            self.emit('on_post', pid=self.primary)
        if self.occupied_once:
            if not present:
                self.gap_s += dt
            self.min_present = min(self.min_present, len(present))
        targets = {self.primary: self.posts[0],
                   self.secondary: self.standbys[0]}
        for k, pid in enumerate(self.pids[2:], start=1):
            targets[pid] = self.posts[k % len(self.posts)]
        if not self.swapping and t >= self.shift_end:
            if self.solo:
                self.metrics.update(handovers=0,
                                    presence_gap_s=round(self.gap_s, 1),
                                    min_present=self.min_present)
                self.emit('relief', pid=self.primary)
                self._finish('solo_shift_done')
                return dict(targets=targets, phase=self.phase, done=self.done)
            self.swapping = True
            self.emit('handover_start', incoming=self.secondary,
                      outgoing=self.primary)
            self.set_phase('接替')
        if self.swapping:
            targets[self.secondary] = self.posts[0]
            targets[self.primary] = self.posts[0]   # 未完成接替前不撤
            if distance(poses[self.secondary], self.posts[0]) <= p['handover_tol']:
                self.handovers += 1
                self.emit('handover_complete', incoming=self.secondary,
                          outgoing=self.primary, at=round(t, 2))
                self.primary, self.secondary = self.secondary, self.primary
                self.swapping = False
                self.shift_end = t + p['shift_s']
                self.set_phase('在位')
                self.emit('relief', pid=self.primary)
                if self.handovers >= int(p['relief_cycles']):
                    self.metrics.update(handovers=self.handovers,
                                        presence_gap_s=round(self.gap_s, 1),
                                        min_present=self.min_present)
                    self._finish('relief_cycles_done')
        if t > 200:
            self._finish('timeout')
        return dict(targets=targets, phase=self.phase, done=self.done)

    def progress_frac(self):
        if self.done:
            return 1.0
        if self.solo:
            return min(1.0, self.t / max(self.params['shift_s'], 1.0)) * 0.9
        return (min(1.0, self.handovers
                    / max(int(self.params['relief_cycles']), 1)) * 0.9
                + (0.1 if self.occupied_once else 0.0))

    def debug(self):
        return dict(primary=self.primary, secondary=self.secondary,
                    swapping=self.swapping, handovers=self.handovers)


BEHAVIORS = {cls.kind: cls for cls in
             (PatrolBehavior, BlockadeBehavior, ReconBehavior,
              AssaultBehavior, HoldBehavior)}


def make_behavior(job, nav, pids, params=None):
    """按作业类型造行为；未知类型退回"原地作业"。

    区域封控有两种几何：历史小场景的"作业点外一圈"（BlockadeBehavior）与
    1028 的"真实封控边界"（ContainmentBehavior）。后者只在输入给了
    ``area`` 多边形时启用，避免改变旧样例与历史回放的语义。
    """
    merged = dict(job.get('_behavior') or {})
    merged.update(params or {})
    if job.get('type') == 'blockade' and merged.get('area'):
        return ContainmentBehavior(job, nav, pids, merged)
    cls = BEHAVIORS.get(job.get('type'))
    if cls is None:
        return Behavior(job, nav, pids, merged)
    return cls(job, nav, pids, merged)
