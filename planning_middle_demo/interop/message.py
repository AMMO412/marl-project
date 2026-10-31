# -*- coding: utf-8 -*-
"""1028 文档 4.1 任务消息与编成表的严格解析。

与 M2 的差异（有意的收紧）：
  * ``schema_version`` 只接受 ``"0.3"``；0.1/0.2 明确拒绝（已确认的外部
    接口规则），不做静默兼容。
  * 任务类型接受五类：四类中性任务 + ``T-ASL``。T-ASL 的目标只允许单点，
    效果参数（effect/required_*）在本层校验并归一化；打击动作和效果判定
    仍由执行层承担，本层不判成败。
  * 编成表单位在 M2 字段基础上增加基座画像字段（payload / sensor /
    battery / work_rate / move_cost / work_cost），两边字段都保留，不合并
    成同一个数值。

坐标与时间口径：
  * 位置是场景单位，``meta.cell_size_m`` 给出 1 场景单位等于多少米；
  * 时间统一为秒，``issued_at`` 只作追溯，不参与相对时刻换算。
"""

import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .errors import UnsupportedFeature, WireError
from .geometry import polygon_centroid
from .model import Platform, Scenario, Task

SCHEMA_VERSION = "0.3"
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_VERSION,)

SOURCE_ALIASES = {
    "UPPER": "UPPER", "上级": "UPPER",
    "ADJUST": "ADJUST", "调整": "ADJUST",
    "AUTONOMOUS": "AUTONOMOUS", "自主": "AUTONOMOUS",
}

TASK_TYPES = ("T-RCN", "T-SEC", "T-PTL", "T-HLD", "T-ASL")
# 效果三分类：中文标签与 token 都接受，进入 params 后统一为 token。
ASL_EFFECTS = {"damage": "damage", "毁伤": "damage",
               "suppress": "suppress", "压制": "suppress",
               "seize": "seize", "夺占": "seize"}
ASL_POINT_TARGETS = ("point", "key_point", "target_list")
ASL_ROLE_DEFAULT_CAPS = {"scout": {"RCN": 2}, "assessor": {"RCN": 1}}

TARGET_KINDS = ("area", "sector", "patrol_area", "defense_area",
                "route", "point", "key_point", "target_list")

REQUIRED_TASK_FIELDS = ("task_id", "task_type", "priority", "target",
                        "window", "required_capabilities", "min_units",
                        "max_units", "params")

ALLOWED_TASK_KEYS = set(REQUIRED_TASK_FIELDS) | {
    "depends_on", "prerequisites", "allow_split", "description", "constraints"}

ALLOWED_UNIT_KEYS = {
    "unit_id", "platform_type", "platform_class", "robot_id", "capabilities",
    "position", "altitude_m", "heading_rad", "speed_mps", "endurance_s",
    "vertical_speed_mps", "status", "payload", "sensor", "battery",
    "work_rate", "move_cost", "work_cost",
}

CLASS_RANGES = {"UGV": (1, 20), "TANK": (21, 30),
                "PLANE": (31, 40), "WING": (41, 50)}
PLATFORM_TYPE_CLASS = {
    "ugv": "UGV", "ifv": "UGV", "rover": "UGV", "wheeled": "UGV",
    "tracked": "UGV", "tank": "TANK", "mbt": "TANK", "uav": "PLANE",
    "uav_recon": "PLANE", "plane": "PLANE", "fixed_wing": "PLANE",
    "recon_plane": "PLANE", "wing": "WING", "uav_strike": "WING",
    "uav_wing": "WING",
}
CLASS_ALIASES = {"无人车": "UGV", "坦克": "TANK", "固定翼": "PLANE", "飞翼": "WING"}

CLASS_CAPABILITIES = {
    "UGV": {"RCN": 2, "STK": 1, "PTL": 2, "HLD": 2},
    "TANK": {"RCN": 1, "STK": 3, "PTL": 1, "HLD": 3},
    "PLANE": {"RCN": 3, "STK": 0, "PTL": 2, "HLD": 0},
    "WING": {"RCN": 2, "STK": 2, "PTL": 2, "HLD": 0},
}

