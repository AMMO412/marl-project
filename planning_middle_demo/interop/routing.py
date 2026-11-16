# -*- coding: utf-8 -*-
"""风险感知栅格 A*（吸收自 M2，内部统一用米）。

地面平台（UGV/TANK）在栅格上绕开 no_go 多边形；空中平台只遵守对空
no_go，并可按巡航高度越过有高度上限的建筑。``applies_to=all`` 的威胁区
仍会触发风险绕行。
``risk_objective`` 打开时，威胁区格子的边代价加权，路径会主动绕开威胁；
否则走最短可通行路径并做视线捷径平滑。

与 M2 的差异：显式支持 8 邻域（对角线）与 octile 启发式，路径更短、
转向更少；栅格和几何统一按米计算，输出的 path 也是米。
"""

import heapq
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .geometry import (
    point_in_polygon,
    point_segment_distance,
    segment_intersects_polygon,
    segment_polygon_distance,
)

Point = Tuple[float, float]

DEFAULT_CELL_M = 5.0
DEFAULT_MARGIN_M = 1.0
DEFAULT_PADDING_M = 20.0
DEFAULT_THREAT_CLEARANCE_M = 4.0
THREAT_CLEARANCE_PENALTY = 1000.0

# 同一场景滚动重规划会反复建同一张栅格；按几何/分辨率缓存，避免每轮
# 重新做“格子 × 多边形”的百万次距离计算。
_GRID_CACHE = {}


class NoRouteError(ValueError):
    """起点与终点之间没有可行路径。"""


@dataclass
class Route:
    path: List[Point]
    length_m: float


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _path_length(path: Sequence[Point]) -> float:
    return sum(_dist(path[i], path[i + 1]) for i in range(len(path) - 1))


