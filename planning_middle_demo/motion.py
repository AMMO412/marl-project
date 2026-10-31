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
    换算成 m/s、rad/s 后发布到 /container_00/robot_XXX 即可；
    控制逻辑本身不随单位变化。
"""
import math
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


# ------------------------------------------------------------------
# 闭环控制器
# ------------------------------------------------------------------
class GoalController:
    """把"去某个点"变成"这一拍发什么 Twist"。纯计算，不依赖 ROS。"""

    def __init__(self, gains=None, can_climb=False):
        self.g = gains or DriveGains()
        self.can_climb = can_climb

    def arrived(self, pose, goal):
        dxy = math.hypot(goal.x - pose.x, goal.y - pose.y)
        dz = abs(goal.z - pose.z) if self.can_climb else 0.0
        return dxy <= self.g.tol_pos and dz <= self.g.tol_pos

    def update(self, pose, goal):
        """一个控制周期：读位姿 → 出指令。到位返回全零。调用方仍须显式发停止。"""
        if self.arrived(pose, goal):
            return Twist.stop()

        dx, dy = goal.x - pose.x, goal.y - pose.y
        dist = math.hypot(dx, dy)
        err = wrap_pi(math.atan2(dy, dx) - pose.yaw)

        dz = (goal.z - pose.z) if self.can_climb else 0.0
        vz = _clamp(self.g.k_linear * dz, -self.g.max_linear,
                    self.g.max_linear) if self.can_climb else 0.0

        # 航向没对准 → 只转不走（差速/简化偏航都不能横移）
        if abs(err) > self.g.tol_yaw:
            return Twist(linear_x=0.0, linear_z=vz,
                         angular_z=_clamp(self.g.k_angular * err,
                                          -self.g.max_angular,
                                          self.g.max_angular))
        # 对准了 → 边走边微调
        return Twist(linear_x=_clamp(self.g.k_linear * dist, 0.0,
                                     self.g.max_linear),
                     linear_z=vz,
                     angular_z=_clamp(self.g.k_angular * err,
                                      -self.g.max_angular,
                                      self.g.max_angular))


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
