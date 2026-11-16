# -*- coding: utf-8 -*-
"""Deterministic, map-aware task placement for desktop runs.

Task templates define the operation geometry and timing. This module moves
their spatial anchors onto obstacle-free road nodes of one authoritative urban
map while preserving the relative geometry of each task. A persisted seed
makes every generated input reproducible.
"""

from copy import deepcopy
import math
import random
import secrets
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .geometry import point_in_polygon, polygon_centroid
from .urban_maps import _frame, _map_items, _point


Point = Tuple[float, float]


def _box(points, padding=0.0):
    points = list(points)
    return (min(p[0] for p in points)-padding, min(p[1] for p in points)-padding,
            max(p[0] for p in points)+padding, max(p[1] for p in points)+padding)


def _task_box(task):
    from .message import target_points
    points = target_points(task['target'])
    # Include the extent of point missions, rather than spacing only centers.
    params = task.get('params') or {}
    padding = 20.0 if len(points) == 1 else 0.0
    if task['task_type'] == 'T-HLD':
        padding = max(padding, float(params.get('defense_radius', params.get('radius', 35))))
    return _box(points, padding)


def _box_gap(a, b):
    return math.hypot(max(0, a[0]-b[2], b[0]-a[2]),
                      max(0, a[1]-b[3], b[1]-a[3]))


def randomize_threats(formation, message, map_id, seed, start_point=None):
    """Place threat footprints apart; preserve identities, scopes and intensities."""
    result = deepcopy(formation)
    nodes, _, bounds = _candidate_nodes(map_id)
    order = list(nodes)
    random.Random(int(seed) ^ 0x51A7).shuffle(order)
    occupied = [_task_box(task) for task in message['tasks']]
    if start_point is not None:
        occupied.append(_box([start_point], 30))
    placements = []
    for zone in result.get('constraints', []):
        if zone.get('type') != 'threat':
            continue
        area = zone.get('area')
        polygon = area.get('polygon') if isinstance(area, dict) else area
        if not polygon:
            continue
        center = polygon_centroid(polygon)
        candidates = []
        for node in order:
            moved = _translate_points(polygon, node[0]-center[0], node[1]-center[1])
            if not all(_inside_bounds(p, bounds) for p in moved):
                continue
            box = _box(moved)
            gap = min((_box_gap(box, old) for old in occupied), default=1000)
            candidates.append((gap, moved, box))
            if gap >= 25:
                break
        if not candidates:
            raise ValueError('当前地图无法容纳威胁区 '+str(zone.get('constraint_id')))
        gap, moved, box = max(candidates, key=lambda item:item[0])
        zone['area'] = dict(area, polygon=moved) if isinstance(area, dict) else moved
        occupied.append(box)
        placements.append(dict(constraint_id=zone.get('constraint_id'), clearance_m=round(gap,3)))
    result.setdefault('meta', {})['threat_randomization'] = dict(seed=int(seed), placements=placements)
    return result


def new_task_seed() -> int:
    """Return a positive seed suitable for the 32-bit desktop field."""
    return secrets.randbelow(2147483646) + 1


def _pair(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value
        )
    )


def _translate_point(value: Any, dx: float, dy: float) -> Any:
    if not _pair(value):
        return value
    return [round(float(value[0]) + dx, 3), round(float(value[1]) + dy, 3)]


def _translate_points(value: Any, dx: float, dy: float) -> Any:
    if _pair(value):
        return _translate_point(value, dx, dy)
    if isinstance(value, dict):
        return {
            key: _translate_points(item, dx, dy)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_translate_points(item, dx, dy) for item in value]
    return value


