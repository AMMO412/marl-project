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
  hold     要点坚守：按威胁方向配置阵位、持续观察、接替者到位才撤、增援与
           撤离，并用桩判定给"反击/压制"这类抽象效果（KeepBehavior）；
           历史小场景仍走两点轮换的 HoldBehavior。

这一层是**纯决策**：每次 step 只返回每台平台的下一目标点、当前阶段和
事件，不直接改位姿；运动由 city_nav.PathFollower 执行。这样状态机可以
脱开运动学单独测试（见 tests/test_behaviors.py）。

所有几何都在场景坐标（与 simple_city.json 一致），作业点若落在建筑内，
统一先吸附到最近可通行点（NavMap.nearest_free），吸附距离记在 metrics 里。
"""
import math
from itertools import accumulate

from assessment import EFFECT_KINDS, StubAdjudicator, normalize_effect_kind
from city_nav import NavError, distance
import containment_geom as geom
from vehicle_kinematics import clamp_angle, limits_for


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
        self.relay_target = job.get('_relay_target')
        self.relay_origin_s = job.get('_relay_origin_s', 0)
        self.nav = nav
        self.pids = list(pids)
        self.params = dict(self.DEFAULTS)
        self.params.update({k: v for k, v in (params or {}).items()
                            if not str(k).startswith('_')})
        raw_site = site or job.get('pos')
        try:
            self.site, offset = nav.nearest_free(raw_site)
        except NavError:
            # A task point can sit in a large footprint or just outside an
            # imported map.  The editor clamps normal input, but older drafts
            # and generated benchmarks still reach this layer directly.  Keep
            # the run recoverable: first clamp into the map, then search the
            # whole reachable area instead of failing after a fixed 4 m scan.
            raw = [float(raw_site[0]), float(raw_site[1])]
            x0, y0, x1, y1 = map(float, nav.bounds)
            inset = max(0.5, float(getattr(nav, 'radius', 0.0) or 0.0))
            clamped = [
                min(max(raw[0], x0 + inset), x1 - inset),
                min(max(raw[1], y0 + inset), y1 - inset),
            ]
            span = math.hypot(x1 - x0, y1 - y0)
            self.site, offset = nav.nearest_free(
                clamped, max_radius=max(8.0, span), step=0.25)
            offset += distance(raw, clamped)
        self.site_snap = round(offset, 3)
        self.phase = '待命'
        self.done = False
        self.t = 0.0
        self._events = []
        self.history = []          # 全量事件（drain 不清空，供测试/复盘）
        self.platform_caps = {}    # 平台画像（类目/爬升/载荷），第二道能力闸门用
        # 空中平台遇到威胁区时，运动层会把逻辑航点投影到安全边界外。
        # 行为层仍保留原始航点事件，但到点判断要认这个安全投影点；否则
        # 飞机已停在安全位置，状态机却一直等待原始威胁区内坐标。
        self._effective_targets = {}
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

    def set_effective_target(self, pid, logical_target, effective_target):
        """登记逻辑航点及其安全投影点，供子类统一做到点判断。"""
        logical = [float(logical_target[0]), float(logical_target[1])]
        effective = [float(effective_target[0]), float(effective_target[1])]
        if distance(logical, effective) <= 1e-6:
            self._effective_targets.pop(pid, None)
        else:
            self._effective_targets[pid] = (logical, effective)

    def effective_target(self, pid, logical_target):
        """返回当前逻辑航点的可到达替代点（默认就是逻辑航点）。"""
        item = self._effective_targets.get(pid)
        if item is not None and distance(item[0], logical_target) <= 0.2:
            return item[1]
        return logical_target

    def air_orbit_radius(self, center, radius, min_radius=8.0):
        """把盘旋圈收缩到"整圈都在对空威胁区外"的最大半径。

        行为层生成的盘旋航点一旦落进 ``applies_to: air/all`` 的威胁区，
        运动层只能把每个航点投影到最近的安全点。威胁区把圆圈切出两段弧
        时，"最近边"会从威胁区一侧跳到另一侧，飞机就会在威胁区/建筑角
        附近来回折返（表现为"到建筑物附近乱飞"）。这里在生成航点前一次性
        把圈缩到整圈可用的半径，航点始终在区外，投影分支不再被触发。

        未配对空威胁图时原值返回，普通场景行为不变。
        """
        radius = float(radius or 0.0)
        if radius <= 0.0 or self.nav is None:
            return radius
        threat_map = getattr(self.nav, 'air_threat_map', None)
        if threat_map is None:
            return radius
        key = (round(float(center[0]), 3), round(float(center[1]), 3),
               round(radius, 3))
        cache = getattr(self, '_air_orbit_radius_cache', None)
        if cache is None:
            cache = self._air_orbit_radius_cache = {}
        if key in cache:
            return cache[key]
        clearance = max(2.0, float(getattr(threat_map, 'radius', 0.0) or 0.0) + 2.0)

        def clear(r):
            steps = max(24, int(math.ceil(2.0 * math.pi * r / 1.5)))
            for i in range(steps):
                angle = 2.0 * math.pi * i / steps
                point = (float(center[0]) + r * math.cos(angle),
                         float(center[1]) + r * math.sin(angle))
                if not threat_map.free(point, radius=clearance):
                    return False
            return True

        effective = radius
        if not clear(effective):
            effective = 0.0
            trial = radius - 1.0
            while trial >= min_radius:
                if clear(trial):
                    effective = round(trial, 2)
                    break
                trial -= 1.0
        cache[key] = effective
        return effective

    def set_phase(self, phase):
        if phase != self.phase:
            self.phase = phase
            self.emit('phase', phase=phase)

    def occupy(self, poses, targets, tol=0.6):
        return all(self.reached(poses, pid, targets[i], tol)
                   for i, pid in enumerate(self.pids[:len(targets)]))

    def reached(self, poses, pid, target, tol):
        """空中平台在站点周围盘旋时仍视为占位。"""
        return (distance(poses[pid], target) <= tol
                or bool(getattr(self, "station_holds",
                                lambda *_: False)(pid, target, tol)))

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


    def subtask_progress(self, pid):
        """单个平台席位（子任务）的进度 [0,1]。

        2.1(4) 的子任务偏差判定需要"一个平台一个槽位"的进度；默认退化为
        作业级进度，侦察/巡逻等有 per-pid 状态的子类覆盖为更细的口径。
        """
        return self.progress_frac()

    def report_loss(self, pid, t):
        """执行期成员失联：默认只记录。运行层随后会为该席位找替补。"""
        self.lost_pids = getattr(self, 'lost_pids', set())
        if pid in self.lost_pids:
            return
        self.lost_pids.add(pid)
        self.emit('member_lost', pid=pid,
                  role=getattr(self, 'roles', {}).get(pid, ''))

    def replace_agent(self, old_pid, new_pid, can_climb=None):
        """编成内改派：把一个席位从旧平台换到新平台。

        只改本层自己的成员账本；位姿/速度由 BehaviorRunner 负责。子类若
        还有 per-pid 的进度结构（扇区、检查点、在位记录），必须覆盖。
        """
        if old_pid in self.pids:
            self.pids[self.pids.index(old_pid)] = new_pid
        elif new_pid not in self.pids:
            self.pids.append(new_pid)
        for name in ("platform_caps", "roles", "arrivals"):
            value = getattr(self, name, None)
            if isinstance(value, dict) and old_pid in value:
                value[new_pid] = value.pop(old_pid)


# ------------------------------------------------------------------
# 1. 巡逻警戒：闭环 + 检查点 + 重访间隔
# ------------------------------------------------------------------
class PatrolBehavior(Behavior):
    kind = 'patrol'
    label = '巡逻警戒'
    DEFAULTS = dict(radius=2.4, checkpoints=6, cycles=3,
                    arrive_tol=0.7, center_shift=0.0,
                    air_pass_tolerance_m=2.5,
                    air_patrol_speed_mps=3.0,
                    air_route_inset_m=0.0,
                    air_route_point_spacing_m=5.0,
                    air_patrol_radius_m=0.0,
                    air_orbit_period_s=35.0,
                    air_orbit_entry_margin_m=4.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        waypoints = self.params.get('waypoints')
        self.continuous = bool(waypoints)
        self.patrol_started_at = None
        self.target_started = False
        self.target_started_at = None
        self.target_finished_at = None
        self.target_detected = False
        self.target_report_count = 0
        self.target_first_detection_s = None
        self.target_last_detection_s = None
        self.target_last_reports = {}
        self.patrol_groups = {'ground': self.pids, 'air': []}
        self.sensor_radii = {}
        self.cell_size_m = float(self.params.get('cell_size_m', 1.0))
        self.loop = [tuple(p) for p in waypoints] if waypoints else self._build_loop()
        if waypoints:
            lengths = (distance(a, b) for a, b in zip(self.loop, self.loop[1:] + self.loop[:1]))
            self.loop_distances = list(accumulate(lengths, initial=0.0))
        self.metrics['radius'] = round(self.params['radius'], 2)
        self.metrics['checkpoints'] = len(self.loop)
        self.metrics['loop'] = [[round(v, 2) for v in q] for q in self.loop]
        self.idx = {}
        self.cycles = {pid: 0 for pid in self.pids}
        self.last_cycle_t = {pid: 0.0 for pid in self.pids}
        self.visits = {pid: [] for pid in self.pids}
        self.air_orbit_started_at = {}
        self.air_orbit_centers = {}
        self.air_orbit_radii = {}
        self.air_boundary_stations = {}
        self.air_routes = {}
        self.air_route_insets = {}
        # 多机沿环路均匀错开，避免挤在同一个检查点
        for k, pid in enumerate(self.pids):
            self.idx[pid] = (k * len(self.loop) // max(1, len(self.pids))) % len(self.loop)
            if waypoints:
                role = self.params.get('roles', {}).get(pid, '')
                start = int(role.split(':')[1]) - 1 if role.startswith('patrol:') else self.idx[pid]
                self.idx[pid] = (start - 1) % len(self.loop)
        self.set_phase('机动')

    def set_platform_caps(self, caps):
        super().set_platform_caps(caps)
        self.patrol_groups = {'ground': [], 'air': []}
        self.sensor_radii = {}
        for pid in self.pids:
            group = 'air' if caps.get(pid, {}).get('can_climb') else 'ground'
            self.patrol_groups[group].append(pid)
            radius = (self.params.get('sensor_radius_m') or {}).get(group)
            if radius:
                self.sensor_radii[pid] = float(radius)
        self._configure_air_orbit()

    def _configure_air_orbit(self):
        """生成固定翼可连续飞行的区内边界航路。

        地面平台的矩形角点对固定翼并不友好：飞机无法在角点悬停，按
        原始角点追会让它不断画大圈。这里为固定翼生成一条向任务区内部
        偏移的闭环，并在每条边上增加连续航点；飞机按实际巡航速度沿四边
        飞行，既贴近边界，又能在转弯半径内始终留在任务区中。
        """
        air = list(self.patrol_groups.get('air', []))
        self.air_orbit_centers = {}
        self.air_orbit_radii = {}
        self.air_boundary_stations = {}
        self.air_routes = {}
        self.air_route_insets = {}
        if not air or not self.loop:
            return
        xs = [point[0] for point in self.loop]
        ys = [point[1] for point in self.loop]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        span = max(1.0, min(width, height))
        speed = max(1.0, float(
            self.params.get('air_patrol_speed_mps', 3.0)))
        yaw_rate = max(0.15, float(
            self.params.get('air_max_yaw_rate', 0.35)))
        turn_radius = max(4.0, speed / yaw_rate)
        configured_inset = float(
            self.params.get('air_route_inset_m') or 0.0)
        inset = (configured_inset if configured_inset > 0.0
                 else max(6.0, min(0.28 * span, 1.35 * turn_radius + 2.0)))
        inset = min(inset, max(1.0, 0.34 * span))
        x0, x1 = min_x + inset, max_x - inset
        y0, y1 = min_y + inset, max_y - inset
        if x0 > x1:
            x0 = x1 = (min_x + max_x) * 0.5
        if y0 > y1:
            y0 = y1 = (min_y + max_y) * 0.5
        spacing = max(2.5, float(
            self.params.get('air_route_point_spacing_m', 5.0)))
        # 固定翼不能在矩形尖角瞬时转向。按尖角航点飞时，飞机会为了回到
        # 下一条边反复绕小圈，虽然位置仍在任务区内，但一圈耗时会被放大数倍。
        # 用与转弯半径匹配的圆角闭环替代尖角航路。
        corner_radius = min(
            turn_radius + 1.0, max(1.0, (x1 - x0) * 0.5),
            max(1.0, (y1 - y0) * 0.5))
        route = []

        def append_point(point):
            rounded = (round(point[0], 3), round(point[1], 3))
            if not route or distance(route[-1], rounded) > 1e-6:
                route.append(rounded)

        def append_segment(start, end):
            length = distance(start, end)
            count = max(1, int(math.ceil(length / spacing)))
            for step in range(count):
                fraction = step / float(count)
                append_point((
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction))

        def append_arc(center, radius, start_angle, end_angle):
            length = abs(end_angle - start_angle) * radius
            count = max(1, int(math.ceil(length / spacing)))
            for step in range(count):
                angle = start_angle + (
                    end_angle - start_angle) * step / float(count)
                append_point((
                    center[0] + radius * math.cos(angle),
                    center[1] + radius * math.sin(angle)))

        if x1 - x0 <= corner_radius * 2.0 or y1 - y0 <= corner_radius * 2.0:
            corner_radius = max(
                1.0, min((x1 - x0) * 0.5, (y1 - y0) * 0.5))
        append_segment((x0 + corner_radius, y0),
                       (x1 - corner_radius, y0))
        append_arc((x1 - corner_radius, y0 + corner_radius),
                   corner_radius, -math.pi / 2.0, 0.0)
        append_segment((x1, y0 + corner_radius),
                       (x1, y1 - corner_radius))
        append_arc((x1 - corner_radius, y1 - corner_radius),
                   corner_radius, 0.0, math.pi / 2.0)
        append_segment((x1 - corner_radius, y1),
                       (x0 + corner_radius, y1))
        append_arc((x0 + corner_radius, y1 - corner_radius),
                   corner_radius, math.pi / 2.0, math.pi)
        append_segment((x0, y1 - corner_radius),
                       (x0, y0 + corner_radius))
        append_arc((x0 + corner_radius, y0 + corner_radius),
                   corner_radius, math.pi, 3.0 * math.pi / 2.0)
        if not route:
            route = [tuple(self.site)]
        for index, pid in enumerate(air):
            offset = (index * len(route) // max(1, len(air))) % len(route)
            assigned = route[offset:] + route[:offset]
            self.air_routes[pid] = assigned
            self.air_route_insets[pid] = inset
            self.idx[pid] = 0
            self.air_boundary_stations[pid] = [
                [round(point[0], 2), round(point[1], 2)]
                for point in assigned
            ]
        self.metrics['air_patrol'] = dict(
            mode='boundary_follow',
            speed_mps=round(speed, 2),
            inset_m=round(inset, 2),
            turn_radius_m=round(turn_radius, 2),
            corner_radius_m=round(corner_radius, 2),
            routes={
                pid: [[round(point[0], 2), round(point[1], 2)]
                      for point in assigned]
                for pid, assigned in self.air_routes.items()
            },
        )

    def _air_speed_scales(self):
        target_speed = max(1.0, float(
            self.params.get('air_patrol_speed_mps', 3.0)))
        scales = {}
        for pid in self.patrol_groups.get('air', []):
            cruise = max(
                0.1,
                float((getattr(self, 'speeds', None) or {}).get(pid)
                      or (self.platform_caps.get(pid) or {}).get('speed')
                      or target_speed))
            scales[pid] = max(0.05, min(1.0, target_speed / cruise))
        return scales

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
        loiter_radius = {}
        explicit_loop = self.continuous
        if (not explicit_loop and self.phase == '机动'
                and distance(poses[self.pids[0]], self.site)
                <= self.params['radius'] + 1.0):
            self.patrol_started_at = t
            self.set_phase('巡逻')
        for pid in self.pids:
            is_air = explicit_loop and pid in self.air_routes
            route = self.air_routes[pid] if is_air else self.loop
            route_n = len(route)
            i = self.idx.get(pid, 0) % route_n
            target = route[(i + 1) % route_n]
            targets[pid] = target
            tolerance = (self.params.get('corner_lookahead_m', 1.8)
                         if explicit_loop and self.phase == '巡逻' else self.params['arrive_tol'])
            if is_air:
                # The route is already densified along the boundary.  A large
                # pass radius would skip several points and visibly cut across
                # the task area, so only a small fixed-wing tolerance is used.
                tolerance = max(
                    tolerance,
                    float(self.params.get('air_pass_tolerance_m', 2.5)))
            arrival_target = self.effective_target(pid, target)
            if distance(poses[pid], arrival_target) <= tolerance:
                self.idx[pid] = (i + 1) % route_n
                if explicit_loop and self.phase == '巡逻':
                    targets[pid] = route[(i + 2) % route_n]
                self.visits[pid].append(dict(
                    index=(i + 1) % route_n, t=round(t, 2)))
                self.emit('checkpoint_visited', pid=pid,
                          index=(i + 1) % route_n, cycle=self.cycles[pid],
                          target=[round(v, 2) for v in target],
                          effective_target=[round(v, 2)
                                            for v in arrival_target])
                legs = len(self.visits[pid]) - 1
                completed_lap = (legs > 0 and legs % route_n == 0
                                 if explicit_loop
                                 else self.idx[pid] == 0)
                if completed_lap:
                    self.cycles[pid] += 1
                    interval = t - self.last_cycle_t[pid]
                    self.last_cycle_t[pid] = t
                    self.emit('cycle_completed', pid=pid,
                              cycle=self.cycles[pid],
                              revisit_s=round(interval, 2))
                    if self.cycles[pid] >= int(self.params['cycles']):
                        self.metrics['revisit_s'] = round(interval, 2)
        if explicit_loop and self.phase == '机动' and all(self.visits.values()):
            self.last_cycle_t = dict.fromkeys(self.pids, t)
            self.patrol_started_at = t
            self.air_orbit_started_at = {
                pid: t for pid in self.patrol_groups.get('air', [])}
            self.set_phase('巡逻')
        ground_scale, air_scale = {}, {}
        if explicit_loop and self.phase == '巡逻':
            ground_scale, _ = self._spacing_speed(poses)
        air_scale = self._air_speed_scales() if explicit_loop else {}
        if explicit_loop:
            self._observe_target(poses)
        cycles_done = all(
            self.cycles[pid] >= int(self.params['cycles']) for pid in self.pids)
        if cycles_done:
            observation_target = self.params.get('observation_target')
            target_complete = (
                observation_target is None
                or (self.target_started and (
                    self.relay_target is not None
                    or self.target_finished_at is not None))
            )
            if target_complete:
                self._settle_patrol()
        return dict(targets=targets, phase=self.phase, done=self.done,
                    speed_scale=ground_scale, air_speed_scale=air_scale,
                    loiter_radius=loiter_radius)

    def _spacing_speed(self, poses):
        """比较各车从自己起巡点走过的弧长，领先的车减速等队形。"""
        perimeter = self.loop_distances[-1]
        progress = {}
        group = self.patrol_groups.get('ground', [])
        for pid in group:
            i = self.idx[pid]
            start = self.visits[pid][0]['index']
            arc = (self.loop_distances[i] - self.loop_distances[start]) % perimeter
            a, b = self.loop[i], self.loop[(i + 1) % len(self.loop)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            x, y = poses[pid][:2]
            length = self.loop_distances[i + 1] - self.loop_distances[i]
            projection = ((x - a[0]) * dx + (y - a[1]) * dy) / length
            ahead = min(length, max(0.0, projection))
            progress[pid] = self.cycles[pid] * perimeter + arc + ahead

        slowest = min((progress[pid] for pid in group), default=0.0)
        # 容许少量间距误差，避免在拐弯处反复急加速、急减速。
        ground_scale = {
            pid: max(
                0.65,
                1.0 - max(0.0, progress[pid] - slowest - 4.0) / 24.0)
            for pid in group
        }
        return ground_scale, {}

    def _observe_target(self, poses):
        target = self.params.get('observation_target')
        if not target:
            return
        target_id = target['target_id']
        start = target.get('start', target.get('point'))
        goal = target.get('goal', start)
        if 'start' not in target:
            # 兼容旧场景中在起巡后一段时间出现的定点目标。
            if (self.patrol_started_at is None
                    or self.t - self.patrol_started_at < target['appear_after_s']):
                return
            duration = 0.0
            target_active_at = self.patrol_started_at + float(
                target['appear_after_s'])
        else:
            duration = distance(start, goal) / target['speed_mps']
            delay = float(target.get('start_after_patrol_s', 0.0))
            if self.patrol_started_at is None and delay > 0.0:
                return
            patrol_origin = (self.patrol_started_at
                             if self.patrol_started_at is not None else 0.0)
            target_active_at = patrol_origin + delay
            if self.t + 1e-9 < target_active_at:
                return
        if self.relay_target:
            if self.relay_target.started_at is None:
                return
            pos = [round(v, 3) for v in self.relay_target.position(
                self.relay_origin_s + self.t)]
        else:
            elapsed = max(0.0, self.t - target_active_at)
            fraction = min(1.0, elapsed / duration) if duration else 1.0
            pos = [round(a + (b - a) * fraction, 3)
                   for a, b in zip(start, goal)]
        if not self.target_started:
            self.target_started = True
            self.target_started_at = target_active_at
            self.emit('patrol_target_started', target_id=target_id,
                      pos=pos if self.relay_target else start, goal=goal,
                      duration_s=(distance(pos, goal) / target['speed_mps']
                                  if self.relay_target else duration),
                      started_at_s=round(target_active_at, 3),
                      start_after_patrol_s=round(
                          target_active_at - (self.patrol_started_at or 0.0), 3))
        if (not self.relay_target
                and (duration <= 0.0
                     or self.t - target_active_at >= duration - 1e-9)
                and self.target_finished_at is None):
            self.target_finished_at = self.t
            self.emit('patrol_target_departed', target_id=target_id,
                      pos=pos, elapsed_s=round(duration, 3))
        for pid, radius in self.sensor_radii.items():
            last = self.target_last_reports.get(pid)
            if distance(poses[pid], pos) * self.cell_size_m > radius:
                if last is not None:
                    del self.target_last_reports[pid]
                    self.emit('patrol_target_lost', target_id=target_id, pid=pid)
                continue
            if last is None:
                self.target_detected = True
                if self.target_first_detection_s is None:
                    self.target_first_detection_s = round(self.t, 3)
                self.target_last_detection_s = round(self.t, 3)
                self.emit('target_detected', target_id=target_id, pid=pid, pos=pos)
            elif self.t - last < 1.0 - 1e-9:
                continue
            self.target_last_reports[pid] = self.t
            self.target_last_detection_s = round(self.t, 3)
            self.target_report_count += 1
            self.emit('patrol_position_report', target_id=target_id, pid=pid, pos=pos,
                      coordinate_frame='scenario_xy_m', source='simulation')

    def _settle_patrol(self):
        target = self.params.get('observation_target')
        if target and self.target_started:
            detected = bool(self.target_report_count)
            verdict = 'succeeded' if detected else 'failed'
            reason = ('target_detected_and_reported' if detected
                      else 'target_not_detected')
            result = dict(
                overall=verdict,
                label='巡逻警戒与目标侦察',
                target_id=target['target_id'],
                target_detected=detected,
                report_count=self.target_report_count,
                first_detection_s=self.target_first_detection_s,
                last_detection_s=self.target_last_detection_s,
                target_started_at_s=(round(self.target_started_at, 3)
                                     if self.target_started_at is not None else None),
                cycles_completed=min(
                    self.cycles[pid] for pid in self.pids),
                reason=reason,
                adjudicator='patrol_sensor_simulation',
                verified=False,
                verification_scope='local_mock_simulation',
            )
            self.metrics.update(
                target_detected=detected,
                target_report_count=self.target_report_count,
                target_first_detection_s=self.target_first_detection_s,
                target_last_detection_s=self.target_last_detection_s,
                result=dict(result),
            )
            self.result = result
            self.emit('patrol_result', **result)
        self._finish('patrol_cycles_done')

    def progress_frac(self):
        if self.done:
            return 1.0
        target = self.params.get('observation_target')
        if (target and all(self.cycles[pid] >= int(self.params['cycles'])
                           for pid in self.pids)
                and self.target_started and self.target_finished_at is None):
            return 0.98
        total = max(1, len(self.pids) * int(self.params['cycles']))
        return min(1.0, sum(self.cycles.values()) / total)

    def debug(self):
        return dict(idx={k: v for k, v in self.idx.items()},
                    cycles=dict(self.cycles))


    def subtask_progress(self, pid):
        """按已访问检查点计进度；只看完成圈数会把整圈内的推进都算成 0。"""
        checkpoints = max(1, len(self.loop))
        target = max(1, int(self.params.get('cycles') or 1))
        return min(1.0, len(self.visits.get(pid, []))
                   / float(checkpoints * target))

    def replace_agent(self, old_pid, new_pid, can_climb=None):
        super().replace_agent(old_pid, new_pid, can_climb)
        self.idx[new_pid] = self.idx.pop(old_pid, 0)
        self.cycles[new_pid] = self.cycles.pop(old_pid, 0)
        self.last_cycle_t[new_pid] = self.last_cycle_t.pop(old_pid, 0.0)
        self.visits[new_pid] = self.visits.pop(old_pid, [])
        for group in self.patrol_groups.values():
            if old_pid in group:
                group.remove(old_pid)
        group_name = 'air' if can_climb else 'ground'
        if new_pid not in self.patrol_groups[group_name]:
            self.patrol_groups[group_name].append(new_pid)
        self.sensor_radii.pop(old_pid, None)
        for key in list(self.target_last_reports):
            if key == old_pid or isinstance(key, tuple) and len(key)>1 and key[1] == old_pid:
                del self.target_last_reports[key]
        radius = (self.params.get('sensor_radius_m') or {}).get(group_name)
        if radius:
            self.sensor_radii[new_pid] = float(radius)


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
CN_STATE_WITHDRAWING = "撤离中"
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
        self.intercept_point = None
        self.withdraw_goal = list(self.start)
        self.track = []
        self.version = 1

    def velocity(self, retreat=False):
        tx, ty = (self.withdraw_goal if retreat else self.goal)
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
        warning_response_s=2.0,
        retreat_clearance_m=10.0,
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
        # 空中监视的盘旋圈如果切进对空威胁区，先收缩再生成航点：否则运动层
        # 会把圈上航点逐拍投影到威胁区两侧，飞机在威胁区/建筑角来回折返。
        self.air_orbit_radius_m = float(p['air_orbit_radius_m'])
        self.air_orbit_radius_effective_m = self.air_orbit_radius(
            tuple(self.center), self.air_orbit_radius_m)
        if (self.air_pids and abs(self.air_orbit_radius_effective_m
                                  - self.air_orbit_radius_m) > 1e-6):
            for post in self.post_list:
                if post.get('air'):
                    post['orbit_radius_configured_m'] = self.air_orbit_radius_m
                    post['orbit_radius_m'] = self.air_orbit_radius_effective_m
            reason = ('对空威胁区与 %.0f m 盘旋圈相交，盘旋半径收缩到 %.0f m'
                      % (self.air_orbit_radius_m,
                         self.air_orbit_radius_effective_m))
            for pid in self.air_pids:
                self.emit('air_orbit_adjusted', pid=pid,
                          configured_radius_m=self.air_orbit_radius_m,
                          effective_radius_m=self.air_orbit_radius_effective_m,
                          reason=reason)
            self._log(0.0, 'air_orbit_adjusted',
                      configured_radius_m=self.air_orbit_radius_m,
                      effective_radius_m=self.air_orbit_radius_effective_m)
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
            air_orbit_radius_m=self.air_orbit_radius_m,
            air_orbit_radius_effective_m=self.air_orbit_radius_effective_m,
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
            safe_post = self._free_point(post['post'], max_radius=30.0)
            self.posts[pid] = list(safe_post)
            self.sectors[pid] = (post['s0'], post['s1'])
            self.roles[pid] = 'boundary:%d/%d' % (post['index'], sector_count)
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(safe_post),
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
            safe_post = self._free_point(
                inward,
                max_radius=max(
                    12.0,
                    float((gate or {}).get('width', 12.0)) / 2.0 + 20.0))
            self.posts[pid] = [round(safe_post[0], 3),
                               round(safe_post[1], 3)]
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
            self.posts[pid] = self._free_point(standby, max_radius=20.0)
            self.sectors[pid] = None
            self.roles[pid] = 'intercept:standby'
            self.post_list.append(dict(pid=pid, role=self.roles[pid],
                                       point=list(self.posts[pid]),
                                       mid=list(self.posts[pid]), sector=None))
        for pid in reserve_pids:
            self.posts[pid] = self._free_point(reserve, max_radius=20.0)
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
        self._last_poses = {
            pid: tuple(pose[:2]) for pid, pose in poses.items()}
        p = self.params
        warn_range = float(p['warn_range_m'] or p['sensor_radius_m'])
        targets_out = dict(self.posts)
        loiter_radius = {}
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

        was_established = self.control_established_at is not None
        for spec in self.targets:
            self._update_target(spec, poses, t, dt, warn_range)

        self._track_control(poses, t, dt)
        if (not was_established and self.control_established_at is not None
                and p.get('target_start_mode') == 'after_control'):
            for spec in self.targets:
                if not spec.appeared:
                    self._update_target(spec, poses, t, dt, warn_range)

        for pid, post in self.posts.items():
            if pid in self.lost_pids:
                continue
            if pid in self.intercept_tasks:
                target = self._target_of(pid)
                if target is not None and target.state == CN_STATE_INTERCEPT:
                    point = target.intercept_point or self._free_point(geom.lead_intercept(
                        tuple(poses[pid])[:2],
                        target.pos,
                        target.velocity()[0],
                        self._speed_of(pid)))
                    targets_out[pid] = point
                continue
            if str(self.roles.get(pid, '')).split(':')[0] == 'air':
                # The fixed-wing runner uses its own bounded orbit controller.
                # Keep the logical target stable at the containment centre and
                # request the circle only when the aircraft arrives at its
                # tangent station.  Sending the point that moves around the
                # circumference every second makes the aircraft chase a moving
                # waypoint, replan, and overlap several large circles.
                radius = float(getattr(
                    self, 'air_orbit_radius_effective_m',
                    p['air_orbit_radius_m']) or 0.0)
                targets_out[pid] = post
                entry_band = max(1.5, self._speed_of(pid) * dt * 1.5)
                if (radius > 0.0
                        and distance(tuple(poses[pid])[:2],
                                     tuple(post)) <= radius + entry_band):
                    loiter_radius[pid] = radius
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
        return dict(targets=targets_out, loiter_radius=loiter_radius,
                    phase=self.phase, done=self.done,
                    speed_scale=speed_scale, pursuit_pids=tuple(self.intercept_tasks))

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
            point = self._free_point(point, max_radius=12.0)
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
            arc = geom.arc_of_point(self.polygon, tuple(gate['point']))['s']
            base, _ = geom.point_at(self.polygon, arc,
                                    float(p['gate_standoff_m']))
            off = amp * math.sin(2 * math.pi * t / period + phase)
            # While an interceptor is driving through this gate, the sentry
            # holds at the opposite flank instead of sweeping across the
            # interceptor's centre line.  Otherwise the two routes intersect
            # at almost the same instant and the platform icons stack.
            approaches = []
            for intercept_pid in self.intercept_tasks:
                target = self._target_of(intercept_pid)
                if target is not None:
                    approaches.append(target.intercept_point or target.pos)
            # Also reserve the flank while an interceptor is returning to its
            # standby circle after the target has already been resolved.
            for other_pid, pose in getattr(self, '_last_poses', {}).items():
                if str(self.roles.get(other_pid, '')).startswith('intercept'):
                    approaches.append(pose)
            for approach in approaches:
                if distance(approach, tuple(gate['point'])) > max(
                        36.0, float(gate.get('width', 12.0)) * 2.0):
                    continue
                relative = ((approach[0] - base[0]) * nx
                            + (approach[1] - base[1]) * ny)
                off = amp if relative <= 0.0 else -amp
                break
            point = self._free_point(
                [base[0] + nx * off, base[1] + ny * off],
                max_radius=max(
                    12.0,
                    float(gate.get('width', 12.0)) / 2.0 + 20.0))
            return [round(point[0], 3), round(point[1], 3)]
        if kind in ('intercept', 'reserve'):
            center = self.posts.get(pid)
            if not center:
                return None
            radius = float(p['standby_loop_radius_m']) * (0.75 if kind == 'reserve' else 1.0)
            period = max(20.0, float(p['patrol_period_s']))
            theta = 2 * math.pi * t / period + phase
            point = self._free_point(
                [center[0] + radius * math.cos(theta),
                 center[1] + radius * math.sin(theta)],
                max_radius=12.0)
            return [round(point[0], 3), round(point[1], 3)]
        if kind == 'air':
            # The moving-layer AirLoiter owns the circle.  A transient orbit
            # point here would be treated as a new global route target every
            # second and recreate the very churn that AirLoiter avoids.
            return list(self.center)
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
        new_appearance = not target.appeared
        if new_appearance:
            origin = (self.control_established_at
                      if p.get('target_start_mode') == 'after_control' else 0.0)
            if origin is None or t < origin + target.t_start:
                return
            relay = self.relay_target
            if relay and target.id == relay.spec["target_id"]:
                target.pos = relay.position(self.relay_origin_s + t)
                relay.containment = target
            target.appeared = True
            self.counts['unauthorized' if not target.authorized
                        else 'authorized'] += 1
            self.emit('target_appeared', target_id=target.id,
                      authorized=target.authorized,
                      pos=[round(v, 2) for v in target.pos])
            self._log(t, 'target_appeared', target=target.id,
                      authorized=target.authorized)
        if target.state == CN_STATE_WARNED and target.compliance:
            if t - target.warned_t >= float(p['warning_response_s']):
                target.state = CN_STATE_WITHDRAWING
                ux, uy = _unit(target.start, target.goal)
                distance_out = float(p['retreat_clearance_m'])
                target.withdraw_goal = [target.start[0] - ux * distance_out,
                                        target.start[1] - uy * distance_out]
                self.emit('target_withdraw_started', target_id=target.id,
                          pos=list(target.pos), goal=list(target.withdraw_goal))
                self._log(t, 'target_withdraw_started', target=target.id)
        elif not new_appearance:
            target.move(dt, retreat=target.state == CN_STATE_WITHDRAWING)
        target.track.append([round(t, 1), round(target.pos[0], 2),
                             round(target.pos[1], 2)])

        if not target.authorized and geom.inside(self.polygon, target.pos):
            self._mark_breach(target, t, pid=target.interceptor)
            return

        if target.state == CN_STATE_WITHDRAWING:
            if distance(target.pos, target.withdraw_goal) <= 1e-6:
                target.state = CN_STATE_WITHDRAWN
                target.resolved_t = round(t, 2)
                self.counts['warning_effective'] += 1
                self.emit('warning_effective', target_id=target.id, pos=list(target.pos))
                self._log(t, 'warning_effective', target=target.id)
            return

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
            pid, point, eta, entry_eta = self._pick_interceptor(poses, target)
            if pid is None:
                return
            target.state = CN_STATE_INTERCEPT
            target.intercept_t = round(t, 2)
            target.interceptor = pid
            target.intercept_point = point
            self.intercept_tasks[pid] = target.id
            self.counts['intercept_attempts'] += 1
            if target.detected_t is not None:
                self.response_times.append(round(t - target.detected_t, 2))
            self.emit('intercept_assigned', target_id=target.id, pid=pid,
                      role=self._role_label(pid), eta_s=eta, entry_eta_s=entry_eta,
                      point=point)
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
                target.intercept_point = None
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
        """优先派能及时到达的机动组；赶不及时由可更早到达的门哨支援。"""
        busy = set(self.intercept_tasks)
        fraction = geom.first_entry_fraction(self.polygon, target.pos, target.goal)
        entry_eta, point = None, None
        if fraction is not None:
            (vx, vy), length = target.velocity()
            entry_eta = fraction * length / target.speed
            ahead = max(0.0, entry_eta - min(1.0, entry_eta / 2.0))
            point = self._free_point([target.pos[0] + vx * ahead, target.pos[1] + vy * ahead])
        options = []
        for pid in self.interceptors:
            if pid in busy or pid in self.lost_pids:
                continue
            mobile = self.roles.get(pid, '').startswith('intercept:')
            estimate = self._intercept_eta(pid, poses[pid], point or target.pos)
            if not math.isfinite(estimate):
                continue
            timely = entry_eta is None or estimate <= entry_eta
            options.append((not timely, not mobile if timely else False, estimate, pid))
        if not options:
            return None, None, None, None
        _, _, eta, pid = min(options)
        return pid, point, round(eta, 2), None if entry_eta is None else round(entry_eta, 2)

    def _intercept_eta(self, pid, pose, point):
        start = pose[:2]
        length, heading_to = distance(start, point), point
        if hasattr(self.nav, 'plan') and length > 1e-6:
            try:
                path = self.nav.plan(start, point, densify=0)
            except NavError:
                return math.inf
            length = path['length']
            if len(path['path']) > 1:
                heading_to = path['path'][1]
        if length <= 1e-6:
            return 0.0
        speed = self._speed_of(pid)
        kind = (getattr(self, 'platform_caps', {}).get(pid) or {}).get('kind') or 'UGV'
        limits = limits_for(kind, speed)
        heading = math.atan2(heading_to[1] - start[1], heading_to[0] - start[0])
        turn_time = abs(clamp_angle(heading - (pose[2] if len(pose) > 2 else 0.0))) / limits.max_yaw_rate
        accel = limits.max_accel
        accel_distance = speed * speed / (2 * accel)
        travel = (math.sqrt(2 * length / accel) if length < accel_distance else
                  speed / accel + (length - accel_distance) / speed)
        return travel + turn_time

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
            # 盘旋半径：配置值 + 实际使用值（对空威胁区相交时会收缩）。
            air_orbit_radius_m=getattr(self, 'air_orbit_radius_m', None),
            air_orbit_radius_effective_m=getattr(
                self, 'air_orbit_radius_effective_m', None),
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
        if timeout and p.get('target_start_mode') == 'after_control' and self.control_established_at is None:
            verdict, reason = 'failed', '封控时段结束前未建立控制，目标未出场'
        elif timeout:
            verdict, reason = 'failed', '封控时段结束前未完成本次封控'
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
        return dict(verdict=verdict, reason=reason, items=items, timeout=timeout,
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
            targets=[dict(target_id=x.id, state=x.state, appeared=x.appeared,
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
        self.cells = self._grid_cells()
        self.unknown = set(self.cells)
        self.explored = set()
        self.claimed = {}
        self.phase = '展开'
        self.report_sent = False
        self.last_coverage_emit = 0.0
        self.metrics.update(cells=len(self.cells),
                            sensor_radius=p['sensor_radius'],
                            area_radius=p['area_radius'])

    def _grid_cells(self):
        p = self.params
        cell = p['cell']
        x0, y0, x1, y1 = self.nav.bounds
        cx, cy = self.site
        r = p['area_radius']
        cells = []
        nx = int(2 * r / cell)
        for i in range(nx + 1):
            for j in range(nx + 1):
                q = [cx - r + i * cell, cy - r + j * cell]
                if not (x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                    continue
                if self.nav.clearance(q) < 0.2:
                    continue
                cells.append((round(q[0], 2), round(q[1], 2)))
        return cells

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
                    targets={k: v for k, v in self.claimed.items() if v},
                    air_search_stations={
                        pid: [round(point[0], 2), round(point[1], 2)]
                        for pid, point in getattr(
                            self, 'air_search_stations', {}).items()})


class AreaReconBehavior(ReconBehavior):
    """空地平台在同一份室外网格上分区搜索、共享覆盖并补盲。"""
    continuous = True
    DEFAULTS = dict(ReconBehavior.DEFAULTS, cell=4.0, frontier_tol=1.2,
                    sensor_radius_m={'ground': 9.0, 'air': 13.0},
                    air_search_speed_mps=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not 0 < self.params['coverage_target'] <= 1:
            raise ValueError('侦察覆盖目标须大于 0 且不超过 1')
        starts = self.params['search_starts']
        self.claimed = {pid: tuple(starts[pid]) for pid in self.pids}
        self.sector = {cell: min(self.pids, key=lambda pid: (distance(starts[pid], cell), pid))
                       for cell in self.cells}
        self.ground_cells = {cell for cell in self.cells if self.nav.free(cell)}
        self.air_pids = set()
        self.lost_pids = set()
        self.sensor_radii = {}
        self.air_search_speed_effective_mps = None
        self.sweep_samples = {}
        self.result = None
        self.coverage_reached = False
        self.coverage_reached_at = None
        self.tracking_deadline_at = None
        self.air_search_stations = {}
        self.air_search_station_cells = {}
        self.air_search_orbit_radii = {}
        self.tracking_target = self.params.get('tracking_target')
        if self.tracking_target:
            target = self.tracking_target
            if (not geom.inside(self.area, target['start']) or geom.inside(self.area, target['goal'])
                    or target['speed_mps'] <= 0 or target['move_after_s'] < 0
                    or target['track_outside_s'] <= 0):
                raise ValueError('跟踪目标须从区内驶向区外，并给出正速度和跟踪时长')
        self.detected_at = None
        self.track_pid = None
        self.track_seconds = 0.0
        self.track_complete = False
        self.last_track_report = -math.inf
        self.target_entered_area = False
        self.acquire_pid = None
        self.target_sample = None
        self.track_contact_seen = False
        self.track_move_started_at = None
        self.stop_orbit_seconds = 0.0

    def _grid_cells(self):
        self.area = self.params['area']
        xs, ys = zip(*self.area)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        cell = float(self.params['cell'])
        if not math.isfinite(cell) or cell <= 0 or x0 >= x1 or y0 >= y1:
            raise ValueError('侦察区和网格尺寸须为有效的正数范围')
        nx, ny = math.ceil((x1 - x0) / cell), math.ceil((y1 - y0) / cell)
        dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
        cells = [(round(x0 + (i + 0.5) * dx, 3), round(y0 + (j + 0.5) * dy, 3))
                 for i in range(nx) for j in range(ny)]
        cells = [q for q in cells if geom.inside(self.area, q) and self.nav.free(q, radius=0)]
        if not cells:
            raise ValueError('侦察区内没有可侦察的室外网格')
        return cells

    def set_platform_caps(self, caps):
        super().set_platform_caps(caps)
        self.air_pids = {pid for pid in self.pids if caps.get(pid, {}).get('can_climb')}
        # Ground-only recon cannot cover cells whose clearance is smaller than
        # the platform footprint.  Those cells used to stay in the denominator
        # forever, capping a fully explored urban task below 99%.
        if not self.air_pids:
            unreachable = self.unknown - self.ground_cells
            self.unknown.intersection_update(self.ground_cells)
            self.cells = sorted(self.ground_cells)
            self.metrics['source_cells'] = len(self.cells) + len(unreachable)
            self.metrics['unreachable_ground_cells'] = len(unreachable)
            self.metrics['cells'] = len(self.cells)
        radii = self.params['sensor_radius_m']
        self.sensor_radii = {pid: float(radii['air' if pid in self.air_pids else 'ground'])
                             for pid in self.pids}
        self.air_search_speed_effective_mps = self._air_search_speed_limit()
        requested_orbit = self.params.get('air_search_orbit_radius_m', 8.0)
        self.air_search_orbit_radii = {
            pid: max(3.0, min(14.0, float(requested_orbit)))
            for pid in self.air_pids
        }

    def _air_search_speed_limit(self):
        """Return a speed that lets a fixed wing turn inside the search area.

        Recon grids are typically tens of metres across.  A 25--30 m/s fixed
        wing with the configured 0.35 rad/s yaw limit needs roughly 70--85 m to
        turn, so treating each grid cell as an exact waypoint produces long
        loops outside the task area.  An explicit task parameter wins; the
        automatic value uses the shorter area side as a turn-radius budget.
        """
        requested = self.params.get('air_search_speed_mps')
        if requested is not None:
            try:
                requested = float(requested)
            except (TypeError, ValueError):
                requested = 0.0
            if math.isfinite(requested) and requested > 0:
                return requested
        xs, ys = zip(*self.area)
        span = min(max(xs) - min(xs), max(ys) - min(ys))
        yaw_rate = max(
            0.15, float(self.params.get('air_max_yaw_rate', 0.35)))
        # Keep the nominal turn diameter below roughly one third of the short
        # side.  The previous 12 m/s cap could still leave a 35 m turn radius
        # for a 120 m recon block, so the aircraft visibly curved outside the
        # task polygon before re-entering it.
        return max(3.5, min(8.0, 0.18 * span * yaw_rate))

    def _scan(self, pid, pose):
        air = pid in self.air_pids
        radius = self.sensor_radii[pid]
        self.sweep_samples.setdefault(pid, []).append(
            [round(self.t % 1, 2), round(pose[0], 3), round(pose[1], 3)])
        new_cells = sorted(q for q in self.unknown if distance(pose, q) <= radius
                           and (air or self.nav.segment_free(pose, q, radius=0)))
        if new_cells:
            self.unknown.difference_update(new_cells)
            self.explored.update(new_cells)
            self.emit('frontier_mapped', pid=pid, pos=list(pose[:2]), new_cells=new_cells,
                      newly=len(new_cells), coverage=round(self.coverage(), 4))

    def drain_sweep(self):
        samples, self.sweep_samples = self.sweep_samples, {}
        return samples

    def _next_cell(self, pid, pose):
        claimed = set(self.claimed.values())
        candidates = self.unknown if pid in self.air_pids else self.unknown & self.ground_cells

        def air_aware_cost(q):
            direct_distance = distance(pose, q)
            if pid not in self.air_pids:
                return direct_distance
            bearing = math.atan2(q[1] - pose[1], q[0] - pose[0])
            heading_error = abs(_wrap(bearing - float(pose[2])))
            # Prefer a forward, gently turning cell over a slightly nearer
            # cell directly behind the aircraft.  The target remains reachable
            # when every remaining cell is behind; it is merely deprioritised.
            return direct_distance * (1.0 + 2.0 * (1.0 - math.cos(heading_error)))

        available = candidates - claimed
        if not available and pid in self.air_pids:
            # Do not leave a fixed-wing platform pinned to an explored cell
            # merely because other aircraft have claimed its local sector.
            # Fall back to any unclaimed recon cell before declaring no
            # frontier.
            available = self.unknown - claimed
        return min(available,
                   key=lambda q: (self.sector[q] != pid, air_aware_cost(q),
                                  distance(pose, q), q),
                   default=None)

    def _air_search_station(self, pid, pose):
        """Return an in-area orbit station that scans a cluster of unknowns.

        Chasing an exact cell behind a fixed-wing continuously rebuilds a
        short turn arc and looks like circling in place. Holding a bounded
        orbit over a small unknown cluster lets the sensor sweep it, then
        advances to the next cluster.
        """
        station = self.air_search_stations.get(pid)
        cells = self.air_search_station_cells.get(pid, set())
        pending = cells & self.unknown
        if station is not None and pending:
            return list(station), self.air_search_orbit_radii[pid]

        cell = self._next_cell(pid, pose)
        if cell is None:
            if station is not None:
                return list(station), self.air_search_orbit_radii[pid]
            return list(pose[:2]), 0.0

        xs = [point[0] for point in self.area]
        ys = [point[1] for point in self.area]
        radius = self.air_search_orbit_radii[pid]
        # Keep the complete orbit inside the task rectangle even when the
        # selected frontier touches its edge.
        center = [
            min(max(float(cell[0]), min(xs) + radius + 1.5),
                max(xs) - radius - 1.5),
            min(max(float(cell[1]), min(ys) + radius + 1.5),
                max(ys) - radius - 1.5),
        ]
        # A station is complete only when every assigned cell lies inside the
        # actual swept disc (orbit radius + sensor radius). Adding one extra
        # grid cell here left corner cells that the aircraft could never see,
        # which kept it orbiting the same station indefinitely.
        reach = radius + self.sensor_radii[pid] - 0.5 * self.params['cell']
        cells = {
            point for point in self.unknown
            if point in self.cells and distance(point, center) <= reach
        }
        self.claimed[pid] = cell
        self.air_search_stations[pid] = tuple(center)
        self.air_search_station_cells[pid] = cells
        self.emit('air_search_station', pid=pid,
                  frontier=list(cell),
                  center=[round(v, 2) for v in center],
                  orbit_radius_m=round(radius, 2),
                  cells=len(cells))
        return center, radius

    def _target_needs_replacement(self, pid, pose, target):
        if target is None:
            return True
        # Scanning already covers the cell's centre before the platform reaches
        # the exact coordinate.  Keeping that stale claim made fixed wings orbit
        # a cell that had already turned from unknown into explored.
        if target not in self.unknown:
            return True
        if distance(pose, target) <= self.params['frontier_tol']:
            return True
        if pid in self.air_pids:
            heading = float(pose[2])
            to_target = (target[0] - pose[0], target[1] - pose[1])
            forward = (to_target[0] * math.cos(heading)
                       + to_target[1] * math.sin(heading))
            return forward < 0.0
        return False

    def _track_target(self, poses, dt):
        target = self.tracking_target
        if not target:
            return None
        start, goal = target['start'], target['goal']
        target_id = target['target_id']
        relay = self.relay_target
        wait_for_contact = not relay and target.get('move_after_contact')
        def can_see(pid, point):
            return distance(poses[pid], point) <= self.sensor_radii[pid] and (
                pid in self.air_pids or self.nav.segment_free(poses[pid], point, radius=0))

        pos = relay.position(self.relay_origin_s + self.t) if relay else start
        movement_at = self.track_move_started_at if wait_for_contact else (
            None if self.detected_at is None else self.detected_at + target['move_after_s'])
        if not relay and movement_at is not None:
            elapsed = max(0, self.t - movement_at)
            fraction = min(1.0, elapsed * target['speed_mps'] / distance(start, goal))
            pos = [a + (b - a) * fraction for a, b in zip(start, goal)]
        stopped = distance(pos, goal) <= 1e-6
        moving = not stopped and bool(relay or (movement_at is not None and self.t > movement_at))
        self.target_sample = dict(target_id=target_id, pos=[round(v, 3) for v in pos],
                                  moving=bool(moving), pid=self.track_pid, status='waiting')
        if self.track_complete:
            self.target_sample['status'] = 'completed'
            return None
        self.target_entered_area |= geom.inside(self.area, pos)
        if self.detected_at is None:
            observers = [pid for pid in poses if can_see(pid, pos)]
            if observers:
                observer = min(observers, key=lambda pid: (distance(poses[pid], pos), pid))
                self.detected_at = self.t
                self.emit('target_detected', target_id=target_id, pid=observer, pos=pos)
                self.emit('recon_target_report', target_id=target_id, pid=observer, pos=pos,
                          coordinate_frame='scenario_xy_m', source='simulation')
                self.target_sample['status'] = 'reported'
            return None

        elapsed = self.t - self.detected_at - target['move_after_s']
        if elapsed < 0 and not wait_for_contact:
            self.target_sample['status'] = 'reported'
            return None
        if not self.coverage_reached:
            # 目标发现和覆盖搜索是并行事实，但派出跟踪平台必须等可侦察
            # 网格先达标；否则最先发现目标的平台会提前离开搜索扇区，
            # 界面看到覆盖没完成却已有车辆去追目标。
            self.target_sample['status'] = 'reported'
            return None
        length = distance(start, goal)
        if self.track_pid is None:
            # Choose the closest platform that currently has contact, across
            # both ground and air.  Always forcing an aircraft as the primary
            # tracker could leave a ground observer beside the target while a
            # distant fixed-wing aircraft spent the remaining deadline trying
            # to catch up.
            self.track_pid = min(self.pids, key=lambda pid: (
                not can_see(pid, pos), distance(poses[pid], pos), pid))
            self.claimed[self.track_pid] = None
            self.emit('recon_track_started', target_id=target_id, pid=self.track_pid,
                      pos=pos, goal=goal, speed_mps=target['speed_mps'])
        pid = self.track_pid
        observers = [other for other in self.pids if can_see(other, pos)]
        visible = pid in observers
        observed = bool(observers)
        if observed and not visible:
            previous = self.track_pid
            self.track_pid = min(
                observers, key=lambda other: (distance(poses[other], pos), other))
            pid = self.track_pid
            visible = True
            self.emit('recon_track_handoff', target_id=target_id,
                      previous_pid=previous, pid=pid, pos=list(pos),
                      reason='原跟踪平台失去接触，转交现场可见平台')
        report_pid = min(
            observers, key=lambda other: (distance(poses[other], pos), other)
        ) if observers else pid
        if wait_for_contact and self.track_move_started_at is None and visible and elapsed >= 0:
            self.track_move_started_at = self.t
        self.track_contact_seen |= observed
        self.target_sample.update(pid=report_pid, status='tracking' if observed else
                                  ('reacquiring' if self.track_contact_seen else 'approaching'))
        if observed and self.target_entered_area and not geom.inside(self.area, pos):
            self.track_seconds += dt
        else:
            self.track_seconds = 0.0
        if observed and self.t - self.last_track_report >= 1.0 - 1e-9:
            self.last_track_report = self.t
            self.emit('recon_track_report', target_id=target_id, pid=report_pid,
                      pos=[round(v, 3) for v in pos], coordinate_frame='scenario_xy_m',
                      source='simulation', moving=bool(moving))
        if stopped and observed:
            required_after_stop = (
                float(target.get('stop_hold_s', 3))
                if target.get('until_stopped')
                else float(target.get('stop_orbit_s', 18.0)))
            extended = self.t + max(5.0, required_after_stop + 15.0)
            if (self.tracking_deadline_at is None
                    or extended > self.tracking_deadline_at):
                self.tracking_deadline_at = extended
                self.emit('recon_tracking_deadline_extended',
                          target_id=target_id, deadline_s=round(extended, 2),
                          reason='目标已停止，保留最终观测与盘航证据时间')
        if (target.get('until_stopped') and stopped and observed
                and not getattr(self, 'target_stopped_emitted', False)):
            self.target_stopped_emitted = True
            self.target_stopped_at = self.t
            self.emit('target_stopped', target_id=target_id, pid=report_pid,
                      pos=list(pos), speed_mps=0.0,
                      coordinate_frame='scenario_xy_m', source='simulation')
        track_done = (stopped and observed and
                      self.t-getattr(self,'target_stopped_at',self.t)>=float(target.get('stop_hold_s',3)))
        outside_met = self.track_seconds + 1e-9 >= target['track_outside_s']
        orbit_s = float(target.get('stop_orbit_s', 18.0))
        # A fixed-wing platform cannot hover beside a stopped target.  Unless
        # the scenario explicitly requests a stop-and-hold adjudication, keep
        # an airborne tracker in a small orbit while final track evidence is
        # being accumulated.  Previously the default left the aircraft pinned
        # to a stationary follow point until the tracking timer expired.
        orbit_at_stop = (
            stopped
            and pid in self.air_pids
            and orbit_s > 0
            and not target.get('until_stopped')
            and target.get('track_until_stop', True))
        orbit_radius_m = min(
            float(self.params.get('air_orbit_radius_m', 3.0)),
            self.sensor_radii[pid] / 2)
        station_hold = getattr(self, 'station_holds', lambda *_: False)(pid, goal)
        # ``station_holds`` is true only after the runner has already entered an
        # orbit.  Requiring it before asking for the first orbit is circular:
        # a continuous recon aircraft reaches the stopped target, keeps a
        # straight-line follow target, and can never start the orbit.  Treat
        # the aircraft being at the orbit station as sufficient, while later
        # steps continue to use the shared station-hold predicate.
        at_orbit_station = (
            station_hold
            or distance(poses[pid], goal) <= max(2.0, orbit_radius_m))
        if orbit_at_stop and visible and at_orbit_station:
            self.stop_orbit_seconds += dt
            self.target_sample['status'] = 'orbiting'
        else:
            self.stop_orbit_seconds = 0.0
        orbit_met = not orbit_at_stop or self.stop_orbit_seconds + 1e-9 >= orbit_s
        if (track_done if target.get('until_stopped') else
                outside_met and orbit_met and (stopped or not target.get('track_until_stop'))):
            self.track_complete = True
            self.target_sample['status'] = 'completed'
            self.emit('recon_track_completed', target_id=target_id, pid=pid,
                      pos=[round(v, 3) for v in pos], tracked_outside_s=round(self.track_seconds, 2))
            return None
        # 跟在目标后方半个感知半径，避免飞到目标点上。
        standoff = self.sensor_radii[pid] / 2
        point = list(goal) if orbit_at_stop else [
            p - (b - a) * standoff / length for p, a, b in zip(pos, start, goal)]
        if orbit_at_stop:
            self.target_sample['orbit_radius'] = orbit_radius_m
        self.target_sample['follow_point'] = point
        return point

    def step(self, poses, t, dt):
        self.t = t
        if self.phase == '展开':
            self.emit('map_initialised', cells=len(self.cells), coverage=0.0)
            self.set_phase('探索')
        for pid in self.pids:
            self._scan(pid, poses[pid])
        coverage = self.coverage()
        if coverage - self.last_coverage_emit >= 0.1:
            self.last_coverage_emit = coverage
            self.emit('map_shared', coverage=round(coverage, 4), explored=len(self.explored))
        reached = coverage >= self.params['coverage_target']
        if reached and not self.coverage_reached:
            self.coverage_reached = True
            self.coverage_reached_at = t
            self.emit('coverage_reached', coverage=round(coverage, 4),
                      definition='可侦察室外网格覆盖',
                      covered_cells=len(self.explored),
                      total_cells=len(self.cells))
        track_point = self._track_target(poses, dt)
        follow_pid, follow_point = self.track_pid, track_point
        if self.relay_target and self.tracking_target and self.detected_at is None and self.air_pids:
            follow_point = self.relay_target.position(self.relay_origin_s + t)
            if self.acquire_pid is None:
                self.acquire_pid = min(self.air_pids,
                                       key=lambda pid: (distance(poses[pid], follow_point), pid))
                self.claimed[self.acquire_pid] = None
            follow_pid = self.acquire_pid
        if (self.coverage_reached and self.tracking_target
                and not self.track_complete):
            self.set_phase('目标跟踪')
            if self.tracking_deadline_at is None:
                target = self.tracking_target
                configured_grace = self.params.get('track_grace_s')
                if configured_grace is None:
                    target_travel_s = (
                        distance(target['start'], target['goal'])
                        / max(float(target.get('speed_mps') or 1.0), 1e-6))
                    stop_orbit_s = float(target.get('stop_orbit_s', 18.0))
                    configured_grace = max(
                        20.0,
                        min(
                            90.0,
                            float(target.get('track_outside_s', 0.0))
                            + float(target.get('move_after_s', 0.0))
                            + stop_orbit_s
                            + min(20.0, target_travel_s * 0.5)
                            + 10.0))
                self.tracking_deadline_at = (
                    t + max(5.0, float(configured_grace)))
                self.emit(
                    'recon_tracking_phase_started',
                    coverage=round(coverage, 4),
                    deadline_s=round(self.tracking_deadline_at, 2),
                    grace_s=round(float(configured_grace), 2),
                    definition='覆盖已达标，继续完成区外目标持续跟踪')
        complete = reached and (not self.tracking_target or self.track_complete)
        # Coverage has its own deadline; target tracking starts only after the
        # sensor map finds the target and may legitimately continue longer.
        # Applying the coverage deadline to both phases made a fully explored
        # area fail at t=120 while the aircraft was still following a target
        # that had not yet remained outside for the required duration.
        tracking_deadline = self.tracking_deadline_at
        if tracking_deadline is None:
            tracking_deadline = float(self.params.get(
                'track_deadline_s',
                float(self.params['search_limit_s']) + 60.0))
        deadline_reached = (
            t >= float(self.params['search_limit_s'])
            if not reached else
            t >= tracking_deadline)
        if complete or deadline_reached:
            if self.target_sample and not self.track_complete:
                self.target_sample.update(status='ended', follow_point=None)
            self.set_phase('回传')
            reason = (
                'coverage_reached' if complete else
                ('track_timeout' if reached and self.tracking_target
                 else 'search_deadline'))
            self.result = dict(overall='succeeded' if complete else 'failed',
                               termination=reason, coverage=round(coverage, 4),
                               coverage_target=self.params['coverage_target'],
                               cells=len(self.cells), covered_cells=sorted(self.explored),
                               remaining_cells=sorted(self.unknown),
                               coverage_definition='可侦察室外网格覆盖',
                               coverage_cell_size_m=float(self.params['cell']),
                               coverage_reached_at_s=(
                                   round(self.coverage_reached_at, 2)
                                   if self.coverage_reached_at is not None else None),
                               tracking_deadline_at_s=(
                                   round(self.tracking_deadline_at, 2)
                                   if self.tracking_deadline_at is not None else None),
                               coordinate_frame='scenario_xy_m', source='simulation')
            if self.tracking_target:
                self.result['tracking'] = dict(
                    target_id=self.tracking_target['target_id'], detected=self.detected_at is not None,
                    tracker=self.track_pid, completed=self.track_complete,
                    tracked_outside_s=round(self.track_seconds, 2))
            self.emit('report_sent', **self.result)
            self._finish(reason)
            return dict(targets={}, phase=self.phase, done=True)
        targets = {}
        loiter_radius = {}
        tracking_phase = (
            self.coverage_reached and self.tracking_target
            and not self.track_complete and follow_point is not None)
        backup_pid = None
        backup_point = None
        if tracking_phase:
            # 覆盖结束后仍有移动目标未跟稳时，不再让其余平台继续原地扫描
            # 已覆盖网格。保留主跟踪者，并让最近的一台平台前出接续观测。
            candidates = [
                pid for pid in self.pids
                if pid != follow_pid and pid not in self.lost_pids
            ]
            if candidates:
                backup_pid = min(
                    candidates,
                    key=lambda pid: (distance(poses[pid], follow_point), pid))
                dx = follow_point[0] - poses[backup_pid][0]
                dy = follow_point[1] - poses[backup_pid][1]
                norm = max(1e-6, math.hypot(dx, dy))
                # 与主跟踪者错开约一个感知半径，避免两车叠在同一点。
                offset = min(5.0, self.sensor_radii[backup_pid] * 0.45)
                backup_point = [
                    follow_point[0] - dy / norm * offset,
                    follow_point[1] + dx / norm * offset,
                ]
        for pid in self.pids:
            if follow_point is not None and pid in (follow_pid, backup_pid):
                targets[pid] = (follow_point if pid == follow_pid
                                else backup_point)
                continue
            if pid in self.air_pids:
                center, radius = self._air_search_station(pid, poses[pid])
                targets[pid] = center
                if radius > 0.0:
                    loiter_radius[pid] = radius
                continue
            target = self.claimed.get(pid)
            if self._target_needs_replacement(pid, poses[pid], target):
                self.claimed[pid] = self._next_cell(pid, poses[pid])
            targets[pid] = self.claimed[pid] or poses[pid]
        if follow_point is not None:
            targets[follow_pid] = follow_point
            if self.target_sample and 'orbit_radius' in self.target_sample:
                loiter_radius[follow_pid] = self.target_sample['orbit_radius']
        air_speed_scale = {}
        limit = self.air_search_speed_effective_mps
        speeds = getattr(self, 'speeds', {}) or {}
        if limit:
            for pid in self.air_pids:
                cruise = max(0.1, float(speeds.get(pid, limit) or limit))
                air_speed_scale[pid] = max(0.05, min(1.0, limit / cruise))
        return dict(targets=targets, phase=self.phase, done=False,
                    pursuit_pids=tuple(
                        pid for pid in (follow_pid, backup_pid)
                        if pid is not None and track_point is not None),
                    air_speed_scale=air_speed_scale,
                    loiter_radius=loiter_radius)

    def progress_frac(self):
        if self.done:
            return 1.0
        coverage_progress = min(
            1.0, self.coverage() / self.params['coverage_target'])
        if self.tracking_target and self.coverage_reached and not self.track_complete:
            # 覆盖不是整个任务：目标持续跟踪未完成时保留 2% 未完成量，
            # 避免界面在任务仍在运行时显示 100%。
            return 0.98
        return coverage_progress


    def subtask_progress(self, pid):
        """按该平台分担的扇区网格计进度；替补平台接管旧平台的扇区。"""
        cells = [cell for cell, owner in self.sector.items() if owner == pid]
        if not cells:
            return self.progress_frac()
        return min(1.0, sum(1 for cell in cells if cell in self.explored)
                   / float(len(cells)))

    def replace_agent(self, old_pid, new_pid, can_climb=None):
        super().replace_agent(old_pid, new_pid, can_climb)
        if old_pid in self.claimed:
            self.claimed[new_pid] = self.claimed.pop(old_pid)
        else:
            self.claimed.setdefault(new_pid, None)
        self.sector = {cell: (new_pid if owner == old_pid else owner)
                       for cell, owner in self.sector.items()}
        if can_climb is None:
            can_climb = old_pid in self.air_pids
        self.air_pids.discard(old_pid)
        self.air_pids.discard(new_pid)
        if can_climb:
            self.air_pids.add(new_pid)
        radii = self.params['sensor_radius_m']
        self.sensor_radii.pop(old_pid, None)
        self.sensor_radii[new_pid] = float(
            radii['air' if can_climb else 'ground'])
        self.sweep_samples.pop(old_pid, None)
        self.sweep_samples.pop(new_pid, None)
        if self.track_pid == old_pid:
            self.track_pid = new_pid
        if self.acquire_pid == old_pid:
            self.acquire_pid = new_pid
        for name in ('air_search_stations', 'air_search_station_cells', 'air_search_orbit_radii'):
            getattr(self, name).pop(old_pid, None)
        if can_climb:
            requested = self.params.get('air_search_orbit_radius_m', 8.0)
            self.air_search_orbit_radii[new_pid] = max(3.0, min(14.0, float(requested)))
        self.air_search_speed_effective_mps = self._air_search_speed_limit()


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
        # 探测半径：只用于工作台画"智能体探测范围"，不参与到位与效果判定
        sensor_radius_m=35.0,
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
        # 到位后的"游走/盘旋"：只改变到位后的观感与站位，不改进位判定口径。
        #   地面平台沿目标环切向小幅踱步（径向几乎不变，不会走出判定环）；
        #   空中平台绕观察位/评估位定半径盘旋。
        loiter_radius_m=1.2, loiter_period_s=24.0,
        # 空中盘旋：半径/周期缺省 0 = 自动推算。
        # 盘旋速度取 air_orbit_speed_mps（编成表里飞机是 25/30 场景单位每秒，
        # 2.0 的是本工作台场景的简装值），按它反推半径 v²/(g·tan 坡度)；
        # 目标点线速度与盘旋速度一致，飞机才是"跟着圆飞"而不是一步冲过圆心。
        air_orbit_radius_m=0.0, air_orbit_period_s=0.0,
        air_orbit_speed_mps=6.0, air_bank_deg=15.0,
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
        # 规划层保存的风险规避路线（4.2 assignments 的 path）。行为层只把它
        # 当“到同一目标的路线证据”，不改变行为决策；目标未变时复用，防止
        # 本地硬障碍重规划把已规避威胁的路线又拉回威胁区角点。
        self.planned_paths = {
            str(item.get('unit_id') or ''): [tuple(float(v) for v in point)
                                             for point in (item.get('path') or [])]
            for item in (p.get('_planned_assignments') or [])
            if item.get('unit_id') and item.get('path')
        }
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
        self.staging = self._reachable_ring_points(
            self.staging_center, p['staging_radius'], n)
        self.objective = self._reachable_ring_points(
            self.site, p['objective_radius'], n)
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
        self.withdraw_targets = (self._reachable_ring_points(
            self.withdraw_point, p['withdraw_ring'], n)
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
        self.waiting_events_emitted = set()
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

    def _emit_wait_once(self, key, reason, until_s=None, **detail):
        if key in self.waiting_events_emitted:
            return
        self.waiting_events_emitted.add(key)
        remaining = (max(0.0, float(until_s) - self.t)
                     if until_s is not None else None)
        self.emit('waiting', reason=reason,
                  until_s=(round(float(until_s), 2)
                           if until_s is not None else None),
                  remaining_s=(round(remaining, 2)
                               if remaining is not None else None),
                  **detail)

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
        if self.reached(poses, pid, target, tol):
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

    def _safe_ring_snap(self, point, radius, max_radius):
        """吸附环点；局部搜索失败时按地图尺度继续找一次。

        随机场景可能把撤离中心放开、把整个指定小环吞进建筑膨胀区。
        固定 3–4 m 的搜索半径此时找不到自由点，但地图其他位置仍有大量
        可通行区域。这种输入应退化为一个可执行的替代环点，不能在建行为
        状态机时抛出 ``nearest_free_failed`` 终止整轮仿真。
        """
        raw = [float(point[0]), float(point[1])]
        try:
            snapped, offset = self.nav.nearest_free(
                raw, max_radius=max_radius, radius=radius)
            return [float(snapped[0]), float(snapped[1])], offset
        except NavError:
            pass

        x0, y0, x1, y1 = map(float, self.nav.bounds)
        inset = max(radius, 0.5)
        search_center = [
            min(max(raw[0], x0 + inset), x1 - inset),
            min(max(raw[1], y0 + inset), y1 - inset),
        ]
        span = max(1.0, math.hypot(x1 - x0, y1 - y0))
        outside = distance(raw, search_center)
        searches = (
            (max(8.0, float(max_radius)), 0.1),
            (max(float(max_radius), 0.25 * span), 0.25),
            (span, 0.25),
            (span, 0.1),
        )
        for search_radius, step in searches:
            try:
                snapped, offset = self.nav.nearest_free(
                    search_center, max_radius=search_radius,
                    step=step, radius=radius)
                return [float(snapped[0]), float(snapped[1])], outside + offset
            except NavError:
                continue
        return None

    def _reachable_ring_point(self, center, radius, angle):
        """环上一点，保证从 center 有较直路径可达（否则沿径向回缩）。

        assault 的 staging/objective 若落在建筑另一侧，平台要绕很远、
        甚至卡在墙角（PathFollower 局部重规划）。这里若直连不可行就
        沿 center→点 方向回缩到最近的可直连点；若中心本身位于威胁区
        或障碍内，先把中心吸附到最近可通行锚点，再从锚点取环点。
        """
        safe_radius = self.nav.radius + 0.5
        anchor_result = self._safe_ring_snap(
            center, safe_radius, max(6.0, radius * 2.0))
        if anchor_result is None:
            # If the map itself has no free point for this platform, leave the
            # run recoverable at the already validated task site.
            return list(self.site)
        anchor, _ = anchor_result
        max_snap = max(1.0, radius * 0.5)
        angle_offsets = (
            0.0, 0.15, -0.15, 0.3, -0.3, 0.6, -0.6,
            math.pi / 2.0, -math.pi / 2.0, math.pi,
        )
        for frac in (1.0, 0.8, 0.6, 0.45, 0.3, 0.2):
            for delta in angle_offsets:
                result = self._safe_ring_snap(
                    _polar(anchor, radius * frac, angle + delta),
                    safe_radius, max_snap)
                if result is None:
                    continue
                cand, _ = result
                if self.nav.segment_free(anchor, cand, radius=safe_radius):
                    return cand
        return anchor

    def _reachable_ring_points(self, center, radius, count):
        """生成一组安全、可互相区分且可从安全锚点直达的环点。

        威胁区内或贴障碍的中心不能原样作为多台平台的集结点：旧实现会
        给所有平台返回同一个不可通行中心，地面平台因此持续
        ``goal_in_obstacle``。中心不可达时，先吸附到最近安全点，再扫描
        安全弧段并选出 ``count`` 个间距最大的离散点；正常中心仍沿用原
        环形阵位，避免改变既有场景布局。
        """
        count = max(1, int(count))
        safe_radius = self.nav.radius + 0.5
        if self.nav.free(center, radius=safe_radius):
            normal = [
                self._reachable_ring_point(
                    center, radius, 2 * math.pi * i / count)
                for i in range(count)
            ]
            if (all(self.nav.free(point, radius=safe_radius)
                    for point in normal)
                    and all(self.nav.segment_free(
                        center, point, radius=safe_radius)
                            for point in normal)):
                return normal

        anchor_result = self._safe_ring_snap(
            center, safe_radius, max(8.0, radius * 2.0))
        if anchor_result is None:
            anchor = list(self.site)
        else:
            anchor, _ = anchor_result
        candidates = []
        for factor in (1.0, 1.5, 2.0, 2.5):
            sample_count = max(24, count * 8)
            for index in range(sample_count):
                raw = _polar(anchor, radius * factor,
                             2 * math.pi * index / sample_count)
                result = self._safe_ring_snap(
                    raw, safe_radius, max(1.0, radius * 0.5))
                if result is None:
                    continue
                point, _ = result
                if not self.nav.segment_free(
                        anchor, point, radius=safe_radius):
                    continue
                if any(distance(point, item) < max(0.2, radius * 0.04)
                       for item in candidates):
                    continue
                candidates.append(point)
            if len(candidates) >= count:
                break

        if len(candidates) < count:
            candidates.extend([anchor] * (count - len(candidates)))
        preferred = [
            point for point in candidates
            if self.nav.clearance(point)
            >= safe_radius + max(0.25, radius * 0.75)
        ]
        if len(preferred) >= count:
            candidates = preferred
        if len(candidates) > count:
            candidates.sort(key=lambda point: math.atan2(
                point[1] - anchor[1], point[0] - anchor[0]))
            best = None
            stride = len(candidates) / float(count)
            for rotation in range(len(candidates)):
                selected = [
                    candidates[int((rotation + index * stride)
                                   % len(candidates))]
                    for index in range(count)
                ]
                spread = min(
                    distance(selected[i], selected[j])
                    for i in range(count)
                    for j in range(i)
                ) if count > 1 else 0.0
                if best is None or spread > best[0]:
                    best = (spread, selected)
            candidates = best[1]
        return candidates[:count]

    # ---- 到位后的游走/盘旋（只改观感与站位，不改判定口径） ----
    def _is_air(self, pid):
        """与 BehaviorRunner 同一套判据：能爬升且配了巡航高度才算空中。"""
        caps = (self.platform_caps or {}).get(pid) or {}
        if not caps.get('can_climb'):
            return False
        alt = (self.params.get('air_altitude') or {}).get(pid)
        return float(alt or 0.0) > 0.0

    def _air_station_radius(self, pid, point):
        p = self.params
        cruise = max(0.1, float(
            (getattr(self, 'speeds', None) or {}).get(
                pid, 1.0) or 1.0))
        speed = min(cruise, max(0.2, float(
            p.get('air_orbit_speed_mps') or 6.0)))
        radius = float(p.get('air_orbit_radius_m') or 0.0)
        if radius <= 0.0:
            bank = math.radians(max(5.0, min(45.0, float(
                p.get('air_bank_deg') or 15.0))))
            radius = (speed * speed) / (9.8 * math.tan(bank))
        # Lower/upper bounds are display and kinematic guards.  The runtime
        # further limits the orbit speed to the circle this radius can fly.
        radius = min(80.0, max(10.0, radius))
        return self.air_orbit_radius((point[0], point[1]), radius)

    def _station_loiter(self, pid, point, t, phase=0.0):
        """站点附近的小幅游走目标。

        地面沿**切向**踱步：径向距离几乎不变，``objective_radius +
        arrive_tol`` 的判定环不会因为游走把平台挤出去，开火与在位记账仍成立。
        空中绕站点定半径盘旋（只影响 2D 投影，高度由运动层控制）。
        """
        p = self.params
        if self._is_air(pid):
            cruise = max(0.1, float(
                (getattr(self, 'speeds', None) or {}).get(pid, 1.0) or 1.0))
            speed = min(cruise, max(0.2, float(
                p.get('air_orbit_speed_mps') or 6.0)))
            radius = self._air_station_radius(pid, point)
            period = float(p.get('air_orbit_period_s') or 0.0)
            if period <= 0.0:
                # 目标点线速度与盘旋速度一致时，飞机才是在"跟着圆飞"，
                # 而不是一步冲过圆心再折回来。
                period = 2.0 * math.pi * radius / max(speed, 1e-3)
            period = max(6.0, period)
            ang = 2.0 * math.pi * t / period + phase
            return [point[0] + radius * math.cos(ang),
                    point[1] + radius * math.sin(ang)]
        amp = max(0.0, float(p.get('loiter_radius_m') or 0.0))
        period = max(8.0, float(p.get('loiter_period_s') or 24.0))
        if amp <= 0.0:
            return list(point)
        dx, dy = point[0] - self.site[0], point[1] - self.site[1]
        radius = math.hypot(dx, dy)
        if radius <= 1e-6:
            return [point[0], point[1] + amp * math.sin(
                2.0 * math.pi * t / period + phase)]
        # 阵位经过障碍吸附后，初始半径可能略大于 objective_radius。
        # 游走振幅必须按距离在位边界的剩余径向预算收紧，否则目标会偶尔
        # 越过 objective_radius + arrive_tol，坚守刚开始就误报 control_lost。
        radial_limit = (float(p['objective_radius'])
                        + float(p['arrive_tol']) + 0.04)
        radial_budget = max(0.0, radial_limit - radius)
        amp = min(amp, math.sqrt(max(
            0.0, (radius + radial_budget) ** 2 - radius ** 2)))
        off = amp * math.sin(2.0 * math.pi * t / period + phase)
        tx, ty = -dy / radius, dx / radius
        return [point[0] + tx * off, point[1] + ty * off]

    def _apply_station_loiter(self, targets, t):
        """给已到位地面席位加小幅游走；空中席位保持固定圆心。

        Air stations must not receive a new point on the circle every second:
        doing so forced a fresh route-plan and visibly stacked crossing arcs.
        ``_station_loiter_radii`` tells the runtime to fly one continuous orbit.
        """
        out = dict(targets)
        for index, pid in enumerate(self.pids):
            point = out.get(pid)
            if point is None:
                continue
            if self._is_air(pid):
                continue
            if pid == self.scout:
                if 'observation' not in self.arrivals[pid]:
                    continue
            elif pid == self.assessor:
                if 'assessment_post' not in self.arrivals[pid]:
                    continue
            elif 'objective' not in self.arrivals[pid]:
                continue
            out[pid] = self._station_loiter(pid, point, t, index * 1.1)
        return out

    def _station_loiter_radii(self, targets):
        if self.phase not in ('机动', '执行', '坚守', '结果确认'):
            return {}
        radii = {}
        for pid in self.pids:
            point = targets.get(pid)
            if point is None or not self._is_air(pid):
                continue
            if pid == self.scout:
                ready = 'observation' in self.arrivals[pid]
            elif pid == self.assessor:
                ready = 'assessment_post' in self.arrivals[pid]
            else:
                ready = 'objective' in self.arrivals[pid]
            if ready:
                radii[pid] = self._air_station_radius(pid, point)
        return radii

    def _air_speed_scale_now(self):
        """盘旋中的空中平台按配置减速；还没到位的仍全速飞向站位。

        只影响空中直飞分支（BehaviorRunner._air_speed_scale），地面游走的
        限速仍走 speed_scale，两套互不覆盖。
        """
        scale = {}
        if self.phase not in ('机动', '执行', '坚守', '结果确认'):
            return scale        # 撤离/收尾不减速，撤离时限仍按全速核验
        for pid in self.pids:
            if not self._is_air(pid):
                continue
            if pid == self.scout:
                ready = 'observation' in self.arrivals[pid]
            elif pid == self.assessor:
                ready = 'assessment_post' in self.arrivals[pid]
            else:
                ready = False
            if ready:
                cruise = max(0.1, float(
                    (getattr(self, 'speeds', None) or {}).get(pid, 1.0) or 1.0))
                target = max(0.2, float(
                    self.params.get('air_orbit_speed_mps') or 6.0))
                scale[pid] = max(0.05, min(1.0, target / cruise))
        return scale

    # ---- 目标分配 ----
    def _targets_at(self, points):
        out = {}
        if self.scout:
            out[self.scout] = self.observation
        for i, pid in enumerate(self.assault_pids):
            out[pid] = points[min(i, len(points) - 1)]
        return out

    def _planned_route_targets(self, phase):
        """按 4.2 分配顺序找到每个平台在当前阶段的计划终点。"""
        source = (self.staging if phase == 'staging'
                  else self.withdraw_targets if phase == 'withdraw'
                  else self.objective)
        out = {}
        if self.scout:
            out[self.scout] = self.observation
        for i, pid in enumerate(self.assault_pids):
            out[pid] = source[min(i, len(source) - 1)]
        if self.assessor:
            slot = min(self._assessor_slot, len(source) - 1)
            out[self.assessor] = source[slot]
        return out

    def _planned_routes_for(self, targets, route_targets,
                            include_staging=False):
        """复用计划路线，直到平台接近该路线终点并切换到下一个目标。"""
        out = {}
        for pid, goal in targets.items():
            path = self.planned_paths.get(pid)
            if not path or len(path) < 2 or goal is None:
                continue
            end = path[-1]
            if distance(end, goal) > max(4.0, self.params['arrive_tol'] * 6):
                continue
            # 到位/执行开始后，计划终点仍是集结位时不再复用旧路线。
            staging_goal = (self.staging[min(0, len(self.staging) - 1)]
                            if self.staging else None)
            if (not include_staging and staging_goal is not None
                    and distance(end, staging_goal) < 1e-6
                    and distance(goal, staging_goal) > 1e-6):
                continue
            out[pid] = dict(
                path=[list(point) for point in path],
                length=round(sum(distance(path[i], path[i + 1])
                                 for i in range(len(path) - 1)), 3),
                straight_length=round(distance(path[0], path[-1]), 3),
                straight_line_ok=False,
                min_clearance=None,
                mode='planned_threat_route')
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
        routes = {}
        loiter_radius = {}
        if self.phase == '机动':
            targets = self._targets_at(self.staging)
            routes = self._planned_routes_for(
                targets, self._planned_route_targets('staging'))
            if self.assessor:
                # 评估组与突击分队同时出发，但直接前出评估观察位。固定翼
                # 不能先在集结环停住、进入执行阶段再掉头横跨数十米；这样
                # 会产生很长的转弯弧，突击组已在目标环完成打击后仍长时间
                # 等待评估回传。提前预置不改变“评估席位到场后才发起评估”
                # 的判定，只消除无效的中途驻留。
                targets[self.assessor] = self.assessment_post
                self._record_arrival(
                    poses, self.assessor, 'assessment_post',
                    self.assessment_post, tol)
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
            # 集结完成条件是突击组全部到位。评估组独立前出观察位，不能把
            # 它的远距离预置时间叠加成突击分队的无意义等待。
            staged = self._all_arrived('staging')
            if staged and (self.scout is None or self.designated):
                self.emit('all_staged', staging=self.staging,
                          pids=list(self.assault_pids))
                self.set_phase('到位')
                self.stage_enter_t = t
                self.phase_times.append(dict(phase='到位', t=round(t, 2)))
                self._emit_wait_once(
                    'formation_settle', '突击组到位后稳定 1 秒',
                    until_s=t + 1.0, configured_s=1.0)
        elif self.phase == '到位':
            targets = self._targets_at(self.staging)
            if self.assessor:
                targets[self.assessor] = self.assessment_post
            if t - self.stage_enter_t >= 1.0:
                self._schedule_release(t)
                self.set_phase('执行')
                self.execute_start_t = t
                if (p.get('execute_deadline') is not None
                        and float(p['execute_deadline']) > 0.0):
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
            release_routes = {}
            for i, pid in enumerate(self.assault_pids):
                if t < self.release_at.get(pid, 0.0):
                    targets[pid] = self.staging[min(i, len(self.staging) - 1)]
                    release_routes[pid] = self.staging[min(i, len(self.staging) - 1)]
                else:
                    targets[pid] = self.objective[min(i, len(self.objective) - 1)]
                    release_routes[pid] = self.objective[min(i, len(self.objective) - 1)]
            if self.scout:
                targets[self.scout] = self.observation
                release_routes[self.scout] = self.observation
            if self.assessor:
                # 评估组前出评估观察位（在位后才有资格发起评估）
                targets[self.assessor] = self.assessment_post
                release_routes[self.assessor] = self.assessment_post
            routes = self._planned_routes_for(
                targets, release_routes, include_staging=False)
            if self.assessor:
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
            elif self.position_reported:
                future = [until for pid, until in self.release_at.items()
                          if t < until]
                if future:
                    self._emit_wait_once(
                        'synchronized_release',
                        '等待分批次出发时刻以保持同时到达',
                        until_s=max(future), pids=sorted(self.release_at))
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
                    if self.assessment_t > t:
                        self._emit_wait_once(
                            'assessment_feedback',
                            '等待评估回传',
                            until_s=self.assessment_t,
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
            withdraw_routes = {}
            if self.scout:
                targets[self.scout] = self.observation
                withdraw_routes[self.scout] = self.observation
            for i, pid in enumerate(self.assault_pids):
                targets[pid] = self.withdraw_targets[min(i, len(self.withdraw_targets) - 1)]
                withdraw_routes[pid] = self.withdraw_targets[
                    min(i, len(self.withdraw_targets) - 1)]
            if self.assessor:
                slot = min(self._assessor_slot, len(self.withdraw_targets) - 1)
                targets[self.assessor] = self.withdraw_targets[slot]
                withdraw_routes[self.assessor] = self.withdraw_targets[slot]
                self._record_arrival(poses, self.assessor, 'withdraw',
                                     self.withdraw_targets[slot], tol)
            routes = self._planned_routes_for(targets, withdraw_routes,
                                              include_staging=False)
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
        if self.phase in ('机动', '执行', '坚守', '结果确认'):
            targets = self._apply_station_loiter(targets, t)
            loiter_radius = self._station_loiter_radii(targets)
        return dict(targets=targets, phase=self.phase, done=self.done,
                    air_speed_scale=self._air_speed_scale_now(),
                    planned_routes=routes, loiter_radius=loiter_radius)

    def progress_frac(self):
        if self.done:
            return 1.0
        if self.phase == '结果确认' and self.assess_requested and not self.assessed:
            start = float(self.stage_enter_t or self.t)
            end = max(start, float(self.assessment_t or start))
            if end > start:
                # 评估等待期间保持可见进展，避免进度条长时间固定在 90%。
                return 0.90 + 0.05 * min(1.0, max(0.0, (self.t - start) / (end - start)))
            return 0.95
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
# 5. 要点坚守（T-HLD）：阵位占位 + 观察 + 轮换接替 + 增援 + 撤离
#
# 1028 §2.5：保持对指定要点/防御区域的控制；按威胁方向配置阵位；持续观察；
# 触发增援、轮换或撤离。本层能写到的边界（任务书 §9.2）：
#   * 做：阵位分配、预备队、轮换与接替、增援路线、撤离时序，以及在这些过程上
#     记账（在位/观察/空窗/增援/接替）；
#   * 用**抽象效果**表示阵内反击与火力控制可用性（``counter_attack`` 事件 +
#     ``suppressed`` 状态），判定交 ``assessment.Adjudicator`` 的桩实现并标
#     ``verified=False``；
#   * 不做：弹道、命中概率、毁伤/杀伤模型、武器性能参数，规划层也不预测成败。
# 控制权口径：本层用"有效在位数量 + 阵位状态"近似控制权，是模型近似，不是
# 对现实控制权的确认（1028 §2.5.2 明确覆盖状态不等于现实控制权）。
# ------------------------------------------------------------------
HL_SCOPE_NOTE = ('控制权口径：本层用"有效在位数量 + 阵位状态"近似控制权，'
                 '只是模型近似，不等于对现实控制权的确认（1028 §2.5.2）；'
                 '效果类结论均为桩判定·未验证')
HL_CRITERIA = ('quantity', 'coverage')
HL_CRITERIA_LABELS = {'quantity': '在位数量', 'coverage': '观察覆盖'}


class KeepBehavior(Behavior):
    """要点坚守：按阵位占位、持续观察、接替轮换、增援与撤离（T-HLD）。

    与 ``HoldBehavior``（历史小场景的两点轮换演示）的分工：
      * HoldBehavior 保留给旧场景，几何是"作业点外两圈"、参数小场景化；
      * 本类只在输入给出要点/阵位（``_behavior.positions``）时启用，几何来自
        4.1 的 ``positions`` / 威胁方向（经 ``containment_geom`` 统一给出）。

    时序（1028 §2.5.4）：机动进场 → 占位（达到 ``min_on_post`` 记
    ``control_established``）→ 观察（覆盖与中断）→ 接替/轮换（到位才撤）→
    增援（触发→到达时间）→ 撤离/结束 → ``hold_result`` 结算。
    """

    kind = 'hold'
    label = '要点坚守'
    DEFAULTS = dict(
        key_point=None,
        positions=(),
        stations=None,
        threats=(),
        sensor_radius_m=35.0,
        observation_ring_m=None,
        observation_samples=12,
        hold_criteria="quantity",
        min_on_post=2,
        observation_gap_max_s=5.0,
        post_tolerance_m=3.0,
        # 在岗不等于钉在原地：到点后在阵位前方左右踱步（垂直于朝向），
        # 观察扇面随之扫过，比站着不动更接近"持续观察/占位"。
        patrol_enabled=True,
        patrol_radius_m=5.0,
        patrol_speed_mps=1.5,
        patrol_period_s=50.0,
        handover_tol_m=3.0,
        handover_timeout_s=60.0,
        swap_requires_arrival=True,
        arrive_tol=2.5,
        relief_interval_s=0.0,
        relief_cycles=0,
        reinforce_trigger="position_lost",
        reinforce_ratio=1.5,
        reinforce_arrive_within_s=60.0,
        withdraw_allowed=False,
        withdraw_route=(),
        withdraw_deadline_s=30.0,
        enemy_events=(),
        counter_attack=None,
        effect=None,
        duration_s=180.0,
        max_steps=600,
        control_lost_after_s=30.0,
        min_hold_ratio=0.9,
        max_control_interruption_s=30.0,
    )

    def __init__(self, job, nav, pids, params=None, site=None):
        raw = dict(params or {})
        super().__init__(job, nav, pids, raw, site)
        p = self.params
        # 4.1 的任务参数名是 hold_duration_s；基座行为层内部统一用 duration_s。
        # 直接按 4.1 参数构造（测试/自建场景）时也要认这个名字，不能悄悄
        # 退回默认 180 s——那会让"坚守 5 s"的用例等 180 s 还不结算。
        if 'hold_duration_s' in raw and 'duration_s' not in raw:
            p['duration_s'] = float(raw['hold_duration_s'])
        if 'max_steps' not in raw:
            p['max_steps'] = max(float(p['duration_s']) * 3.0, 120.0)
        self._normalize_policy()
        self.key_point = [float(v) for v in (p.get('key_point') or self.site)]
        self.threats = [dict(item) for item in (p.get('threats') or [])]
        self.criteria = str(p.get('hold_criteria') or 'quantity')
        if self.criteria not in HL_CRITERIA:
            raise ValueError("hold_criteria 必须是 %s" % "/".join(HL_CRITERIA))
        self.adjudicator = StubAdjudicator()
        self.post_tolerance = max(0.5, float(p['post_tolerance_m']))
        # 岗内游走：到点后在阵位附近踱步。振幅进"在位区间"，否则正常游走会被
        # 判成离岗（区域封控踩过的坑：用"离点 ≤ ε"判在位会把巡视记成脱岗）。
        self.patrol_enabled = bool(p['patrol_enabled'])
        self.patrol_radius = (max(0.0, float(p['patrol_radius_m']))
                              if self.patrol_enabled else 0.0)
        self.patrol_speed = max(0.2, float(p['patrol_speed_mps']))
        self.patrol_period = max(10.0, float(p['patrol_period_s']))
        self.handover_tol = max(0.5, float(p['handover_tol_m']))
        self.arrive_tol = max(0.5, float(p['arrive_tol']))
        self.swap_requires_arrival = bool(p['swap_requires_arrival'])
        self.sensor_radius = float(p['sensor_radius_m'])

        # ---- 阵位：与规划层同一份点/朝向（经 containment_geom 推出的坐标）----
        self.positions = []
        for index, item in enumerate(p.get('positions') or []):
            if isinstance(item, dict):
                point = item.get('point') or [0.0, 0.0]
                position_id = str(item.get('id') or "P%d" % (index + 1))
                facing = float(item.get('facing_deg') or 0.0)
                need = int(item.get('min_units') or 1)
            else:
                point = item
                position_id = "P%d" % (index + 1)
                facing, need = 0.0, 1
            snapped, offset = self._snap(point)
            self.positions.append(dict(
                id=position_id, point=snapped, snap=round(offset, 3),
                facing_deg=facing % 360.0, min_units=max(0, need)))
        if not self.positions:
            self.positions = [dict(id='P1', point=list(self.key_point), snap=0.0,
                                   facing_deg=0.0, min_units=1)]
        self.post_ids = [item['id'] for item in self.positions]
        self.post_point = {item['id']: list(item['point'])
                           for item in self.positions}
        self.post_facing = {item['id']: item['facing_deg']
                            for item in self.positions}
        self.min_on_post = min(max(1, int(p.get('min_on_post') or 2)),
                               len(self.positions))

        stations = dict(p.get('stations') or {})
        self.reserve_point = self._snap(
            stations.get('reserve') or self._default_reserve())[0]
        support = [self._snap(point)[0] for point in (stations.get('support') or [])]
        self.support_points = support
        self.relay_point = self._snap(
            stations.get('relay') or self.key_point)[0]

        # ---- 观察采样：固定点集，覆盖统计可复现（与封控同口径）----
        ring = float(p['observation_ring_m'] or max(10.0,
                                                   self.sensor_radius * 0.55))
        self.observation_ring_m = ring
        self.samples = geom.observation_ring(self.key_point, ring,
                                             int(p['observation_samples']))
        self.samples += geom.approach_points(self.key_point, self.threats, ring, 1)
        self.post_samples = {}
        for position in self.positions:
            threat = self._threat_of_position(position)
            self.post_samples[position['id']] = geom.approach_points(
                self.key_point,
                [dict(bearing_deg=position['facing_deg'],
                      width_deg=(threat or {}).get('width_deg', 60.0))],
                ring, 3)

        # ---- 分工 ----
        self.lost_pids = set()
        self.post_owner = {}
        self.post_of_pid = {}
        self.role = {}
        self._assign_roles()
        self.on_post = {}
        # 游走相位按平台错开，避免所有阵位同手同脚一起走。
        self.patrol_phase = {pid: (index * 1.9) % (2 * math.pi)
                             for index, pid in enumerate(sorted(self.pids))}

        # ---- 过程记账 ----
        self.control_established_at = None
        self.control_released_at = None
        self.hold_elapsed = 0.0
        self.control_time = 0.0
        self.interrupt_time = 0.0
        self.under_s = 0.0
        self.control_lost_at = None
        self.interruption_open = False
        self.coverage_sum = 0.0
        self.coverage_t = 0.0
        self.gap_run = 0.0
        self.gap_logged = False
        self.gap_total = 0.0
        self.gap_max = 0.0
        self.gaps = []
        self.post_obs_run = {key: 0.0 for key in self.post_ids}
        self.post_obs_best = {key: 0.0 for key in self.post_ids}
        self.occupancy = []            # 在位甘特：post_id/pid/enter_s/leave_s
        self._open_intervals = {}
        self.handover = None
        self.handover_list = []
        self.handover_hold_targets = {}
        self.relief_done = 0
        self.relief_cursor = 0
        self.relief_skipped = 0
        self.reinforce = None
        self.reinforce_list = []
        self.enemy_index = 0
        self.enemy_events = [dict(item) for item in (p.get('enemy_events') or [])]
        self.effects = []
        self.suppressed = set()
        self.counts = dict(attacks=0, defended=0, repelled=0, breaches=0,
                           counter_attacks=0, denied=0, post_lost=0)
        self.withdraw_started_at = None
        self.withdraw_target = None
        self.withdraw_points = {}
        self.withdraw_deadline = None
        self.withdraw_reason = None
        self.withdraw_timed_out = False
        self.timeline = []
        # 空中观察席的盘旋圈若切进对空威胁区，先收缩到整圈可用的半径，
        # 避免运动层把航点逐拍投影到威胁区两侧造成来回折返。
        self.air_orbit_radius_m = float(p.get('air_orbit_radius_m') or 45.0)
        self.air_orbit_radius_effective_m = self.air_orbit_radius(
            tuple(self.key_point), self.air_orbit_radius_m)
        if (self.air_pids and abs(self.air_orbit_radius_effective_m
                                  - self.air_orbit_radius_m) > 1e-6):
            reason = ('对空威胁区与 %.0f m 盘旋圈相交，盘旋半径收缩到 %.0f m'
                      % (self.air_orbit_radius_m,
                         self.air_orbit_radius_effective_m))
            for pid in self.air_pids:
                self.emit('air_orbit_adjusted', pid=pid,
                          configured_radius_m=self.air_orbit_radius_m,
                          effective_radius_m=self.air_orbit_radius_effective_m,
                          reason=reason)
            self._log(0.0, 'air_orbit_adjusted',
                      configured_radius_m=self.air_orbit_radius_m,
                      effective_radius_m=self.air_orbit_radius_effective_m)
        self.verdict = None
        self._last_coverage = 0.0
        self._last_gaps = []
        self._worst_gaps = []
        self._min_coverage = 1.0
        self.air_watch_s = 0.0
        self.metrics.update(
            key_point=[round(v, 2) for v in self.key_point],
            positions=[dict(item) for item in self.positions],
            min_on_post=self.min_on_post,
            hold_criteria=self.criteria,
            hold_criteria_label=HL_CRITERIA_LABELS[self.criteria],
            sensor_radius_m=self.sensor_radius,
            observation_ring_m=self.observation_ring_m,
            observation_samples=len(self.samples),
            threats=[dict(item) for item in self.threats],
            role_counts=dict(p.get('role_counts') or {}),
            patrol_enabled=self.patrol_enabled,
            patrol_radius_m=self.patrol_radius,
            patrol_speed_mps=(self.patrol_speed if self.patrol_enabled else None),
            patrol_period_s=(self.patrol_period if self.patrol_enabled else None),
            post_tolerance_m=self.post_tolerance,
            scope=HL_SCOPE_NOTE,
        )
        self.set_phase('机动')

    # ---------------- 工具 ----------------
    def _normalize_policy(self):
        """把 4.1 的嵌套策略（relief / reinforce / withdraw）摊平成行为参数。

        4.1 里这三项是 ``{interval_s, handover_tol_m, ...}`` 形式的字典，
        直接下发即可；行为层内部统一用扁平键，避免"字典给了但没生效"这类
        静默失效（轮换没跑、增援阈值没读，从产物上看不出来）。
        """
        p = self.params
        relief = dict(p.get('relief') or {})
        p['relief_interval_s'] = float(relief.get('interval_s')
                                       or p.get('relief_interval_s') or 0.0)
        p['relief_cycles'] = int(relief.get('relief_cycles')
                                 or p.get('relief_cycles') or 0)
        p['handover_tol_m'] = float(relief.get('handover_tol_m')
                                    or p.get('handover_tol_m') or 3.0)
        p['swap_requires_arrival'] = bool(relief.get(
            'swap_requires_arrival', p.get('swap_requires_arrival', True)))
        reinforce = dict(p.get('reinforce') or {})
        p['reinforce_trigger'] = str(reinforce.get('trigger')
                                     or p.get('reinforce_trigger')
                                     or 'position_lost')
        p['reinforce_ratio'] = float(reinforce.get('enemy_ratio')
                                     or p.get('reinforce_ratio') or 1.5)
        p['reinforce_arrive_within_s'] = float(
            reinforce.get('arrive_within_s')
            or p.get('reinforce_arrive_within_s') or 60.0)
        withdraw = dict(p.get('withdraw') or {})
        p['withdraw_allowed'] = bool(withdraw.get('allowed',
                                                  p.get('withdraw_allowed')))
        p['withdraw_route'] = [list(point) for point in
                               (withdraw.get('route') or p.get('withdraw_route')
                                or [])]
        p['withdraw_deadline_s'] = float(withdraw.get('deadline_s')
                                        or p.get('withdraw_deadline_s') or 30.0)

    def _snap(self, point, max_radius=6.0):
        """阵位点若落在静态障碍里，吸附到最近可通行点（吸附距离进产物）。"""
        nav = getattr(self, 'nav', None)
        try:
            snapped, offset = nav.nearest_free((float(point[0]), float(point[1])),
                                               max_radius=max_radius)
            return [round(float(snapped[0]), 3), round(float(snapped[1]), 3)], offset
        except Exception:      # noqa: BLE001  吸附失败就用原点，交回按原样执行
            return [float(point[0]), float(point[1])], 0.0

    def _withdraw_point(self, pid):
        """Give every withdrawing platform a distinct nearby assembly slot."""
        cached = self.withdraw_points.get(pid)
        if cached is not None:
            return list(cached)
        center = self.withdraw_target or self._default_reserve()
        nav = getattr(self, 'nav', None)
        # Separate targets by substantially more than one platform diameter;
        # otherwise several ground icons still look merged on the map even
        # though their coordinates differ by a few metres.
        gap = max(10.0, (float(getattr(nav, 'radius', 0.0) or 0.0)
                         * 5.0))
        used = list(self.withdraw_points.values())
        fallback = None
        for ring in range(5):
            radius = (0.0 if ring == 0 else ring * gap)
            samples = 1 if ring == 0 else max(8, ring * 8)
            for index in range(samples):
                angle = (2.0 * math.pi * index / samples
                         + 0.37 * len(self.withdraw_points))
                raw = [float(center[0]) + radius * math.cos(angle),
                       float(center[1]) + radius * math.sin(angle)]
                point, _ = self._snap(raw, max_radius=gap)
                if fallback is None:
                    fallback = point
                if used and any(distance(point, other) < gap for other in used):
                    continue
                if nav is not None:
                    try:
                        if not nav.free(point, radius=max(
                                0.8, float(getattr(nav, 'radius', 0.0)) + 0.2)):
                            continue
                    except Exception:      # noqa: BLE001  调用方无自由检查时照常使用
                        pass
                self.withdraw_points[pid] = tuple(point)
                return list(point)
        # A dense obstacle ring can defeat all nearby samples.  Preserve
        # completion by using the snapped fallback, but keep it deterministic.
        point = fallback or [float(center[0]), float(center[1])]
        self.withdraw_points[pid] = tuple(point)
        return list(point)

    def _default_reserve(self):
        threats = self.threats
        mean = (sum(float(item.get('bearing_deg', 0.0)) for item in threats)
                / len(threats)) if threats else 180.0
        back = geom.compass_vector((mean + 180.0) % 360.0)
        offset = max(10.0, float(self.params.get('reserve_standoff_m')
                                 or self.params.get('post_radius_m') or 30.0))
        return [self.key_point[0] + back[0] * offset,
                self.key_point[1] + back[1] * offset]

    def _threat_of_position(self, position):
        """阵位朝向最接近的威胁方向（阵位责任扇区）。"""
        if not self.threats:
            return None
        facing = float(position.get('facing_deg') or 0.0)
        return min(self.threats, key=lambda item: geom.angle_gap_deg(
            float(item.get('bearing_deg', 0.0)), facing))

    def _assign_roles(self):
        """把平台分到 阵位 / 预备队 / 支援 / 中继。

        优先用计划下发的角色（``roles[pid]``，如 ``post:P2``）；角色缺失或
        指向不存在的阵位时才按"空阵位 → 预备队"补位。执行层不擅自把
        "守 P2"改成"守 P1"。
        """
        pids = list(self.pids)
        declared = {pid: str(role) for pid, role in
                    (self.params.get('roles') or {}).items() if pid in pids}
        free = []
        for pid in pids:
            kind, _, detail = declared.get(pid, '').partition(':')
            if kind == 'post' and detail in self.post_point \
                    and detail not in self.post_owner:
                self.post_owner[detail] = pid
                self.post_of_pid[pid] = detail
                self.role[pid] = 'post:%s' % detail
            elif kind in ('reserve', 'support', 'relay', 'air'):
                self.role[pid] = declared[pid]
            else:
                free.append(pid)
        for post_id in self.post_ids:
            if post_id in self.post_owner or not free:
                continue
            pid = free.pop(0)
            self.post_owner[post_id] = pid
            self.post_of_pid[pid] = post_id
            self.role[pid] = 'post:%s' % post_id
        for pid in free:
            self.role[pid] = 'reserve:standby'
        # 空中观察席：绕要点上空定高盘旋（防空/对空警戒）。地面平台没有
        # 高度层，不能顶这个席位——计划层用 pinned_unit/air_capabilities 保证，
        # 这里再复核一次，避免"地面上站了个空中席位"。
        self.air_pids = [pid for pid in pids
                         if str(self.role.get(pid, '')).startswith('air')]
        if self.air_pids:
            altitude = float(self.params.get('air_altitude_m') or 60.0)
            # 能力复核：平台画像里有 can_climb 时才据它过滤（测试替身没有画像，
            # 不做过滤）；地面平台被误分到空中席位时这里会把它退回。
            if self.platform_caps:
                allowed = [pid for pid in self.air_pids
                           if (self.platform_caps.get(pid) or {}).get('can_climb')]
                if allowed:
                    self.air_pids = allowed
            self.params['air_altitude'] = {pid: altitude for pid in self.air_pids}
            self.air_altitude_m = altitude
        else:
            self.air_altitude_m = None

    def _role_kind(self, pid):
        return str(self.role.get(pid, '')).split(':')[0]

    def set_platform_caps(self, caps):
        """平台画像到齐后复核空中席位：飞不起来的平台不能占空中观察席。

        计划层已经用 ``air_unit`` / ``air_capabilities`` 固定了席位，但指令
        在下发途中可能被改写；这里按"能不能爬升"再挡一次，挡下来就退回预备队
        并留痕，而不是让它在地面上假装在飞。
        """
        super().set_platform_caps(caps)
        air = list(getattr(self, 'air_pids', []) or [])
        if not air:
            return
        caps = caps or {}
        keep = [pid for pid in air if (caps.get(pid) or {}).get('can_climb')]
        if len(keep) == len(air):
            return
        for pid in air:
            if pid in keep:
                continue
            self.role[pid] = 'reserve:standby'
            self.emit('air_seat_reassigned', pid=pid,
                      reason='平台不具备爬升能力，空中观察席退回预备队')
            self._log(self.t, 'air_seat_reassigned', pid=pid)
        self.air_pids = keep
        if keep:
            altitude = float(self.params.get('air_altitude_m') or 60.0)
            self.params['air_altitude'] = {pid: altitude for pid in keep}
        else:
            self.params.pop('air_altitude', None)
            self.air_altitude_m = None

    def _role_label(self, pid):
        return self.role.get(pid, '未分工')

    def _station_of(self, pid):
        post_id = self.post_of_pid.get(pid)
        if post_id:
            return list(self.post_point[post_id])
        kind = self._role_kind(pid)
        if kind == 'support':
            detail = str(self.role.get(pid, '')).split(':')[1] if ':' in \
                str(self.role.get(pid, '')) else ''
            try:
                index = max(1, int(detail.lstrip('S'))) - 1
            except ValueError:
                index = 0
            spots = self.support_points or [self.reserve_point]
            return list(spots[index % len(spots)])
        if kind == 'relay':
            return list(self.relay_point)
        if kind == 'air':
            return list(self.key_point)
        return list(self.reserve_point)

    def _handover_approach_point(self, post_id, pid=None):
        """Arrival slot for a relief/reinforcement near an occupied post.

        The incoming platform still counts as arrived inside ``handover_tol``,
        but it does not drive into the outgoing platform's exact centre.
        The offset points away from the key point so both platforms remain on
        the responsible side of the position.
        """
        post = self.post_point[post_id]
        incoming_pose = (getattr(self, '_latest_poses', {}) or {}).get(pid)
        if incoming_pose is not None:
            dx = float(incoming_pose[0]) - float(post[0])
            dy = float(incoming_pose[1]) - float(post[1])
        else:
            dx = float(post[0]) - float(self.key_point[0])
            dy = float(post[1]) - float(self.key_point[1])
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            dx, dy, norm = 1.0, 0.0, 1.0
        # The transfer slot sits outside the outgoing platform's body radius,
        # while remaining inside the post's on-position envelope.
        offset = max(3.6, self.handover_tol * 1.2)
        point, _ = self._snap(
            [post[0] + dx / norm * offset,
             post[1] + dy / norm * offset],
            max_radius=max(2.0, self.handover_tol))
        return [float(point[0]), float(point[1])]

    def _reserve_pid(self):
        for pid in self.pids:
            if pid in self.lost_pids:
                continue
            if self._role_kind(pid) == 'reserve':
                return pid
        return None

    def _alive(self, pid):
        return pid is not None and pid not in self.lost_pids

    # ---------------- 事件与时间线 ----------------
    def _log(self, t, event, **fields):
        row = dict(t=round(t, 2), event=event, **fields)
        self.timeline.append(row)
        return row

    def report_loss(self, pid, t):
        """执行期成员失联：不再计在位，并把该阵位留空（空窗照实记账）。"""
        if pid in self.lost_pids:
            return
        self.lost_pids.add(pid)
        self.metrics['our_losses'] = len(self.lost_pids)
        post_id = self.post_of_pid.pop(pid, None)
        if post_id and self.post_owner.get(post_id) == pid:
            self.post_owner[post_id] = None
        self.emit('member_lost', pid=pid, role=self._role_label(pid),
                  post_id=post_id)
        self._log(t, 'member_lost', pid=pid, post_id=post_id)

    # ---------------- 主循环 ----------------
    def step(self, poses, t, dt):
        self.t = t
        self._latest_poses = {
            pid: tuple(pose[:2]) for pid, pose in poses.items()}
        self._refresh_on_post(poses)
        self._track_posts(t)
        self._track_control(t, dt)
        self._track_observation(poses, t, dt)
        if not self.done:
            self._step_enemy(poses, t)
            self._step_relief_schedule(t)
            self._step_handover(poses, t)
            self._step_reinforce(poses, t)
            self._step_end(poses, t)
        return dict(targets=self._targets_for(), phase=self.phase,
                    done=self.done, speed_scale=self._step_speed_scale())

    def _step_speed_scale(self):
        """在岗游走限速：按 patrol_speed_mps 走，前出增援/接替/撤离恢复全速。

        空中观察席不受地面游走限速影响，单独按 air_speed_mps 限速。
        """
        patrol_on = self.patrol_enabled and self.patrol_radius > 0
        if not patrol_on and not getattr(self, 'air_pids', []):
            return {}
        busy = set()
        if self.handover:
            busy.update({self.handover.get('incoming'), self.handover.get('outgoing')})
        if self.reinforce:
            busy.add(self.reinforce.get('pid'))
        scale = {}
        for pid in self.pids:
            if pid in self.lost_pids or pid in busy:
                continue
            if self.withdraw_started_at is not None:
                continue
            if pid in getattr(self, 'air_pids', []):
                # 空中观察席按自己的盘旋速度走，不受地面游走限速影响
                air_speed = float(self.params.get('air_speed_mps') or 14.0)
                scale[pid] = min(1.0, air_speed
                                 / max(self._speed_of(pid), 0.1))
                continue
            if not self.post_of_pid.get(pid) or not self.on_post.get(pid):
                continue
            if not patrol_on:
                continue
            scale[pid] = min(1.0, self.patrol_speed
                             / max(self._speed_of(pid), 0.1))
        return scale

    def _speed_of(self, pid):
        return float((getattr(self, 'speeds', None) or {}).get(pid, 8.0) or 8.0)

    def _refresh_on_post(self, poses):
        """在位判定：按"自己阵位的半径"判，而不是"离作业点 ≤ ε"。

        半径包含游走振幅：到点后平台会在阵位附近踱步，若仍按"离点 ≤ 3 m"
        判，正常游走就会被记成离岗，控制中断也会凭空出现。
        """
        area = self.post_tolerance + self.patrol_radius
        self.on_post = {}
        for pid in self.pids:
            if pid in self.lost_pids:
                self.on_post[pid] = False
                continue
            post_id = self.post_of_pid.get(pid)
            if not post_id:
                self.on_post[pid] = False
                continue
            self.on_post[pid] = distance(
                tuple(poses[pid])[:2], tuple(self.post_point[post_id])) <= area

    def _post_target(self, pid, t):
        """在岗游走目标：在阵位前方沿"朝向的垂线"左右踱步。

        垂直于朝向踱步（而不是朝里/朝外走），阵面始终对着威胁方向，背不露给
        要点；振幅受 ``patrol_radius_m`` 约束，正好落在在位半径里。
        """
        post_id = self.post_of_pid.get(pid)
        if not post_id:
            return None
        point = self.post_point[post_id]
        if self.patrol_radius <= 0:
            return list(point)
        facing = math.radians(float(self.post_facing.get(post_id) or 0.0))
        # 朝向单位向量（0°=北）与其右向垂线
        fx, fy = math.sin(facing), math.cos(facing)
        px, py = fy, -fx
        phase = self.patrol_phase.get(pid, 0.0)
        offset = self.patrol_radius * math.sin(
            2 * math.pi * t / self.patrol_period + phase)
        return [round(point[0] + px * offset, 3),
                round(point[1] + py * offset, 3)]

    def manned_posts(self):
        """当前有效占位的阵位清单（有人、在位、且未被压制）。"""
        manned = []
        for post_id in self.post_ids:
            pid = self.post_owner.get(post_id)
            if not self._alive(pid):
                continue
            if not self.on_post.get(pid):
                continue
            if post_id in self.suppressed:
                continue
            manned.append(post_id)
        return manned

    def _track_posts(self, t):
        """阵位占用区间（甘特图数据源）：换人就闭合旧区间、打开新区间。"""
        for post_id in self.post_ids:
            pid = self.post_owner.get(post_id)
            if (self.withdraw_started_at is not None or not self._alive(pid)
                    or not self.on_post.get(pid)):
                pid = None
            current = self._open_intervals.get(post_id)
            if current and current['pid'] == pid:
                continue
            if current:
                current['leave_s'] = round(t, 2)
                current['duration_s'] = round(t - current['enter_s'], 2)
                self._open_intervals.pop(post_id, None)
            if current or pid is not None:
                self.emit('post_occupancy', post_id=post_id, pid=pid)
            if pid is not None:
                row = dict(post_id=post_id, pid=pid,
                           enter_s=round(t, 2), leave_s=None,
                           duration_s=None)
                self._open_intervals[post_id] = row
                self.occupancy.append(row)

    def _track_control(self, t, dt):
        p = self.params
        manned = self.manned_posts()
        count = len(manned)
        established = self.control_established_at is not None
        active = (established and self.withdraw_started_at is None
                  and self.hold_elapsed < float(p['duration_s']))
        if not established:
            if count >= self.min_on_post:
                self.control_established_at = round(t, 2)
                self.set_phase('坚守在位')
                self.emit('control_established', posts=count,
                          min_on_post=self.min_on_post,
                          manned=list(manned))
                self._log(t, 'control_established', posts=count,
                          min_on_post=self.min_on_post)
            return
        if not active:
            return
        self.hold_elapsed += dt
        if count >= self.min_on_post:
            self.control_time += dt
            self.under_s = 0.0
            if self.interruption_open:
                self.interruption_open = False
                self.emit('control_restored', posts=count)
                self._log(t, 'control_restored', posts=count)
        else:
            self.under_s += dt
            self.interrupt_time += dt
            if not self.interruption_open:
                self.interruption_open = True
                self.emit('control_interrupted', posts=count,
                          min_on_post=self.min_on_post)
                self._log(t, 'control_interrupted', posts=count)
            if (self.control_lost_at is None
                    and self.under_s > float(p['control_lost_after_s'])):
                self.control_lost_at = round(t, 2)
                self.emit('control_lost', posts=count,
                          under_s=round(self.under_s, 1))
                self._log(t, 'control_lost', posts=count)

    def _gap_bearings(self, observers):
        """要点周围哪些方位没有被"在位阵位"的探测圈覆盖（度，0°=北）。

        覆盖按阵位平台的圆形探测半径算，不是按扇区：扇区只表示"威胁来自哪里"，
        真正拦住斜向空隙的是各阵位探测圈对要点一周的覆盖。
        """
        if not observers:
            return [0, 90, 180, 270]
        gaps = []
        squared = self.sensor_radius ** 2
        for sample in self.samples:
            px, py = sample['point']
            if any((px - ox) ** 2 + (py - oy) ** 2 <= squared
                   for ox, oy in observers):
                continue
            bearing = math.degrees(math.atan2(px - self.key_point[0],
                                              py - self.key_point[1])) % 360.0
            gaps.append(round(bearing))
        return sorted(set(gaps))

    def _track_observation(self, poses, t, dt):
        p = self.params
        observers = []
        for post_id in self.manned_posts():
            pid = self.post_owner.get(post_id)
            observers.append(tuple(poses[pid])[:2])
        coverage = geom.coverage_ratio(self.samples, observers,
                                       self.sensor_radius)
        self._last_coverage = coverage
        self._last_gaps = self._gap_bearings(observers)        # 空中观察席在位：只要还有活的空中平台绕要点盘旋就计时（高度由运动层
        # 控制，行为层只拿得到二维位姿，因此按"是否在盘旋半径内"记账）。
        air_alive = [pid for pid in getattr(self, 'air_pids', [])
                     if pid not in self.lost_pids]
        air_ok = bool(air_alive)
        if air_ok:
            radius = float(p.get('air_orbit_radius_m') or 45.0) * 1.6
            air_ok = any(distance(tuple(poses[pid])[:2], tuple(self.key_point))
                         <= radius for pid in air_alive)
        if self.control_established_at is not None \
                and self.withdraw_started_at is None:
            self.coverage_sum += coverage * dt
            self.coverage_t += dt
            if air_ok:
                self.air_watch_s += dt
            # 覆盖缺口按"坚守时段内最差的一拍"记账：撤离后大家离开阵位，
            # 那一刻的空覆盖不能算成"守的时候漏了"。
            if coverage < self._min_coverage:
                self._min_coverage = coverage
            if len(self._last_gaps) > len(self._worst_gaps):
                self._worst_gaps = list(self._last_gaps)
        # 每个阵位对"自己责任扇区"的连续观察时长（抽象效果判定的过程证据）
        for position in self.positions:
            post_id = position['id']
            pid = self.post_owner.get(post_id)
            observed = (self._alive(pid) and self.on_post.get(pid)
                        and post_id not in self.suppressed
                        and geom.coverage_ratio(
                            self.post_samples[post_id],
                            [tuple(poses[pid])[:2]], self.sensor_radius) > 0)
            if observed:
                self.post_obs_run[post_id] += dt
                self.post_obs_best[post_id] = max(
                    self.post_obs_best[post_id], self.post_obs_run[post_id])
            else:
                self.post_obs_run[post_id] = 0.0
        if self.control_established_at is None or self.withdraw_started_at:
            return
        allowance = float(p['observation_gap_max_s'])
        if coverage <= 1e-9:
            self.gap_run += dt
            if self.gap_run > allowance and not self.gap_logged:
                self.gap_logged = True
                self.emit('observation_gap', gap_s=round(self.gap_run, 1),
                          allowance_s=allowance, posts=len(observers))
                self._log(t, 'observation_gap', gap_s=round(self.gap_run, 1))
        else:
            if self.gap_run > 0:
                self.gap_total += self.gap_run
                self.gap_max = max(self.gap_max, self.gap_run)
                self.gaps.append(dict(start_s=round(t - self.gap_run, 2),
                                      end_s=round(t, 2),
                                      duration_s=round(self.gap_run, 1)))
                if self.gap_logged:
                    self.emit('observation_restored',
                              gap_s=round(self.gap_run, 1))
                    self._log(t, 'observation_restored',
                              gap_s=round(self.gap_run, 1))
            self.gap_run = 0.0
            self.gap_logged = False

    # ---------------- 敌方进攻（输入事件 → 抽象效果） ----------------
    def _bearing_of_direction(self, direction):
        """敌方来向：优先按威胁方向 id 查角度，其次按数值方位角。"""
        text = str(direction if direction is not None else '').strip()
        for threat in self.threats:
            if str(threat.get('id')) == text:
                return float(threat.get('bearing_deg', 0.0))
        try:
            return float(text) % 360.0
        except (TypeError, ValueError):
            return float(self.threats[0].get('bearing_deg', 0.0)) \
                if self.threats else 0.0

    def _threatened_post(self, bearing):
        if not self.positions:
            return None
        return min(self.positions, key=lambda item: geom.angle_gap_deg(
            item['facing_deg'], bearing))['id']

    def _step_enemy(self, poses, t):
        for event in self.enemy_events[self.enemy_index:]:
            if t < float(event.get('t_s', 0) or 0):
                break
            self.enemy_index += 1
            self._handle_enemy(event, poses, t)

    def _handle_enemy(self, event, poses, t):
        kind = str(event.get('kind') or 'probe')
        try:
            ratio = float(event.get('ratio') or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        bearing = self._bearing_of_direction(event.get('direction'))
        post_id = self._threatened_post(bearing)
        pid = self.post_owner.get(post_id)
        manned = self._alive(pid) and bool(self.on_post.get(pid))
        self.counts['attacks'] += 1
        self.emit('enemy_attack', attack_kind=kind, post_id=post_id,
                  bearing_deg=round(bearing, 1), ratio=ratio,
                  manned=manned,
                  direction=str(event.get('direction') or ''))
        self._log(t, 'enemy_attack', attack_kind=kind, post_id=post_id,
                  ratio=ratio, manned=manned)
        if not manned:
            self.counts['post_lost'] += 1
            self.counts['breaches'] += 1
            self._suppress_post(post_id, t)
            self.emit('post_lost', post_id=post_id, reason='进攻时该阵位无人')
            self._log(t, 'post_lost', post_id=post_id)
        else:
            self.counts['defended'] += 1
            self._counter_attack(post_id, pid, bearing, t)
        if kind == 'assault' and ratio >= float(self.params['reinforce_ratio']):
            self._trigger_reinforce(post_id, poses, t, 'enemy_ratio')
        elif self.params.get('reinforce_trigger') == 'position_lost' and not manned:
            self._trigger_reinforce(post_id, poses, t, 'position_lost')
        # A failed counter-attack suppresses the post even when the owner is
        # still physically present.  Without replacement that post contributes
        # zero to the hold count until the end of the task, so a later attack on
        # another post can drop the whole task below min_on_post.  Dispatch an
        # available reserve as soon as a post is suppressed, before the next
        # attack has to create that shortage.
        if (post_id in self.suppressed and self.reinforce is None
                and self.handover is None
                and self.withdraw_started_at is None):
            self._trigger_reinforce(post_id, poses, t, 'post_suppressed')

    def _counter_attack(self, post_id, pid, bearing, t):
        """阵内反击/火力控制可用性：只出抽象效果，判定走桩，写 verified=false。"""
        p = self.params
        policy = dict(p.get('counter_attack') or {})
        authorized = bool(policy.get('authorized'))
        max_range = float(policy.get('max_range_m') or 0.0)
        if not authorized:
            self.counts['denied'] += 1
            self.emit('counter_attack_denied', post_id=post_id, pid=pid,
                      reason='无阵内反击授权')
            self._log(t, 'counter_attack_denied', post_id=post_id, pid=pid)
            self._suppress_post(post_id, t)
            return
        approach = geom.approach_points(
            self.key_point, [dict(bearing_deg=bearing)], self.observation_ring_m, 1)
        range_m = (distance(self.post_point[post_id],
                            approach[0]['point']) if approach else 0.0)
        if max_range > 0 and range_m > max_range:
            self.counts['denied'] += 1
            self.emit('counter_attack_out_of_range', post_id=post_id, pid=pid,
                      range_m=round(range_m, 1), max_range_m=max_range)
            self._log(t, 'counter_attack_out_of_range', post_id=post_id,
                      pid=pid, range_m=round(range_m, 1))
            return
        self.counts['counter_attacks'] += 1
        required = float((p.get('effect') or {}).get('required_duration', 10.0))
        evidence = dict(
            window=[round(t, 2), round(t + float(p['duration_s']), 2)],
            effect_achieved_t=round(t, 2),
            longest_suppression_s=self.post_obs_best[post_id],
            post_id=post_id,
            bearing_deg=round(bearing, 1),
            positions=list(self.post_ids),
        )
        ref = dict(job_id=self.job_id, target_id='%s/D%s' % (post_id, int(bearing)),
                   attempt=1, effect_kind='suppress',
                   params=dict(required_duration=required))
        result = self.adjudicator.adjudicate(ref, evidence)
        self.effects.append(dict(
            post_id=post_id, pid=pid, effect_kind='suppress',
            overall=result['overall'], verified=result['verified'],
            adjudicator=result['adjudicator'], note=result['note'],
            items=[dict(item) for item in result['items']],
            at_s=round(t, 2)))
        self.emit('counter_attack', post_id=post_id, pid=pid,
                  bearing_deg=round(bearing, 1), range_m=round(range_m, 1))
        self._log(t, 'counter_attack', post_id=post_id, pid=pid,
                  overall=result['overall'])
        self.emit('effect_adjudicated', effect_kind='suppress',
                  overall=result['overall'], verified=result['verified'],
                  adjudicator=result['adjudicator'], note=result['note'],
                  items=[dict(item) for item in result['items']],
                  post_id=post_id, target_id=ref['target_id'])
        if result['overall'] == 'succeeded':
            self.counts['repelled'] += 1
            self.emit('attack_repelled', post_id=post_id, pid=pid,
                      verified=False, adjudicator=result['adjudicator'],
                      note=result['note'])
            self._log(t, 'attack_repelled', post_id=post_id)
        else:
            self.emit('attack_unresolved', post_id=post_id,
                      overall=result['overall'], verified=False)
            self._log(t, 'attack_unresolved', post_id=post_id,
                      overall=result['overall'])
            self._suppress_post(post_id, t)

    def _suppress_post(self, post_id, t=None):
        """压制状态：同一阵位只记一条 ``post_suppressed``（恢复后才重新记）。"""
        if post_id in self.suppressed:
            return
        self.suppressed.add(post_id)
        self.emit('post_suppressed', post_id=post_id)
        self._log(self.t if t is None else t, 'post_suppressed',
                  post_id=post_id)

    # ---------------- 轮换/接替 ----------------
    def _step_handover(self, poses, t):
        handover = self.handover
        if not handover:
            return
        incoming = handover['incoming']
        post_id = handover['post_id']
        if not self._alive(incoming):
            self.emit('handover_aborted', post_id=post_id, incoming=incoming,
                      reason='接替者失联')
            self._log(t, 'handover_aborted', post_id=post_id)
            self.handover = None
            return
        if distance(poses[incoming], handover['approach_point']) <= max(
                self.arrive_tol, 0.8):
            self._complete_handover(t)
            return
        if t - handover['started_t'] > float(self.params['handover_timeout_s']):
            self.emit('handover_timeout', post_id=post_id, incoming=incoming,
                      elapsed_s=round(t - handover['started_t'], 1))
            self._log(t, 'handover_timeout', post_id=post_id)
            self.handover = None

    def _complete_handover(self, t):
        handover = self.handover
        post_id = handover['post_id']
        incoming = handover['incoming']
        outgoing = self.post_owner.get(post_id)
        self.post_owner[post_id] = incoming
        self.post_of_pid[incoming] = post_id
        self.role[incoming] = 'post:%s' % post_id
        if self._alive(outgoing) and outgoing != incoming:
            self.role[outgoing] = 'reserve:standby'
            self.post_of_pid.pop(outgoing, None)
        arrival = round(t - handover['started_t'], 2)
        compliant = not handover.get('early_release', False)
        self.handover_list.append(dict(
            post_id=post_id, incoming=incoming, outgoing=outgoing,
            started_s=handover['started_t'], completed_s=round(t, 2),
            arrival_s=arrival, arrival_before_departure=compliant))
        self.emit('handover_complete', post_id=post_id, incoming=incoming,
                  outgoing=outgoing, arrival_s=arrival,
                  arrival_before_departure=compliant)
        self._log(t, 'handover_complete', post_id=post_id, incoming=incoming,
                  outgoing=outgoing, arrival_s=arrival)
        self.relief_done += 1
        self.relief_cursor += 1
        self.handover_hold_targets[incoming] = dict(
            point=list(handover['approach_point']),
            until=t + 4.0)
        self.handover = None
        self.set_phase('坚守在位')

    def _step_relief_schedule(self, t):
        p = self.params
        interval = float(p['relief_interval_s'] or 0.0)
        cycles = int(p['relief_cycles'] or 0)
        if interval <= 0 or cycles <= 0:
            return
        if self.control_established_at is None or self.handover \
                or self.reinforce or self.relief_done >= cycles:
            return
        if self.withdraw_started_at is not None or self.control_lost_at is not None:
            return
        due = self.control_established_at + interval * (self.relief_done + 1)
        if t < due:
            return
        incoming = self._reserve_pid()
        if incoming is None:
            self.relief_skipped += 1
            self.emit('relief_skipped', reason='无可用预备队',
                      plan_t=round(due, 1))
            self._log(t, 'relief_skipped', reason='无可用预备队')
            self.relief_done += 1
            return
        post_id = self.post_ids[self.relief_cursor % len(self.post_ids)]
        outgoing = self.post_owner.get(post_id)
        if not self._alive(outgoing):
            self.relief_cursor += 1
            return
        self.handover = dict(
            incoming=incoming, outgoing=outgoing, post_id=post_id,
            started_t=round(t, 2),
            approach_point=self._handover_approach_point(post_id, incoming))
        # 接替者到位才撤：先让出接替者赶路，原占位者继续在岗。
        early = not self.swap_requires_arrival
        if early:
            self.handover['early_release'] = True
            self.post_owner[post_id] = None
            self.post_of_pid.pop(outgoing, None)
            self.role[outgoing] = 'reserve:standby'
        self.emit('handover_start', post_id=post_id, incoming=incoming,
                  outgoing=outgoing, swap_requires_arrival=self.swap_requires_arrival,
                  plan_t=round(due, 1))
        self._log(t, 'handover_start', post_id=post_id, incoming=incoming,
                  outgoing=outgoing)
        self.set_phase('接替')

    # ---------------- 增援 ----------------
    def _trigger_reinforce(self, post_id, poses, t, reason):
        if self.reinforce is not None or post_id is None:
            return
        policy = dict(self.params.get('reinforce') or {})
        arrive_within = float(policy.get('arrive_within_s')
                              or self.params['reinforce_arrive_within_s'])
        pid = self._pick_reinforce_unit(post_id, poses)
        if pid is None:
            self.emit('reinforce_unavailable', post_id=post_id, reason=reason)
            self._log(t, 'reinforce_unavailable', post_id=post_id)
            return
        self.reinforce = dict(pid=pid, post_id=post_id, reason=reason,
                              started_t=round(t, 2),
                              arrive_within=arrive_within,
                              approach_point=self._handover_approach_point(
                                  post_id, pid),
                              timeout_logged=False)
        self.emit('reinforce_triggered', post_id=post_id, pid=pid,
                  reason=reason, arrive_within_s=arrive_within)
        self._log(t, 'reinforce_triggered', post_id=post_id, pid=pid,
                  reason=reason)
        self.set_phase('增援')

    def _pick_reinforce_unit(self, post_id, poses):
        """选增援台：预备队优先，其次离该阵位最近的可用平台。"""
        candidates = []
        for pid in self.pids:
            if not self._alive(pid):
                continue
            # The air watch seat cannot replace a ground post.  Keeping it out
            # also prevents a doomed cross-layer assignment when the reserve is
            # temporarily unavailable.
            if self._role_kind(pid) == 'air':
                continue
            if self.post_of_pid.get(pid) == post_id:
                continue
            if self.handover and pid == self.handover.get('incoming'):
                continue
            candidates.append(pid)
        if not candidates:
            return None
        reserve = [pid for pid in candidates
                   if self._role_kind(pid) == 'reserve']
        pool = reserve or candidates
        return min(pool, key=lambda pid: distance(poses[pid],
                                                  self.post_point[post_id]))

    def _step_reinforce(self, poses, t):
        pending = self.reinforce
        if not pending:
            return
        pid = pending['pid']
        post_id = pending['post_id']
        if not self._alive(pid):
            self.emit('reinforce_aborted', post_id=post_id, pid=pid)
            self._log(t, 'reinforce_aborted', post_id=post_id, pid=pid)
            self.reinforce = None
            return
        if distance(poses[pid], pending['approach_point']) <= max(
                self.arrive_tol, 0.8):
            arrival = round(t - pending['started_t'], 2)
            on_time = arrival <= pending['arrive_within']
            previous = self.post_owner.get(post_id)
            self.post_owner[post_id] = pid
            self.post_of_pid[pid] = post_id
            self.role[pid] = 'post:%s' % post_id
            if self._alive(previous) and previous != pid:
                self.role[previous] = 'reserve:standby'
                self.post_of_pid.pop(previous, None)
            self.handover_hold_targets[pid] = dict(
                point=list(pending['approach_point']),
                until=t + 4.0)
            self.reinforce_list.append(dict(
                post_id=post_id, pid=pid, reason=pending['reason'],
                triggered_s=pending['started_t'], arrived_s=round(t, 2),
                arrival_s=arrival, on_time=on_time))
            self.emit('reinforce_arrived', post_id=post_id, pid=pid,
                      arrival_s=arrival, on_time=on_time,
                      arrive_within_s=pending['arrive_within'])
            self._log(t, 'reinforce_arrived', post_id=post_id, pid=pid,
                      arrival_s=arrival, on_time=on_time)
            if not on_time:
                self.emit('reinforce_timeout', post_id=post_id, pid=pid,
                          arrival_s=arrival,
                          arrive_within_s=pending['arrive_within'])
                self._log(t, 'reinforce_timeout', post_id=post_id, pid=pid)
            self.reinforce = None
            if post_id in self.suppressed:
                self.suppressed.discard(post_id)
                self.emit('post_restored', post_id=post_id)
                self._log(t, 'post_restored', post_id=post_id)
            self.set_phase('坚守在位')
            return
        if (t - pending['started_t'] > pending['arrive_within']
                and not pending['timeout_logged']):
            pending['timeout_logged'] = True
            self.emit('reinforce_timeout', post_id=post_id, pid=pid,
                      elapsed_s=round(t - pending['started_t'], 1),
                      arrive_within_s=pending['arrive_within'])
            self._log(t, 'reinforce_timeout', post_id=post_id, pid=pid)

    # ---------------- 撤离与结算 ----------------
    def _step_end(self, poses, t):
        if self.withdraw_started_at is not None:
            alive = [pid for pid in self.pids if pid not in self.lost_pids]
            # 对空威胁区可能覆盖撤离终点。固定翼会安全投影到区外，
            # 到点判定也必须认投影点，否则飞机到边界后只能持续盘旋，
            # 最后被误判为撤离超时。
            def arrived_at(pid):
                target = self.effective_target(pid, self._withdraw_point(pid))
                if distance(poses[pid], target) <= self.arrive_tol:
                    return True
                # Fixed-wing platforms cannot hold an exact point.  Once the
                # runner has established a withdrawal orbit around the target,
                # the station is occupied even though the pose stays on the
                # circle and is intentionally outside arrive_tol.
                if pid in getattr(self, 'air_pids', []):
                    holds = getattr(self, 'station_holds', None)
                    return bool(holds and holds(pid, target))
                return False

            arrived = all(arrived_at(pid) for pid in alive)
            if not alive or arrived:
                self.emit('withdrawn',
                          elapsed_s=round(t - self.withdraw_started_at, 2),
                          target=[round(v, 2) for v in self.withdraw_target],
                          reason=self.withdraw_reason)
                self._log(t, 'withdrawn', reason=self.withdraw_reason)
                self._finalize(t, 'withdrawn')
            elif t > self.withdraw_deadline or t >= self.params.get('task_limit_s', math.inf):
                self.withdraw_timed_out = True
                self.emit('withdraw_timeout',
                          elapsed_s=round(t - self.withdraw_started_at, 2),
                          deadline_s=round(self.withdraw_deadline
                                           - self.withdraw_started_at, 1))
                self._log(t, 'withdraw_timeout')
                self._finalize(t, 'withdraw_timeout')
            return
        if t >= self.params.get('task_limit_s', math.inf):
            self._finalize(t, 'task_window_end', timeout=True)
            return
        if self.control_lost_at is not None:
            self._begin_withdraw(t, 'control_lost')
            return
        if (self.control_established_at is not None
                and t - self.control_established_at
                >= float(self.params['duration_s'])):
            self._begin_withdraw(t, 'hold_period_end')
            return
        if t > float(self.params['max_steps']):
            self._finalize(t, 'timeout', timeout=True)

    def _begin_withdraw(self, t, reason):
        p = self.params
        # 撤离优先于接替：在途接替直接中止并留痕，不能让它拖到超时，
        # 否则时间线上会出现"已撤离、接替却超时"这种自相矛盾的记录。
        if self.handover:
            self.emit('handover_aborted', post_id=self.handover['post_id'],
                      incoming=self.handover['incoming'],
                      outgoing=self.handover.get('outgoing'),
                      reason='撤离开始')
            self._log(t, 'handover_aborted', post_id=self.handover['post_id'],
                      reason='撤离开始')
            self.handover = None
        allowed = bool(p['withdraw_allowed'])
        if not allowed:
            self._finalize(t, 'control_lost' if reason == 'control_lost'
                           else 'hold_period_end')
            return
        route = p.get('withdraw_route') or []
        target = route[-1] if route else (p.get('assembly_point')
                                          or self.key_point)
        deadline = float(p['withdraw_deadline_s'] or 30.0)
        self.withdraw_target = [float(target[0]), float(target[1])]
        self.withdraw_points = {}
        self.withdraw_started_at = round(t, 2)
        self.withdraw_deadline = t + deadline
        self.withdraw_reason = reason
        self.set_phase('撤离')
        self.emit('withdraw_started', reason=reason,
                  target=[round(v, 2) for v in self.withdraw_target],
                  deadline_s=deadline, allowed=True)
        self._log(t, 'withdraw_started', reason=reason)

    def _targets_for(self):
        targets = {}
        for pid in self.pids:
            if pid in self.lost_pids:
                continue
            if self.withdraw_started_at is not None:
                targets[pid] = self._withdraw_point(pid)
                continue
            settle = self.handover_hold_targets.get(pid)
            if settle and self.t < settle['until']:
                targets[pid] = list(settle['point'])
                continue
            if settle:
                self.handover_hold_targets.pop(pid, None)
            if self.handover and pid == self.handover['incoming']:
                targets[pid] = list(self.handover['approach_point'])
                continue
            if self.handover and pid == self.handover['outgoing'] \
                    and not self.handover.get('early_release'):
                # 接替者未到位前不得撤：原占位者仍守本阵位。
                targets[pid] = list(self.post_point[self.handover['post_id']])
                continue
            if self.reinforce and pid == self.reinforce['pid']:
                targets[pid] = list(self.reinforce['approach_point'])
                continue
            if pid in getattr(self, 'air_pids', []):
                # 空中观察席的盘旋由运动层的 AirLoiter 直接执行。这里只给
                # 稳定的盘旋中心；若每拍下发圆周上的瞬态点，固定翼会被当成
                # 追赶动态航点反复重规划，航迹会叠成多组不规则大圈。
                targets[pid] = list(self.key_point)
                continue
            # 只占位才游走：预备队/支援/中继在各自站位待机，不到处走。
            walk = self._post_target(pid, self.t) if self.post_of_pid.get(pid) \
                else None
            targets[pid] = walk if walk is not None else self._station_of(pid)
        return targets

    # ---------------- 结算 ----------------
    def _finalize(self, t, reason, timeout=False):
        if self.done:
            return
        if self.handover:
            self.handover = None
        self.control_released_at = round(t, 2)
        for row in self._open_intervals.values():
            row['leave_s'] = round(t, 2)
            row['duration_s'] = round(t - row['enter_s'], 2)
        self._open_intervals = {}
        hold_span = max(self.hold_elapsed, 1e-6)
        metrics = dict(
            key_point=[round(v, 2) for v in self.key_point],
            control_established_at_s=self.control_established_at,
            control_released_at_s=self.control_released_at,
            control_lost_at_s=self.control_lost_at,
            hold_span_s=round(self.hold_elapsed, 1),
            control_hold_ratio=round(self.control_time / hold_span, 4),
            control_time_s=round(self.control_time, 1),
            control_interruption_s=round(self.interrupt_time, 1),
            observation_coverage_mean=round(
                self.coverage_sum / max(self.coverage_t, 1e-9), 4),
            observation_gap_max_s=round(self.gap_max, 1),
            observation_gap_total_s=round(self.gap_total, 1),
            observation_gaps=[dict(item) for item in self.gaps],
            # 全向覆盖：按各阵位圆形探测圈对要点一周的覆盖统计，不是按扇区。
            coverage_gap_bearings=list(getattr(self, '_worst_gaps', [])),
            coverage_gap_count=len(getattr(self, '_worst_gaps', [])),
            coverage_min_instant=round(getattr(self, '_min_coverage', 1.0), 4),
            air_units=len(getattr(self, 'air_pids', [])),
            air_altitude_m=getattr(self, 'air_altitude_m', None),
            air_watch_s=round(self.air_watch_s, 1),
            air_watch_ratio=round(min(1.0, self.air_watch_s
                                      / max(hold_span, 1e-6)), 4),
            min_on_post=self.min_on_post,
            hold_criteria=self.criteria,
            hold_criteria_label=HL_CRITERIA_LABELS[self.criteria],
            patrol_enabled=self.patrol_enabled,
            patrol_radius_m=self.patrol_radius,
            patrol_speed_mps=(self.patrol_speed if self.patrol_enabled else None),
            relief_count=len(self.handover_list),
            relief_skipped=self.relief_skipped,
            handovers=[dict(item) for item in self.handover_list],
            reinforcement_count=len(self.reinforce_list),
            reinforcements=[dict(item) for item in self.reinforce_list],
            enemy_attacks=self.counts['attacks'],
            enemy_breaches=self.counts['breaches'],
            defended=self.counts['defended'],
            repelled=self.counts['repelled'],
            counter_attacks=self.counts['counter_attacks'],
            counter_attack_denied=self.counts['denied'],
            our_losses=len(self.lost_pids),
            withdrawals=(1 if self.withdraw_started_at is not None else 0),
            withdraw_timed_out=self.withdraw_timed_out,
            positions=[self._position_snapshot(item) for item in self.positions],
            effects=[dict(item) for item in self.effects],
            timeline=[dict(row) for row in self.timeline],
            scope=HL_SCOPE_NOTE,
        )
        result = self._verdict(metrics, timeout=timeout, reason=reason)
        metrics['verdict'] = result
        self.metrics.update(metrics)
        self.verdict = result
        self._log(t, 'hold_result', verdict=result['verdict'],
                  reason=result['reason'])
        summary = {k: v for k, v in metrics.items()
                   if k not in ('positions', 'timeline', 'effects')}
        self.emit('hold_result', verdict=result['verdict'], settle_reason=result['settle_reason'],
                  reason=result['reason'], items=result['items'],
                  metrics=summary, scope=HL_SCOPE_NOTE,
                  positions=[self._position_snapshot(item)
                             for item in self.positions],
                  handovers=[dict(item) for item in self.handover_list],
                  reinforcements=[dict(item) for item in self.reinforce_list],
                  effects=[dict(item) for item in self.effects],
                  timeline=[dict(row) for row in self.timeline])
        self._finish('hold_timeout' if timeout else 'hold_done')

    def _position_snapshot(self, position):
        post_id = position['id']
        rows = [row for row in self.occupancy if row['post_id'] == post_id]
        occupied = sum((row['duration_s'] or 0.0) for row in rows)
        span = max(1e-6, self.hold_elapsed or self.t or 1.0)
        return dict(id=post_id,
                    point=[round(v, 2) for v in position['point']],
                    facing_deg=round(position['facing_deg'], 1),
                    snap=position['snap'],
                    min_units=position['min_units'],
                    occupied_s=round(occupied, 1),
                    occupancy_ratio=round(min(1.0, occupied / span), 4),
                    occupants=[dict(row) for row in rows])

    def _verdict(self, metrics, timeout=False, reason=''):
        p = self.params
        items = []

        def item(item_id, label, value, target, ok, required=True, note=None):
            return dict(id=item_id, label=label, value=value, target=target,
                        ok=bool(ok), required=required, note=note)

        established = self.control_established_at is not None
        ratio_need = float(p['min_hold_ratio'])
        items.append(item('control_hold_ratio', '控制保持率（控制在位时间/坚守时段）',
                          metrics['control_hold_ratio'], ratio_need,
                          metrics['control_hold_ratio'] >= ratio_need,
                          required=(self.criteria == 'quantity')))
        items.append(item('control_interruption_s', '控制中断时间(s)',
                          metrics['control_interruption_s'],
                          float(p['max_control_interruption_s']),
                          metrics['control_interruption_s']
                          <= float(p['max_control_interruption_s'])))
        gap_need = float(p['observation_gap_max_s'])
        items.append(item('observation_gap_max_s', '最长观察中断(s)',
                          metrics['observation_gap_max_s'], gap_need,
                          metrics['observation_gap_max_s'] <= gap_need,
                          required=(self.criteria == 'coverage')))
        # 要点全向覆盖：按阵位圆形探测圈对要点一周的覆盖，不按扇区。任务给了
        # min_key_point_coverage 才作为必需判据（旧样例不受影响）。
        coverage_need = p.get('min_key_point_coverage')
        if coverage_need is not None or self.criteria == 'coverage':
            need = float(coverage_need if coverage_need is not None else 0.95)
            items.append(item(
                'key_point_coverage', '要点全向覆盖（按阵位探测圈）',
                metrics.get('observation_coverage_mean', 0.0), need,
                metrics.get('observation_coverage_mean', 0.0) >= need,
                required=True,
                note=('未覆盖方位 %d 个（°）：%s'
                      % (metrics.get('coverage_gap_count', 0),
                         metrics.get('coverage_gap_bearings', [])[:6]))))
        if metrics.get('air_units'):
            need = float(p.get('min_air_watch_ratio') or 0.9)
            items.append(item(
                'air_watch', '空中观察在位率（防空警戒席）',
                metrics.get('air_watch_ratio', 0.0), need,
                metrics.get('air_watch_ratio', 0.0) >= need,
                required=True,
                note='平均高度 %s m' % (metrics.get('air_altitude_m'),)))
        if metrics['relief_count'] or metrics['relief_skipped']:
            bad = [row for row in self.handover_list
                   if not row.get('arrival_before_departure')]
            items.append(item(
                'relief_compliance', '接替合规（到位才撤）',
                len(self.handover_list) - len(bad), len(self.handover_list),
                not bad and not self.relief_skipped,
                note=('未到位的接替 %d 次；无预备队跳过 %d 次'
                      % (len(bad), self.relief_skipped))))
        if metrics['reinforcement_count']:
            late = [row for row in self.reinforce_list if not row.get('on_time')]
            items.append(item(
                'reinforce_arrival', '增援到达及时',
                len(self.reinforce_list) - len(late), len(self.reinforce_list),
                not late,
                note='超时 %d 次' % len(late)))
        items.append(item('enemy_breaches', '敌方突破阵位次数',
                          metrics['enemy_breaches'], 0,
                          metrics['enemy_breaches'] == 0))
        if self.withdraw_started_at is not None:
            items.append(item('withdraw_compliance', '撤离按时完成',
                              (0 if self.withdraw_timed_out else 1), 1,
                              not self.withdraw_timed_out))
        items.append(item('our_losses', '我方损失台数（代价指标，非失败必要条件）',
                          metrics['our_losses'], None, True, required=False))
        items.append(item('effect_verified', '效果类结论待外部裁决',
                          'pending', 'verified', False, required=False,
                          note='桩判定·未验证：反击/压制不作战果，只作过程证据'))
        failed = [row for row in items if row['required'] and not row['ok']]
        if self.control_lost_at is not None:
            verdict = 'failed'
            verdict_reason = ('控制权丧失：有效在位数量低于下限持续 %.1f s'
                              '（被追撤离）' % (self.under_s,))
        elif reason == 'task_window_end':
            verdict = 'failed'
            verdict_reason = '任务时间窗已结束，坚守流程未完成'
        elif not established:
            verdict = 'pending'
            verdict_reason = ('坚守时段内未建立控制（未达到 min_on_post=%d）：'
                              '只支持"机动到位"结论' % self.min_on_post)
        elif self.withdraw_timed_out:
            verdict = 'failed'
            verdict_reason = '撤离超时：未在时限内到达撤离位置'
        elif failed:
            verdict = 'failed'
            verdict_reason = '；'.join(
                '%s=%s（要求 %s）' % (row['label'], row['value'], row['target'])
                for row in failed)
        elif not self.counts['attacks']:
            verdict = 'pending'
            verdict_reason = ('本次未出现敌方进攻事件：只支持"控制维持"结论，'
                              '不证明击退/增援能力')
        else:
            verdict = 'succeeded'
            verdict_reason = (
                '必需判据均有过程证据满足（坚守 %s s，在位 %d，判定口径%s，'
                '敌方进攻 %d 次、突破 %d 次）'
                % (int(metrics['hold_span_s']), self.min_on_post,
                   HL_CRITERIA_LABELS[self.criteria], self.counts['attacks'],
                   self.counts['breaches']))
        return dict(verdict=verdict, reason=verdict_reason, items=items,
                    criteria=self.criteria, settle_reason=reason,
                    timeout=timeout,
                    evidence='本地行为状态机 + 4.1 输入仿真的过程记录',
                    scope=HL_SCOPE_NOTE,
                    effects_verified=False)

    # ---------------- 展示 ----------------
    def progress_frac(self):
        if self.done:
            return 1.0
        if self.control_established_at is None:
            return 0.1 * min(1.0, self.t / 30.0)
        span = max(float(self.params['duration_s']), 1.0)
        elapsed = self.t - self.control_established_at
        base = min(1.0, elapsed / span)
        return min(0.98, 0.1 + 0.85 * base)

    def debug(self):
        return dict(
            roles=dict(self.role),
            post_owner={key: value for key, value in self.post_owner.items()},
            on_post={pid: bool(v) for pid, v in self.on_post.items()},
            manned=list(self.manned_posts()),
            coverage=round(self._last_coverage, 3),
            coverage_gaps=list(getattr(self, '_last_gaps', [])),
            air=list(getattr(self, 'air_pids', [])),
            handover=(dict(self.handover) if self.handover else None),
            reinforce=(dict(self.reinforce) if self.reinforce else None),
            suppressed=sorted(self.suppressed),
            counts=dict(self.counts))


# ------------------------------------------------------------------
# 5b. 要点坚守（历史小场景）：在位/待命轮换，接替者到位才撤
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

    两类任务各有新旧两种几何，按输入是否带结构参数分派，旧样例不被改写：
      * 区域封控：历史小场景"作业点外一圈"（BlockadeBehavior）与 1028 的
        真实封控边界（ContainmentBehavior，仅当输入给了 ``area``）；
      * 要点坚守：历史两点轮换（HoldBehavior）与 1028 的要点阵位
        （KeepBehavior，仅当输入给了 ``positions``）。
    """
    merged = dict(job.get('_behavior') or {})
    merged.update(params or {})
    if job.get('type') == 'recon' and merged.get('search_starts'):
        return AreaReconBehavior(job, nav, pids, merged)
    if job.get('type') == 'blockade' and merged.get('area'):
        return ContainmentBehavior(job, nav, pids, merged)
    if job.get('type') == 'hold' and merged.get('positions'):
        return KeepBehavior(job, nav, pids, merged)
    cls = BEHAVIORS.get(job.get('type'))
    if cls is None:
        return Behavior(job, nav, pids, merged)
    return cls(job, nav, pids, merged)
