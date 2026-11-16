# -*- coding: utf-8 -*-
"""
motion.py —— 目标点 → Twist 的闭环运动控制层（自 planning/bridge.py 移植）

这一层补的是「规划层与下游之间缺失的一段」：下游只认速度级指令
（geometry_msgs/msg/Twist），没有"到达目标点"接口；规划层出的却是
任务级指令（"去 T03 干活"）。中间这段"把目标点翻译成每拍发什么 Twist"
必须由我们补，本文件就是它。

移植自旧版 planning/bridge.py 的 GoalController / Twist / Pose / DriveGains，
只动接口与单位口径，控制逻辑不变：

  * 闭环：每拍读一次位姿、重算一次指令，直到进入容差。
    为什么必须闭环：下游速度按仿真时间生效、Seconds 按墙钟计算，
    RTF<1 时"速度×秒数"推不出位移，开环定时发令必然到不准。
  * 先转后走：下游是差速驱动（无人车/坦克）与简化偏航（飞机），
    都不能横移（linear.y 恒为 0），不先对准就直走会绕弯。
  * 只有飞机（PLANE/WING）支持 linear.z（升降），地面平台 z 恒 0。
  * 到位返回全零 Twist；调用方仍须显式发送停止（下游无超时自动停车）。

单位口径（与 fleet.py 一致，别混）：
  * 本层纯几何，坐标无量纲、速度=场景单位/步。
  * 真实对接时，把本层的输出按 fleet.M_PER_SCENE_UNIT / SEC_PER_STEP
    换算成 m/s、rad/s 后发布到 /container_00/robot_XXX/cmd_vel 即可；
    控制逻辑本身不随单位变化。
"""
import math

MOTION_MODEL = 'marl-browser-20261113-dynamic-v1'
from dataclasses import dataclass


# ------------------------------------------------------------------
# Twist：一条速度级指令（等价 geometry_msgs/msg/Twist 的非零字段）
# ------------------------------------------------------------------
@dataclass
class Twist:
    linear_x: float = 0.0     # 前进/后退（场景单位/步）
    linear_z: float = 0.0     # 上升/下降，仅 PLANE/WING 可用
    angular_z: float = 0.0    # 左转/右转（rad/步）

    def to_dict(self):
        """给 ROS 2 发布用的字典（等价 Twist 字段，linear.y 与 angular.x/y 恒 0）。"""
        return {"linear": {"x": self.linear_x, "y": 0.0, "z": self.linear_z},
                "angular": {"x": 0.0, "y": 0.0, "z": self.angular_z}}

    def is_stop(self):
        return (self.linear_x == 0.0 and self.linear_z == 0.0
                and self.angular_z == 0.0)

    @staticmethod
    def stop():
        """全零速度。下游没有超时停车，停止只能靠显式发这个。"""
        return Twist()


# ------------------------------------------------------------------
# Pose：位姿（无量纲；yaw 俯视逆时针为正，与 angular_z 同号）
# ------------------------------------------------------------------
@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


