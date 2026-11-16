# -*- coding: utf-8 -*-
"""折线路径的圆角平滑（规划与回放共用）。

A* 只保证"折线可通行"，不保证"车辆转得过来"。直接沿折线走，车辆会在
拐点急停/原地大角度转向。这里在拐点用二次 Bézier 圆角替换尖角：

* 入口/出口速度方向与原折线一致，因此圆角两端切向连续；
* 圆角半径受相邻线段长度限制，不会吃掉整段路；
* 每个采样点、每个圆角小段都要通过调用方给的 free 回调；不通过就逐步
  缩小半径，仍不行则保留原拐点（交给运动层低速转向）。

调用方传 ``free_point`` / ``free_segment`` 即可，不绑定具体地图实现。
"""
import math


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _wrap(angle):
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _dedupe(points):
    result = []
    for point in points:
        p = (float(point[0]), float(point[1]))
        if not result or _dist(result[-1], p) > 1e-9:
            result.append(p)
    return result


def _bezier(a, control, b, steps):
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        u = 1.0 - t
        points.append((u * u * a[0] + 2.0 * u * t * control[0] + t * t * b[0],
                       u * u * a[1] + 2.0 * u * t * control[1] + t * t * b[1]))
    return points


def _curve_free(curve, free_point, free_segment):
    if free_point is not None:
        for point in curve:
            if not free_point(point):
                return False
    if free_segment is not None:
        for a, b in zip(curve, curve[1:]):
            if not free_segment(a, b):
                return False
    return True


def smooth_corners(points, radius, free_point=None, free_segment=None,
                   samples=8, min_radius=0.20, angle_tol=0.035):
    """把折线拐角替换成圆弧（二次 Bézier），返回新的折线。

    ``radius`` 是期望圆角半径（米）；实际半径还会被相邻线段长度压缩。
    ``min_radius`` 以下不再尝试，保留尖角，让运动层明确减速/转向。
    """
    pts = _dedupe(points)
    if len(pts) < 3 or radius is None or float(radius) <= 0:
        return pts
    radius = float(radius)
    result = [pts[0]]
    for index in range(1, len(pts) - 1):
        a, p, b = pts[index - 1], pts[index], pts[index + 1]
        len_in, len_out = _dist(a, p), _dist(p, b)
        if len_in < 1e-9 or len_out < 1e-9:
            continue
        turn = abs(_wrap(math.atan2(b[1] - p[1], b[0] - p[0])
                         - math.atan2(p[1] - a[1], p[0] - a[0])))
        if turn <= angle_tol:
            # 共线或几乎共线：保留原折点，避免把噪声放大成小圆角。
            result.append(p)
            continue
        trim = min(radius, 0.40 * len_in, 0.40 * len_out)
        rounded = None
        while trim >= min_radius:
            in_dir = _unit(a, p)
            out_dir = _unit(p, b)
            entry = (p[0] - in_dir[0] * trim, p[1] - in_dir[1] * trim)
            exit_ = (p[0] + out_dir[0] * trim, p[1] + out_dir[1] * trim)
            curve = _bezier(entry, p, exit_, samples)
            if (_curve_free(curve, free_point, free_segment)
                    and (free_segment is None
                         or free_segment(result[-1], curve[0]))):
                rounded = curve
                break
            trim *= 0.62
        if rounded is None:
            result.append(p)
        else:
            result.extend(rounded[1:])
    result.append(pts[-1])
    return _dedupe(result)


def sharp_corners(points, threshold_deg=45.0):
    """返回折线中转角超过阈值的内部拐点（测试/诊断用）。"""
    pts = _dedupe(points)
    result = []
    for index in range(1, len(pts) - 1):
        a, p, b = pts[index - 1], pts[index], pts[index + 1]
        turn = abs(_wrap(math.atan2(b[1] - p[1], b[0] - p[0])
                         - math.atan2(p[1] - a[1], p[0] - a[0])))
        if math.degrees(turn) > threshold_deg:
            result.append((index, math.degrees(turn), p))
    return result
