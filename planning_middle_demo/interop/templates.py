# -*- coding: utf-8 -*-
"""四类中性任务的分解规则（T-RCN / T-SEC / T-PTL / T-HLD）。

沿用 M2 的槽位思路：一个父任务按“区域竖条 / 路线分段 / 入口点 / 阵位点”
拆成若干可独立执行的单平台子任务；父任务依赖在末尾展开为子任务之间的
完成到开始依赖。T-ASL 不在本层范围，解析阶段已经拒绝。
"""

import copy

from typing import Dict, List, Optional, Sequence, Tuple

from .errors import PlanningError
from .geometry import bbox, polygon_centroid
from .message import target_points
from .model import Platform, Scenario, Subtask, Task

Point = Tuple[float, float]
POLYGON_KEYS = ("area", "sector", "patrol_area", "defense_area")


def count_capable(platforms: Sequence[Platform], required: Dict[str, int]) -> int:
    return sum(1 for p in platforms
               if p.status == "READY"
               and all(int(p.capabilities.get(code, 0)) >= int(level)
                       for code, level in required.items()))


def as_point(value) -> Point:
    if isinstance(value, dict) and "x" in value and "y" in value:
        return (float(value["x"]), float(value["y"]))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    raise PlanningError("无法解析点目标: %r" % (value,))


def as_polygon(value) -> List[Point]:
    if isinstance(value, dict):
        value = value.get("polygon")
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise PlanningError("区域目标至少需要 3 个点")
    return [as_point(p) for p in value]


def as_route(value) -> List[Point]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise PlanningError("路线目标至少需要 2 个航点")
    return [as_point(p) for p in value]


def task_polygon(task: Task, keys: Sequence[str]) -> Optional[List[Point]]:
    for key in keys:
        if key in task.target:
            return as_polygon(task.target[key])
        if key in task.params:
            return as_polygon(task.params[key])
    return None


def task_route(task: Task) -> Optional[List[Point]]:
    if "route" in task.target:
        return as_route(task.target["route"])
    if "route" in task.params:
        return as_route(task.params["route"])
    return None


def task_point(task: Task, keys: Sequence[str]) -> Optional[Point]:
    for key in keys:
        if key in task.target:
            return as_point(task.target[key])
        if key in task.params:
            return as_point(task.params[key])
    return None