def _task_anchor(task: Dict[str, Any]) -> Sequence[float]:
    target = task.get("target") or {}
    task_type = task.get("task_type")
    if task_type == "T-SEC":
        polygon = target.get("defense_area") or target.get("area")
        if isinstance(polygon, dict):
            polygon = polygon.get('polygon')
        if isinstance(polygon, list) and len(polygon) >= 3:
            return polygon_centroid(polygon)
    if task_type == "T-PTL":
        polygon = target.get("patrol_area") or target.get("area")
        if isinstance(polygon, dict):
            polygon = polygon.get('polygon')
        if isinstance(polygon, list) and len(polygon) >= 3:
            return polygon_centroid(polygon)
        route = target.get("route") or []
        if route and _pair(route[0]):
            return tuple(route[0])
    if task_type == "T-RCN":
        polygon = target.get("area")
        if isinstance(polygon, dict):
            polygon = polygon.get('polygon')
        if isinstance(polygon, list) and len(polygon) >= 3:
            return polygon_centroid(polygon)
        params = task.get("params") or {}
        points = (target.get("target_list") or
                  params.get("search_points") or
                  list((params.get("search_starts") or {}).values()))
        if points and _pair(points[0]):
            return tuple(points[0])
    if task_type == "T-HLD":
        return tuple(target.get("key_point") or (0.0, 0.0))
    if task_type == "T-ASL":
        if "point" in target:
            return tuple(target["point"])
        if "key_point" in target:
            return tuple(target["key_point"])
        values = target.get("target_list") or []
        if values:
            return tuple(values[0])
    raise ValueError("地图随机化不支持任务类型：%s" % task_type)


def _translate_task(task: Dict[str, Any], dx: float, dy: float) -> None:
    task["target"] = _translate_points(task.get("target") or {}, dx, dy)
    params = task.get("params")
    if not isinstance(params, dict):
        return
    task_type = task.get("task_type")
    direct_points = {
        "T-SEC": ("intercept_post",),
        "T-HLD": ("assembly_point",),
        "T-ASL": (
            "staging_center",
            "assessment_post",
            "withdraw_point",
        ),
    }.get(task_type, ())
    for key in direct_points:
        if key in params:
            params[key] = _translate_point(params[key], dx, dy)

    if task_type == "T-SEC":
        for gate in params.get("gates") or []:
            gate["point"] = _translate_point(gate.get("point"), dx, dy)
        for target in params.get("intruders") or []:
            for key in ("start", "goal"):
                if key in target:
                    target[key] = _translate_point(target[key], dx, dy)
    elif task_type == "T-PTL":
        target = params.get("observation_target") or {}
        for key in ("start", "goal"):
            if key in target:
                target[key] = _translate_point(target[key], dx, dy)
    elif task_type == "T-RCN":
        starts = params.get("search_starts")
        if isinstance(starts, dict):
            for unit_id, point in list(starts.items()):
                starts[unit_id] = _translate_point(point, dx, dy)
        if isinstance(params.get("search_points"), list):
            params["search_points"] = [
                _translate_point(point, dx, dy)
                for point in params["search_points"]
            ]
        for key in ("tracking_target", "relay_target"):
            target = params.get(key) or {}
            for point_key in ("start", "goal"):
                if point_key in target:
                    target[point_key] = _translate_point(
                        target[point_key], dx, dy
                    )
    elif task_type == "T-HLD":
        for position in params.get("positions") or []:
            if "point" in position:
                position["point"] = _translate_point(
                    position["point"], dx, dy
                )
        withdraw = params.get("withdraw") or {}
        if "route" in withdraw:
            withdraw["route"] = _translate_points(
                withdraw["route"], dx, dy
            )


def _clear_points(task: Dict[str, Any]) -> Iterable[Sequence[float]]:
    """Yield points that should be on the traversable road network."""
    target = task.get("target") or {}
    task_type = task.get("task_type")
    params = task.get("params") or {}
    if task_type == "T-HLD" and "key_point" in target:
        yield target["key_point"]
    elif task_type == "T-ASL":
        for key in ("point", "key_point"):
            if key in target:
                yield target[key]
                break
        else:
            for point in target.get("target_list") or []:
                yield point
    elif task_type == "T-PTL":
        # A patrol area may span buildings, but each concrete checkpoint is a
        # platform destination.  Choosing a road node as the task anchor does
        # not prove that the translated polygon vertices are also clear; one
        # vertex inside a building makes that seat impossible to route and the
        # whole four-platform patrol is rejected before launch.
        polygon = target.get("patrol_area") or target.get("area")
        if polygon:
            yield from _collect_polygon_vertices(polygon)
        route = target.get("route") or []
        yield from _collect_polygon_vertices(route)
        yield from _collect_polygon_vertices(params.get("checkpoints") or [])

    if task_type == "T-SEC":
        if "intercept_post" in params:
            yield params["intercept_post"]
        for gate in params.get("gates") or []:
            if "point" in gate:
                yield gate["point"]
    elif task_type == "T-RCN":
        for point in (params.get("search_starts") or {}).values():
            yield point
    elif task_type == "T-HLD":
        for position in params.get("positions") or []:
            if "point" in position:
                yield position["point"]
        withdraw = params.get("withdraw") or {}
        for point in withdraw.get("route") or []:
            yield point
    elif task_type == "T-ASL":
        for key in ("staging_center", "assessment_post", "withdraw_point"):
            if key in params:
                yield params[key]


