# -*- coding: utf-8 -*-
"""路径跟随的时间估算与速度采样（吸收自 M2，单位改成米/秒）。

与旧版"每个折点先原地满角速度转向、再全速直行"不同，本版：

* 地面平台允许原地转向，但角速度按线性/角加速度斜坡建立，拐点前后的
  速度也做加减速；小转角直接协调转弯通过，不再每 0.5 m 停一次；
* 空中平台不允许原地转，按"边飞边转"的单车模型积分，角速度同样受限；
* 输出仍只含 linear.x / angular.z（neutral 任务不改变高度），
  但相邻指令之间不会出现 0 → 最大角速度、全速 → 零速的阶跃。

限幅值统一来自 ``vehicle_kinematics``，规划、回放替身和 4.2 指令同源。
"""

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from vehicle_kinematics import approach, clamp_angle, limits_for

Point = Tuple[float, float]

MAX_SAMPLE_S = 120.0    # 单条 4.2 指令最长时长
GROUND_DT = 0.20        # 地面轨迹采样周期（秒）
AIR_DT = 0.20           # 空中轨迹采样周期（秒）
PIVOT_ANGLE = 0.90      # 超过该转角（约 52°）改为停车原地转


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
    return clamp_angle(angle)


def simulate_path(path: Sequence[Point], platform, heading_rad: float,
                  speed_mps: float) -> MotionPlan:
    speed = max(float(speed_mps), 1e-6)
    if len(path) < 2:
        return MotionPlan(0.0, wrap(heading_rad), [])
    limits = limits_for(platform, speed)
    speed = min(speed, limits.max_speed) if limits.max_speed > 1e-9 else speed
    if limits.can_pivot:
        return _simulate_ground(path, heading_rad, speed, limits)
    return _simulate_air(path, heading_rad, speed, limits)


def _simulate_ground(path: Sequence[Point], heading_rad: float,
                     speed: float, limits) -> MotionPlan:
    """差速地面平台：可低速原地转，但所有角/线速度都经过加速度斜坡。"""
    x, y = path[0]
    psi = wrap(heading_rad)
    v = 0.0
    w = 0.0
    elapsed = 0.0
    samples = []  # type: List[MotionSample]

    def emit(linear, angular, duration=GROUND_DT):
        nonlocal elapsed
        if duration <= 1e-9:
            return
        samples.append(MotionSample(float(linear), float(angular), float(duration)))
        elapsed += duration

    def decel_to_zero():
        nonlocal v, w, psi
        while v > 1e-6:
            v = max(0.0, v - limits.max_decel * GROUND_DT)
            w = approach(w, 0.0, limits.max_yaw_accel * GROUND_DT)
            psi = wrap(psi + w * GROUND_DT)
            emit(v, w)

    def pivot_to(desired):
        nonlocal psi, w
        desired = wrap(desired)
        # 先确保已经停稳；原地转向只改变航向，不产生位移。
        decel_to_zero()
        # v 已经为 0 时 decel_to_zero 不会再动 w；先把残余角速度收敛掉，
        # 否则下一段指令会从残余 w 直接跳到新目标。
        guard = 0
        while abs(w) > 0.02 and guard < 1000:
            guard += 1
            w = approach(w, 0.0, limits.max_yaw_accel * GROUND_DT)
            psi = wrap(psi + w * GROUND_DT)
            emit(0.0, w)
        w = 0.0
        error = wrap(desired - psi)
        if abs(error) <= 1e-3:
            return
        # 用解析的梯形/三角形角速度曲线一次排完整个转角，保证末角速度为 0；
        # 逐拍 feedback 式的 approach 在末段容易因为减速不及而被迫阶跃。
        angle = abs(error)
        direction = 1.0 if error > 0 else -1.0
        w_max = limits.max_yaw_rate
        accel = limits.max_yaw_accel
        t_acc = w_max / accel
        angle_acc = 0.5 * w_max * t_acc
        if angle < 2.0 * angle_acc:
            w_max = math.sqrt(max(0.0, accel * angle))
            t_acc = w_max / accel
            t_cruise = 0.0
        else:
            t_cruise = (angle - 2.0 * angle_acc) / w_max
        total = 2.0 * t_acc + t_cruise
        t = 0.0
        while t < total - 1e-9:
            step_t = min(GROUND_DT, total - t)
            middle = t + step_t * 0.5
            if middle < t_acc:
                w = direction * min(w_max, accel * middle)
            elif middle < t_acc + t_cruise:
                w = direction * w_max
            else:
                w = direction * max(
                    0.0, w_max - accel * (middle - t_acc - t_cruise))
            psi = wrap(psi + w * step_t)
            emit(0.0, w, step_t)
            t += step_t
        psi = desired
        w = 0.0

    # 起始朝向与第一段不一致时，先在原地平滑转向（差速平台允许）。
    if len(path) > 1:
        first = math.atan2(path[1][1] - path[0][1], path[1][0] - path[0][0])
        if abs(wrap(first - psi)) > 0.25:
            pivot_to(first)

    for target in path[1:]:
        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        if distance < 1e-9:
            continue
        desired = math.atan2(dy, dx)
        error = wrap(desired - psi)

        # 大转角或极短段：停车、原地平滑转，再走下一段。这样即使路径
        # 因障碍无法圆角化，也不会出现"全速突然甩 135°"。
        if abs(error) > PIVOT_ANGLE or (distance < 0.8 and abs(error) > 0.35):
            pivot_to(desired)
            v = 0.0
            x, y = target
            continue

        v_target = speed
        if abs(error) > 1e-6:
            # 在 distance 内转完 error，需要的角速度 = error*v/distance；
            # 同时受角速度上限和横向加速度上限约束，取对应速度上限。
            v_yaw = limits.max_yaw_rate * distance / abs(error)
            v_lat = math.sqrt(max(0.0, limits.max_lateral_accel * distance / abs(error)))
            v_target = min(v_target, v_yaw, v_lat)
        if abs(error) > 0.30 and v_target < 0.22 * speed:
            pivot_to(desired)
            v = 0.0
            x, y = target
            continue
        v_target = max(v_target, 0.05)
        w_target = error * v_target / max(distance, 1e-9)

        moved = 0.0
        guard = 0
        while moved < distance - 1e-6 and guard < 200000:
            guard += 1
            a = limits.max_accel if v < v_target else limits.max_decel
            v = approach(v, v_target, a * GROUND_DT)
            w = approach(w, w_target, limits.max_yaw_accel * GROUND_DT)
            w = max(-limits.max_yaw_rate, min(limits.max_yaw_rate, w))
            if v > 0.05:
                cap = min(limits.max_yaw_rate, limits.max_lateral_accel / v)
                w = max(-cap, min(cap, w))
            step = min(v * GROUND_DT, distance - moved)
            if step <= 1e-9:
                break
            psi = wrap(psi + w * GROUND_DT)
            moved += step
            emit(v, w)
        # 路径点作为权威位置；航向按实际角速度积分，下一段会继续修正。
        x, y = target

    decel_to_zero()
    return MotionPlan(elapsed, wrap(psi), samples)


