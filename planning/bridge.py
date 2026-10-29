# -*- coding: utf-8 -*-
"""
bridge.py —— 下游机器人移动接口适配层

依据下游提供的《机器人移动话题说明》（GazeboUEBridge，50 台混合机器人）编写。

本层只做两件事：
  1. 描述下游接口（编号 / 话题 / 字段 / 单位 / 边界），做成配置而不是散在代码里
  2. 把"去某个坐标"翻译成"此刻该发什么 Twist"——**下游没有这一层**

> [!warning] **最关键的一条：下游没有"到达目标点"接口。**
> 说明第 7 节明确写道：当前没有"到达目标点""执行航线""自动避障"等任务话题或 Action，
> 增加这些能力需要额外导航/飞控模块，**将目标转成底层指令**。
> 也就是说：我们下发的是任务级指令（去 T03 干活），下游只接受速度级指令（Twist）。
> 中间这一层必须由我们补，本文件就是它。
>
> 而且说明第 4 节特别提示：**"速度按仿真时间生效，`Seconds` 按墙钟时间计算；
> RTF 低于 1 时，不能用'速度 × 实际发令秒数'推算实际位移。"**
> 这意味着**开环定时发指令根本到不准**，必须闭环读位姿。所以本层做成闭环控制器，
> 不是"发 N 秒就当到达"。

未联调声明：本文件**未在真机/仿真环境验证过**。几何与控制逻辑是纯 Python，
可在无 ROS 的环境自测（见文件末尾 `__main__`）。
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------
# 一、单位与坐标系（我方暂定——下游没给，必须问）
#
#   我们 planning/ 内部：无量纲"步"、100×100 无量纲场景坐标
#   下游 Gazebo      ：米、秒、Z 轴向上
#
# 这两个换算是**全部时间/距离计算的地基**，下游未给，先按 1:1 占位。
# 拿到真实值后只改这两个常量，本文件其余部分不用动。
# ------------------------------------------------------------------
M_PER_SCENE_UNIT = 1.0      # 【我方暂定】1 个场景单位 = 多少米
SEC_PER_STEP = 1.0          # 【我方暂定】1 个规划步 = 多少秒

# ------------------------------------------------------------------
# 二、50 台机器人的编成（下游给定，抄自说明第 1 节）
#
#   01–20  无人车 UGV      20 台
#   21–30  无人坦克 TANK   10 台
#   31–40  常规布局固定翼 PLANE  10 台
#   41–50  Zephyr 飞翼 WING      10 台
#
# 一律用 `/rover_XX/cmd_vel`（内部名称仍是 rover_ 前缀，为兼容旧接口），
# 编号不足两位补零。**每台一个话题，不是广播或通配符。**
# ------------------------------------------------------------------
FLEET_RANGES = [
    ("UGV",   1,  20),
    ("TANK", 21,  30),
    ("PLANE", 31, 40),
    ("WING", 41, 50),
]
FLEET_SIZE = 50

# 我们 planning/ 的四类平台 → 下游四类（**我方暂定**：下游没给传感器/载荷信息，
# 只能按"外形与运动方式"对应，不能按能力对应。真实对应须问下游）
PTYPE_TO_KIND = {
    "ugv":   "UGV",
    "tank":  "TANK",
    "uav_a": "PLANE",
    "uav_b": "WING",
}
KIND_TO_PTYPE = {v: k for k, v in PTYPE_TO_KIND.items()}

# 只有 31–50（两类飞机）支持 linear.z；无人车与坦克的 linear.z 必须保持 0
CLIMB_KINDS = {"PLANE", "WING"}


def topic_of(robot_no: int) -> str:
    """机器人编号 → cmd_vel 话题名。"""
    if not 1 <= robot_no <= FLEET_SIZE:
        raise ValueError("机器人编号应在 1–%d 之间：%r" % (FLEET_SIZE, robot_no))
    return "/rover_%02d/cmd_vel" % robot_no


def pose_topic_of(robot_no: int) -> str:
    """机器人编号 → 位姿话题名（Gazebo → ROS 2 → UE，只读）。"""
    if not 1 <= robot_no <= FLEET_SIZE:
        raise ValueError("机器人编号应在 1–%d 之间：%r" % (FLEET_SIZE, robot_no))
    return "/model/rover_%02d/pose" % robot_no


def build_roster() -> List[Dict]:
    """生成 50 台的编成表。字段与下游 `fleet-roster.json` 对齐。"""
    roster = []
    for kind, lo, hi in FLEET_RANGES:
        for no in range(lo, hi + 1):
            roster.append(dict(no=no, kind=kind, topic=topic_of(no),
                               pose_topic=pose_topic_of(no),
                               can_climb=(kind in CLIMB_KINDS)))
    return roster


def robot_no_from_pid(pid: str) -> Optional[int]:
    """我们的 `P00` 风格编号 → 下游 1–50 编号。

    映射规则【我方暂定】：`P<k>` → 下游第 `k+1` 号（即 P00→1 号、P14→15 号）。
    下游编成是固定的 50 台、类型按号段划分，所以**这个映射会改变平台类型**——
    不能只改名字，必须同时把 `PTYPE_TO_KIND` 对上，否则会出现
    "我们把 P00 当 ugv 规划，下游 1 号其实是 UGV"这类错位（此处恰好对上，
    但若我们自定义编成就不一定）。
    """
    if not pid or not pid[0] in "Pp":
        return None
    try:
        k = int(pid[1:])
    except ValueError:
        return None
    no = k + 1
    return no if 1 <= no <= FLEET_SIZE else None


# ------------------------------------------------------------------
# 三、Twist 指令
#
# 下游只认 `geometry_msgs/msg/Twist`。可用字段（说明第 3 节）：
#   linear.x   前进/后退        m/s    全部
#   angular.z  左转/右转        rad/s  全部
#   linear.z   上升/下降        m/s    **仅 31–50**
#   linear.y、angular.x、angular.y  恒为 0
#
# 约定（说明第 3 节，别套 UE 坐标）：
#   Gazebo Z 轴向上；angular.z > 0 为**俯视逆时针**，负值顺时针
#   linear.x > 0 向前，linear.z > 0 上升
#
# Twist 本身没有"持续几秒"或"目标坐标"字段——**持续时间由发令程序管理**，
# 而且**停止必须显式发全零**（说明第 7 节：无超时自动停车机制）。
# ------------------------------------------------------------------
@dataclass
class Twist:
    linear_x: float = 0.0
    linear_z: float = 0.0
    angular_z: float = 0.0

    def to_dict(self) -> Dict[str, Dict[str, float]]:
        """给 ROS 2 发布用的字典（等价于 geometry_msgs/msg/Twist 的字段）。"""
        return {"linear": {"x": self.linear_x, "y": 0.0, "z": self.linear_z},
                "angular": {"x": 0.0, "y": 0.0, "z": self.angular_z}}

    def is_stop(self) -> bool:
        return self.linear_x == 0.0 and self.linear_z == 0.0 and self.angular_z == 0.0

    @staticmethod
    def stop() -> "Twist":
        """全零速度。**下游没有超时停车，停止只能靠显式发这个。**"""
        return Twist()


@dataclass
class Pose:
    """位姿。x/y/z 单位米；yaw 弧度（俯视逆时针为正，与 angular.z 同号）。"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


