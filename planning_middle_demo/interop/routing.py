# -*- coding: utf-8 -*-
"""风险感知栅格 A*（吸收自 M2，内部统一用米）。

地面平台（UGV/TANK）在栅格上绕开 no_go 多边形；空中平台按直线航路处理。
``risk_objective`` 打开时，威胁区格子的边代价加权，路径会主动绕开威胁；
否则走最短可通行路径并做视线捷径平滑。

与 M2 的差异：显式支持 8 邻域（对角线）与 octile 启发式，路径更短、
转向更少；栅格和几何统一按米计算，输出的 path 也是米。
"""

import heapq
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .geometry import point_in_polygon, point_segment_distance

Point = Tuple[float, float]

DEFAULT_CELL_M = 5.0
DEFAULT_MARGIN_M = 1.0
DEFAULT_PADDING_M = 20.0

# 同一场景滚动重规划会反复建同一张栅格；按几何/分辨率缓存，避免每轮
# 重新做“格子 × 多边形”的百万次距离计算。
_GRID_CACHE = {}  # type: Dict[Any, Tuple[bytearray, List[float]]]


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
                 margin_m: Optional[float] = None, risk_weight: float = 0.0):
        self.scale = float(scenario.cell_size_m)
        meta = getattr(scenario, "meta", {}) or {}
        self.cell_m = float(cell_m if cell_m is not None
                            else meta.get("grid_cell_m", DEFAULT_CELL_M))
        self.margin_m = float(margin_m if margin_m is not None
                              else meta.get("grid_margin_m", DEFAULT_MARGIN_M))
        if self.cell_m <= 0 or self.margin_m < 0:
            raise ValueError("栅格尺寸必须为正、膨胀余量不能为负")
        self.risk_weight = max(0.0, float(risk_weight))
        self.polygons = []  # type: List[List[Point]]
        self.threats = []  # type: List[Tuple[List[Point], float]]

        for item in scenario.constraints:
            polygon = _polygon_of(item)
            if polygon is None:
                continue
            if item.get("type") == "threat":
                self.threats.append(([(x * self.scale, y * self.scale)
                                      for x, y in polygon],
                                     float(item.get("intensity", 1.0))))
            elif item.get("type") == "no_go":
                # 未标注的 no_go 视为地面障碍；applies_to=all 表示也约束空中，
                # 但空中绕行尚未实现，这里仍只作用于地面栅格。
                if item.get("applies_to", "ground") not in ("ground", "all"):
                    continue
                self.polygons.append([(x * self.scale, y * self.scale)
                                      for x, y in polygon])

        xs, ys = [], []
        for platform in scenario.platforms:
            xs.append(platform.position[0] * self.scale)
            ys.append(platform.position[1] * self.scale)
        for polygon in self.polygons + [p for p, _ in self.threats]:
            xs.extend(p[0] for p in polygon)
            ys.extend(p[1] for p in polygon)
        for subtask in subtasks:
            for point in _target_points(subtask.target):
                xs.append(float(point[0]) * self.scale)
                ys.append(float(point[1]) * self.scale)

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
        self.blocked = None  # type: Optional[bytearray]
        self.threat_grid = None  # type: Optional[List[float]]

    # ------------------------------------------------------------------
    def route(self, start_m: Point, goal_m: Point, is_air: bool = False) -> Route:
        start = (float(start_m[0]), float(start_m[1]))
        goal = (float(goal_m[0]), float(goal_m[1]))
        if _dist(start, goal) < 1e-9:
            return Route([start, goal], 0.0)
        if is_air:
            return Route([start, goal], _dist(start, goal))
        if self.risk_weight <= 1e-9 and self._los_free(start, goal):
            return Route([start, goal], _dist(start, goal))
        path = self._astar(start, goal)
        return Route(path, _path_length(path))

    # ------------------------------------------------------------------
    def _ensure_grid(self) -> None:
        if self.blocked is not None:
            return
        key = (
            round(self.cell_m, 6), round(self.margin_m, 6),
            self.nx, self.ny, round(self.x0, 3), round(self.y0, 3),
            tuple((round(p[0], 3), round(p[1], 3))
                  for poly in self.polygons for p in poly),
            tuple((round(intensity, 6),
                   tuple((round(p[0], 3), round(p[1], 3)) for p in poly))
                  for poly, intensity in self.threats),
        )
        cached = _GRID_CACHE.get(key)
        if cached is not None:
            self.blocked, self.threat_grid = cached
            return
        blocked = bytearray(self.nx * self.ny)
        threat_grid = [0.0] * (self.nx * self.ny)
        for j in range(self.ny):
            cy = self.y0 + (j + 0.5) * self.cell_m
            base = j * self.nx
            for i in range(self.nx):
                cx = self.x0 + (i + 0.5) * self.cell_m
                for polygon in self.polygons:
                    if _polygon_distance((cx, cy), polygon) < self.margin_m + 1e-9:
                        blocked[base + i] = 1
                        break
                if self.threats:
                    value = 0.0
                    for polygon, intensity in self.threats:
                        if point_in_polygon((cx, cy), polygon):
                            value = max(value, intensity)
                    threat_grid[base + i] = value
        self.blocked = blocked
        self.threat_grid = threat_grid
        if len(_GRID_CACHE) > 32:
            _GRID_CACHE.clear()
        _GRID_CACHE[key] = (blocked, threat_grid)

    def _cell(self, point: Point) -> Tuple[int, int]:
        return (int(math.floor((point[0] - self.x0) / self.cell_m)),
                int(math.floor((point[1] - self.y0) / self.cell_m)))

    def _center(self, i: int, j: int) -> Point:
        return (self.x0 + (i + 0.5) * self.cell_m,
                self.y0 + (j + 0.5) * self.cell_m)

    def _inside(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny

    def _free(self, i: int, j: int) -> bool:
        return self._inside(i, j) and not self.blocked[j * self.nx + i]

    def _nearest_free(self, point: Point) -> Tuple[int, int]:
        self._ensure_grid()
        i, j = self._cell(point)
        if self._free(i, j):
            return i, j
        best = None
        limit = max(self.nx, self.ny)
        for radius in range(1, limit + 1):
            for dj in range(-radius, radius + 1):
                for di in range(-radius, radius + 1):
                    if max(abs(di), abs(dj)) != radius:
                        continue
                    if not self._free(i + di, j + dj):
                        continue
                    distance = _dist(point, self._center(i + di, j + dj))
                    if best is None or distance < best[0]:
                        best = (distance, i + di, j + dj)
            if best is not None:
                return best[1], best[2]
        raise NoRouteError("起点 %.1f,%.1f 附近没有可通行栅格" % point)

    def _los_free(self, a: Point, b: Point) -> bool:
        self._ensure_grid()
        steps = max(1, int(math.ceil(_dist(a, b) / (self.cell_m * 0.5))))
        for k in range(steps + 1):
            t = k / float(steps)
            i, j = self._cell((a[0] + (b[0] - a[0]) * t,
                               a[1] + (b[1] - a[1]) * t))
            if not self._free(i, j):
                return False
        return True

    def _astar(self, start: Point, goal: Point) -> List[Point]:
        self._ensure_grid()
        si, sj = self._nearest_free(start)
        gi, gj = self._nearest_free(goal)
        start_id = sj * self.nx + si
        goal_id = gj * self.nx + gi

        def heuristic(i, j):
            dx = abs(i - gi)
            dy = abs(j - gj)
            return (dx + dy) + (math.sqrt(2) - 2.0) * min(dx, dy)

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
                if not self._free(ni, nj):
                    continue
                # 禁止斜穿两个被挡格之间的角
                if di and dj and (not self._free(i + di, j)
                                  or not self._free(i, j + dj)):
                    continue
                nid = nj * self.nx + ni
                edge = step
                if self.risk_weight > 1e-9 and self.threat_grid is not None:
                    edge += self.risk_weight * 5.0 * self.threat_grid[nid] * step
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
        if self.risk_weight > 1e-9:
            return points
        return self._los_simplify(points)

    def _los_simplify(self, points: List[Point]) -> List[Point]:
        if len(points) <= 2:
            return points
        result = [points[0]]
        index = 1
        while index < len(points):
            far = len(points) - 1
            while far > index and not self._los_free(result[-1], points[far]):
                far -= 1
            result.append(points[far])
            index = far + 1
        return result


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
