# -*- coding: utf-8 -*-
"""五类任务的分解规则（T-RCN / T-SEC / T-PTL / T-HLD / T-ASL）。

沿用 M2 的槽位思路：一个父任务按“区域竖条 / 路线分段 / 入口点 / 阵位点”
拆成若干可独立执行的单平台子任务；父任务依赖在末尾展开为子任务之间的
完成到开始依赖。T-ASL 额外按侦察/突击/评估三类角色拆槽位，打击与效果
判定仍由执行层承担。
"""

import copy
import math

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .errors import PlanningError
from .geometry import bbox, polygon_centroid
from .message import target_point, target_points
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


SEC_ROLE_KEYS = ("boundary", "gate", "intercept", "reserve", "air")
SEC_DEFAULT_ROLES = {"boundary": 2, "gate": 1, "intercept": 1,
                     "reserve": 0, "air": 0}


def _sec_roles(task: Task) -> Dict[str, int]:
    """占位组/门哨/机动拦截组/预备队的台数（1028 §2.2.3 兵力组成）。

    4.1 原生输入用 ``params.roles`` 显式给出；未给出时按入口/边界段自动配：
    有入口点就"每入口 1 台 + 剩余做边界段 + 至少 1 台机动拦截"。
    """
    raw = task.params.get("roles")
    if isinstance(raw, dict) and raw:
        roles = {}
        for key in SEC_ROLE_KEYS:
            value = raw.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PlanningError("%s.roles.%s 必须是整数" % (task.task_id, key))
            roles[key] = max(0, int(value))
        unknown = [k for k in raw if k not in SEC_ROLE_KEYS]
        if unknown:
            raise PlanningError("%s.roles 含未知角色 %s（可选 %s）"
                                % (task.task_id, unknown, "/".join(SEC_ROLE_KEYS)))
        if sum(roles.values()) <= 0:
            raise PlanningError("%s.roles 台数合计必须大于 0" % task.task_id)
        return roles
    gates = task.params.get("gates") or []
    gate_count = len(gates) if isinstance(gates, list) else 0
    if gate_count:
        return {"boundary": 0, "gate": gate_count, "intercept": 1,
                "reserve": 0, "air": 0}
    return dict(SEC_DEFAULT_ROLES)


def _sec_gates(task: Task) -> List[Dict]:
    """通道口列表：``{gate_id, point, width, direction, authorized_classes}``。"""
    raw = task.params.get("gates")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)) or not raw:
        raise PlanningError("%s.gates 必须是非空数组" % task.task_id)
    gates = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or "point" not in item:
            raise PlanningError("%s.gates[%d] 必须给出 point" % (task.task_id, index))
        point = as_point(item["point"])
        direction = item.get("direction") or [0.0, 1.0]
        if not isinstance(direction, (list, tuple)) or len(direction) != 2:
            raise PlanningError("%s.gates[%d].direction 必须是 [dx, dy]"
                                % (task.task_id, index))
        gates.append(dict(
            gate_id=str(item.get("gate_id") or "G%d" % (index + 1)),
            point=[point[0], point[1]],
            width=float(item.get("width", 12.0)),
            direction=[float(direction[0]), float(direction[1])],
        ))
    return gates