def _coordination(task: Task) -> List[str]:
    value = task.params.get("coordination", [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _split_bbox(polygon: Sequence[Sequence[float]], n: int) -> List[List[Point]]:
    if n <= 1:
        return [[(float(p[0]), float(p[1])) for p in polygon]]
    x0, y0, x1, y1 = bbox(polygon)
    width = (x1 - x0) / n
    if abs(width) < 1e-9:
        return [[(float(p[0]), float(p[1])) for p in polygon]]
    strips = []
    for i in range(n):
        left = x0 + i * width
        right = x0 + (i + 1) * width
        strips.append([(left, y0), (right, y0), (right, y1), (left, y1)])
    return strips


def _split_route(route: Sequence[Sequence[float]], n: int) -> List[List[Point]]:
    pts = [(float(p[0]), float(p[1])) for p in route]
    if n <= 1 or len(pts) <= 2:
        return [pts]
    n = min(n, len(pts) - 1)
    cuts = [int(round(i * (len(pts) - 1) / float(n))) for i in range(n + 1)]
    cuts[0], cuts[-1] = 0, len(pts) - 1
    for i in range(1, len(cuts)):
        if cuts[i] <= cuts[i - 1]:
            cuts[i] = cuts[i - 1] + 1
    segments = []
    for i in range(n):
        a, b = cuts[i], min(cuts[i + 1], len(pts) - 1)
        segment = pts[a:b + 1]
        if len(segment) >= 2:
            segments.append(segment)
    return segments or [pts]


def _perimeter_samples(polygon: Sequence[Sequence[float]], n: int) -> List[Point]:
    pts = [(float(p[0]), float(p[1])) for p in polygon]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if n <= 1:
        return [polygon_centroid(pts)]
    n = min(n, len(pts))
    step = len(pts) / float(n)
    return [pts[int(i * step)] for i in range(n)]


def _make_subtask(task: Task, index: int, target: Dict, duration_s: float,
                  coordination: Optional[List[str]] = None,
                  window: Optional[Tuple[float, float]] = None) -> Subtask:
    start, end = window if window else (task.window_start_s, task.window_end_s)
    return Subtask(
        subtask_id="%s-S%d" % (task.task_id, index),
        parent_task_id=task.task_id,
        index=index,
        task_type=task.task_type,
        target=target,
        required_capabilities=dict(task.required_capabilities),
        duration_s=float(duration_s),
        window_start_s=float(start),
        window_end_s=float(end),
        priority=task.priority,
        coordination=list(coordination or []),
        role="",
    )


def _units_for_split(task: Task, platforms: Sequence[Platform], limit: int = 4) -> int:
    """可拆分的槽位数：能力可达平台数，再受 allow_split / max_units 约束。

    M2 的区域/路线拆分不读 max_units，会出现“拆出 4 段但任务上限 2 台”
    的矛盾；这里显式取上限，避免生成超出兵力约束的槽位。
    """
    n = count_capable(platforms, task.required_capabilities)
    if not task.allow_split:
        return 1
    n = max(1, min(n, limit))
    if task.max_units is not None:
        n = min(n, int(task.max_units))
    return max(1, n)


def _decompose_rcn(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    duration = float(task.params.get("duration_s", 120.0))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)

    raw_list = task.target.get("target_list", task.params.get("target_list"))
    if raw_list is not None:
        if not isinstance(raw_list, (list, tuple)) or not raw_list:
            raise PlanningError("%s.target_list 不能为空" % task.task_id)
        return [_make_subtask(task, i + 1, {"point": list(as_point(p))},
                              duration, coordination=coordination)
                for i, p in enumerate(raw_list)]

    route = task_route(task)
    if route is not None:
        segments = _split_route(route, _units_for_split(task, platforms))
        return [_make_subtask(task, i + 1,
                              {"route": [list(p) for p in seg]},
                              duration, coordination=coordination)
                for i, seg in enumerate(segments)]

    area = task_polygon(task, ("area", "sector"))
    if area is not None:
        strips = _split_bbox(area, _units_for_split(task, platforms))
        return [_make_subtask(task, i + 1,
                              {"area": {"polygon": [list(p) for p in strip]}},
                              duration, coordination=coordination)
                for i, strip in enumerate(strips)]

    raise PlanningError("%s（T-RCN）缺少 area / route / target_list" % task.task_id)


def _decompose_sec(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    duration = float(task.params.get("hold_duration_s",
                                     task.params.get("duration_s", 600.0)))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)
    area = task_polygon(task, ("area", "defense_area", "sector"))
    if area is None:
        raise PlanningError("%s（T-SEC）缺少 area" % task.task_id)

    entry_points = task.params.get("entry_points", task.target.get("entry_points"))
    if entry_points:
        if not isinstance(entry_points, (list, tuple)) or not entry_points:
            raise PlanningError("%s.entry_points 不能为空" % task.task_id)
        points = [as_point(p) for p in entry_points]
    else:
        points = _perimeter_samples(area, _units_for_split(task, platforms))
    return [_make_subtask(task, i + 1, {"point": list(p)}, duration,
                          coordination=coordination)
            for i, p in enumerate(points)]


def _decompose_ptl(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    duration = float(task.params.get("duration_s", 300.0))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)
    if task.params.get("handover_points"):
        coordination = list(dict.fromkeys(coordination + ["handover"]))

    route = task_route(task)
    if route is not None:
        segments = _split_route(route, _units_for_split(task, platforms))
        return [_make_subtask(task, i + 1, {"route": [list(p) for p in seg]},
                              duration, coordination=coordination)
                for i, seg in enumerate(segments)]

    area = task_polygon(task, ("patrol_area", "area"))
    if area is not None:
        strips = _split_bbox(area, _units_for_split(task, platforms))
        return [_make_subtask(task, i + 1,
                              {"patrol_area": {"polygon": [list(p) for p in s]}},
                              duration, coordination=coordination)
                for i, s in enumerate(strips)]

    point = task_point(task, ("point", "key_point"))
    if point is not None:
        return [_make_subtask(task, 1, {"point": list(point)}, duration,
                              coordination=coordination)]

    raise PlanningError("%s（T-PTL）缺少 route / patrol_area / point" % task.task_id)


def _decompose_hld(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    duration = float(task.params.get("hold_duration_s",
                                     task.params.get("duration_s", 600.0)))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)

    positions = task.params.get("defense_positions",
                                task.target.get("defense_positions"))
    if positions:
        if not isinstance(positions, (list, tuple)) or not positions:
            raise PlanningError("%s.defense_positions 不能为空" % task.task_id)
        return [_make_subtask(task, i + 1, {"point": list(as_point(p))},
                              duration, coordination=coordination)
                for i, p in enumerate(positions)]

    point = task_point(task, ("key_point", "point"))
    if point is not None:
        return [_make_subtask(task, 1, {"point": list(point)}, duration,
                              coordination=coordination)]

    area = task_polygon(task, ("defense_area", "area"))
    if area is not None:
        center = polygon_centroid(area)
        return [_make_subtask(task, 1, {"point": list(center)}, duration,
                              coordination=coordination)]

    raise PlanningError("%s（T-HLD）缺少 key_point / defense_area / defense_positions"
                        % task.task_id)


_DECOMPOSERS = {
    "T-RCN": _decompose_rcn,
    "T-SEC": _decompose_sec,
    "T-PTL": _decompose_ptl,
    "T-HLD": _decompose_hld,
}


def _apply_slots(task: Task, items: List[Subtask]) -> List[Subtask]:
    """``params.slots``：把单点作业扩成多平台同点作业（仅运行适配器用）。

    4.1 原生的兵力数量靠区域/路线拆分或多阵位表达；基座 v2 的 crew 语义是
    “N 台平台合作同一作业”。从 v2 场景导入时用 slots 显式表达，避免凭空
    造出多个不同阵位。4.1 原生输入不会带这个参数。
    """
    slots = task.params.get("slots")
    if not isinstance(slots, int) or slots <= 1 or len(items) != 1:
        return items
    template = items[0]
    result = []
    for index in range(1, slots + 1):
        item = copy.deepcopy(template)
        item.subtask_id = "%s-S%d" % (task.task_id, index)
        item.index = index
        if "simultaneous_arrival" not in item.coordination:
            item.coordination = list(item.coordination) + ["simultaneous_arrival"]
        result.append(item)
    return result


def decompose(scenario: Scenario) -> List[Subtask]:
    subtasks = []
    by_task = {}
    for task in scenario.tasks:
        decomposer = _DECOMPOSERS.get(task.task_type)
        if decomposer is None:
            raise PlanningError("未知任务类型: %s" % task.task_type)
        items = decomposer(task, scenario.platforms)
        items = _apply_slots(task, items)
        if not items:
            raise PlanningError("%s 分解后没有子任务" % task.task_id)
        subtasks.extend(items)
        by_task[task.task_id] = items

    for task in scenario.tasks:
        dep_subtask_ids = []
        for dep_task_id in task.depends_on:
            dep_items = by_task.get(dep_task_id)
            if not dep_items:
                raise PlanningError("%s 依赖的任务 %s 没有子任务"
                                    % (task.task_id, dep_task_id))
            dep_subtask_ids.extend(s.subtask_id for s in dep_items)
        if dep_subtask_ids:
            for subtask in by_task[task.task_id]:
                subtask.depends_on = list(dep_subtask_ids)
    return subtasks


def task_target_points(task: Task) -> List[Point]:
    return target_points(task.target)