class Router(object):
    def __init__(self, scenario, subtasks, cell_m: Optional[float] = None,
                 margin_m: Optional[float] = None, risk_weight: float = 0.0,
                 threat_clearance_m: Optional[float] = None):
        self.scale = float(scenario.cell_size_m)
        meta = getattr(scenario, "meta", {}) or {}
        self.cell_m = float(cell_m if cell_m is not None
                            else meta.get("grid_cell_m", DEFAULT_CELL_M))
        self.margin_m = float(margin_m if margin_m is not None
                              else meta.get("grid_margin_m", DEFAULT_MARGIN_M))
        if self.cell_m <= 0 or self.margin_m < 0:
            raise ValueError("栅格尺寸必须为正、膨胀余量不能为负")
        self.risk_weight = max(0.0, float(risk_weight))
        self.threat_clearance_m = max(
            0.0,
            float(DEFAULT_THREAT_CLEARANCE_M
                  if threat_clearance_m is None else threat_clearance_m))
        self.ground_polygons = []
        # 空中 no_go: (polygon, max_altitude_m)。None 表示没有可靠高度，
        # 或这是显式对空禁飞区，必须对所有高度强制执行。
        self.air_obstacles = []
        self.ground_threats = []
        self.air_threats = []

        for item in scenario.constraints:
            polygon = _polygon_of(item)
            if polygon is None:
                continue
            if item.get("type") == "threat":
                applies = str(item.get("applies_to", "ground"))
                if applies not in ("ground", "air", "all"):
                    raise ValueError(
                        "threat.applies_to 只能是 ground/air/all：%s" % applies)
                if applies in ("ground", "all"):
                    self.ground_threats.append(
                        ([(x * self.scale, y * self.scale) for x, y in polygon],
                         float(item.get("intensity", 1.0))))
                if applies in ("air", "all"):
                    self.air_threats.append(
                        ([(x * self.scale, y * self.scale) for x, y in polygon],
                         float(item.get("intensity", 1.0))))
            elif item.get("type") == "no_go":
                applies = str(item.get("applies_to", "ground"))
                if applies not in ("ground", "air", "all"):
                    raise ValueError(
                        "no_go.applies_to 只能是 ground/air/all：%s" % applies)
                scaled = [(x * self.scale, y * self.scale)
                          for x, y in polygon]
                if applies in ("ground", "all"):
                    self.ground_polygons.append(scaled)
                if applies in ("air", "all"):
                    # 对空禁飞区没有“飞得更高就通过”的语义；只有空地
                    # 均作用且带物高数据的 no_go 才允许巡航高度越过。
                    max_altitude = None
                    if applies == "all" and item.get("height_m") is not None:
                        max_altitude = float(item["height_m"])
                        if max_altitude < 0:
                            raise ValueError("no_go.height_m 不能为负")
                    self.air_obstacles.append((scaled, max_altitude))

        self._ground_boxes = [
            (polygon, min(p[0] for p in polygon), min(p[1] for p in polygon),
             max(p[0] for p in polygon), max(p[1] for p in polygon))
            for polygon in self.ground_polygons]
        xs, ys = [], []
        for platform in scenario.platforms:
            xs.append(platform.position[0] * self.scale)
            ys.append(platform.position[1] * self.scale)
        obstacles = self.ground_polygons + [
            polygon for polygon, _max_altitude in self.air_obstacles]
        for polygon in obstacles + [p for p, _ in
                                    self.ground_threats + self.air_threats]:
            xs.extend(p[0] for p in polygon)
            ys.extend(p[1] for p in polygon)
        for subtask in subtasks:
            for point in _target_points(subtask.target):
                xs.append(float(point[0]) * self.scale)
                ys.append(float(point[1]) * self.scale)

        fixed_bounds = meta.get("grid_bounds_m")
        if (isinstance(fixed_bounds, (list, tuple))
                and len(fixed_bounds) == 4
                and float(fixed_bounds[2]) > float(fixed_bounds[0])
                and float(fixed_bounds[3]) > float(fixed_bounds[1])):
            self.x0, self.y0, self.x1, self.y1 = map(
                float, fixed_bounds
            )
        else:
            pad = DEFAULT_PADDING_M
            self.x0 = (min(xs) if xs else 0.0) - pad
            self.x1 = (max(xs) if xs else 0.0) + pad
            self.y0 = (min(ys) if ys else 0.0) - pad
            self.y1 = (max(ys) if ys else 0.0) + pad
        self.nx = int(math.ceil((self.x1 - self.x0) / self.cell_m)) + 1
        self.ny = int(math.ceil((self.y1 - self.y0) / self.cell_m)) + 1
        if self.nx * self.ny > 4_000_000:
            raise ValueError("栅格过大（%d x %d），请调大 grid_cell_m"
                             % (self.nx, self.ny))
        self.blocked = None
        self.ground_threat_grid = None
        self.air_threat_grid = None
        # Scheduler evaluations frequently ask for the same start/goal pair
        # during one plan and again after short-horizon replans.  The scenario
        # topology, footprint layers and risk parameters are immutable after
        # construction, so a route result can be reused safely.
        self._route_cache = {}
        self._no_route_cache = {}
        self._scoped_grids = {}

    # ------------------------------------------------------------------
    def route(self, start_m: Point, goal_m: Point, is_air: bool = False,
              altitude_m: Optional[float] = None, platform=None) -> Route:
        start = (float(start_m[0]), float(start_m[1]))
        goal = (float(goal_m[0]), float(goal_m[1]))
        altitude = (None if altitude_m is None
                    else float(altitude_m))
        if altitude is not None and not math.isfinite(altitude):
            raise ValueError("altitude_m 必须是有限数值")
        from vehicle_kinematics import turn_radius_for
        radius = turn_radius_for(platform) if platform is not None and not is_air else 0.0
        cache_key = (
            round(radius, 6),
            round(start[0], 6), round(start[1], 6),
            round(goal[0], 6), round(goal[1], 6),
            bool(is_air),
            None if altitude is None else round(altitude, 6),
        )
        cached = self._route_cache.get(cache_key)
        if cache_key in self._no_route_cache:
            raise NoRouteError(self._no_route_cache[cache_key])
        if cached is not None:
            path, length = cached
            return Route([list(point) for point in path], length)
        if _dist(start, goal) < 1e-9:
            route = Route([start, goal], 0.0)
            self._route_cache[cache_key] = (
                tuple(tuple(point) for point in route.path), route.length_m)
            return route
        obstacles = self._obstacles_for(is_air, altitude)
        scope = (bool(is_air), altitude)
        grid = self._scoped_grids.get(scope)
        if grid is None:
            grid = self._ensure_grid(obstacles)
            self._scoped_grids[scope] = grid
        self.blocked, self.ground_threat_grid, self.air_threat_grid = grid
        blocked = self.blocked
        threats = self.air_threats if is_air else self.ground_threats
        los_free = self._los_free(start, goal, blocked)
        if los_free and (self.risk_weight <= 1e-9
                         or not self._segment_hits_threat(start, goal,
                                                          threats)):
            # 直线既不穿障碍也不穿威胁区时直接走直线。以前只要
            # risk_weight>0 就一律跑栅格 A*，栅格化路径比直线略长，
            # 会让暴露度/风险目标在“本来就没有暴露”的场景里凭空变慢。
            route = Route([start, goal], _dist(start, goal))
            self._route_cache[cache_key] = (
                tuple(tuple(point) for point in route.path), route.length_m)
            return route
        try:
            path = self._astar(start, goal, threats, blocked)
        except NoRouteError as error:
            # Static geometry also makes a failed query reusable. Repeating a
            # full-grid search every control tick cannot make the same leg valid.
            if len(self._no_route_cache)>=4096:
                self._no_route_cache.clear()
            self._no_route_cache[cache_key]=str(error)
            raise
        if radius>0 and len(path)>2:
            from path_smoothing import smooth_corners
            def safe_segment(a,b):
                if not self._los_free(a,b,blocked):
                    return False
                left, right = sorted((a[0], b[0]))
                bottom, top = sorted((a[1], b[1]))
                margin = self.margin_m
                for polygon, x0, y0, x1, y1 in self._ground_boxes:
                    if right<x0-margin or left>x1+margin or top<y0-margin or bottom>y1+margin:
                        continue
                    if segment_polygon_distance(a,b,polygon)<margin-1e-9:
                        return False
                return not (self.risk_weight>1e-9 and self._segment_hits_threat(a,b,threats))
            path = smooth_corners(path,radius,
                free_point=lambda p:self._los_free(p,p,blocked),free_segment=safe_segment)
        route = Route(path, _path_length(path))
        if len(self._route_cache) >= 50000:
            self._route_cache.clear()
        self._route_cache[cache_key] = (
            tuple(tuple(point) for point in route.path), route.length_m)
        return route

    def _obstacles_for(self, is_air: bool,
                       altitude_m: Optional[float]) -> Tuple[List[Point], ...]:
        """选择当前平台实际受约束的硬障碍。

        地面平台始终只受地面 no_go 约束。空中平台只考虑 air/all no_go；
        对空地均作用且记录了物高的障碍，只有巡航高度不高于物高时才绕行。
        没有巡航高度时保守地把这类障碍视为仍然有效。
        """
        if not is_air:
            return tuple(self.ground_polygons)
        if altitude_m is None:
            return tuple(polygon
                         for polygon, _max_altitude in self.air_obstacles)
        return tuple(
            polygon for polygon, max_altitude in self.air_obstacles
            if max_altitude is None
            or altitude_m <= max_altitude + 1e-9)

    def _segment_hits_threat(self, start: Point, goal: Point,
                             threats=None) -> bool:
        """Whether a segment enters a threat safety corridor.

        Exposure routing is required to leave a real safety margin, not just
        avoid a mathematical overlap with the polygon.  A path placed exactly
        on the boundary looks safe in plan output but a stepwise follower
        overshoots into the threat during execution.
        """
        clearance = self.threat_clearance_m if self.risk_weight > 1e-9 else 0.0
        for polygon, _intensity in (threats if threats is not None
                                    else self.ground_threats + self.air_threats):
            if (segment_intersects_polygon(start, goal, polygon)
                    or segment_polygon_distance(start, goal, polygon)
                    <= clearance + 1e-9):
                return True
        return False

    # ------------------------------------------------------------------
    def _ensure_grid(self, obstacles=None):
        obstacles = (tuple(self.ground_polygons)
                     if obstacles is None else tuple(obstacles))
        key = (
            round(self.cell_m, 6), round(self.margin_m, 6),
            round(self.threat_clearance_m, 6),
            self.nx, self.ny, round(self.x0, 3), round(self.y0, 3),
            tuple((round(p[0], 3), round(p[1], 3))
                  for poly in obstacles for p in poly),
            tuple((round(intensity, 6),
                   tuple((round(p[0], 3), round(p[1], 3)) for p in poly))
                  for poly, intensity in
                  self.ground_threats + self.air_threats),
        )
        cached = _GRID_CACHE.get(key)
        if cached is not None:
            (self.blocked, self.ground_threat_grid,
             self.air_threat_grid) = cached
            return cached
        blocked = bytearray(self.nx * self.ny)
        ground_threat_grid = [0.0] * (self.nx * self.ny)
        air_threat_grid = [0.0] * (self.nx * self.ny)
        obstacle_boxes = [
            (
                polygon,
                min(point[0] for point in polygon) - self.margin_m,
                min(point[1] for point in polygon) - self.margin_m,
                max(point[0] for point in polygon) + self.margin_m,
                max(point[1] for point in polygon) + self.margin_m,
            )
            for polygon in obstacles
        ]
        ground_threat_boxes = [
            (
                polygon,
                intensity,
                min(point[0] for point in polygon) - self.threat_clearance_m,
                min(point[1] for point in polygon) - self.threat_clearance_m,
                max(point[0] for point in polygon) + self.threat_clearance_m,
                max(point[1] for point in polygon) + self.threat_clearance_m,
            )
            for polygon, intensity in self.ground_threats
        ]
        air_threat_boxes = [
            (
                polygon,
                intensity,
                min(point[0] for point in polygon) - self.threat_clearance_m,
                min(point[1] for point in polygon) - self.threat_clearance_m,
                max(point[0] for point in polygon) + self.threat_clearance_m,
                max(point[1] for point in polygon) + self.threat_clearance_m,
            )
            for polygon, intensity in self.air_threats
        ]
        def cells_in_box(x0, y0, x1, y1):
            # Conservative candidate cells; retain the original exact bbox and
            # polygon-distance checks. Only the iteration order changes.
            ilo = max(0, int(math.floor((x0-self.x0)/self.cell_m))-1)
            ihi = min(self.nx-1, int(math.ceil((x1-self.x0)/self.cell_m))+1)
            jlo = max(0, int(math.floor((y0-self.y0)/self.cell_m))-1)
            jhi = min(self.ny-1, int(math.ceil((y1-self.y0)/self.cell_m))+1)
            for j in range(jlo, jhi+1):
                cy = self.y0 + (j+0.5)*self.cell_m
                if not y0 <= cy <= y1:
                    continue
                for i in range(ilo, ihi+1):
                    cx = self.x0 + (i+0.5)*self.cell_m
                    if x0 <= cx <= x1:
                        yield j*self.nx+i, (cx, cy)

        for polygon, x0, y0, x1, y1 in obstacle_boxes:
            for index, point in cells_in_box(x0, y0, x1, y1):
                if not blocked[index] and _polygon_distance(point, polygon) < self.margin_m + 1e-9:
                    blocked[index] = 1
        for boxes, grid in ((ground_threat_boxes, ground_threat_grid),
                            (air_threat_boxes, air_threat_grid)):
            for polygon, intensity, x0, y0, x1, y1 in boxes:
                for index, point in cells_in_box(x0, y0, x1, y1):
                    if _polygon_distance(point, polygon) <= self.threat_clearance_m + 1e-9:
                        grid[index] = max(grid[index], intensity)
        self.blocked = blocked
        self.ground_threat_grid = ground_threat_grid
        self.air_threat_grid = air_threat_grid
        if len(_GRID_CACHE) > 32:
            _GRID_CACHE.clear()
        result = (blocked, ground_threat_grid, air_threat_grid)
        _GRID_CACHE[key] = result
        return result

    def _cell(self, point: Point) -> Tuple[int, int]:
        return (int(math.floor((point[0] - self.x0) / self.cell_m)),
                int(math.floor((point[1] - self.y0) / self.cell_m)))

    def _center(self, i: int, j: int) -> Point:
        return (self.x0 + (i + 0.5) * self.cell_m,
                self.y0 + (j + 0.5) * self.cell_m)

    def _inside(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny

    def _free(self, i: int, j: int, blocked=None) -> bool:
        blocked = self.blocked if blocked is None else blocked
        return self._inside(i, j) and not blocked[j * self.nx + i]

    def _nearest_free(self, point: Point,
                      blocked) -> Tuple[int, int]:
        i, j = self._cell(point)
        if self._free(i, j, blocked):
            return i, j
        best = None
        limit = max(self.nx, self.ny)
        for radius in range(1, limit + 1):
            for dj in range(-radius, radius + 1):
                for di in range(-radius, radius + 1):
                    if max(abs(di), abs(dj)) != radius:
                        continue
                    if not self._free(i + di, j + dj, blocked):
                        continue
                    distance = _dist(point, self._center(i + di, j + dj))
                    if best is None or distance < best[0]:
                        best = (distance, i + di, j + dj)
            if best is not None:
                return best[1], best[2]
        raise NoRouteError("起点 %.1f,%.1f 附近没有可通行栅格" % point)

    def _los_free(self, a: Point, b: Point, blocked) -> bool:
        steps = max(1, int(math.ceil(_dist(a, b) / (self.cell_m * 0.5))))
        for k in range(steps + 1):
            t = k / float(steps)
            i, j = self._cell((a[0] + (b[0] - a[0]) * t,
                               a[1] + (b[1] - a[1]) * t))
            if not self._free(i, j, blocked):
                return False
        return True

    def _astar(self, start: Point, goal: Point, threats=None,
               blocked=None) -> List[Point]:
        blocked = (self.blocked if blocked is None
                   else blocked)
        si, sj = self._nearest_free(start, blocked)
        gi, gj = self._nearest_free(goal, blocked)
        start_id = sj * self.nx + si
        goal_id = gj * self.nx + gi
        nx, ny = self.nx, self.ny
        diagonal_delta = math.sqrt(2) - 2.0
        threat_grid = (self.air_threat_grid if threats is self.air_threats
                       else self.ground_threat_grid)

        def heuristic(i, j):
            dx = abs(i - gi)
            dy = abs(j - gj)
            return (dx + dy) + diagonal_delta * min(dx, dy)

        heap = [(heuristic(si, sj), 0.0, start_id)]
        came = {start_id: None}
        cost = {start_id: 0.0}
        neighbors = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                     (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
                     (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)))
        while heap:
            _, current, node = heapq.heappop(heap)
            if node == goal_id:
                break
            if current > cost.get(node, float("inf")) + 1e-9:
                continue
            i, j = node % self.nx, node // self.nx
            for di, dj, step in neighbors:
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or blocked[nj * nx + ni]:
                    continue
                # 禁止斜穿两个被挡格之间的角
                if di and dj and (blocked[j * nx + ni] or blocked[nj * nx + i]):
                    continue
                nid = nj * self.nx + ni
                edge = step
                if self.risk_weight > 1e-9 and threat_grid is not None:
                    edge += (self.risk_weight * THREAT_CLEARANCE_PENALTY
                             * threat_grid[nid] * step)
                new_cost = current + edge
                if new_cost + 1e-9 < cost.get(nid, float("inf")):
                    cost[nid] = new_cost
                    came[nid] = node
                    heapq.heappush(heap,
                                   (new_cost + heuristic(ni, nj), new_cost, nid))

        if goal_id not in came and goal_id != start_id:
            raise NoRouteError("起点 %.1f,%.1f 到终点 %.1f,%.1f 没有可行路径"
                               % (start + goal))

        cells = []
        node = goal_id
        while node is not None:
            cells.append((node % self.nx, node // self.nx))
            node = came.get(node)
        cells.reverse()

        points = [start]
        for i, j in cells:
            center = self._center(i, j)
            if _dist(points[-1], center) > 1e-6:
                points.append(center)
        if _dist(points[-1], goal) > 1e-6:
            points.append(goal)
        # 暴露度/风险目标下也要做视线捷径平滑，只是捷径不能重新穿回威胁区。
        # 以前 risk_weight>0 直接返回原始栅格点，路径比实际需要长 5% 左右，
        # 会让“本来没有暴露”的场景凭空变慢。
        return self._los_simplify(points,
                                  threats=threats,
                                  avoid_threats=self.risk_weight > 1e-9,
                                  blocked=blocked)

    def _los_simplify(self, points: List[Point],
                      threats=None,
                      avoid_threats: bool = False,
                      blocked=None) -> List[Point]:
        if len(points) <= 2:
            return points
        result = [points[0]]
        index = 1
        while index < len(points):
            far = len(points) - 1
            while far > index and not self._clear(
                    result[-1], points[far], threats, avoid_threats,
                    blocked):
                far -= 1
            result.append(points[far])
            index = far + 1
        return result

    def _clear(self, start: Point, goal: Point, threats=None,
               avoid_threats: bool = False,
               blocked=None) -> bool:
        """捷径检查：不穿障碍；avoid_threats 时也不能重新穿进威胁区。"""
        if not self._los_free(start, goal, blocked):
            return False
        return not (avoid_threats and self._segment_hits_threat(start, goal,
                                                                threats))


def _polygon_of(item: Dict) -> Optional[List[Point]]:
    area = item.get("area")
    polygon = area.get("polygon") if isinstance(area, dict) else area
    if not polygon or len(polygon) < 3:
        return None
    return [(float(p[0]), float(p[1])) for p in polygon]


def _target_points(target: Dict) -> List[Point]:
    from .message import target_points
    try:
        return target_points(target)
    except Exception:
        return []


def _polygon_distance(p: Point, polygon: Sequence[Point]) -> float:
    if point_in_polygon(p, polygon):
        return 0.0
    return min(point_segment_distance(p, polygon[i], polygon[(i + 1) % len(polygon)])
               for i in range(len(polygon)))