def wrap_pi(a: float) -> float:
    """把角度归一化到 (-π, π]。"""
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


# ------------------------------------------------------------------
# 四、目标点 → Twist：闭环控制器
#
# 为什么闭环：说明第 4 节——速度按仿真时间生效、Seconds 按墙钟时间计，
# RTF<1 时"速度×秒数"推不出位移。开环定时必然到不准。
# 所以这里每个控制周期读一次位姿、重算一次指令，直到进入容差。
#
# 为什么"先转后走"：下游是差速驱动（无人车/坦克）与简化偏航（飞机），
# 都**不能横移**（linear.y 恒为 0）。不先对准目标方向就直接前进会绕弯。
# ------------------------------------------------------------------
@dataclass
class DriveGains:
    """控制增益（我方暂定，须在仿真里标定，不要当默认值直接交付）。"""
    max_linear: float = 1.0      # m/s，注意下游示例：无人车 0.2、飞机 1.0
    max_angular: float = 0.5     # rad/s
    k_linear: float = 0.8        # 距离 → 线速度
    k_angular: float = 1.5       # 航向误差 → 角速度
    tol_pos: float = 0.5         # m，到位容差
    tol_yaw: float = 0.15        # rad，对准容差（约 8.6°）


class GoalController:
    """把"去某个点"变成"这一拍发什么 Twist"。纯计算，不依赖 ROS。"""

    def __init__(self, gains: Optional[DriveGains] = None, can_climb: bool = False):
        self.g = gains or DriveGains()
        self.can_climb = can_climb

    def arrived(self, pose: Pose, goal: Pose) -> bool:
        dxy = math.hypot(goal.x - pose.x, goal.y - pose.y)
        dz = abs(goal.z - pose.z) if self.can_climb else 0.0
        return dxy <= self.g.tol_pos and dz <= self.g.tol_pos

    def update(self, pose: Pose, goal: Pose) -> Twist:
        """一个控制周期：读位姿 → 出指令。到位返回全零。**调用方仍须显式发送停止。**"""
        if self.arrived(pose, goal):
            return Twist.stop()

        dx, dy = goal.x - pose.x, goal.y - pose.y
        dist = math.hypot(dx, dy)
        err = wrap_pi(math.atan2(dy, dx) - pose.yaw)

        # 高度：只有飞机有，且独立于平面运动
        dz = (goal.z - pose.z) if self.can_climb else 0.0
        vz = _clamp(self.g.k_linear * dz, -self.g.max_linear, self.g.max_linear) \
            if self.can_climb else 0.0

        # 航向没对准 → 只转不走（差速/简化偏航都不能横移）
        if abs(err) > self.g.tol_yaw:
            return Twist(linear_x=0.0, linear_z=vz,
                         angular_z=_clamp(self.g.k_angular * err,
                                          -self.g.max_angular, self.g.max_angular))
        # 对准了 → 边走边微调
        return Twist(linear_x=_clamp(self.g.k_linear * dist, 0.0, self.g.max_linear),
                     linear_z=vz,
                     angular_z=_clamp(self.g.k_angular * err,
                                      -self.g.max_angular, self.g.max_angular))


