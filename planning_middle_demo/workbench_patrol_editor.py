"""Map placement and planning preview for the workbench configuration editor."""

from copy import deepcopy
from dataclasses import replace
from math import dist, isfinite

import city_nav
from interop.gate import gate_platform
from interop.message import parse_message, target_points
from interop.runtime import OBJECTIVE_MAP
from interop.scheduler import Planner
from interop.templates import as_polygon, patrol_has_loop, patrol_loop, slot_keys, task_polygon
from workbench_target_editor import apply_targets, editor_targets


AREA_KEYS = ('area', 'patrol_area', 'defense_area', 'sector')
POINT_KEYS = {'point', 'key_point'}
POINT_LIST_PARAMS = ('checkpoints', 'search_points', 'entry_points', 'defense_positions',
                     'support_points', 'handover_points')
POINT_PARAMS = ('assembly_point', 'intercept_post', 'reserve_post', 'reserve_point',
                'relay_point', 'staging_center', 'assessment_post', 'withdraw_point')


def _check_settings(task):
    from behaviors import CN_AUTHORITY, CN_LEVELS, CN_OBJECTIVES, HL_CRITERIA

    params = task.params
    task_type = task.task_type

    def number(key, label, minimum, maximum=float('inf'), *, strict=False):
        if key not in params:
            return
        value = params[key]
        if (type(value) not in (int, float) or not isfinite(value) or value > maximum
                or (value <= minimum if strict else value < minimum)):
            bounds = ('大于' if strict else '不小于') + '%g' % minimum
            if isfinite(maximum):
                bounds += '且不超过%g' % maximum
            raise ValueError('%s · %s须%s' % (task.task_id, label, bounds))

    def choice(key, label, choices):
        if key in params and params[key] not in choices:
            raise ValueError('%s · 请选择有效的%s' % (task.task_id, label))

    if task_type == 'T-RCN':
        number('coverage_target', '侦察覆盖目标', 0, 1, strict=True)
        number('cell', '网格尺寸', 0, strict=True)
        number('search_limit_s', '侦察限时', 0, strict=True)
        number('search_deadline_s', '侦察截止时刻', task.window_start_s, strict=True)
        if 'sensor_radius_m' in params:
            radii = params['sensor_radius_m']
            if (not isinstance(radii, dict) or set(radii) != {'ground', 'air'}
                    or any(type(radius) not in (int, float) or not isfinite(radius) or radius <= 0
                           for radius in radii.values())):
                raise ValueError('%s · 地面和空中探测半径均须大于 0' % task.task_id)
    elif task_type == 'T-SEC':
        choice('control_objective', '控制目标', CN_OBJECTIVES)
        choice('target_start_mode', '目标出场方式', ('after_control', 'task_clock'))
        choice('control_level', '控制等级', CN_LEVELS)
        choice('engagement_authority', '授权类型', CN_AUTHORITY)
        number('max_leak_rate', '允许漏出率', 0, 1)
        number('sensor_radius_m', '探测半径', 0, strict=True)
        number('warning_response_s', '警告响应时间', 0)
        number('retreat_clearance_m', '撤离距离', 0, strict=True)
    elif task_type == 'T-HLD':
        choice('hold_criteria', '坚守判定口径', HL_CRITERIA)
        number('min_key_point_coverage', '最低覆盖率', 0, 1)
        number('sensor_radius_m', '探测半径', 0, strict=True)
        number('observation_ring_m', '观察环半径', 0, strict=True)
        minimum = params.get('min_on_post', 1)
        if type(minimum) is not int or minimum < 1:
            raise ValueError('%s · 最少在岗数须为正整数' % task.task_id)
    elif task_type == 'T-ASL' and task.params.get('_workbench_task'):
        if any(params[role]['count'] != 1 for role in ('scout', 'assessor')):
            raise ValueError('%s · 当前仿真各使用 1 个侦察席和 1 个评估席' % task.task_id)
    if task_type in ('T-SEC', 'T-HLD') and params.get('roles'):
        if not isinstance(params['roles'], dict) or any(
                type(count) is not int or count < 0 for count in params['roles'].values()):
            raise ValueError('%s · 角色席位数须为非负整数' % task.task_id)


