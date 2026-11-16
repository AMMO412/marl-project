# -*- coding: utf-8 -*-
"""能力闸门：与平台当前位置无关的硬过滤。

通过/拒绝都带原因码，调用方把原因写进 unassigned / conflicts，不静默丢弃。
"""

from typing import Optional, Any, Dict, List, Tuple

from .geometry import point_in_polygon
from .message import target_points
from .model import Platform, Scenario, Subtask

EPS = 1e-6


def has_capabilities(platform: Platform, required: Dict[str, int]) -> bool:
    return all(int(platform.capabilities.get(code, 0)) >= int(level)
               for code, level in required.items())


SENSOR_FAMILY = {
    "eo": {"eo", "ir"},
    "ir": {"ir"},
    "sar": {"sar"},
    "any": {"eo", "ir", "sar"},
}

def sensor_ok(platform: Platform, requirement: Dict[str, Any]) -> Tuple[bool, str]:
    if not requirement:
        return True, ""
    spec = getattr(platform, "sensor_spec", {}) or {}
    actual = str(spec.get("type") or platform.sensor or "").lower()
    wanted = str(requirement.get("type") or "").lower()
    if wanted and wanted not in ("any", "*"):
        if actual not in SENSOR_FAMILY.get(wanted, {wanted}):
            return False, "传感器类别不满足（需 %s，实际 %s）" % (wanted, actual or "无")
    min_range = requirement.get("min_range_m")
    if min_range is not None:
        actual_range = float(spec.get("range_m") or 0.0)
        if actual_range + EPS < float(min_range):
            return False, "探测距离 %.0f m 低于要求 %.0f m" % (
                actual_range, float(min_range))
    max_res = requirement.get("max_resolution_m")
    if max_res is not None:
        actual_res = spec.get("resolution_m")
        if actual_res is None or float(actual_res) > float(max_res) + EPS:
            return False, "分辨率不满足（需不高于 %.2f m）" % float(max_res)
    min_fov = requirement.get("min_fov_deg")
    if min_fov is not None:
        actual_fov = float(spec.get("fov_deg") or 0.0)
        if actual_fov + EPS < float(min_fov):
            return False, "视场 %.0f° 小于要求 %.0f°" % (actual_fov, float(min_fov))
    return True, ""


def motion_ok(platform: Platform, requirement: Dict[str, Any]) -> Tuple[bool, str]:
    if not requirement:
        return True, ""
    spec = {"max_speed_mps": platform.speed_mps,
            **(getattr(platform, "motion_spec", {}) or {})}
    checks = (
        ("min_speed_mps", "max_speed_mps", "最大速度", "m/s"),
        ("min_accel_mps2", "max_accel_mps2", "最大加速度", "m/s²"),
        ("min_yaw_rate_rad_s", "max_yaw_rate_rad_s", "最大角速度", "rad/s"),
        ("min_climb_rate_mps", "max_climb_rate_mps", "最大爬升率", "m/s"),
        ("min_altitude_ceiling_m", "max_altitude_m", "最大高度", "m"),
    )
    for req_key, spec_key, label, unit in checks:
        if req_key not in requirement:
            continue
        actual = float(spec.get(spec_key) or 0.0)
        if actual + EPS < float(requirement[req_key]):
            return False, "%s %.2f %s 低于要求 %.2f %s" % (
                label, actual, unit, float(requirement[req_key]), unit)
    if "max_turn_radius_m" in requirement:
        actual = float(spec.get("min_turn_radius_m") or 0.0)
        if actual <= 0 or actual > float(requirement["max_turn_radius_m"]) + EPS:
            return False, "最小转弯半径 %.1f m 大于允许 %.1f m" % (
                actual, float(requirement["max_turn_radius_m"]))
    return True, ""


def platform_meets_requirements(platform: Platform, *, payload_kg: float = 0.0,
                                sensor: Optional[Dict[str, Any]] = None,
                                endurance_s: float = 0.0,
                                motion: Optional[Dict[str, Any]] = None,
                                duration_s: float = 0.0) -> bool:
    """槽位/任务性能闸门（不含状态、时间窗、禁入区等场景约束）。"""
    if platform.status != "READY":
        return False
    if payload_kg > 0 and float(getattr(platform, "payload_kg", 0.0)) + EPS < float(payload_kg):
        return False
    ok, _ = sensor_ok(platform, sensor or {})
    if not ok:
        return False
    if duration_s > float(platform.endurance_s) + EPS:
        return False
    if endurance_s > float(platform.endurance_s) + EPS:
        return False
    ok, _ = motion_ok(platform, motion or {})
    return ok