def _decompose_sec(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    """T-SEC 分解：边界段占位 + 通道哨位 + 机动拦截 + 预备队（1028 §2.2）。

    与旧版"只按入口点摆人"的差别：
      * 有 ``roles`` 时按角色出兵，边界段按**弧长均分**，占位点从段中点向
        区域内缩 ``standoff_m``（与执行层同一套几何，见 containment_geom）；
      * 目标点仍写成 4.2 契约里的 ``{"point": [x, y]}``，角色写在
        ``Subtask.role`` / ``Assignment.role``，不往 target 里塞私有字段；
      * 未给 roles 的旧输入（入口点/包围采样）保持原样，不改变历史样例语义。
    """
    duration = float(task.params.get("hold_duration_s",
                                     task.params.get("duration_s", 600.0)))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)
    area = task_polygon(task, ("area", "defense_area", "sector"))
    if area is None:
        raise PlanningError("%s（T-SEC）缺少 area" % task.task_id)

    if task.params.get("roles") or task.params.get("gates"):
        import containment_geom as geom
        polygon = geom.as_polygon([[float(p[0]), float(p[1])] for p in area])
        roles = _sec_roles(task)
        if task.max_units is not None:
            # 兵力上限优先保证"有人在位"：先减预备队与空中监视，再减边界段，
            # 最后减门哨；机动拦截组保留（否则拦阻义务无人承担）。
            limit = max(1, int(task.max_units))
            for key in ("reserve", "air", "boundary", "gate"):
                while roles[key] > 0 and sum(roles.values()) > limit:
                    roles[key] -= 1
        if sum(roles.values()) <= 0:
            roles["boundary"] = 1
        standoff = float(task.params.get("standoff_m", 12.0))
        gates = _sec_gates(task)
        reserve_post = task.params.get("reserve_post")
        intercept_post = task.params.get("intercept_post")
        center = geom.polygon_center(polygon)

        items: List[Tuple[Dict[str, Any], str]] = []
        boundary_count = roles["boundary"]
        if boundary_count:
            posts = geom.sector_posts(polygon, boundary_count, standoff=standoff)
            for post in posts:
                items.append(({"point": list(post["post"])},
                              "boundary:%d/%d" % (post["index"], boundary_count)))
        for index, gate in enumerate(gates[:roles["gate"]]):
            items.append(({"point": list(gate["point"])}, "gate:%s" % gate["gate_id"]))
        for _ in range(max(0, roles["gate"] - len(gates))):
            items.append(({"point": list(center)}, "gate:unassigned"))
        for _ in range(roles["intercept"]):
            items.append(({"point": [float(v) for v in
                                     (intercept_post or center)]},
                          "intercept:standby"))
        for _ in range(roles["reserve"]):
            spot = reserve_post or [center[0], center[1] - standoff]
            items.append(({"point": [float(v) for v in spot]}, "reserve:standby"))
        air_caps = task.params.get("air_capabilities") or {"RCN": 2}
        air_unit = task.params.get("air_unit")
        for _ in range(roles["air"]):
            # 空中监视/中继：绕封控区上方盘旋，传感器覆盖整块区域。
            # 席位按 air_unit 固定或用 air_capabilities 限定，避免被地面平台
            # 拿了"空中席位"（地面平台没有高度层，飞不上去）。
            items.append(({"point": [float(v) for v in center]}, "air:watch"))
        subtasks = []
        for index, (target, role) in enumerate(items):
            subtask = _make_subtask(task, index + 1, target, duration,
                                    coordination=coordination)
            subtask.role = role
            if role.startswith("air:"):
                subtask.required_capabilities = dict(air_caps)
                if air_unit:
                    subtask.pinned_unit = str(air_unit)
            subtasks.append(subtask)
        return subtasks

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


HLD_ROLE_KEYS = ("post", "reserve", "support", "relay")
# 兵力上限裁剪顺序：阵位最后裁，否则"裁完没人守要点"（任务书 §9.4）。
HLD_CROP_ORDER = ("support", "relay", "reserve")


def _hld_threats(task: Task) -> List[Dict[str, Any]]:
    """威胁方向清单：``[{id, bearing_deg, width_deg}]``（0°=北，顺时针）。"""
    raw = task.params.get("threat_directions")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise PlanningError("%s.threat_directions 必须是数组" % task.task_id)
    threats = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or "bearing_deg" not in item:
            raise PlanningError("%s.threat_directions[%d] 必须给出 bearing_deg"
                                % (task.task_id, index))
        try:
            bearing = float(item["bearing_deg"])
            width = float(item.get("width_deg", 60.0))
        except (TypeError, ValueError):
            raise PlanningError("%s.threat_directions[%d] 角度必须是数字"
                                % (task.task_id, index))
        if not -360.0 <= bearing <= 720.0:
            raise PlanningError("%s.threat_directions[%d].bearing_deg 越界"
                                % (task.task_id, index))
        threats.append(dict(
            id=str(item.get("id") or "D%d" % (index + 1)),
            bearing_deg=bearing % 360.0,
            width_deg=max(0.0, min(360.0, width)),
        ))
    return threats


def hld_key_point(task: Task) -> Optional[Point]:
    """要点：``target.key_point`` / ``point`` / ``defense_area`` 重心。"""
    point = task_point(task, ("key_point", "point"))
    if point is not None:
        return point
    area = task_polygon(task, ("defense_area", "area"))
    if area is not None:
        return polygon_centroid(area)
    return None


