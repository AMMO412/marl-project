"""Structural validation of external plan documents, without executing commands."""
import math

from .message import _validate_target


def validate_plan_document(data):
    problems = []
    if not isinstance(data, dict):
        return ["计划根节点必须是对象"]

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def number(value):
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    def identity(value, path, seen=None):
        if not text(value):
            problems.append(path + " 必须是非空字符串")
        elif seen is not None:
            if value in seen:
                problems.append(path + " 重复: " + value)
            seen.add(value)

    def time_value(value, path, positive=False):
        if not number(value) or (value <= 0 if positive else value < 0):
            problems.append(path + (" 必须是正有限数" if positive else " 必须是非负有限数"))
            return False
        return True

    if data.get("schema_version") != "0.3":
        problems.append('schema_version 必须为 "0.3"；旧版本明确拒绝')
    identity(data.get("plan_id"), "plan_id")
    arrays = {}
    for key in ("assignments", "commands"):
        value = data.get(key)
        if not isinstance(value, list):
            problems.append(key + " 必须是数组")
            value = []
        arrays[key] = value

    seen_assign = set()
    for index, item in enumerate(arrays["assignments"]):
        path = "assignments[%d]" % index
        if not isinstance(item, dict):
            problems.append(path + " 必须是对象")
            continue
        identity(item.get("subtask_id"), path + ".subtask_id", seen_assign)
        for key in ("unit_id", "task_type"):
            identity(item.get(key), path + "." + key)
        start_ok = time_value(item.get("start_s"), path + ".start_s")
        end_ok = time_value(item.get("end_s"), path + ".end_s")
        if start_ok and end_ok and item["start_s"] > item["end_s"]:
            problems.append(path + " 开始晚于结束")
        if not isinstance(item.get("target"), dict) or not item["target"]:
            problems.append(path + ".target 必须是非空对象")
        else:
            try:
                _validate_target(item["target"], path)
            except (ValueError, OverflowError) as exc:
                problems.append(path + ".target 不合法: " + str(exc))

    seen_cmd = set()
    for index, item in enumerate(arrays["commands"]):
        path = "commands[%d]" % index
        if not isinstance(item, dict):
            problems.append(path + " 必须是对象")
            continue
        robot = item.get("robot_id")
        if type(robot) is not int or not 1 <= robot <= 50:
            problems.append(path + ".robot_id 必须是1至50的整数")
        if not text(item.get("topic")):
            problems.append(path + ".topic 必须是非空字符串")
        elif type(robot) is int and 1 <= robot <= 50:
            from .model import robot_topic
            if item["topic"] != robot_topic(robot):
                problems.append(path + ".topic 与robot_id不一致")
        time_value(item.get("duration_s"), path + ".duration_s", positive=True)
        # These are interop extensions, not required fields in the minimum 4.2 example.
        if "command_id" in item:
            identity(item["command_id"], path + ".command_id", seen_cmd)
        if "at_s" in item:
            time_value(item["at_s"], path + ".at_s")
        if "phase" in item and item["phase"] not in ("TRANSIT", "HOLD", "EGRESS", "STOP"):
            problems.append(path + ".phase 不合法")
        if "attempt" in item and (type(item["attempt"]) is not int or item["attempt"] < 1):
            problems.append(path + ".attempt 必须是正整数")
        twist = item.get("twist")
        values = []
        if not isinstance(twist, dict):
            problems.append(path + ".twist 必须是对象")
            continue
        for group in ("linear", "angular"):
            components = twist.get(group)
            if not isinstance(components, dict):
                problems.append(path + ".twist." + group + " 必须是对象")
                continue
            for axis in ("x", "y", "z"):
                value = components.get(axis)
                if not number(value):
                    problems.append(path + ".twist." + group + "." + axis + " 必须是有限数")
                else:
                    values.append(value)
        if item.get("phase") == "STOP" and len(values) == 6 and any(v != 0 for v in values):
            problems.append(path + " STOP的六个速度分量必须全为0")
    return problems
