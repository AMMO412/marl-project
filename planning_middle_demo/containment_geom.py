# -*- coding: utf-8 -*-
"""containment_geom.py —— 区域封控（T-SEC）共用几何。

规划层（``interop.templates``）与执行层（``behaviors.ContainmentBehavior``）
必须看到同一条封控边界、同一组边界段和同一个占位点，否则"计划说守东段、
执行却站到西段"这类偏差无法从数据上区分。因此边界弧段、占位点和监视覆盖
的计算集中在本文件，两边只记账、不复算。

坐标与单位：场景坐标（编成表 ``meta.cell_size_m`` 定义 1 单位=多少米，默认
1 单位=1 米）；角度为弧度。时间不在本文件内。

边界约定：
  * 多边形取顶点序列，首尾不必闭合（重复首点会被去掉）；
  * 弧长参数 ``s`` 从 ``polygon[0]`` 起算，按边累加，范围 ``[0, perimeter)``；
  * 顺时针/逆时针都由有符号面积判定，**内向法线**统一指向多边形内部；
  * 占位点在"边界段中点 → 内部"方向内缩 ``standoff`` 米。
"""

import math

Point = tuple

EPS = 1e-9


def as_polygon(value):
    """把 ``[{"x","y"}]`` / ``[[x,y]]`` / ``{"polygon": [...]}`` 统一成点元组列表。"""
    if isinstance(value, dict):
        value = value.get("polygon")
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise ValueError("封控区域至少需要 3 个顶点")
    points = []
    for item in value:
        if isinstance(item, dict):
            points.append((float(item["x"]), float(item["y"])))
        else:
            points.append((float(item[0]), float(item[1])))
    if len(points) > 3 and points[0] == points[-1]:
        points.pop()
    return points


def signed_area(polygon):
    total = 0.0
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def centered(polygon):
    """把顶点平移到重心原点，避免大坐标下的叉积相消误差（仅内部计算用）。"""
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return [(p[0] - cx, p[1] - cy) for p in polygon], (cx, cy)


def is_ccw(polygon):
    shifted, _ = centered(polygon)
    return signed_area(shifted) > 0


def perimeter(polygon):
    total = 0.0
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def _edges(polygon):
    n = len(polygon)
    out = []
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= EPS:
            continue
        out.append(dict(index=i, a=a, b=b, length=length, tangent=(
            (b[0] - a[0]) / length, (b[1] - a[1]) / length)))
    return out


def inward_normal(tangent, ccw):
    """切线 → 指向区域内部的标准法线（CCW 多边形左侧为内）。"""
    if ccw:
        return (-tangent[1], tangent[0])
    return (tangent[1], -tangent[0])


def point_at(polygon, s, offset=0.0):
    """弧长 ``s`` 处的边界点与内向法线。

    ``offset`` 为沿内向法线的偏移（正数向区域内），用于占位点。
    返回 ``(point, inward_normal)``。
    """
    ccw = is_ccw(polygon)
    edges = _edges(polygon)
    total = sum(e["length"] for e in edges)
    if total <= EPS:
        raise ValueError("封控区域周长为 0")
    s = s % total
    walked = 0.0
    for edge in edges:
        if s <= walked + edge["length"] + EPS:
            t = (s - walked) / edge["length"]
            point = (edge["a"][0] + (edge["b"][0] - edge["a"][0]) * t,
                     edge["a"][1] + (edge["b"][1] - edge["a"][1]) * t)
            normal = inward_normal(edge["tangent"], ccw)
            return ((point[0] + normal[0] * offset,
                     point[1] + normal[1] * offset), normal)
        walked += edge["length"]
    last = edges[-1]
    normal = inward_normal(last["tangent"], ccw)
    return ((last["b"][0] + normal[0] * offset, last["b"][1] + normal[1] * offset),
            normal)


def split_sectors(polygon, count):
    """按弧长把边界均分成 ``count`` 段，返回 ``[(s0, s1), ...]``。"""
    total = perimeter(polygon)
    count = max(1, int(count))
    return [(total * i / count, total * (i + 1) / count) for i in range(count)]


def sector_posts(polygon, count, standoff=0.0, start_s=0.0):
    """每段中点向内缩 ``standoff`` 米，作为该段的占位点。

    返回 ``[{"index", "s0", "s1", "post", "mid", "normal", "mid_s"}, ...]``。
    占位点取边界中点沿内向法线内缩（不是朝重心），阵地始终"贴着自己那段边界"。
    中点正好落在顶点时（例如正方形均分两段），沿弧长挪四分之一个段长：
    在角上取法线是病态的，会把阵地摆到相邻那条边上。
    """
    sectors = split_sectors(polygon, count)
    total = perimeter(polygon)
    vertices = list(polygon)
    posts = []
    for index, (s0, s1) in enumerate(sectors):
        span = s1 - s0
        s_mid = ((s0 + s1) / 2.0 + start_s) % total
        mid, normal = point_at(polygon, s_mid, 0.0)
        if min(math.hypot(mid[0] - v[0], mid[1] - v[1]) for v in vertices) < 0.5:
            s_mid = ((s0 + s1) / 2.0 + span * 0.25 + start_s) % total
            mid, normal = point_at(polygon, s_mid, 0.0)
        post, _ = point_at(polygon, s_mid, float(standoff))
        posts.append(dict(index=index + 1, s0=round(s0, 2), s1=round(s1, 2),
                          post=[round(post[0], 3), round(post[1], 3)],
                          mid=[round(mid[0], 3), round(mid[1], 3)],
                          normal=[round(normal[0], 4), round(normal[1], 4)],
                          mid_s=round(s_mid, 2)))
    return posts