def _bounds(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _edges(points, closed):
    return list(zip(points, points[1:] + points[:1] if closed else points[1:]))


def _intersects(left, right, left_area=False, right_area=False):
    lx, ly, hx, hy = _bounds(left)
    rx, ry, sx, sy = _bounds(right)
    if hx < rx or sx < lx or hy < ry or sy < ly:
        return False
    if left_area and any(city_nav.inside(p, left) for p in right):
        return True
    if right_area and any(city_nav.inside(p, right) for p in left):
        return True
    if len(left) == 1:
        return (city_nav.distance(left[0], right[0]) < 1e-6 if len(right) == 1
                else any(city_nav.point_segment(left[0], a, b) < 1e-6
                         for a, b in _edges(right, right_area)))
    if len(right) == 1:
        return any(city_nav.point_segment(right[0], a, b) < 1e-6
                   for a, b in _edges(left, left_area))
    return any(city_nav.segment_distance(a, b, c, d) < 1e-6
               for a, b in _edges(left, left_area) for c, d in _edges(right, right_area))


def _obstacles(scenario):
    return [(zone.get('source') or zone.get('constraint_id') or '禁入区',
             as_polygon(zone['area']))
            for zone in scenario.constraints if zone.get('type') == 'no_go' and zone.get('area')]


def task_geometry_error(task, scenario, obstacles):
    points = target_points(task.target)
    area = task_polygon(task, AREA_KEYS) or []
    loop = []
    if task.task_type == 'T-PTL' and patrol_has_loop(task):
        _, loop, _ = patrol_loop(task)
    bounds = scenario.meta.get('map_scene_bounds') or scenario.meta.get('scene_bounds')
    stations = []
    if task.task_type == 'T-HLD':
        withdrawal = task.params.get('withdraw')
        if isinstance(withdrawal, dict) and withdrawal.get('allowed', True):
            route = withdrawal.get('route') or []
            exit_point = route[-1] if route else task.params.get('assembly_point')
            if exit_point is not None:
                stations.append(('撤离终点', exit_point))
    elif task.task_type == 'T-ASL':
        for key, label in (('staging_center', '集结点'), ('assessment_post', '评估点'),
                           ('withdraw_point', '撤离点')):
            if task.params.get(key) is not None:
                stations.append((label, task.params[key]))
    if bounds:
        for label, (x, y) in [*(('任务点', point) for point in [*points, *loop]), *stations]:
            if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
                return label + '超出当前地图范围'
    if area:
        edges = _edges(area, True)
        if abs(city_nav.polygon_area(area)) < 1e-6 or any(
                city_nav.segment_distance(a, b, c, d) < 1e-6
                for i, (a, b) in enumerate(edges) for c, d in edges[i + 2:]
                if len({a, b, c, d}) == 4):
            return '任务区域需要三个以上有效顶点，且边界不能自交'
    # A no-go polygon inside the patrol area is fine when the loop stays outside it.
    for name, polygon in obstacles:
        if not polygon:
            continue
        if loop and any(_intersects([a, b], polygon, right_area=True) for a, b in _edges(loop, True)):
            return '巡逻路线经过禁入区「%s」，请调整巡逻点' % name
        if any(city_nav.inside(point, polygon) for point in points):
            return '任务点位于禁入区「%s」' % name
        for label, point in stations:
            if (city_nav.inside(point, polygon) or
                    any(city_nav.point_segment(point, a, b) < 1.5 for a, b in _edges(polygon, True))):
                return '%s距禁入区「%s」过近，请调整位置' % (label, name)
    tracking = task.params.get('tracking_target')
    if task.task_type == 'T-RCN' and area and tracking:
        if not city_nav.inside(tracking['start'], area) or city_nav.inside(tracking['goal'], area):
            return '跟踪目标需要从侦察区内驶向区外'
    return ''


def _footprint(task):
    area = task_polygon(task, AREA_KEYS)
    if area:
        return area, True
    points = target_points(task.target)
    if task.task_type == 'T-ASL' and len(points) == 1 and task.params.get('objective_radius', 0) > 0:
        x, y = points[0]
        radius = task.params['objective_radius']
        return [(x - radius, y - radius), (x + radius, y - radius),
                (x + radius, y + radius), (x - radius, y + radius)], True
    if task.task_type == 'T-HLD' and len(points) == 1 and task.params.get('positions'):
        posts = [row['point'] for row in task.params['positions'] if row.get('point')]
        if posts:
            x0, y0, x1, y1 = _bounds(points + posts)
            if x1 > x0 and y1 > y0:
                return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True
    return points, False


def _overlaps(task, tasks):
    points, is_area = _footprint(task)
    if not points:
        return []
    overlaps = []
    for other in tasks:
        if (other.task_id == task.task_id or
                max(other.window_start_s, task.window_start_s) >= min(other.window_end_s, task.window_end_s)):
            continue
        other_points, other_area = _footprint(other)
        if other_points and _intersects(points, other_points, is_area, other_area):
            overlaps.append(other.task_id)
    return overlaps


def _move_task(task, center, origin, ratio):
    def point(value):
        return [round(center[i] + (value[i] - origin[i]) * ratio, 3) for i in range(2)]

    def points(values):
        return [point(value) for value in values]

    target = dict(task.target)
    for key, value in target.items():
        if key in POINT_KEYS:
            target[key] = point(value)
        elif key in AREA_KEYS and isinstance(value, dict):
            target[key] = dict(value, polygon=points(value['polygon']))
        elif key in AREA_KEYS or key in ('route', 'target_list', 'entry_points'):
            target[key] = points(value)
    params = deepcopy(task.params)
    changed = {}
    for key in POINT_PARAMS:
        if params.get(key) is not None:
            changed[key] = point(params[key])
    for key in POINT_LIST_PARAMS:
        if params.get(key):
            changed[key] = points(params[key])
    if params.get('search_starts'):
        changed['search_starts'] = {unit: point(value) for unit, value in params['search_starts'].items()}
    for key in ('gates', 'positions', 'intruders'):
        if params.get(key):
            changed[key] = [{**entry, **{name: point(entry[name]) for name in ('point', 'start', 'goal')
                                       if entry.get(name) is not None}} for entry in params[key]]
    for key in ('tracking_target', 'observation_target', 'relay_target'):
        if isinstance(params.get(key), dict):
            entry = params[key]
            changed[key] = {**entry, **{name: point(entry[name]) for name in ('point', 'start', 'goal')
                                       if entry.get(name) is not None}}
    if isinstance(params.get('withdraw'), dict) and params['withdraw'].get('route'):
        changed['withdraw'] = dict(params['withdraw'], route=points(params['withdraw']['route']))
    return replace(task, target=target, params=dict(params, **changed)), changed


def _center(points):
    x0, y0, x1, y1 = _bounds(points)
    return (x0 + x1) / 2, (y0 + y1) / 2


def _recommendations(task, scenario, existing, obstacles):
    points, _ = _footprint(task)
    x0, y0, x1, y1 = _bounds(points)
    width, height = max(x1 - x0, 1), max(y1 - y0, 1)
    origin = _center(target_points(task.target))
    poses = [p.position for p in scenario.platforms if p.status == 'READY']
    poses = poses or [p.position for p in scenario.platforms]
    px, py = (sum(axis) / len(poses) for axis in zip(*poses))
    preferred = origin if task.task_type == 'T-ASL' else (px, py)
    bounds = scenario.meta.get('map_scene_bounds') or scenario.meta.get('scene_bounds')
    if bounds:
        xlo, ylo, xhi, yhi = bounds
        width_ratio = min(1, (xhi - xlo) * 0.8 / width, (yhi - ylo) * 0.8 / height)
    else:
        # Synthetic maps use their own coordinate scale and often have no declared extent.
        anchors = poses + [p for other in existing if other.task_id != task.task_id
                           for p in target_points(other.target)]
        xlo, ylo, xhi, yhi = _bounds(anchors)
        span = max(xhi - xlo, yhi - ylo, 16 / scenario.cell_size_m)
        width_ratio = min(1, span / max(width, height))
        xlo, ylo, xhi, yhi = xlo - span, ylo - span, xhi + span, yhi + span
    centers = {origin, (px, py)}
    centers.update((xlo + (xhi - xlo) * i / 10, ylo + (yhi - ylo) * j / 10)
                   for i in range(1, 10) for j in range(1, 10))
    if task.task_type == 'T-ASL':
        centers.update((origin[0] + i * width, origin[1] + j * height)
                       for i in range(-2, 3) for j in range(-2, 3))
    candidates = []
    for x, y in sorted(centers):
        candidate, changed = _move_task(task, (x, y), origin, width_ratio)
        if not task_geometry_error(candidate, scenario, obstacles):
            overlap = _overlaps(candidate, existing)
            score = len(overlap), (x - preferred[0]) ** 2 + (y - preferred[1]) ** 2
            candidates.append((score, candidate, changed, overlap))
    return sorted(candidates, key=lambda entry: entry[0])


def _task_assignments(plan, task, slots):
    rows = [row for row in plan.assignments if row.parent_task_id == task.task_id]
    unassigned = {row['subtask_id']: row['detail'] for row in plan.unassigned
                  if row['parent_task_id'] == task.task_id}
    for slot in slots:
        if slot.parent_task_id == task.task_id and slot.pinned_class and slot.subtask_id in unassigned:
            return rows, '%s 席位无法分配 %s 类平台。%s' % (
                slot.role, slot.pinned_class, unassigned[slot.subtask_id])
    if len(rows) < task.min_units:
        return rows, next(iter(unassigned.values()), '符合要求的可用平台不足')
    if task.task_type == 'T-HLD' and task.params.get('min_on_post') and sum(
            row.role.startswith('post:') for row in rows) < task.params['min_on_post']:
        return rows, '实际可分配的阵位少于最少在岗数'
    return rows, ''


def _pending_scenario(scenario, now, occupied, completed):
    active = {}
    busy = {}
    for row in occupied:
        active[row['task_id']] = max(active.get(row['task_id'], 0), row['end_s'])
        busy[row['unit_id']] = max(busy.get(row['unit_id'], 0), row['end_s'])
    platforms = [replace(platform, busy_until_s=max(now, busy.get(platform.unit_id, 0)))
                 for platform in scenario.platforms]
    tasks = [replace(task,
                     window_start_s=max(now, task.window_start_s,
                                        *(active.get(dep, 0) for dep in task.depends_on)),
                     depends_on=[dep for dep in task.depends_on if dep not in active and dep not in completed])
             for task in scenario.tasks if task.task_id not in active and task.task_id not in completed]
    return replace(scenario, tasks=tasks, platforms=platforms)


def preview_task(data):
    now = data.get('now', 0)
    if type(now) is not int or now < 0:
        raise ValueError('无效的配置时刻')
    message = data.get('message')
    completed = set(data.get('completed', []))
    if isinstance(message, dict) and 'targets' in data:
        message = dict(message, tasks=apply_targets(message.get('tasks'), data['targets'],
                                                   skip_task_ids=completed))
    scenario = parse_message(message, data.get('formation'))
    task = next((task for task in scenario.tasks if task.task_id == data.get('task_id')), None)
    if task is None:
        raise ValueError('请选择需要试算的任务')
    if task.window_end_s <= now:
        raise ValueError('任务时间窗已结束，请调整结束时间')
    _check_settings(task)
    occupied = data.get('occupied', [])
    if not isinstance(occupied, list) or any(
            not isinstance(row, dict) or not isinstance(row.get('task_id'), str)
            or not isinstance(row.get('unit_id'), str)
            or type(row.get('end_s')) not in (int, float) or not isfinite(row['end_s'])
            for row in occupied):
        raise ValueError('平台占用信息无效')
    occupied = [row for row in occupied if row['task_id'] != task.task_id]
    pending = _pending_scenario(scenario, now, occupied, completed - {task.task_id})
    task = next(item for item in pending.tasks if item.task_id == task.task_id)
    obstacles = _obstacles(scenario)
    existing = [item for item in scenario.tasks if item.task_id not in completed]
    center = data.get('center')
    if center is not None:
        if not isinstance(center, list) or len(center) != 2 or not all(
                type(value) in (int, float) and isfinite(value) for value in center):
            raise ValueError('地图选点无效')
        placed, changed = _move_task(task, center, _center(target_points(task.target)), 1)
        choices = [(None, placed, changed, _overlaps(placed, existing))]
    else:
        candidates = _recommendations(task, scenario, existing, obstacles) if data.get('recommend') else []
        choices = candidates[:6] or [(None, task, {}, _overlaps(task, existing))]
    best = None
    for _, candidate, changed, overlap in choices:
        error = task_geometry_error(candidate, scenario, obstacles)
        if error:
            return _preview_result(candidate, changed, overlap, [], error)
        planner = Planner(replace(pending, tasks=[candidate if item.task_id == task.task_id else item
                                                 for item in pending.tasks]),
                          objective=OBJECTIVE_MAP.get(data.get('objective'), 'timeliness'))
        rows, error = _task_assignments(planner.plan(), candidate, planner.subtasks)
        if best is None or not error:
            best = candidate, changed, overlap, planner, rows, error
        if not error:
            break
    candidate, changed, overlap, planner, rows, error = best
    slots = [slot for slot in planner.subtasks if slot.parent_task_id == candidate.task_id]
    assigned = {row.subtask_id: row for row in rows}
    slot_choices = []
    for key, slot in zip(slot_keys(slots), slots):
        row = assigned.get(slot.subtask_id)
        unpinned = replace(slot, pinned_unit="", pinned_class="")
        compatible = [p.unit_id for p in scenario.platforms if gate_platform(p, unpinned, scenario)[0]]
        slot_choices.append(dict(key=key, role=slot.role, pinned_unit=slot.pinned_unit,
                                 pinned_class=slot.pinned_class,
                                 point=next(iter(target_points(slot.target)), None),
                                 unit_id=row.unit_id if row else None,
                                 start_s=row.start_s if row else None, eligible=compatible))
    timing = _preview_timing(candidate, rows, scenario.platforms, data.get('max_ticks'))
    return _preview_result(candidate, changed, overlap, slot_choices, error, timing)


def _preview_timing(task, rows, platforms, horizon):
    if not rows or task.task_type not in ('T-HLD', 'T-SEC', 'T-RCN'):
        return None
    params = task.params
    ready = max(row.start_s for row in rows)
    finish = max(row.end_s for row in rows)
    release = None
    warnings = []
    by_id = {p.unit_id: p for p in platforms}
    if task.task_type == 'T-HLD':
        withdrawal = params.get('withdraw')
        if isinstance(withdrawal, dict) and withdrawal.get('allowed', True):
            finish += float(withdrawal.get('deadline_s') or 30)
            route = withdrawal.get('route') or []
            release = route[-1] if route else params.get('assembly_point') or (
                next(iter(target_points(task.target)), None))
    elif task.task_type == 'T-SEC':
        intruders = params.get('intruders') or []
        gated = params.get('target_start_mode') == 'after_control'
        if intruders and gated:
            duration = float(params.get('hold_duration_s', params.get('duration_s', 600)))
            available = min(duration, task.window_end_s - ready)
            if any(target.get('t_start_s', 0) >= available for target in intruders):
                warnings.append('部分目标的出场延时超过预计封控时段，请延长时段或缩短延时。')
        elif any(task.window_start_s + target.get('t_start_s', 0) < ready
                 for target in intruders):
            warnings.append('固定计时下，目标可能先于席位到位。可改为封控建立后出场。')
    elif (params.get('tracking_target') or {}).get('track_until_stop'):
        target = params['tracking_target']
        earliest = target['move_after_s'] + dist(target['start'], target['goal']) / target['speed_mps']
        if any(by_id[row.unit_id].is_air for row in rows):
            earliest += target.get('stop_orbit_s', 18.0)
        search_limit = min(float(params.get('search_limit_s', float('inf'))),
                           float(params.get('search_deadline_s', task.window_end_s))
                           - task.window_start_s)
        if earliest > search_limit:
            warnings.append('当前侦察限时可能不足以完成目标移动和停点盘旋，请调整时间或速度。')
    direct_returns = []
    for row in rows:
        platform = by_id[row.unit_id]
        point = release or next(iter(target_points(row.target)), None)
        if point is not None and platform.speed_mps > 0:
            direct_returns.append(dist(point, platform.position) / platform.speed_mps)
    home = finish + max(direct_returns, default=0)
    if finish > task.window_end_s:
        warnings.append('当前任务时间窗可能不足，请给进场、作业和撤离留出时间。')
    if type(horizon) in (int, float) and isfinite(horizon) and horizon < home:
        warnings.append('当前仿真总时长可能不足以显示完整返航，请适当延长。')
    return dict(ready_s=ready, finish_s=finish, home_s=home, warnings=warnings)


def _preview_result(task, changed, overlap, slots, error, timing=None):
    red_targets = editor_targets({'tasks': [dict(task_id=task.task_id, task_type=task.task_type,
                                               target=task.target, params=task.params)]})
    return dict(target=task.target, geometry_params=changed, targets=red_targets,
                checkpoints=task.params.get('checkpoints'), overlap=overlap, slots=slots, error=error,
                timing=timing)


def check_task_drafts(scenario, task_ids=None, objective='timeliness', *,
                        now=0, occupied=(), completed=(), excluded=(), geometry_task_ids=None):
    drafts = [task for task in scenario.tasks
               if (task.params.get('_workbench_task') or task.params.get('_workbench_patrol'))
               and (task_ids is None or task.task_id in task_ids)]
    if not drafts:
        return
    obstacles = _obstacles(scenario)
    for task in drafts:
        _check_settings(task)
        error = (task_geometry_error(task, scenario, obstacles)
                 if geometry_task_ids is None or task.task_id in geometry_task_ids else '')
        if error:
            raise ValueError('%s · %s' % (task.task_id, error))
        unavailable = set(task.depends_on).intersection(excluded)
        if unavailable:
            raise ValueError('%s · 前置任务未纳入本轮：%s' % (task.task_id, '、'.join(sorted(unavailable))))
    relevant = replace(scenario, tasks=[task for task in scenario.tasks if task.task_id not in excluded])
    pending = _pending_scenario(relevant, now, occupied, completed)
    planner = Planner(pending, objective=objective)
    plan = planner.plan()
    for task in drafts:
        if task.task_id in completed:
            continue
        _, error = _task_assignments(plan, task, planner.subtasks)
        if error:
            raise ValueError('%s · %s' % (task.task_id, error))


preview_patrol = preview_task