def hld_positions(task: Task) -> List[Dict[str, Any]]:
    """阵位清单：``[{id, point, facing_deg, min_units}]``。

    规划层与执行层共用这一份（执行层通过 ``_behavior.positions`` 拿到同样的
    点与朝向）。顺序：4.1 ``params.positions`` → 旧样例 ``defense_positions``
    → 按威胁方向在要点外布点 → 要点本身一个阵位。
    """
    import containment_geom as geom

    key_point = hld_key_point(task)
    threats = _hld_threats(task)
    raw = task.params.get("positions")
    legacy = task.params.get("defense_positions",
                             task.target.get("defense_positions"))
    if raw is None and legacy is not None:
        raw = legacy
        dict_form = False
    else:
        dict_form = True
    positions: List[Dict[str, Any]] = []
    if raw is not None:
        if not isinstance(raw, (list, tuple)) or not raw:
            raise PlanningError("%s.positions 不能为空" % task.task_id)
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                if "point" not in item:
                    raise PlanningError("%s.positions[%d] 必须给出 point"
                                        % (task.task_id, index))
                point = as_point(item["point"])
                position_id = str(item.get("id") or "P%d" % (index + 1))
                facing = item.get("facing_deg")
                min_units = item.get("min_units", 1)
            else:
                point = as_point(item)
                position_id = "P%d" % (index + 1)
                facing = None
                min_units = 1
            if facing is None:
                # 朝向缺省按"要点 → 阵位"的方位：面朝威胁来向、背靠要点。
                facing = (geom.facing_of(point, key_point)
                          if key_point is not None else 0.0)
            try:
                facing = float(facing) % 360.0
                min_units = max(0, int(min_units))
            except (TypeError, ValueError):
                raise PlanningError("%s.positions[%d] facing_deg/min_units 非数字"
                                    % (task.task_id, index))
            positions.append(dict(id=position_id, point=[float(point[0]),
                                                         float(point[1])],
                                  facing_deg=facing, min_units=min_units))
        return positions
    if key_point is None:
        return []
    radius = float(task.params.get("post_radius_m", 30.0))
    if threats:
        bearings = [item["bearing_deg"] for item in threats]
        for index, point in enumerate(geom.threat_posts(key_point, bearings,
                                                        radius)):
            threat = threats[index]
            positions.append(dict(
                id="P%d" % (index + 1),
                point=[float(point[0]), float(point[1])],
                facing_deg=float(threat["bearing_deg"]) % 360.0,
                min_units=1))
        return positions
    return [dict(id="P1", point=[float(key_point[0]), float(key_point[1])],
                 facing_deg=0.0, min_units=1)]


def _hld_role_counts(task: Task, position_count: int) -> Dict[str, int]:
    """各路席位台数；未给 ``roles`` 时按"阵位全员 + 无预备队"配。"""
    raw = task.params.get("roles")
    if isinstance(raw, dict) and raw:
        counts = {}
        for key in HLD_ROLE_KEYS:
            value = raw.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PlanningError("%s.roles.%s 必须是整数" % (task.task_id, key))
            counts[key] = max(0, int(value))
        unknown = [k for k in raw if k not in HLD_ROLE_KEYS]
        if unknown:
            raise PlanningError("%s.roles 含未知角色 %s（可选 %s）"
                                % (task.task_id, unknown, "/".join(HLD_ROLE_KEYS)))
        counts["post"] = min(counts["post"], position_count) or min(1, position_count)
        if sum(counts.values()) <= 0:
            raise PlanningError("%s.roles 台数合计必须大于 0" % task.task_id)
        return counts
    return dict(post=position_count, reserve=0, support=0, relay=0)


def _crop_hld_roles(counts: Dict[str, int], limit: int) -> Dict[str, int]:
    """按 ``support → relay → reserve → post`` 裁到兵力上限；阵位至少留 1 个。"""
    for key in HLD_CROP_ORDER:
        while counts[key] > 0 and sum(counts.values()) > limit:
            counts[key] -= 1
    while sum(counts.values()) > limit and counts["post"] > 1:
        counts["post"] -= 1
    return counts