def _collect_polygon_vertices(value: Any) -> Iterable[Sequence[float]]:
    if _pair(value):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _collect_polygon_vertices(item)
    elif isinstance(value, list):
        for item in value:
            for point in _collect_polygon_vertices(item):
                yield point


def _parameter_points(value: Any) -> Iterable[Sequence[float]]:
    """Read coordinate fields, never interpreting directions/times as poses."""
    point_keys = {'point', 'key_point', 'center', 'start', 'goal',
                  'intercept_post', 'staging_center', 'assessment_post',
                  'withdraw_point', 'assembly_point'}
    path_keys = {'route', 'search_points', 'search_starts'}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in point_keys and _pair(item):
                yield item
            elif key in path_keys:
                yield from _collect_polygon_vertices(item)
            elif isinstance(item, (dict, list)):
                yield from _parameter_points(item)
    elif isinstance(value, list):
        for item in value:
            yield from _parameter_points(item)


def task_boundary_points(task: Dict[str, Any]) -> Iterable[Sequence[float]]:
    """Full authored geometry plus the circular motion envelope.

    A valid center alone does not establish that the task fits on the map.
    Axis extrema suffice for circles inside an axis-aligned map rectangle.
    """
    yield from _collect_polygon_vertices(task.get('target') or {})
    params = task.get('params') or {}
    yield from _parameter_points(params)
    defaults = {'T-SEC': 55.0, 'T-HLD': 45.0}
    radius = max(0.0, float(params.get('air_orbit_radius_m') or
                            defaults.get(task.get('task_type'), 0.0)))
    if radius:
        x, y = _task_anchor(task)
        for dx, dy in ((radius, 0), (-radius, 0), (0, radius), (0, -radius)):
            yield (x + dx, y + dy)


def validate_task_bounds(message: Dict[str, Any], map_id: str) -> None:
    """Reject invalid manual input before creating a worker/run directory."""
    bounds = _map_items(map_id)['bounds']
    for task in message.get('tasks') or []:
        for point in task_boundary_points(task):
            if not _inside_bounds(point, bounds):
                raise ValueError(
                    '任务 %s 的区域或活动范围超出地图边界：'
                    '点 (%.3f, %.3f)，地图范围 %s（预留 5 米边距）。'
                    % (task.get('task_id'), point[0], point[1], bounds))


def _inside_bounds(point: Sequence[float], bounds: Sequence[float],
                   margin: float = 5.0) -> bool:
    return (
        float(bounds[0]) + margin <= float(point[0]) <= float(bounds[2]) - margin
        and float(bounds[1]) + margin <= float(point[1]) <= float(bounds[3]) - margin
    )


def _candidate_nodes(
    map_id: str,
) -> Tuple[List[Point], List[List[List[float]]], List[float]]:
    frame = _frame(map_id)
    geometry = _map_items(map_id)
    obstacles = [
        item["polygon"] for item in geometry.get("obstacles") or []
    ]
    nodes = []
    seen = set()

    def add(point: Sequence[float]) -> None:
        converted = tuple(round(float(value), 3) for value in point)
        if converted in seen:
            return
        if not _inside_bounds(converted, geometry["bounds"]):
            return
        if any(point_in_polygon(converted, polygon) for polygon in obstacles):
            return
        seen.add(converted)
        nodes.append(converted)

    for raw in frame["doc"].get("nodes") or []:
        add(_point(raw, frame))
    source_nodes = frame["doc"].get("nodes") or []
    for road in frame["doc"].get("roads") or []:
        start = source_nodes[int(road["a"])]
        end = source_nodes[int(road["b"])]
        for fraction in (0.18, 0.32, 0.5, 0.68, 0.82):
            source = [
                float(start[0]) + (float(end[0]) - float(start[0])) * fraction,
                float(start[1]) + (float(end[1]) - float(start[1])) * fraction,
            ]
            add(_point(source, frame))
    if not nodes:
        raise ValueError("地图没有可用于随机任务点的道路节点：%s" % map_id)
    return nodes, obstacles, geometry["bounds"]


