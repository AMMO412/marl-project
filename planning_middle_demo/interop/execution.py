# -*- coding: utf-8 -*-
"""把计划层转换为 1028 4.2 执行层速度指令。

TRANSIT：按分配路径生成，地面平台先原地转向再直行，固定翼边前进边转向；
HOLD：到达后全零 Twist 覆盖任务时段；
STOP：每台机器人最后一次作业结束后 1 s 全零，显式停车。

任务段的真实动作（巡逻绕环、侦察覆盖、封控拦截、坚守换班）不在本层
建模，由基座 behaviors.py / 导航控制模块按计划层的 task_type、target、
start_s、end_s 接管。
"""

from typing import Dict, List, Tuple

from .motion import coalesce, simulate_path
from .model import Assignment, Scenario, VelocityCommand

MAX_COMMAND_DURATION_S = 120.0
EPS = 1e-6


def _slices(total_s: float) -> List[Tuple[float, float]]:
    total = max(0.0, float(total_s))
    result = []
    offset = 0.0
    while total - offset > EPS:
        duration = min(MAX_COMMAND_DURATION_S, total - offset)
        result.append((offset, duration))
        offset += duration
    return result


def _command(platform, assignment, phase, at_s, duration_s, vx, wz=0.0):
    return VelocityCommand(
        robot_id=platform.robot_id,
        topic=platform.topic,
        linear_x=vx,
        angular_z=wz,
        duration_s=duration_s,
        unit_id=assignment.unit_id,
        subtask_id=assignment.subtask_id,
        phase=phase,
        at_s=at_s,
    )


def build_commands(assignments: List[Assignment], scenario: Scenario) -> List[VelocityCommand]:
    platforms = scenario.platform_map
    commands = []
    for assignment in assignments:
        platform = platforms.get(assignment.unit_id)
        if platform is None:
            continue
        path_m = list(assignment.path)
        motion = simulate_path(path_m, platform, assignment.heading_start,
                               max(platform.speed_mps, 0.1))
        if motion.samples:
            departure_s = max(0.0, assignment.start_s - assignment.travel_s)
            offset = 0.0
            for sample in coalesce(motion.samples):
                command = _command(platform, assignment, "TRANSIT",
                                   departure_s + offset, sample.duration_s,
                                   sample.vx, sample.wz)
                commands.append(command)
                offset += sample.duration_s

        for offset, duration in _slices(assignment.end_s - assignment.start_s):
            commands.append(_command(platform, assignment, "HOLD",
                                     assignment.start_s + offset, duration,
                                     0.0, 0.0))

    # 每台机器人最后一次作业结束后的显式停车
    last_end = {}  # type: Dict[int, Tuple[float, Assignment]]
    for assignment in assignments:
        platform = platforms.get(assignment.unit_id)
        if platform is None:
            continue
        key = platform.robot_id
        if key not in last_end or assignment.end_s > last_end[key][0]:
            last_end[key] = (assignment.end_s, assignment)
    for robot_id, (end_s, assignment) in last_end.items():
        platform = platforms[assignment.unit_id]
        commands.append(_command(platform, assignment, "STOP", end_s, 1.0,
                                 0.0, 0.0))

    commands.sort(key=lambda c: (c.robot_id, c.at_s, c.phase, c.subtask_id))
    for index, command in enumerate(commands, start=1):
        command.command_id = "CMD-%05d" % index
    return commands