def hld_stations(task: Task, key_point: Optional[Point] = None,
                 positions: Optional[Sequence[Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    """预备队/支援/中继的位置：由威胁方向与要点推出，或用 4.1 给定点。

    返回 ``{reserve: [x, y], support: [[x, y], ...], relay: [x, y]}``。
    规划层用它摆槽位，运行层把它塞进 ``_behavior.stations``，执行层据此站位
    ——三处用同一组坐标，不再各算一份。都没有时全部回落到要点本身：宁可
    "都在要点上"，也不要凭空编一个后方坐标。
    """
    import containment_geom as geom

    if key_point is None:
        key_point = hld_key_point(task)
    if positions is None:
        positions = hld_positions(task)
    anchor = ([float(key_point[0]), float(key_point[1])]
              if key_point is not None
              else ([float(positions[0]["point"][0]),
                     float(positions[0]["point"][1])] if positions
                    else [0.0, 0.0]))
    threats = _hld_threats(task)
    if threats:
        mean = sum(item["bearing_deg"] for item in threats) / len(threats)
    else:
        mean = 180.0
    standoff = task.params.get("reserve_standoff_m")
    standoff = (max(10.0, float(standoff)) if standoff is not None
                else max(10.0, float(task.params.get("post_radius_m", 30.0))))
    back = geom.compass_vector((mean + 180.0) % 360.0)
    reserve_point = task.params.get("reserve_point")
    if reserve_point is not None:
        reserve_point = list(as_point(reserve_point))
    else:
        reserve_point = [anchor[0] + back[0] * standoff,
                         anchor[1] + back[1] * standoff]

    roles = task.params.get("roles")
    support_roles = int(roles.get("support") or 0) if isinstance(roles, dict) else 0
    support_raw = task.params.get("support_points")
    support_points: List[List[float]] = []
    if isinstance(support_raw, (list, tuple)) and support_raw:
        support_points = [list(as_point(p)) for p in support_raw]
    elif support_roles:
        # 未给支援位时，在预备队左右各偏 40° 摆开，避免与预备队重叠。
        for offset in (40.0, -40.0, 0.0):
            vec = geom.compass_vector((mean + 180.0 + offset) % 360.0)
            support_points.append([anchor[0] + vec[0] * standoff * 0.8,
                                   anchor[1] + vec[1] * standoff * 0.8])

    relay_raw = task.params.get("relay_point")
    relay_point = (list(as_point(relay_raw)) if relay_raw is not None
                   else list(anchor))
    return dict(reserve=[round(v, 3) for v in reserve_point],
                support=[[round(v, 3) for v in p] for p in support_points],
                relay=[round(v, 3) for v in relay_point])


def _decompose_hld(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    """T-HLD 分解：阵位 + 预备队 + 支援 + 中继（1028 §2.5）。

    与旧版"只按 defense_positions 摆点"的差别：
      * 阵位语义升到 4.1 ``params.positions``（``{id, point, facing_deg,
        min_units}``），角色写 ``Subtask.role`` / ``Assignment.role``
        （``post:P1`` / ``reserve:standby`` / ``support:S1`` / ``relay:standby``）；
      * 目标点仍写 4.2 契约里的 ``{"point": [x, y]}``，不往 target 里塞私有字段；
      * 兵力上限裁剪顺序固定为 ``support → relay → reserve → post``：阵位最后裁，
        否则会出现"上限裁完没人守要点"；
      * 阵位几何与朝向由 ``containment_geom`` 统一给出（与执行层同一套角度），
        不在分解器里另写一份；
      * 旧样例（只给 ``defense_positions``）仍按点列分解，槽位数不变，只是补上
        角色与朝向，历史语义不回退。
    """
    duration = float(task.params.get("hold_duration_s",
                                     task.params.get("duration_s", 600.0)))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)
    coordination = _coordination(task)
    key_point = hld_key_point(task)
    positions = hld_positions(task)
    if not positions:
        raise PlanningError("%s（T-HLD）缺少 key_point / defense_area / positions"
                            % task.task_id)
    counts = _hld_role_counts(task, len(positions))
    if task.max_units is not None:
        _crop_hld_roles(counts, max(1, int(task.max_units)))
    stations = hld_stations(task, key_point, positions)
    reserve_point = stations["reserve"]
    support_points = stations["support"]
    relay_point = stations["relay"]

    items: List[Tuple[Dict[str, Any], str]] = []
    for index, position in enumerate(positions[:counts["post"]]):
        items.append(({"point": [float(position["point"][0]),
                                 float(position["point"][1])]},
                      "post:%s" % position["id"]))
    for _ in range(counts["reserve"]):
        items.append(({"point": [float(reserve_point[0]),
                                 float(reserve_point[1])]}, "reserve:standby"))
    for index in range(counts["support"]):
        point = support_points[index % len(support_points)] if support_points \
            else reserve_point
        items.append(({"point": [float(point[0]), float(point[1])]},
                      "support:S%d" % (index + 1)))
    for _ in range(counts["relay"]):
        items.append(({"point": [float(relay_point[0]),
                                 float(relay_point[1])]}, "relay:standby"))

    if not items:
        raise PlanningError("%s（T-HLD）分解后没有阵位" % task.task_id)
    subtasks = []
    for index, (target, role) in enumerate(items):
        subtask = _make_subtask(task, index + 1, target, duration,
                                coordination=coordination)
        subtask.role = role
        subtasks.append(subtask)
    return subtasks


def _asl_ring_point(center: Point, radius: float, angle: float) -> Point:
    return (float(center[0]) + float(radius) * math.cos(angle),
            float(center[1]) + float(radius) * math.sin(angle))


def _decompose_asl(task: Task, platforms: Sequence[Platform]) -> List[Subtask]:
    """T-ASL：按侦察 / 突击 / 评估三类角色拆槽位。

    - 侦察席在观察位，先到位；突击席依赖侦察席完成（指示后才发起冲击）；
    - 突击席按 ``assault_units`` 数量围绕目标均匀展开，带载荷下限；
    - 评估席前出评估观察位，与突击同时段机动，不等待突击结束；
    - 显式 ``scout_unit`` / ``assessor_unit`` 时把该槽位固定到指定平台。
    打击动作、弹药与效果判定不在本层，由执行层行为与评估接口接管。
    """
    params = task.params
    site = target_point(task.target)
    duration = float(params.get("duration_s", 140.0))
    if duration <= 0:
        raise PlanningError("%s.duration_s 必须大于 0" % task.task_id)

    scout = params.get("scout") or {"count": 1, "capabilities": {"RCN": 2},
                                    "unit": params.get("scout_unit")}
    assessor = params.get("assessor") or {"count": 1, "capabilities": {"RCN": 1},
                                          "unit": params.get("assessor_unit")}
    scout_count = int(scout.get("count", 1))
    assessor_count = int(assessor.get("count", 1))
    assault_units = int(params.get("assault_units")
                        or max(1, int(task.min_units) - scout_count - assessor_count))
    payload_required = float(params.get("payload_required", 4.0))
    objective_radius = float(params.get("objective_radius", 14.0))
    observe_radius = float(params.get("observe_radius", 25.0))
    observe_angle = float(params.get("observe_angle", 0.0))
    scout_duration = float(params.get("scout_duration_s", 10.0))
    assess_duration = float(params.get("assess_duration_s", 10.0))

    observation = _asl_ring_point(site, observe_radius, observe_angle)
    assessment_post = params.get("assessment_post")
    if assessment_post is None:
        assessment_post = _asl_ring_point(site, observe_radius, math.pi / 2.0)
    assessment_post = (float(assessment_post[0]), float(assessment_post[1]))

    items: List[Subtask] = []
    scout_ids: List[str] = []
    index = 1
    for _ in range(scout_count):
        subtask = _make_subtask(task, index, {"point": list(observation)},
                                scout_duration, coordination=_coordination(task))
        subtask.role = "scout"
        subtask.required_capabilities = dict(scout.get("capabilities") or {})
        if scout_count == 1 and scout.get("unit"):
            subtask.pinned_unit = str(scout["unit"])
        items.append(subtask)
        scout_ids.append(subtask.subtask_id)
        index += 1

    for i in range(assault_units):
        angle = 2.0 * math.pi * i / max(1, assault_units)
        target = _asl_ring_point(site, objective_radius, angle)
        subtask = _make_subtask(
            task, index, {"point": list(target)}, duration,
            coordination=list(dict.fromkeys(_coordination(task)
                                            + ["simultaneous_arrival"])))
        subtask.role = "assault"
        subtask.min_payload = payload_required
        subtask.depends_on = list(scout_ids)
        items.append(subtask)
        index += 1

    for _ in range(assessor_count):
        subtask = _make_subtask(task, index, {"point": list(assessment_post)},
                                assess_duration, coordination=_coordination(task))
        subtask.role = "assessor"
        subtask.required_capabilities = dict(assessor.get("capabilities") or {})
        if assessor_count == 1 and assessor.get("unit"):
            subtask.pinned_unit = str(assessor["unit"])
        items.append(subtask)
        index += 1

    if not items:
        raise PlanningError("%s（T-ASL）没有可执行席位" % task.task_id)
    return items


_DECOMPOSERS = {
    "T-RCN": _decompose_rcn,
    "T-SEC": _decompose_sec,
    "T-PTL": _decompose_ptl,
    "T-HLD": _decompose_hld,
    "T-ASL": _decompose_asl,
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