def target_inside_no_go(target: Dict[str, Any],
                        constraints: List[Dict[str, Any]]) -> bool:
    # Area-style missions are allowed to encompass buildings, parks and road
    # furniture; execution must route around those geometry features.  Their
    # concrete deployment/search waypoints are checked separately after the
    # template decomposes the task.  Treating every polygon vertex as a
    # mandatory platform position invalidates the whole mission merely because
    # an area boundary clips a building footprint.
    if not any(key in target for key in ("point", "route", "target_list")):
        return False
    points = target_points(target)
    if not points:
        return False
    for item in constraints:
        if item.get("type") != "no_go":
            continue
        area = item.get("area")
        polygon = area.get("polygon") if isinstance(area, dict) else area
        if not polygon:
            continue
        for point in points:
            if point_in_polygon(point, polygon):
                return True
    return False


def gate_platform(platform: Platform, subtask: Subtask,
                  scenario: Scenario) -> Tuple[bool, str, str]:
    """返回 (是否可行, 原因码, 说明)。"""
    if platform.status != "READY":
        return False, "STATUS", "平台状态为 %s" % platform.status
    if not has_capabilities(platform, subtask.required_capabilities):
        return False, "NO_CAPABILITY", "能力不满足 %s" % (
            subtask.required_capabilities,)
    if subtask.pinned_unit and platform.unit_id != subtask.pinned_unit:
        return False, "PINNED", "该席位固定给 %s" % subtask.pinned_unit
    if getattr(subtask, "pinned_class", "") and platform.platform_class != subtask.pinned_class:
        return False, "PINNED", "该席位要求 %s 类平台" % subtask.pinned_class
    if subtask.min_payload > 0 and float(platform.payload) + EPS < subtask.min_payload:
        return False, "PAYLOAD", "载荷 %.2f 低于席位下限 %.2f" % (
            float(platform.payload), subtask.min_payload)
    if subtask.payload_required_kg>0 and platform.payload_kg+EPS<subtask.payload_required_kg:
        return False,"PAYLOAD","明确载荷要求不满足"
    for check,requirement in [(sensor_ok,subtask.sensor_required),(motion_ok,subtask.motion_required)]:
        ok,reason=check(platform,requirement)
        if not ok: return False,"NO_CAPABILITY",reason
    if subtask.endurance_required_s>platform.endurance_s+EPS:
        return False,"ENDURANCE","明确续航要求不满足"
    window_length = subtask.window_end_s - subtask.window_start_s
    if subtask.duration_s > window_length + EPS:
        return False, "WINDOW", "作业时长 %.1fs 超过时间窗长度 %.1fs" % (
            subtask.duration_s, window_length)
    if subtask.duration_s > platform.endurance_s + EPS:
        return False, "ENDURANCE", "作业时长 %.1fs 超过平台续航 %.1fs" % (
            subtask.duration_s, platform.endurance_s)
    # T-ASL observation/assessment posts are derived geometry: the nominal
    # point may fall inside a building after a map or target placement change.
    # The assault behavior snaps those posts to the nearest navigable station,
    # and the router also projects an occupied goal cell to the nearest free
    # grid.  Rejecting the whole task here caused valid six-unit assaults to be
    # marked NO_CAPABILITY even with every needed platform idle.
    # Every T-ASL slot is a derived combat geometry (observation, assault ring
    # or assessment post); the objective point itself remains subject to the
    # parent-task NO_GO check in Planner.invalid_tasks.
    derived_asl_post = subtask.task_type == "T-ASL"
    if (target_inside_no_go(subtask.target, scenario.constraints)
            and not derived_asl_post):
        return False, "NO_GO", "任务目标位于禁入区"
    return True, "OK", ""


def reason_to_conflict_type(reason: str) -> str:
    return {
        "NO_CAPABILITY": "CAPABILITY",
        "STATUS": "CAPABILITY",
        "PAYLOAD": "CAPABILITY",
        "PINNED": "COORDINATION",
        "NO_GO": "CONSTRAINT",
        "NO_ROUTE": "ROUTE",
        "WINDOW": "WINDOW",
        "ENDURANCE": "ENDURANCE",
        "DEPENDENCY": "DEPENDENCY",
        "COORDINATION": "COORDINATION",
    }.get(reason, reason)