# 基座 planning_middle_demo/fleet.py 的规划参数（暂定值）。编成表没写
# payload/sensor/battery/work_rate 时用这张表补齐，保持与基座同源。
CLASS_BASE_PROFILE = {
    "UGV": dict(work_rate=1.0, battery=100.0, payload=6.0, sensor="eo",
                move_cost=0.32, work_cost=1.0),
    "TANK": dict(work_rate=1.2, battery=120.0, payload=8.0, sensor="eo",
                 move_cost=0.5, work_cost=1.44),
    "PLANE": dict(work_rate=0.6, battery=320.0, payload=2.0, sensor="sar",
                  move_cost=2.0, work_cost=0.36),
    "WING": dict(work_rate=0.5, battery=280.0, payload=1.5, sensor="ir",
                 move_cost=1.28, work_cost=0.25),
}


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireError("%s 必须是数字，实际为 %r" % (field_name, value))
    if not math.isfinite(float(value)):
        raise WireError("%s 必须是有限数，实际为 %r" % (field_name, value))
    return float(value)


def _positive(value: Any, field_name: str) -> float:
    number = _number(value, field_name)
    if number <= 0:
        raise WireError("%s 必须大于 0" % field_name)
    return number


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireError("%s 必须是整数" % field_name)
    number = int(value)
    if float(number) != float(value):
        raise WireError("%s 必须是整数" % field_name)
    return number


def _as_point(value: Any, field_name: str) -> Tuple[float, float]:
    if isinstance(value, dict) and "x" in value and "y" in value:
        return (_number(value["x"], field_name + ".x"),
                _number(value["y"], field_name + ".y"))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (_number(value[0], field_name + "[0]"),
                _number(value[1], field_name + "[1]"))
    raise WireError("%s 必须是 [x, y] 或 {x, y}" % field_name)


def _as_polygon(value: Any, field_name: str) -> List[Tuple[float, float]]:
    if isinstance(value, dict):
        value = value.get("polygon")
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise WireError("%s.polygon 至少需要 3 个点" % field_name)
    return [_as_point(p, "%s[%d]" % (field_name, i)) for i, p in enumerate(value)]