def wrap_pi(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class AirLoiter:
    """Keep an airborne platform moving on a circle around a station.

    ``center`` is the observed/commanded point while the pose remains the
    aircraft's actual position. Radial entry and exit are bounded so changing
    between tracking and orbit does not create a position jump.
    """

    def __init__(self, center, speed, radius=None, max_yaw_rate=0.35,
                 max_yaw_accel=0.45, safe_transition=None):
        self.max_yaw_rate = float(max_yaw_rate)
        self.max_yaw_accel = max(0.01, float(max_yaw_accel))
        self.center = (float(center[0]), float(center[1]))
        self.speed = max(float(speed), 0.01)
        self.radius = (max(0.5, float(radius)) if radius is not None
                       else max(2.0, self.speed / 0.35))
        self.turn_rate = 0.0
        self.direction = None
        # Optional callback used by the runtime to reject a one-tick segment
        # that would cross an applicable threat/no-go footprint.  Safety is
        # checked on the swept segment rather than only on its endpoint.
        self.safe_transition = safe_transition

    def matches(self, target, tolerance=0.35):
        return math.hypot(target[0] - self.center[0],
                          target[1] - self.center[1]) <= tolerance

    def step(self, pose, dt, radius=None):
        dx, dy = pose.x - self.center[0], pose.y - self.center[1]
        old_radius = math.hypot(dx, dy)
        angle = math.atan2(dy, dx) if old_radius > 1e-9 else pose.yaw
        desired = self.radius if radius is None else max(0.0, float(radius))
        radial = ((math.cos(angle), math.sin(angle))
                  if old_radius > 1e-9
                  else (math.cos(pose.yaw), math.sin(pose.yaw)))

        # A fixed-wing platform cannot follow a tiny circle at cruise speed.
        # Limit the orbit speed to one that the configured yaw rate can
        # actually fly.  Movement remains forward-only and is never a radial
        # teleport back to the circle.
        orbit_speed = min(
            self.speed,
            max(0.05, 0.95 * self.max_yaw_rate * max(desired, 0.5)))

        if self.direction is None:
            ccw_dot = (-math.cos(pose.yaw) * radial[1]
                       + math.sin(pose.yaw) * radial[0])
            self.direction = 1 if ccw_dot >= 0.0 else -1

        tangent = (-self.direction * radial[1],
                    self.direction * radial[0])
        radial_error = _clamp((desired - old_radius) / max(desired, 1.0),
                              -1.5, 1.5)
        vx = tangent[0] + radial_error * radial[0]
        vy = tangent[1] + radial_error * radial[1]
        desired_yaw = math.atan2(vy, vx)

        yaw_error = wrap_pi(desired_yaw - pose.yaw)
        # Feed forward the turn needed for the current orbit radius, then
        # correct the residual heading error.  Without the feed-forward term
        # a fixed-wing platform settles on a wider circle and can appear to
        # "drift" away from the commanded station.
        feed_forward = (
            self.direction * orbit_speed
            / max(old_radius, desired * 0.75, 0.1))
        desired_turn_rate = _clamp(
            feed_forward + 2.2 * yaw_error,
            -self.max_yaw_rate, self.max_yaw_rate)
        self.turn_rate += _clamp(
            desired_turn_rate - self.turn_rate,
            -self.max_yaw_accel * dt,
            self.max_yaw_accel * dt)
        self.turn_rate = _clamp(
            self.turn_rate, -self.max_yaw_rate, self.max_yaw_rate)
        nominal_rate = self.turn_rate
        acceleration_limit = self.max_yaw_accel * dt
        rate_options = [
            nominal_rate,
            min(self.max_yaw_rate, nominal_rate + acceleration_limit),
            max(-self.max_yaw_rate, nominal_rate - acceleration_limit),
        ]
        # If the nominal forward arc intersects a threat boundary, keep the
        # configured turn-rate limits but choose the safest feasible steering
        # direction and distance within this control tick.  When every forward
        # candidate is blocked, remain at the current position for one tick
        # while continuing to turn; the next tick can then leave along a safe
        # tangent instead of jumping or tunnelling through the boundary.
        chosen = None
        for rate in rate_options:
            candidate_yaw = wrap_pi(pose.yaw + rate * dt)
            for fraction in (1.0, 0.5, 0.25):
                candidate_moved = orbit_speed * dt * fraction
                candidate = (
                    pose.x + candidate_moved * math.cos(candidate_yaw),
                    pose.y + candidate_moved * math.sin(candidate_yaw),
                )
                if (self.safe_transition is None
                        or self.safe_transition((pose.x, pose.y), candidate)):
                    chosen = (rate, candidate_yaw, candidate, candidate_moved)
                    break
            if chosen is not None:
                break
        if chosen is None:
            self.turn_rate = nominal_rate
            yaw = wrap_pi(pose.yaw + self.turn_rate * dt)
            return Pose(pose.x, pose.y, pose.z, yaw), 0.0

        self.turn_rate, yaw, (x, y), moved = chosen
        return Pose(x, y, pose.z, yaw), moved


# ------------------------------------------------------------------
# 控制增益（我方暂定，须在仿真里标定，不直接当交付默认值）
# ------------------------------------------------------------------
@dataclass
class DriveGains:
    max_linear: float = 1.0     # 场景单位/步（下游示例：无人车 0.2、飞机 1.0）
    max_angular: float = 0.5    # rad/步
    k_linear: float = 0.8       # 距离 → 线速度
    k_angular: float = 1.5      # 航向误差 → 角速度
    tol_pos: float = 0.5        # 到位容差（场景单位）
    tol_yaw: float = 0.15       # 对准容差（约 8.6°）
    # 物理限幅：加速度/角加速度/横向加速度，单位分别为 单位/步²、rad/步²、
    # 单位/步²。默认值按 1 步 = 1 s、1 单位 = 1 m 取值。
    max_linear_accel: float = 0.8
    max_linear_decel: float = 1.0
    max_angular_accel: float = 1.4
    max_lateral_accel: float = 0.8


# ------------------------------------------------------------------
# 闭环控制器
# ------------------------------------------------------------------
class GoalController:
    """把"去某个点"变成"这一拍发什么 Twist"。纯计算，不依赖 ROS。"""

    def __init__(self, gains=None, can_climb=False):
        self.g = gains or DriveGains()
        self.can_climb = can_climb
        self._v = 0.0
        self._w = 0.0

    def arrived(self, pose, goal):
        dxy = math.hypot(goal.x - pose.x, goal.y - pose.y)
        dz = abs(goal.z - pose.z) if self.can_climb else 0.0
        return dxy <= self.g.tol_pos and dz <= self.g.tol_pos

    def update(self, pose, goal, dt=1.0):
        """一个控制周期：读位姿 → 出指令。到位返回全零。调用方仍须显式发停止。

        ``dt`` 是一个控制周期占多少个仿真步（默认 1）；角/线加速度按它换算
        每拍允许的变化量，所以相邻两拍不会从 0 直接跳到最大角速度。
        """
        if self.arrived(pose, goal):
            self._v = self._w = 0.0
            return Twist.stop()

        dx, dy = goal.x - pose.x, goal.y - pose.y
        dist = math.hypot(dx, dy)
        err = wrap_pi(math.atan2(dy, dx) - pose.yaw)

        dz = (goal.z - pose.z) if self.can_climb else 0.0
        vz = _clamp(self.g.k_linear * dz, -self.g.max_linear,
                    self.g.max_linear) if self.can_climb else 0.0

        # 航向没对准 → 只转不走（差速/简化偏航都不能横移）
        if abs(err) > self.g.tol_yaw:
            desired_v = 0.0
            desired_w = _clamp(self.g.k_angular * err,
                               -self.g.max_angular, self.g.max_angular)
        else:
            desired_v = _clamp(self.g.k_linear * dist, 0.0, self.g.max_linear)
            desired_w = _clamp(self.g.k_angular * err,
                               -self.g.max_angular, self.g.max_angular)
        # 协调转弯：有一定前向速度时，角速度受横向加速度限制。
        if desired_v > 0.05:
            cap = min(self.g.max_angular,
                      self.g.max_lateral_accel / desired_v)
            desired_w = _clamp(desired_w, -cap, cap)
        # 线速度/角速度按加速度限幅
        if desired_v >= self._v:
            v = min(desired_v, self._v + self.g.max_linear_accel * dt)
        else:
            v = max(desired_v, self._v - self.g.max_linear_decel * dt)
        if desired_w >= self._w:
            w = min(desired_w, self._w + self.g.max_angular_accel * dt)
        else:
            w = max(desired_w, self._w - self.g.max_angular_accel * dt)
        if v > 0.05:
            cap = min(self.g.max_angular,
                      self.g.max_lateral_accel / v)
            w = _clamp(w, -cap, cap)
        self._v, self._w = v, w
        return Twist(linear_x=v, linear_z=vz, angular_z=w)


# ------------------------------------------------------------------
# 发令纪律（下游说明第 7 节，写在代码里免得忘）
#   1. 同一机器人只安排一个持续发令源。
#   2. 没有命令超时自动停车；发布器退出≠停止，必须显式发全零。
#   3. 约 20 Hz 是发令频率，不代表位姿同步到 20 Hz。
#   4. 地面机器人收到零速后仍可能短暂减速，到位判定留余量。
# ------------------------------------------------------------------
CMD_PERIOD_S = 0.05           # 约 20 Hz 发令


def gains_for(platform):
    """按平台速度上限构造控制增益（无量纲，速度上限 = max_linear）。

    真实对接时应改用下游实测的最大线/角速度与标定增益；这里只是
    把规划侧的 speed（场景单位/步）作为线速度上限，让运动与规划
    的 travel 估算同源，避免"规划说 2 步到、运动却跑 20 拍"的错位。
    """
    spd = max(getattr(platform, "speed", 1.0), 1e-6)
    return DriveGains(max_linear=spd, max_angular=0.5,
                      k_linear=0.8, k_angular=1.5,
                      tol_pos=0.5, tol_yaw=0.15)


def estimate_arrival_steps(start, goal, max_linear=1.0, can_climb=False,
                           max_steps=200):
    """用闭环控制器预演，估算真实到达某点需要的规划步数。

    这是给规划器用的"运动时间同源估算"：planning 的 travel 若用
    ceil(距离/速度)，在真实运动（先转后走 + 加速减速）下会系统性
    低估到达时间，导致 deviation/timeout 误判。这里用与运动层
    完全相同的 GoalController 跑一遍，数出实际步数。

    start/goal 为 (x, y) 或 (x, y, z, yaw) 元组；返回步数（整数，
    至少 1）。超过 max_steps 仍不到达则返回 max_steps。
    """
    sx, sy = start[0], start[1]
    sz = start[2] if len(start) > 2 else 0.0
    syaw = start[3] if len(start) > 3 else 0.0
    gx, gy = goal[0], goal[1]
    gz = goal[2] if len(goal) > 2 else 0.0
    gyaw = goal[3] if len(goal) > 3 else 0.0

    gains = DriveGains(max_linear=max_linear)
    ctl = GoalController(gains, can_climb=can_climb)
    pose = Pose(sx, sy, sz, syaw)
    goal_pose = Pose(gx, gy, gz, gyaw)

    ticks_per_step = 20
    for step in range(1, max_steps + 1):
        for _ in range(ticks_per_step):
            tw = ctl.update(pose, goal_pose)
            if tw.is_stop():
                break
            dt = 1.0 / ticks_per_step
            pose.yaw += tw.angular_z * dt
            pose.x += tw.linear_x * math.cos(pose.yaw) * dt
            pose.y += tw.linear_x * math.sin(pose.yaw) * dt
            pose.z += tw.linear_z * dt
        if ctl.arrived(pose, goal_pose):
            return step
    return max_steps


if __name__ == "__main__":
    # 纯几何自测：不需要 ROS
    def run(tag, ctl, pose, goal, max_ticks):
        for i in range(max_ticks):
            tw = ctl.update(pose, goal)
            if tw.is_stop():
                print("%s：%d 拍到位，终点 (%.2f, %.2f, %.2f)"
                      % (tag, i, pose.x, pose.y, pose.z))
                return i, True
            pose.yaw += tw.angular_z * CMD_PERIOD_S
            pose.x += tw.linear_x * math.cos(pose.yaw) * CMD_PERIOD_S
            pose.y += tw.linear_x * math.sin(pose.yaw) * CMD_PERIOD_S
            pose.z += tw.linear_z * CMD_PERIOD_S
        print("%s：%d 拍仍未到位" % (tag, max_ticks))
        return max_ticks, False

    run("直行", GoalController(DriveGains(max_linear=0.2), False),
        Pose(0, 0, 0, 0.0), Pose(20, 0, 0, 0.0), 4000)
    run("转向", GoalController(DriveGains(max_linear=0.2, max_angular=0.5),
                               False),
        Pose(0, 0, 0, 0.0), Pose(0, 20, 0, 0.0), 4000)
    run("飞机带高度", GoalController(DriveGains(max_linear=1.0), True),
        Pose(0, 0, 0, 0.0), Pose(30, 0, 10, 0.0), 2000)
