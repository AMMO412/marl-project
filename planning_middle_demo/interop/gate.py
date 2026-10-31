# -*- coding: utf-8 -*-
"""能力闸门：与平台当前位置无关的硬过滤。

通过/拒绝都带原因码，调用方把原因写进 unassigned / conflicts，不静默丢弃。
"""

from typing import Any, Dict, List, Tuple

from .geometry import point_in_polygon
from .message import target_points
from .model import Platform, Scenario, Subtask

EPS = 1e-6


def has_capabilities(platform: Platform, required: Dict[str, int]) -> bool:
    return all(int(platform.capabilities.get(code, 0)) >= int(level)
               for code, level in required.items())


def target_inside_no_go(target: Dict[str, Any],
                        constraints: List[Dict[str, Any]]) -> bool:
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
    if subtask.min_payload > 0 and float(platform.payload) + EPS < subtask.min_payload:
        return False, "PAYLOAD", "载荷 %.2f 低于席位下限 %.2f" % (
            float(platform.payload), subtask.min_payload)
    window_length = subtask.window_end_s - subtask.window_start_s
    if subtask.duration_s > window_length + EPS:
        return False, "WINDOW", "作业时长 %.1fs 超过时间窗长度 %.1fs" % (
            subtask.duration_s, window_length)
    if subtask.duration_s > platform.endurance_s + EPS:
        return False, "ENDURANCE", "作业时长 %.1fs 超过平台续航 %.1fs" % (
            subtask.duration_s, platform.endurance_s)
    if target_inside_no_go(subtask.target, scenario.constraints):
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
