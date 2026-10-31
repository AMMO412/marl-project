# -*- coding: utf-8 -*-
"""平面几何工具：点在多边形内、质心、包围盒、路径长度、穿障碍检查。

坐标单位由调用方保证一致（本包统一为场景单位，默认米）。
"""

import math
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]


def dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def polygon_centroid(polygon: Sequence[Sequence[float]]) -> Point:
    pts = [(float(p[0]), float(p[1])) for p in polygon]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        raise ValueError("空多边形没有质心")
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


def bbox(polygon: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    xs = [float(p[0]) for p in polygon]
    ys = [float(p[1]) for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    """射线法；落在边界上按“在内部”处理（保守，避免边界任务被当成安全）。"""
    x, y = float(point[0]), float(point[1])
    pts = [(float(p[0]), float(p[1])) for p in polygon]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return False

    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 \
                and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def path_length(path: Sequence[Sequence[float]]) -> float:
    return sum(dist(path[i], path[i + 1]) for i in range(len(path) - 1))


def point_segment_distance(p: Sequence[float], a: Sequence[float],
                           b: Sequence[float]) -> float:
    px, py = float(p[0]), float(p[1])
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polygon_distance(p: Sequence[float], polygon: Sequence[Sequence[float]]) -> float:
    if point_in_polygon(p, polygon):
        return 0.0
    pts = [(float(q[0]), float(q[1])) for q in polygon]
    return min(point_segment_distance(p, pts[i], pts[(i + 1) % len(pts)])
               for i in range(len(pts)))


def path_enters_polygon(path: Sequence[Sequence[float]],
                        polygon: Sequence[Sequence[float]],
                        sample_m: float = 1.0) -> bool:
    """路径是否穿过多边形。按 sample_m 采样，不依赖精确相交算法。"""
    if not path:
        return False
    if len(path) == 1:
        return point_in_polygon(path[0], polygon)
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        length = dist(a, b)
        steps = max(1, int(math.ceil(length / max(sample_m, 1e-6))))
        for k in range(steps + 1):
            t = k / float(steps)
            p = (float(a[0]) + (float(b[0]) - float(a[0])) * t,
                 float(a[1]) + (float(b[1]) - float(a[1])) * t)
            if point_in_polygon(p, polygon):
                return True
    return False


def unique_points(points: Iterable[Sequence[float]]) -> List[Point]:
    seen = set()
    out = []
    for p in points:
        key = (round(float(p[0]), 9), round(float(p[1]), 9))
        if key not in seen:
            seen.add(key)
            out.append((float(p[0]), float(p[1])))
    return out