def _valid_placement(
    tasks: Sequence[Dict[str, Any]],
    obstacles: Sequence[Sequence[Sequence[float]]],
    bounds: Sequence[float],
) -> bool:
    for task in tasks:
        for point in _clear_points(task):
            if not _inside_bounds(point, bounds):
                return False
            if any(point_in_polygon(point, polygon) for polygon in obstacles):
                return False
        for vertex in task_boundary_points(task):
            if not _inside_bounds(vertex, bounds):
                return False
    return True


def randomize_message(
    message: Dict[str, Any],
    map_id: str,
    seed: int,
    scenario_key: str = "", start_point=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Move task geometry onto clear roads of ``map_id``.

    The original relative geometry is retained. Relay tasks move as one group
    because their phases exchange the same target object.
    """
    result = deepcopy(message)
    tasks = result.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("任务消息缺少 tasks，不能生成随机任务点")
    nodes, obstacles, bounds = _candidate_nodes(map_id)
    rng = random.Random(
        (int(seed) << 32)
        ^ sum(
            (index + 1) * ord(char)
            for index, char in enumerate(map_id + ":" + scenario_key)
        )
    )
    order = list(nodes)
    rng.shuffle(order)
    existing_meta = result.get("_meta") or {}
    existing_placement = existing_meta.get("task_placement") or {}
    previous = {
        str(item.get("task_id")): item
        for item in existing_placement.get("placements") or []
    }

    def source_anchor(task: Dict[str, Any]) -> Sequence[float]:
        previous_item = previous.get(str(task.get("task_id"))) or {}
        stored = previous_item.get("source_anchor")
        return tuple(stored) if stored else _task_anchor(task)

    selected: List[Point] = []
    boxes = []
    placements = []
    origin = start_point or source_anchor(tasks[0])
    far_distance = max(160.0, math.hypot(bounds[2]-bounds[0], bounds[3]-bounds[1]) * .30)
    # Send a non-dependent mission farther out; dependent targets keep their links.
    independent = [t for t in tasks if not t.get('depends_on') and not t.get('prerequisites')]
    area_tasks = [t for t in independent if any(key in t.get('target', {})
                 for key in ('area', 'patrol_area', 'defense_area', 'sector', 'route'))]
    far_task = (area_tasks or independent or tasks)[-1]['task_id'] if len(tasks)>1 else None
    for task in tasks:
        template_anchor = source_anchor(task)
        anchor = _task_anchor(task)
        chosen = None
        distance = lambda p: math.hypot(p[0]-origin[0], p[1]-origin[1])
        remote = task['task_id'] == far_task
        ranked = sorted(order, key=lambda p: (
            0 if not remote or distance(p)>=far_distance else 1,
            -int(min(200, min((math.dist(p,old) for old in selected),default=0))/40),
            int(abs(distance(p)-(far_distance if remote else 120))/60)))
        choices = []
        for candidate in ranked:
            dx = candidate[0] - float(anchor[0])
            dy = candidate[1] - float(anchor[1])
            trial = deepcopy(task)
            _translate_task(trial, dx, dy)
            box = _task_box(trial)
            gap = min((_box_gap(box, old) for old in boxes), default=1000)
            if _valid_placement([trial], obstacles, bounds):
                if boxes and gap < 20:
                    choices.append((gap, candidate, box))
                    continue
                chosen = candidate
                boxes.append(box)
                break
        if chosen is None and choices:
            _, chosen, box = max(choices, key=lambda item:item[0])
            boxes.append(box)
        if chosen is None:
            raise ValueError(
                "当前地图种子无法为任务 %s 生成无遮挡任务点"
                % task.get("task_id")
            )
        dx = chosen[0] - float(anchor[0])
        dy = chosen[1] - float(anchor[1])
        _translate_task(task, dx, dy)
        selected.append(chosen)
        placements.append({
            "task_id": task.get("task_id"),
            "anchor": list(chosen),
            "source_anchor": list(template_anchor),
            "distance_from_start_m": round(distance(chosen),3),
            "remote": remote,
        })

    result.setdefault("_meta", {})["task_placement"] = {
        "algorithm": "urban-road-spread-v2",
        "map_id": map_id,
        "seed": int(seed),
        "placements": placements,
    }
    return result, result["_meta"]["task_placement"]