def _as_route(value: Any, field_name: str) -> List[Tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise WireError("%s 至少需要 2 个航点" % field_name)
    return [_as_point(p, "%s[%d]" % (field_name, i)) for i, p in enumerate(value)]


def _as_window(value: Any, field_name: str) -> Tuple[float, float]:
    if isinstance(value, dict):
        start = _number(value.get("start_s"), field_name + ".start_s")
        end = _number(value.get("end_s"), field_name + ".end_s")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        start = _number(value[0], field_name + "[0]")
        end = _number(value[1], field_name + "[1]")
    else:
        raise WireError("%s 必须是 {start_s, end_s} 或 [开始, 结束]" % field_name)
    if end <= start:
        raise WireError("%s.end_s 必须大于 start_s" % field_name)
    return start, end


def _as_capabilities(value: Any, field_name: str) -> Dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WireError("%s 必须是能力编码到等级的映射" % field_name)
    result = {}
    for code, level in value.items():
        if not isinstance(code, str) or not code:
            raise WireError("%s 的能力编码必须是非空字符串" % field_name)
        ivalue = _integer(level, "%s.%s" % (field_name, code))
        if ivalue < 0 or ivalue > 3:
            raise WireError("%s.%s 的能力等级必须在 0-3 之间" % (field_name, code))
        result[code] = ivalue
    return result


def normalize_platform_class(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WireError("platform_class 必须是非空字符串")
    text = value.strip()
    name = CLASS_ALIASES.get(text, text.upper())
    if name not in CLASS_RANGES:
        raise WireError("platform_class 必须是 UGV/TANK/PLANE/WING 之一，实际为 %r"
                        % value)
    return name


def infer_platform_class(platform_type: Any) -> Optional[str]:
    if not isinstance(platform_type, str):
        return None
    return PLATFORM_TYPE_CLASS.get(platform_type.strip().lower())


def validate_robot_id(robot_id: int, platform_class: str) -> None:
    low, high = CLASS_RANGES[platform_class]
    if not low <= robot_id <= high:
        raise WireError("%s 的 robot_id 必须在 %d-%d 之间，实际为 %d"
                        % (platform_class, low, high, robot_id))


def _parse_iso8601(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WireError("%s 必须是非空 ISO 8601 字符串" % field_name)
    text = value.strip()
    if "T" not in text:
        raise WireError("%s 必须是带时间的 ISO 8601 字符串: %r" % (field_name, value))
    parsed = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(parsed)
    except ValueError:
        raise WireError("%s 不是合法的 ISO 8601 时间: %r" % (field_name, value))
    return text


def _validate_target(target: Any, task_id: str) -> None:
    if not isinstance(target, dict) or not target:
        raise WireError("%s.target 必须是非空对象" % task_id)
    unknown = [key for key in target if key not in TARGET_KINDS]
    if unknown:
        raise WireError("%s.target 含未知目标类型: %s"
                        % (task_id, ", ".join(str(k) for k in unknown)))
    kinds = [key for key in target if key in TARGET_KINDS]
    if len(kinds) != 1:
        raise WireError("%s.target 必须恰好给出一种目标类型，实际为: %s"
                        % (task_id, ", ".join(kinds) if kinds else "无"))
    kind = kinds[0]
    value = target[kind]
    if kind in ("area", "sector", "patrol_area", "defense_area"):
        _as_polygon(value, "%s.target.%s" % (task_id, kind))
    elif kind == "route":
        _as_route(value, "%s.target.route" % task_id)
    elif kind == "target_list":
        if not isinstance(value, (list, tuple)) or not value:
            raise WireError("%s.target.target_list 不能为空" % task_id)
        for i, point in enumerate(value):
            _as_point(point, "%s.target.target_list[%d]" % (task_id, i))
    else:
        _as_point(value, "%s.target.%s" % (task_id, kind))


def _asl_role(params: Dict[str, Any], key: str,
              task_id: str) -> Dict[str, Any]:
    """归一化侦察/评估角色：``{count, capabilities, unit}``，缺省各 1 台。"""
    raw = params.get(key)
    if raw is None:
        return {"count": 1, "capabilities": dict(ASL_ROLE_DEFAULT_CAPS[key]),
                "unit": None}
    if not isinstance(raw, dict):
        raise WireError("%s.params.%s 必须是对象" % (task_id, key))
    unknown = [item for item in raw
               if item not in ("count", "capabilities", "unit")]
    if unknown:
        raise WireError("%s.params.%s 含未约定字段: %s"
                        % (task_id, key, ", ".join(sorted(unknown))))
    count = _integer(raw.get("count", 1), "%s.params.%s.count" % (task_id, key))
    if count < 0:
        raise WireError("%s.params.%s.count 不能为负" % (task_id, key))
    caps = _as_capabilities(raw.get("capabilities") or {},
                            "%s.params.%s.capabilities" % (task_id, key))
    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit):
        raise WireError("%s.params.%s.unit 必须是非空字符串" % (task_id, key))
    return {"count": count,
            "capabilities": caps or dict(ASL_ROLE_DEFAULT_CAPS[key]),
            "unit": unit}


def _validate_asl(task: Dict[str, Any]) -> None:
    """T-ASL 字段校验与默认值归一化（就地写入 task.params）。

    只校验规划层需要的部分：单点目标、效果参数、角色席位、时序与几何。
    打击动作、弹药消耗和效果判定不在本层，交给执行层行为与评估接口。
    """
    task_id = task["task_id"]
    target = task["target"]
    params = task["params"]

    kinds = [key for key in target if key in TARGET_KINDS]
    if len(kinds) != 1 or kinds[0] not in ASL_POINT_TARGETS:
        raise WireError("%s（T-ASL）target 必须是 point / key_point / "
                        "target_list 之一，实际为: %s"
                        % (task_id, ", ".join(kinds) if kinds else "无"))
    if kinds[0] == "target_list" and len(target["target_list"]) != 1:
        raise WireError("%s（T-ASL）target_list 只能给出一个目标点" % task_id)

    effect = params.get("effect", "damage")
    if not isinstance(effect, str) or effect.strip() not in ASL_EFFECTS:
        raise WireError("%s.params.effect 必须是 damage/suppress/seize"
                        "（或毁伤/压制/夺占），实际为 %r" % (task_id, effect))
    params["effect"] = ASL_EFFECTS[effect.strip()]

    for key, default in (("required_level", 6.0),
                         ("required_duration", 10.0),
                         ("required_control_s", 10.0),
                         ("payload_required", 4.0),
                         ("duration_s", 140.0)):
        params[key] = _positive(params.get(key, default),
                                "%s.params.%s" % (task_id, key))
    for key, default in (("assessment_delay", 0.0),
                         ("confirmation_deadline", 120.0),
                         ("execute_deadline", 0.0),
                         ("withdraw_deadline", 0.0),
                         ("withdraw_ring", 2.0),
                         ("observe_radius", 25.0),
                         ("observe_angle", 0.0),
                         ("objective_radius", 14.0)):
        value = _number(params.get(key, default), "%s.params.%s" % (task_id, key))
        if key != "observe_angle" and value < 0:
            raise WireError("%s.params.%s 不能为负" % (task_id, key))
        params[key] = value

    start, end = _as_window(params.get("attack_window", task["window"]),
                            "%s.params.attack_window" % task_id)
    params["attack_window"] = [start, end]

    scout = _asl_role(params, "scout", task_id)
    assessor = _asl_role(params, "assessor", task_id)
    for key, role in (("scout", scout), ("assessor", assessor)):
        explicit = params.get(key + "_unit")
        if explicit is not None and role["unit"] is not None \
                and explicit != role["unit"]:
            raise WireError("%s.params.%s_unit 与 params.%s.unit 冲突"
                            % (task_id, key, key))
        unit = explicit if explicit is not None else role["unit"]
        if unit is not None and (not isinstance(unit, str) or not unit):
            raise WireError("%s.params.%s_unit 必须是非空字符串" % (task_id, key))
        role["unit"] = unit
        params[key + "_unit"] = unit
    if scout["unit"] and scout["unit"] == assessor["unit"]:
        raise WireError("%s.params 中侦察与评估不能是同一台平台: %s"
                        % (task_id, scout["unit"]))
    params["scout"], params["assessor"] = scout, assessor

    min_units = _integer(task["min_units"], "%s.min_units" % task_id)
    slots = scout["count"] + assessor["count"]
    if slots >= min_units:
        raise WireError("%s（T-ASL）侦察+评估共 %d 席，min_units=%d，"
                        "至少需要 1 个突击席位" % (task_id, slots, min_units))
    params["assault_units"] = min_units - slots

    for key in ("staging_center", "assessment_post", "withdraw_point"):
        if key in params:
            params[key] = list(_as_point(params[key],
                                         "%s.params.%s" % (task_id, key)))
    for key in ("withdraw", "positive_id_required"):
        if key in params and not isinstance(params[key], bool):
            raise WireError("%s.params.%s 必须是布尔值" % (task_id, key))
    for key in ("roe", "collateral_limit", "target_id", "object_label"):
        if key in params and not isinstance(params[key], str):
            raise WireError("%s.params.%s 必须是字符串" % (task_id, key))
    if "waves" in params:
        waves = _integer(params["waves"], "%s.params.waves" % task_id)
        if waves < 1:
            raise WireError("%s.params.waves 必须大于等于 1" % task_id)
        params["waves"] = waves
    if "ammo_per_platform" in params:
        ammo = _integer(params["ammo_per_platform"],
                        "%s.params.ammo_per_platform" % task_id)
        if ammo < 0:
            raise WireError("%s.params.ammo_per_platform 不能为负" % task_id)
        params["ammo_per_platform"] = ammo


def _normalize_task(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise WireError("tasks[%d] 必须是对象" % index)
    missing = [key for key in REQUIRED_TASK_FIELDS if key not in raw]
    if missing:
        raise WireError("tasks[%d] 缺少字段: %s" % (index, ", ".join(missing)))
    task_id = raw["task_id"]
    if not isinstance(task_id, str) or not task_id:
        raise WireError("tasks[%d].task_id 必须是非空字符串" % index)

    unknown = [key for key in raw
               if key not in ALLOWED_TASK_KEYS and not str(key).startswith("_")]
    if unknown:
        raise WireError("%s 含未约定字段: %s" % (task_id, ", ".join(sorted(unknown))))

    if raw["task_type"] not in TASK_TYPES:
        raise WireError("%s.task_type 必须是 %s 之一，实际为 %r"
                        % (task_id, "/".join(TASK_TYPES), raw["task_type"]))

    if "depends_on" in raw and "prerequisites" in raw:
        raise WireError("%s 同时给出 prerequisites 和 depends_on，语义不明确" % task_id)
    task = dict(raw)
    if "prerequisites" in task:
        task["depends_on"] = task.pop("prerequisites")

    _validate_target(task.get("target"), task_id)
    priority = _integer(raw["priority"], "%s.priority" % task_id)
    if priority < 1 or priority > 5:
        raise WireError("%s.priority 必须在 1-5 之间" % task_id)
    _as_window(raw["window"], "%s.window" % task_id)
    _as_capabilities(raw["required_capabilities"], "%s.required_capabilities" % task_id)
    min_units = _integer(raw["min_units"], "%s.min_units" % task_id)
    if min_units < 1:
        raise WireError("%s.min_units 必须大于等于 1" % task_id)
    max_units = raw["max_units"]
    if max_units is not None:
        max_units = _integer(max_units, "%s.max_units" % task_id)
        if max_units < min_units:
            raise WireError("%s.max_units 不能小于 min_units" % task_id)
    if not isinstance(raw["params"], dict):
        raise WireError("%s.params 必须是对象" % task_id)
    if task["task_type"] == "T-ASL":
        _validate_asl(task)
    depends = task.get("depends_on", [])
    if not isinstance(depends, list) or any(not isinstance(d, str) for d in depends):
        raise WireError("%s.depends_on/prerequisites 必须是字符串数组" % task_id)
    if task_id in depends:
        raise WireError("%s.depends_on/prerequisites 不能依赖自己" % task_id)
    return task


def _check_dependency_cycles(tasks: List[Task]) -> None:
    by_id = {task.task_id: task for task in tasks}
    state = {}

    def visit(task_id: str, stack: List[str]) -> None:
        if state.get(task_id) == 2:
            return
        if state.get(task_id) == 1:
            raise WireError("任务依赖存在环: %s" % " -> ".join(stack + [task_id]))
        state[task_id] = 1
        for dep in by_id[task_id].depends_on:
            if dep in by_id:
                visit(dep, stack + [task_id])
        state[task_id] = 2

    for task in tasks:
        visit(task.task_id, [])


def _parse_platform(raw: Any, index: int) -> Platform:
    if not isinstance(raw, dict):
        raise WireError("formation.units[%d] 必须是对象" % index)
    unknown = [key for key in raw
               if key not in ALLOWED_UNIT_KEYS and not str(key).startswith("_")]
    if unknown:
        raise WireError("formation.units[%d] 含未约定字段: %s"
                        % (index, ", ".join(sorted(unknown))))
    unit_id = raw.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise WireError("formation.units[%d].unit_id 必须是非空字符串" % index)

    platform_type = raw.get("platform_type", "unknown")
    if not isinstance(platform_type, str):
        raise WireError("%s.platform_type 必须是字符串" % unit_id)
    platform_class = raw.get("platform_class")
    if platform_class is None:
        platform_class = infer_platform_class(platform_type)
        if platform_class is None:
            raise WireError("%s.platform_class 缺失，且无法从 platform_type=%r 推断"
                            % (unit_id, platform_type))
    else:
        platform_class = normalize_platform_class(platform_class)

    robot_id = raw.get("robot_id")
    if robot_id is not None:
        robot_id = _integer(robot_id, "%s.robot_id" % unit_id)
        validate_robot_id(robot_id, platform_class)

    position = _as_point(raw.get("position"), "%s.position" % unit_id)
    speed = _positive(raw.get("speed_mps"), "%s.speed_mps" % unit_id)
    endurance = _positive(raw.get("endurance_s"), "%s.endurance_s" % unit_id)
    capabilities = _as_capabilities(raw.get("capabilities", {}),
                                    "%s.capabilities" % unit_id)
    status = raw.get("status", "READY")
    if status not in ("READY", "BUSY", "DAMAGED", "LOST", "OFFLINE"):
        raise WireError("%s.status 取值不合法: %r" % (unit_id, status))
    heading = _number(raw.get("heading_rad", 0.0), "%s.heading_rad" % unit_id)
    heading = math.atan2(math.sin(heading), math.cos(heading))

    default_altitude = 0.0
    raw_position = raw.get("position")
    if isinstance(raw_position, dict) and "z" in raw_position:
        default_altitude = _number(raw_position.get("z"), "%s.position.z" % unit_id)
    altitude = _number(raw.get("altitude_m", default_altitude),
                       "%s.altitude_m" % unit_id)
    vertical = _number(raw.get("vertical_speed_mps", 3.0 if platform_class in
                               ("PLANE", "WING") else 0.0),
                       "%s.vertical_speed_mps" % unit_id)
    if vertical < 0:
        raise WireError("%s.vertical_speed_mps 不能为负" % unit_id)

    profile = CLASS_BASE_PROFILE[platform_class]
    payload = _number(raw.get("payload", profile["payload"]), "%s.payload" % unit_id)
    sensor = raw.get("sensor", profile["sensor"])
    if not isinstance(sensor, str):
        raise WireError("%s.sensor 必须是字符串" % unit_id)
    battery = _positive(raw.get("battery", profile["battery"]), "%s.battery" % unit_id)
    work_rate = _positive(raw.get("work_rate", profile["work_rate"]),
                          "%s.work_rate" % unit_id)
    move_cost = _number(raw.get("move_cost", profile["move_cost"]),
                        "%s.move_cost" % unit_id)
    work_cost = _number(raw.get("work_cost", profile["work_cost"]),
                        "%s.work_cost" % unit_id)

    if not capabilities:
        capabilities = dict(CLASS_CAPABILITIES[platform_class])

    return Platform(
        unit_id=unit_id, robot_id=robot_id, platform_class=platform_class,
        position=position, speed_mps=speed, endurance_s=endurance,
        capabilities=capabilities, status=status, platform_type=platform_type,
        heading_rad=heading, altitude_m=altitude, vertical_speed_mps=vertical,
        payload=payload, sensor=sensor, battery=battery, work_rate=work_rate,
        move_cost=move_cost, work_cost=work_cost,
    )


def _allocate_robot_ids(platforms: List[Platform]) -> None:
    used = {}
    for platform in platforms:
        if platform.robot_id is None:
            continue
        if platform.robot_id in used:
            raise WireError("robot_id %d 重复: %s 与 %s"
                            % (platform.robot_id, used[platform.robot_id].unit_id,
                               platform.unit_id))
        validate_robot_id(platform.robot_id, platform.platform_class)
        used[platform.robot_id] = platform

    for platform in platforms:
        if platform.robot_id is not None:
            continue
        low, high = CLASS_RANGES[platform.platform_class]
        for robot_id in range(low, high + 1):
            if robot_id not in used:
                platform.robot_id = robot_id
                used[robot_id] = platform
                break
        else:
            raise WireError("%s 的平台类 %s 编号范围 %d-%d 已用尽"
                            % (platform.unit_id, platform.platform_class, low, high))


def _parse_constraints(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WireError("constraints 必须是数组")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "type" not in item:
            raise WireError("constraints[%d] 必须是带 type 的对象" % i)
        ctype = item.get("type")
        if not isinstance(ctype, str) or not ctype:
            raise WireError("constraints[%d].type 必须是非空字符串" % i)
        entry = dict(item)
        if ctype in ("no_go", "threat"):
            if "area" not in item:
                raise WireError("constraints[%d] 缺少 area" % i)
            entry["area"] = {"polygon": _as_polygon(item["area"],
                                                    "constraints[%d].area" % i)}
            if ctype == "threat":
                entry["intensity"] = _number(item.get("intensity", 1.0),
                                             "constraints[%d].intensity" % i)
                if entry["intensity"] < 0:
                    raise WireError("constraints[%d].intensity 不能为负" % i)
            if "height_m" in item:
                entry["height_m"] = _number(item["height_m"],
                                            "constraints[%d].height_m" % i)
            applies = item.get("applies_to", "ground")
            if applies not in ("ground", "all"):
                raise WireError("constraints[%d].applies_to 只能是 ground/all" % i)
            entry["applies_to"] = applies
        out.append(entry)
    return out


def parse_formation(formation: Any) -> Tuple[List[Platform], List[Dict[str, Any]],
                                             List[Dict[str, Any]], Dict[str, Any]]:
    if not isinstance(formation, dict):
        raise WireError("编成表必须是对象")
    root = formation.get("formation", formation)
    if not isinstance(root, dict):
        raise WireError("formation 必须是对象")
    units = root.get("units")
    if not isinstance(units, list) or not units:
        raise WireError("formation.units 必须是非空数组")
    platforms = [_parse_platform(unit, i) for i, unit in enumerate(units)]
    if len({p.unit_id for p in platforms}) != len(platforms):
        raise WireError("formation.units 中存在重复的 unit_id")
    _allocate_robot_ids(platforms)

    groups = root.get("groups", [])
    if not isinstance(groups, list):
        raise WireError("formation.groups 必须是数组")
    constraints = _parse_constraints(formation.get("constraints"))

    meta = formation.get("meta", {})
    if not isinstance(meta, dict):
        raise WireError("meta 必须是对象")
    cell_size = _positive(meta.get("cell_size_m", 1.0), "meta.cell_size_m")
    plan_id = meta.get("plan_id", "PLAN-INTEROP-001")
    if not isinstance(plan_id, str) or not plan_id:
        plan_id = "PLAN-INTEROP-001"
    meta = dict(meta)
    meta["cell_size_m"] = cell_size
    meta["plan_id"] = plan_id
    return platforms, constraints, list(groups), meta


def parse_message(data: Any, formation: Any) -> Scenario:
    """校验 4.1 消息与编成表，返回统一的 Scenario。"""
    if not isinstance(data, dict):
        raise WireError("任务消息根节点必须是对象")

    version = data.get("schema_version")
    if not isinstance(version, str) or not version:
        raise WireError("消息缺少 schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise WireError("不支持的 schema_version: %r；外部接口只接受 %s，"
                        "0.1/0.2 及更旧版本明确拒绝"
                        % (version, ", ".join(SUPPORTED_SCHEMA_VERSIONS)))

    message_id = data.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise WireError("消息缺少 message_id")
    issued_at = _parse_iso8601(data.get("issued_at"), "issued_at")

    source_raw = data.get("source")
    if not isinstance(source_raw, str) or not source_raw:
        raise WireError("消息缺少 source")
    source = SOURCE_ALIASES.get(source_raw.strip())
    if source is None:
        raise WireError("未知 source: %r（允许 上级/调整/自主 或 UPPER/ADJUST/AUTONOMOUS）"
                        % source_raw)

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise WireError("tasks 必须是非空数组")
    normalized = [_normalize_task(task, i) for i, task in enumerate(tasks_raw)]
    if len({t["task_id"] for t in normalized}) != len(normalized):
        raise WireError("tasks 中存在重复的 task_id")
    known = {t["task_id"] for t in normalized}
    for task in normalized:
        for dep in task.get("depends_on", []):
            if dep not in known:
                raise WireError("%s.depends_on 引用了不存在的任务 %s"
                                % (task["task_id"], dep))

    platforms, constraints, groups, meta = parse_formation(formation)
    unit_ids = {platform.unit_id for platform in platforms}
    for raw in normalized:
        if raw["task_type"] != "T-ASL":
            continue
        for key in ("scout_unit", "assessor_unit"):
            unit = raw["params"].get(key)
            if unit and unit not in unit_ids:
                raise WireError("%s.params.%s=%r 不在编成表中"
                                % (raw["task_id"], key, unit))

    tasks = []
    for raw in normalized:
        start, end = _as_window(raw["window"], "%s.window" % raw["task_id"])
        min_units = _integer(raw["min_units"], "%s.min_units" % raw["task_id"])
        max_units = raw.get("max_units")
        max_units = None if max_units is None else _integer(
            max_units, "%s.max_units" % raw["task_id"])
        tasks.append(Task(
            task_id=raw["task_id"],
            task_type=raw["task_type"],
            priority=_integer(raw["priority"], "%s.priority" % raw["task_id"]),
            target=dict(raw["target"]),
            window_start_s=start,
            window_end_s=end,
            required_capabilities=_as_capabilities(
                raw["required_capabilities"],
                "%s.required_capabilities" % raw["task_id"]),
            min_units=min_units,
            max_units=max_units,
            depends_on=list(raw.get("depends_on", [])),
            params=dict(raw["params"]),
            allow_split=bool(raw.get("allow_split", True)),
            description=str(raw.get("description", "")),
        ))

    _check_dependency_cycles(tasks)

    return Scenario(
        formation_id=str(root_id(formation)),
        platforms=platforms,
        tasks=tasks,
        constraints=constraints,
        groups=groups,
        meta=meta,
        message={
            "schema_version": version,
            "message_id": message_id,
            "issued_at": issued_at,
            "source": source,
        },
        cell_size_m=meta["cell_size_m"],
        plan_id=meta["plan_id"],
        schema_version=version,
    )


def root_id(formation: Any) -> str:
    if isinstance(formation, dict):
        root = formation.get("formation", formation)
        if isinstance(root, dict) and isinstance(root.get("formation_id"), str):
            return root["formation_id"]
    return "FORMATION"


def load_json(path: str) -> Any:
    if not os.path.exists(path):
        raise WireError("文件不存在: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_scenario(message_path: str, formation_path: str) -> Scenario:
    return parse_message(load_json(message_path), load_json(formation_path))


def target_point(target: Dict[str, Any]) -> Tuple[float, float]:
    """目标的首个几何点（用于排程落点）。"""
    if "point" in target:
        return _as_point(target["point"], "target.point")
    if "key_point" in target:
        return _as_point(target["key_point"], "target.key_point")
    if "route" in target:
        return _as_route(target["route"], "target.route")[0]
    if "target_list" in target:
        return _as_point(target["target_list"][0], "target.target_list[0]")
    for key in ("area", "sector", "patrol_area", "defense_area"):
        if key in target:
            return polygon_centroid(_as_polygon(target[key], "target." + key))
    raise WireError("目标没有可识别的点、区域或路线: %r" % (target,))


def target_points(target: Dict[str, Any]) -> List[Tuple[float, float]]:
    """需要做禁入区检查的点集合。"""
    if "point" in target:
        return [_as_point(target["point"], "target.point")]
    if "key_point" in target:
        return [_as_point(target["key_point"], "target.key_point")]
    if "route" in target:
        return _as_route(target["route"], "target.route")
    if "target_list" in target:
        return [_as_point(p, "target.target_list") for p in target["target_list"]]
    for key in ("area", "sector", "patrol_area", "defense_area"):
        if key in target:
            polygon = _as_polygon(target[key], "target." + key)
            return polygon + [polygon_centroid(polygon)]
    return []
