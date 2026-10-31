# -*- coding: utf-8 -*-
"""路径跟随的时间估算与速度采样（吸收自 M2，单位改成米/秒）。

地面平台（差速）：先原地转向，再直线行驶，转向耗时计入 travel；
空中平台（简化固定翼）：按最小转弯半径边前进边转向，再直线飞行。
输出只含 linear.x / angular.z（neutral 任务不改变高度）。
"""

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

Point = Tuple[float, float]

GROUND_W_MAX = 0.8      # rad/s
AIR_W_MAX = 0.5         # rad/s
MAX_SAMPLE_S = 120.0    # 单条 4.2 指令最长时长


@dataclass
class MotionSample:
    vx: float
    wz: float
    duration_s: float


@dataclass
class MotionPlan:
    duration_s: float
    final_heading: float
    samples: List[MotionSample]


def wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def simulate_path(path: Sequence[Point], platform, heading_rad: float,
                  speed_mps: float) -> MotionPlan:
    speed = max(float(speed_mps), 1e-6)
    if len(path) < 2:
        return MotionPlan(0.0, wrap(heading_rad), [])
    if platform.is_air:
        return _simulate_air(path, heading_rad, speed)
    return _simulate_ground(path, heading_rad, speed)


def _simulate_ground(path: Sequence[Point], heading_rad: float,
                     speed: float) -> MotionPlan:
    x, y = path[0]
    psi = wrap(heading_rad)
    elapsed = 0.0
    samples = []
    for target in path[1:]:
        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        if distance < 1e-9:
            continue
        desired = math.atan2(dy, dx)
        error = wrap(desired - psi)
        if abs(error) > 1e-6:
            turn_s = abs(error) / GROUND_W_MAX
            samples.append(MotionSample(0.0, math.copysign(GROUND_W_MAX, error),
                                        turn_s))
            psi = desired
            elapsed += turn_s
        drive_s = distance / speed
        samples.append(MotionSample(speed, 0.0, drive_s))
        x, y = target
        elapsed += drive_s
    return MotionPlan(elapsed, wrap(psi), samples)


def _simulate_air(path: Sequence[Point], heading_rad: float,
                  speed: float) -> MotionPlan:
    x, y = path[0]
    psi = wrap(heading_rad)
    elapsed = 0.0
    samples = []
    for target in path[1:]:
        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        if distance < 1e-9:
            continue
        desired = math.atan2(dy, dx)
        error = wrap(desired - psi)
        if abs(error) > 1e-6:
            wz = math.copysign(AIR_W_MAX, error)
            turn_s = abs(error) / AIR_W_MAX
            radius = speed / wz
            x += radius * (math.sin(psi + error) - math.sin(psi))
            y -= radius * (math.cos(psi + error) - math.cos(psi))
            psi = wrap(psi + error)
            elapsed += turn_s
            samples.append(MotionSample(speed, wz, turn_s))

        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        if distance > 1e-9:
            drive_s = distance / speed
            x, y = target
            elapsed += drive_s
            samples.append(MotionSample(speed, 0.0, drive_s))
    return MotionPlan(elapsed, wrap(psi), samples)


def coalesce(samples: List[MotionSample], max_s: float = MAX_SAMPLE_S) -> List[MotionSample]:
    """合并相同 (vx, wz) 的相邻采样，并按 120 s 上限切段。"""
    merged = []
    for sample in samples:
        if sample.duration_s <= 1e-9:
            continue
        if (merged and abs(merged[-1].vx - sample.vx) < 1e-9
                and abs(merged[-1].wz - sample.wz) < 1e-9):
            merged[-1].duration_s += sample.duration_s
        else:
            merged.append(MotionSample(sample.vx, sample.wz, sample.duration_s))

    result = []
    for sample in merged:
        remaining = sample.duration_s
        while remaining > 1e-9:
            duration = min(max_s, remaining)
            result.append(MotionSample(sample.vx, sample.wz, duration))
            remaining -= duration
    return result