# ------------------------------------------------------------------
# 五、发令纪律（说明第 7 节，写在代码里免得忘）
#
#   1. **同一机器人只安排一个持续发令源。** 另一程序持续发令时，
#      单次停止命令可能立刻被覆盖 → 我们的重规划必须走同一个发令源，
#      不能"新开一个发布器发停止"。
#   2. **没有命令超时自动停车。** 发布器退出 ≠ 停止；必须显式发全零。
#   3. 命令频率约 20 Hz（0.05 s 一次）是**发令频率**，不代表位姿同步到 20 Hz。
#   4. 地面机器人收到零速度后仍可能有短暂减速过程 → 到位判定要留余量。
# ------------------------------------------------------------------
CMD_PERIOD_S = 0.05        # 约 20 Hz 发令


def scene_to_m(v: float) -> float:
    """场景单位 → 米。"""
    return v * M_PER_SCENE_UNIT


def steps_to_s(n: float) -> float:
    """规划步 → 秒。**注意：这只是计划时长，不是墙钟时长**（RTF 相关）。"""
    return n * SEC_PER_STEP


def travel_steps_to_actual_note() -> str:
    return ("下游 RTF 不确定，'步→秒'换算只对计划有效；"
            "实际到达时间必须以位姿闭环判定，不能用 步数×SEC_PER_STEP 推算。")


# ------------------------------------------------------------------
# 自测：纯几何，不需要 ROS
# ------------------------------------------------------------------
if __name__ == "__main__":
    roster = build_roster()
    assert len(roster) == 50
    assert roster[0]["topic"] == "/rover_01/cmd_vel"
    assert roster[20]["topic"] == "/rover_21/cmd_vel"
    assert roster[30]["kind"] == "PLANE" and roster[30]["can_climb"]
    assert roster[40]["kind"] == "WING"
    assert robot_no_from_pid("P00") == 1 and robot_no_from_pid("P14") == 15

    def run(tag, ctl, pose, goal, max_ticks):
        """跑一遍闭环，返回 (拍数, 到位否)。位姿由 Twist 积分推进（替身动力学）。"""
        for i in range(max_ticks):
            tw = ctl.update(pose, goal)
            if tw.is_stop():
                print("%s：%d 拍到位（%.1f s），终点 (%.2f, %.2f, %.2f)"
                      % (tag, i, i * CMD_PERIOD_S, pose.x, pose.y, pose.z))
                return i, True
            pose.yaw += tw.angular_z * CMD_PERIOD_S
            pose.x += tw.linear_x * math.cos(pose.yaw) * CMD_PERIOD_S
            pose.y += tw.linear_x * math.sin(pose.yaw) * CMD_PERIOD_S
            pose.z += tw.linear_z * CMD_PERIOD_S
        print("%s：%d 拍仍未到位 —— 增益需标定" % (tag, max_ticks))
        return max_ticks, False

    # 无人车：朝 +x 起步，目标正东 20 m，无需转向
    run("无人车直行", GoalController(DriveGains(max_linear=0.2), False),
        Pose(0, 0, 0, 0.0), Pose(20, 0, 0, 0.0), 4000)

    # 转向用例：起点朝 +x，目标在正北 —— 必须先转 90°
    run("无人车转向", GoalController(DriveGains(max_linear=0.2, max_angular=0.5), False),
        Pose(0, 0, 0, 0.0), Pose(0, 20, 0, 0.0), 4000)

    # 飞机：带高度，线速度上限 1.0（下游示例用 1）
    run("飞机带高度", GoalController(DriveGains(max_linear=1.0), True),
        Pose(0, 0, 0, 0.0), Pose(30, 0, 10, 0.0), 2000)