def sector_vertices(polygon, s0, s1, step=12.0):
    """把一段边界离散成折线，便于画图与覆盖统计（首尾都取到）。"""
    total = perimeter(polygon)
    span = (s1 - s0) % total if s1 > s0 else (total - s0 + s1)
    steps = max(2, int(math.ceil(span / max(step, 1e-6))))
    out = []
    for i in range(steps + 1):
        s = (s0 + span * i / steps) % total
        point, _ = point_at(polygon, s)
        out.append([round(point[0], 3), round(point[1], 3)])
    return out


def boundary_samples(polygon, step=5.0):
    """沿边界按弧长等距采样，返回 ``[{"s", "point"}]``；覆盖统计用固定采样集。"""
    total = perimeter(polygon)
    if total <= EPS:
        return []
    count = max(8, int(math.ceil(total / max(step, 1e-6))))
    samples = []
    for i in range(count):
        s = total * i / count
        point, _ = point_at(polygon, s)
        samples.append(dict(s=round(s, 2), point=(point[0], point[1])))
    return samples


def arc_of_point(polygon, point):
    """点投影到边界上的最近位置：返回 ``{distance, s, point}``。"""
    edges = _edges(polygon)
    total = perimeter(polygon)
    best = None
    walked = 0.0
    for edge in edges:
        ax, ay = edge["a"]
        bx, by = edge["b"]
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        t = 0.0 if denom <= EPS else max(
            0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / denom))
        px, py = ax + dx * t, ay + dy * t
        distance = math.hypot(point[0] - px, point[1] - py)
        if best is None or distance < best["distance"]:
            best = dict(distance=distance, s=(walked + edge["length"] * t) % total,
                        point=(px, py))
        walked += edge["length"]
    return best


def inside(polygon, point):
    """射线法判定点是否在区域内。"""
    x, y = point[0], point[1]
    n = len(polygon)
    inside_flag = False
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            cross_x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < cross_x:
                inside_flag = not inside_flag
    return inside_flag


def gate_channel(point, direction, width):
    """通道口：把入口点与方向展开成一条横跨通道的监测/拦截线。

    返回 ``[(x0, y0), (x1, y1)]``，即入口点沿通道法线两侧各 ``width/2``。
    """
    angle = math.atan2(direction[1], direction[0])
    nx, ny = -math.sin(angle), math.cos(angle)
    half = float(width) / 2.0
    return [(point[0] - nx * half, point[1] - ny * half),
            (point[0] + nx * half, point[1] + ny * half)]


def coverage_ratio(samples, observers, radius):
    """边界监视覆盖率：被任一观察者覆盖到的采样点比例。

    ``observers`` 是 ``[(x, y), ...]``（应传入"在位"平台的位姿）；半径按传感器
    距离给，不做遮挡折算——遮挡模型属于传感器/地形模块，本层不臆造。
    """
    if not samples:
        return 1.0
    if not observers:
        return 0.0
    radius = float(radius)
    squared = radius * radius
    hit = 0
    for sample in samples:
        px, py = sample["point"]
        for ox, oy in observers:
            if (px - ox) ** 2 + (py - oy) ** 2 <= squared:
                hit += 1
                break
    return hit / float(len(samples))


def lead_intercept(agent, target_point, target_velocity, speed, horizon_s=12.0):
    """解算"平台以 speed 前进、目标匀速飞行"的相遇点（半秒步长迭代）。

    找不到可行解（目标过快/背离）时退回目标当前位置，由调用方判定来不来得及。
    """
    ax, ay = agent
    tx, ty = target_point
    vx, vy = target_velocity
    step = 0.5
    for k in range(1, int(horizon_s / step) + 1):
        t = k * step
        fx, fy = tx + vx * t, ty + vy * t
        if math.hypot(fx - ax, fy - ay) <= max(speed, 1e-6) * t:
            return [fx, fy]
    return [tx, ty]


def polygon_center(polygon):
    """多边形重心（顶点平均，稳定；不是面积质心）。"""
    if not polygon:
        return [0.0, 0.0]
    return [sum(p[0] for p in polygon) / len(polygon),
            sum(p[1] for p in polygon) / len(polygon)]
