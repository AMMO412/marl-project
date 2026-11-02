# -*- coding: utf-8 -*-
"""containment_geom.py —— 区域封控（T-SEC）与要点坚守（T-HLD）共用几何。

规划层（``interop.templates``）与执行层（``behaviors.ContainmentBehavior`` /
``behaviors.KeepBehavior``）必须看到同一条封控边界、同一组边界段和同一个
占位点，否则"计划说守东段、执行却站到西段"这类偏差无法从数据上区分。
因此边界弧段、占位点和监视覆盖的计算集中在本文件，两边只记账、不复算。

T-HLD 的要点阵位也复用本文件（任务书 §9.4/§9.8 要求"不要另写一套几何"）：
威胁方向 → 方位角/向量、阵位点、威胁扇区、观察采样环都在文末「要点几何」
一节，与封控边界同用一套角度与坐标约定。

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


# ------------------------------------------------------------------
# 要点几何（T-HLD 要点坚守，1028 §2.5）
#
# 角度约定与 compass 一致：**0° 指向 +y（北），90° 指向 +x（东），顺时针增大**。
# ``bearing_deg`` 表示"威胁来自哪个方位"，阵位朝向 ``facing_deg`` 用同一套角度，
# 两者之差就是"目标是否落在本阵位的责任扇区里"。规划层与执行层都调这里，
# 否则计划里"P1 朝北"与执行层"P1 守东"会在数据上对不上。
# ------------------------------------------------------------------
def wrap_deg(deg):
    """把任意角度折到 ``(-180, 180]``。"""
    return ((float(deg) + 180.0) % 360.0) - 180.0


def compass_vector(bearing_deg):
    """方位角 → 单位向量（0°=+y 北，90°=+x 东，顺时针）。"""
    angle = math.radians(float(bearing_deg))
    return (math.sin(angle), math.cos(angle))


def bearing_deg(start, end):
    """``start → end`` 的方位角（度，0–360）。"""
    return math.degrees(math.atan2(float(end[0]) - float(start[0]),
                                   float(end[1]) - float(start[1]))) % 360.0


def angle_gap_deg(a, b):
    """两个方位角的最小夹角（0–180）。"""
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def in_sector(center, bearing_deg_, width_deg, radius_m, point):
    """点是否落在 `center` 起、指向 ``bearing_deg_``、张角 ``width_deg`` 的扇区内。

    用于"敌方从哪个方向来"和"该阵位是否正对这股敌人"：只按方位与距离判，
    不做地形遮挡。
    """
    dx = float(point[0]) - float(center[0])
    dy = float(point[1]) - float(center[1])
    distance = math.hypot(dx, dy)
    if distance > float(radius_m) + EPS:
        return False
    if distance <= EPS:
        return True
    angle = math.degrees(math.atan2(dx, dy)) % 360.0
    return angle_gap_deg(angle, bearing_deg_) <= float(width_deg) / 2.0


def threat_sector(center, bearing_deg_, width_deg, radius_m, step_deg=6.0):
    """威胁扇区折线（中心 + 弧上采样点），供画图与"进入扇区"判定共用。

    返回闭区间外的多边形顶点序列（首点为中心），前端按同一序列填充即可，
    不必自己按角度重算。
    """
    half = max(0.0, float(width_deg)) / 2.0
    steps = max(2, int(math.ceil(max(float(width_deg), 1e-6) / max(step_deg, 1e-6))))
    points = [(float(center[0]), float(center[1]))]
    for i in range(steps + 1):
        vec = compass_vector(float(bearing_deg_) - half
                             + float(width_deg) * i / steps)
        points.append((float(center[0]) + vec[0] * float(radius_m),
                       float(center[1]) + vec[1] * float(radius_m)))
    return points


def threat_posts(center, bearings, distance_m):
    """按威胁方向给出一组阵位点：沿该方位从要点向外偏移 ``distance_m``。"""
    posts = []
    for bearing in bearings:
        vec = compass_vector(bearing)
        posts.append([round(float(center[0]) + vec[0] * float(distance_m), 3),
                      round(float(center[1]) + vec[1] * float(distance_m), 3)])
    return posts


def facing_of(post, center):
    """阵位朝向 = 由要点指向阵位的方位（面朝威胁来向、背靠要点）。"""
    return round(bearing_deg(center, post), 1)


def observation_ring(center, radius_m, count=12):
    """要点周围的观察采样环（覆盖统计用固定采样集，不用随机点）。

    与封控的 ``boundary_samples`` 同一思路：先定一组固定采样点，再用
    ``coverage_ratio`` 统计"任一在位平台能否看到"，指标才可复现。
    """
    count = max(4, int(count))
    radius = float(radius_m)
    samples = [dict(s=0.0, point=(float(center[0]), float(center[1])))]
    for i in range(count):
        angle = 2.0 * math.pi * i / count
        samples.append(dict(
            s=round(2.0 * math.pi * i / count, 3),
            point=(float(center[0]) + radius * math.cos(angle),
                   float(center[1]) + radius * math.sin(angle))))
    return samples


def approach_points(center, threats, radius_m, count=1):
    """威胁接近采样点：每条威胁方向上按半径取 ``count`` 个点（由外向内）。

    用于"观察是否覆盖来袭方向"：只覆盖要点中心、不覆盖接近路的配置会在
    这里露出来，而不是被一个圆心采样掩盖掉。
    """
    points = []
    count = max(1, int(count))
    for threat in threats or []:
        bearing = float(threat.get("bearing_deg", 0.0))
        for i in range(count):
            factor = 1.0 - 0.5 * i / count
            vec = compass_vector(bearing)
            points.append(dict(
                s=round(bearing, 2),
                point=(float(center[0]) + vec[0] * float(radius_m) * factor,
                       float(center[1]) + vec[1] * float(radius_m) * factor)))
    return points