def _simulate_air(path: Sequence[Point], heading_rad: float,
                  speed: float, limits) -> MotionPlan:
    """固定翼/飞翼：不能原地转，按"转弯弧 + 直线"处理。

    转弯段的角速度用解析梯形/三角形曲线，起止角速度都为 0；转弯弧上的
    位移按积分计入。目标落在最小转弯圆内侧时最多做 3 次修正转弯，随后
    直线飞向目标，避免纯追踪"绕着目标永远打转"。
    """
    x, y = path[0]
    psi = wrap(heading_rad)
    w = 0.0
    elapsed = 0.0
    samples = []  # type: List[MotionSample]
    v = max(speed, 0.1)

    def emit(angular, duration=AIR_DT):
        nonlocal elapsed
        samples.append(MotionSample(v, float(angular), float(duration)))
        elapsed += duration

    def turn_arc(error):
        nonlocal x, y, psi, w
        error = wrap(error)
        angle = abs(float(error))
        if angle <= 1e-6:
            return
        direction = 1.0 if error > 0 else -1.0
        w_max = limits.max_yaw_rate
        accel = limits.max_yaw_accel
        t_acc = w_max / accel
        angle_acc = 0.5 * w_max * t_acc
        if angle < 2.0 * angle_acc:
            w_max = math.sqrt(max(0.0, accel * angle))
            t_acc = w_max / accel
            t_cruise = 0.0
        else:
            t_cruise = (angle - 2.0 * angle_acc) / w_max
        total = 2.0 * t_acc + t_cruise
        t = 0.0
        while t < total - 1e-9:
            step_t = min(AIR_DT, total - t)
            middle = t + step_t * 0.5
            if middle < t_acc:
                w = direction * min(w_max, accel * middle)
            elif middle < t_acc + t_cruise:
                w = direction * w_max
            else:
                w = direction * max(
                    0.0, w_max - accel * (middle - t_acc - t_cruise))
            psi = wrap(psi + w * step_t)
            x += v * math.cos(psi) * step_t
            y += v * math.sin(psi) * step_t
            emit(w, step_t)
            t += step_t
        w = 0.0

    for target in path[1:]:
        # 转弯弧最多修正 8 次；每次都把机头继续转向当前目标方位，直到
        # 误差足够小，直飞段的 vx 才和机头方向一致（Twist 没有横移分量）。
        for _ in range(8):
            dx, dy = target[0] - x, target[1] - y
            if math.hypot(dx, dy) < 1e-9:
                break
            error = wrap(math.atan2(dy, dx) - psi)
            if abs(error) <= 0.08:
                break
            turn_arc(error)
        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        if distance > 1e-9:
            # 航向已对准目标；直飞段按恒定巡航速度执行，不再改 yaw。
            duration = distance / max(v, 1e-6)
            emit(0.0, duration)
            x, y = target

    return MotionPlan(elapsed, wrap(psi), samples)


def coalesce(samples: List[MotionSample], max_s: float = MAX_SAMPLE_S,
             tol_v: float = 0.0, tol_w: float = 0.0) -> List[MotionSample]:
    """合并相同 (vx, wz) 的相邻采样，并按 120 s 上限切段。

    默认只合并完全相同的值。允许 ``tol_v/tol_w`` 近似合并会把一个很小的
    斜坡段并进下一段，合并后的边界差可能超过单拍加速度上限；要保证
    物理限幅可核对，默认不启用近似合并。
    """
    merged = []
    for sample in samples:
        if sample.duration_s <= 1e-9:
            continue
        if (merged and abs(merged[-1].vx - sample.vx) <= tol_v
                and abs(merged[-1].wz - sample.wz) <= tol_w):
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
