# -*- coding: utf-8 -*-
"""共享运动学限幅（规划、回放替身、4.2 指令生成共用）。

上游规划只给"去哪"，下游只认速度级 Twist。如果没有一层统一的物理上限，
路径求出来的折线会被直接翻译成"瞬时 0.8 rad/s 原地转 + 全速直行"，
回放里就会出现一秒内几十度的航向跳变。本模块把四类平台的线速度、角速度、
线/角加速度和横向加速度集中到一张表：

* 地面 UGV/TANK 允许低速原地转向，但角速度与角加速度都有上限；
* 空中 PLANE/WING 不允许原地转向，只能边飞边转，转弯半径由速度/角速度决定；
* 所有数值是演示用暂定值，真实指标到位只需改这一张表。

单位：米、秒、弧度。规划侧场景单位默认 1 单位 = 1 米（编成表 cell_size_m）。
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class KinematicLimits:
    kind: str
    max_speed: float
    max_accel: float          # m/s^2
    max_decel: float          # m/s^2，正值
    max_yaw_rate: float       # rad/s
    max_yaw_accel: float      # rad/s^2
    max_lateral_accel: float  # m/s^2，转弯时的横向加速度上限
    min_turn_radius: float    # m
    can_pivot: bool           # 是否允许原地转向（差速地面平台）


# 平台类别的基准值（演示暂定）。速度上限由调用方按平台实际 speed 再收紧。
_BASE = {
    'UGV': dict(max_accel=0.8, max_decel=1.0, yaw_rate=0.70,
                yaw_accel=1.40, lateral=2.00, radius=1.0, pivot=True),
    'TANK': dict(max_accel=0.7, max_decel=0.9, yaw_rate=0.60,
                 yaw_accel=1.20, lateral=1.80, radius=1.2, pivot=True),
    'PLANE': dict(max_accel=0.6, max_decel=1.2, yaw_rate=0.45,
                  yaw_accel=0.50, lateral=1.50, radius=4.5, pivot=False),
    'WING': dict(max_accel=0.5, max_decel=1.0, yaw_rate=0.40,
                 yaw_accel=0.45, lateral=1.40, radius=5.0, pivot=False),
}
_DEFAULT = _BASE['UGV']


def _kind_of(platform):
    if isinstance(platform, str):
        return platform.upper()
    for attr in ('platform_class', 'kind'):
        value = getattr(platform, attr, None)
        if value:
            return str(value).upper()
    return ''


def _speed_of(platform, speed_mps):
    if speed_mps is not None:
        return max(float(speed_mps), 0.0)
    for attr in ('speed_mps', 'speed'):
        value = getattr(platform, attr, None)
        if value is not None:
            return max(float(value), 0.0)
    return 0.0


def limits_for(platform, speed_mps=None):
    """返回平台的运动学限幅。

    ``max_yaw_rate`` 是平台自身的转向能力上限，不再按当前速度直接压小；
    高速时的横向加速度约束由运动/控制层"先减速再转"实现（若在这里把
    角速度压到 a_lat/v，高速平台会得到几十米的转弯半径，城市任务直接
    转不过来）。``min_turn_radius`` 则按当前速度给出，供路径圆角使用。
    """
    kind = _kind_of(platform)
    base = _BASE.get(kind, _DEFAULT)
    speed = _speed_of(platform, speed_mps)
    yaw_rate = max(0.15, base['yaw_rate'])
    radius = max(base['radius'], speed / max(yaw_rate, 1e-6)) if speed > 1e-6 else base['radius']
    return KinematicLimits(
        kind=kind or 'UNKNOWN',
        max_speed=speed,
        max_accel=base['max_accel'],
        max_decel=base['max_decel'],
        max_yaw_rate=yaw_rate,
        max_yaw_accel=base['yaw_accel'],
        max_lateral_accel=base['lateral'],
        min_turn_radius=radius,
        can_pivot=bool(base['pivot']),
    )


def turn_radius_for(platform, speed_mps=None, margin=1.15):
    """路径圆角半径：不小于最小转弯半径，并留一点余量。"""
    limits = limits_for(platform, speed_mps)
    return max(limits.min_turn_radius, limits.max_speed / max(limits.max_yaw_rate, 1e-6)) * margin


def clamp_angle(angle):
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def approach(current, target, max_delta):
    """以不超过 ``max_delta`` 的步长趋近目标。"""
    delta = float(target) - float(current)
    if delta > max_delta:
        return float(current) + max_delta
    if delta < -max_delta:
        return float(current) - max_delta
    return float(target)


def turn_toward(current, target, max_rate, dt):
    """一步最多转 ``max_rate * dt`` 弧度，返回（新航向, 实际角速度）。"""
    error = clamp_angle(float(target) - float(current))
    limit = max(0.0, float(max_rate)) * max(0.0, float(dt))
    if abs(error) <= limit or limit <= 1e-12:
        return clamp_angle(float(target)), (error / dt if dt > 1e-12 else 0.0)
    step = math.copysign(limit, error)
    return clamp_angle(float(current) + step), step / dt
