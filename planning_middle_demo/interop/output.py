# -*- coding: utf-8 -*-
"""4.2 输出组织：plan.json（完整）+ CSV（字段子集）+ report.md + manifest。

沿用 M2 的分工：JSON 保存全量结构，CSV 明确是字段子集，Markdown 供人工
审阅；同一轮产物由 manifest.json 关联输入哈希、后端、目标与文件清单。
"""

import csv
import hashlib
import json
import os
import platform as _platform
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import __version__
from .model import Plan, Scenario


def _target_text(target: Any) -> str:
    if isinstance(target, dict):
        return json.dumps(target, ensure_ascii=False, sort_keys=True)
    if isinstance(target, (list, tuple)):
        return " | ".join("(%.2f,%.2f)" % (float(p[0]), float(p[1]))
                          for p in target)
    return str(target)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(value: float) -> str:
    if value is None:
        return "-"
    return ("%.3f" % float(value)).rstrip("0").rstrip(".")


def ros2_pub_line(command) -> str:
    """一条 4.2 速度记录 → 可直接粘贴的 ros2 topic pub 命令。

    ROS 2 的 Twist 字段是小写 ``z``（用户给的示例里大写 Z 只是笔误，ROS 2
    会拒绝）；话题按 2026-10-30 后的 /container_00/robot_XXX 输出。
    """
    return ('ros2 topic pub -r 20 %s geometry_msgs/msg/Twist '
            '"{linear: {x: %.3f, y: %.3f, z: %.3f}, '
            'angular: {x: %.3f, y: %.3f, z: %.3f}}"'
            % (command.topic, command.linear_x, command.linear_y,
               command.linear_z, command.angular_x, command.angular_y,
               command.angular_z))


def build_report(plan: Plan, scenario: Scenario) -> str:
    m = plan.metrics
    lines = []
    lines.append("# 4.2 计划报告（interop 统一层）")
    lines.append("")
    lines.append("- 计划编号：`%s`；计划版本：%d；后端：`%s`"
                 % (plan.plan_id, plan.plan_version, plan.backend))
    lines.append("- 生成时间：%s" % plan.generated_at)
    lines.append("- 目标：`%s`；权重 time/risk/energy = %.2f / %.2f / %.2f"
                 % (plan.objective, plan.weights.get("time", 1.0),
                    plan.weights.get("risk", 0.0),
                    plan.weights.get("energy", 0.0)))
    lines.append("- 结果口径：`%s` / `%s`（计划层默认口径，不是外部执行确认）"
                 % (plan.result_status or "-", plan.evidence_source or "-"))
    if plan.source_message:
        lines.append("- 来源消息：`%s`，下发时刻 %s，来源 %s，schema %s"
                     % (plan.source_message.get("message_id"),
                        plan.source_message.get("issued_at"),
                        plan.source_message.get("source"),
                        plan.source_message.get("schema_version")))
    lines.append("")
    lines.append("## 1 指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | ---: |")
    lines.append("| 父任务数 | %d |" % m.tasks_total)
    lines.append("| 全部槽位落实的父任务 | %d |" % m.tasks_fully_assigned)
    lines.append("| 子任务槽位 | %d |" % (m.assigned_subtasks + m.unassigned_subtasks))
    lines.append("| 已分配 | %d |" % m.assigned_subtasks)
    lines.append("| 未分配 | %d |" % m.unassigned_subtasks)
    lines.append("| makespan | %s s |" % _fmt(m.makespan_s))
    lines.append("| 冲突 | %d（已解决 %d） |"
                 % (m.conflicts_detected, m.conflicts_resolved))
    lines.append("| 规划耗时 | %s ms |" % _fmt(m.plan_latency_ms))
    if plan.objective_metrics:
        om = plan.objective_metrics
        lines.append("| 总能耗（模型值） | %s |" % _fmt(om.get("total_energy", 0)))
        lines.append("| 总风险（模型值） | %s |" % _fmt(om.get("total_risk", 0)))
    lines.append("")

    lines.append("## 2 分配")
    lines.append("")
    if plan.assignments:
        lines.append("| 槽位 | 父任务 | 平台 | 机器人 | 开始–结束 / s | 移动 / s "
                     "| 路径 / m | 风险 | 能耗 |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for a in plan.assignments:
            lines.append("| %s | %s | %s | %s | %.1f–%.1f | %.1f | %.1f | %.3f | %.2f |"
                         % (a.subtask_id, a.parent_task_id, a.unit_id,
                            a.robot_id if a.robot_id is not None else "-",
                            a.start_s, a.end_s, a.travel_s, a.path_length_m,
                            a.risk, a.energy))
    else:
        lines.append("（无已分配子任务）")
    lines.append("")

    lines.append("## 3 执行层")
    lines.append("")
    phases = {}
    for c in plan.commands:
        phases[c.phase] = phases.get(c.phase, 0) + 1
    lines.append("- 指令 %d 条；阶段分布：%s"
                 % (len(plan.commands),
                    "，".join("%s %d" % (k, v) for k, v in sorted(phases.items()))
                    or "无"))
    if plan.commands:
        end_s = max(c.at_s + c.duration_s for c in plan.commands)
        robots = sorted({c.robot_id for c in plan.commands})
        lines.append("- 覆盖 %d 台机器人（%s）；最后一条指令结束 %.1f s"
                     % (len(robots), ", ".join(str(r) for r in robots), end_s))
        lines.append("- 单条指令最长 120 s，TRANSIT/HOLD/STOP 分阶段；"
                     "末段 STOP 为显式全零，运行时不依赖超时停车。")
        lines.append("- `ros2_commands.txt` 给出可按 at_s 执行的 `ros2 topic pub "
                     "-r 20` 命令（话题 `/container_00/robot_XXX`，字段小写 z）。")
    lines.append("")

    lines.append("## 4 未分配与冲突")
    lines.append("")
    if plan.unassigned:
        lines.append("| 槽位 | 父任务 | 原因 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for item in plan.unassigned:
            lines.append("| %s | %s | %s | %s |"
                         % (item.get("subtask_id"), item.get("parent_task_id"),
                            item.get("reason"), item.get("detail")))
    else:
        lines.append("- 未分配：无")
    lines.append("")
    if plan.conflicts:
        lines.append("| 冲突 | 类型 | 相关槽位 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for c in plan.conflicts:
            lines.append("| %s | %s | %s | %s |"
                         % (c.conflict_id, c.type, ", ".join(c.subtask_ids),
                            c.reason))
    else:
        lines.append("- 冲突：无")
    lines.append("")

    lines.append("## 5 解释")
    lines.append("")
    for line in plan.explain:
        lines.append("- %s" % line)
    lines.append("")

    lines.append("## 6 口径与边界")
    lines.append("")
    lines.append("- 时间单位秒；坐标与路径单位为米（编成表 `meta.cell_size_m` 已折算）。")
    lines.append("- 工期、能耗、风险系数是演示值；能耗/风险只在同一后端内比较，"
                 "不能拿不同后端的绝对值排名。")
    lines.append("- 本层只做计划；commands 是计划指令，不表示已发布、已执行或已确认。")
    lines.append("- 任务段动作不在本层实现，由基座行为层/导航控制模块接管。")
    lines.append("- 不含 T-ASL、攻击阵位、fires、毁伤/效果判定。")
    lines.append("")
    return "\n".join(lines)


def write_outputs(plan: Plan, scenario: Scenario, out_dir: str,
                  input_paths: Optional[Dict[str, str]] = None,
                  extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    plan_path = os.path.join(out_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan.to_dict(), fh, ensure_ascii=False, indent=2)

    platforms = scenario.platform_map
    assignments_path = os.path.join(out_dir, "assignments.csv")
    with open(assignments_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "unit_id", "robot_id", "topic", "platform_class",
            "subtask_id", "parent_task_id", "task_type",
            "target", "start_s", "end_s", "window_start_s", "window_end_s",
            "depends_on", "coordination", "status",
            "path_length_m", "waypoint_count", "risk", "energy", "path",
        ])
        for a in plan.assignments:
            platform = platforms.get(a.unit_id)
            writer.writerow([
                a.unit_id, a.robot_id, a.topic,
                platform.platform_class if platform else "",
                a.subtask_id, a.parent_task_id, a.task_type,
                _target_text(a.target), "%.3f" % a.start_s, "%.3f" % a.end_s,
                "%.3f" % a.window_start_s, "%.3f" % a.window_end_s,
                ";".join(a.depends_on), ";".join(a.coordination), a.status,
                "%.3f" % a.path_length_m, str(len(a.path)),
                "%.3f" % a.risk, "%.3f" % a.energy, _target_text(a.path),
            ])

    commands_path = os.path.join(out_dir, "commands.csv")
    with open(commands_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "command_id", "attempt", "action", "robot_id", "topic",
            "unit_id", "subtask_id", "phase", "at_s", "duration_s",
            "linear_x", "linear_y", "linear_z",
            "angular_x", "angular_y", "angular_z",
        ])
        for c in plan.commands:
            writer.writerow([
                c.command_id, c.attempt, c.action, c.robot_id, c.topic,
                c.unit_id, c.subtask_id, c.phase, "%.3f" % c.at_s,
                "%.3f" % c.duration_s, "%.3f" % c.linear_x,
                "%.3f" % c.linear_y, "%.3f" % c.linear_z,
                "%.3f" % c.angular_x, "%.3f" % c.angular_y,
                "%.3f" % c.angular_z,
            ])

    report_path = os.path.join(out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(build_report(plan, scenario))

    ros2_path = os.path.join(out_dir, "ros2_commands.txt")
    with open(ros2_path, "w", encoding="utf-8") as fh:
        fh.write("# 4.2 执行层 → ROS 2 发布命令（话题 /container_00/robot_XXX）\n")
        fh.write("# 每条命令按 at_s 排程、持续 duration_s；-r 20 约 20 Hz。\n")
        fh.write("# Ctrl+C 后仍需发一次全零 Twist；本文件只给命令，不自动发布。\n")
        for command in plan.commands:
            fh.write("# %s  at=%.3f s  duration=%.3f s  phase=%s\n"
                     % (command.command_id, command.at_s, command.duration_s,
                        command.phase))
            fh.write(ros2_pub_line(command) + "\n")

    manifest = {
        "generator": "planning_middle_demo/interop",
        "interop_version": __version__,
        "backend": plan.backend,
        "objective": plan.objective,
        "weights": dict(plan.weights),
        "plan_id": plan.plan_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "python": sys.version.split()[0],
        "platform": _platform.platform(),
        "scenario": {
            "formation_id": scenario.formation_id,
            "cell_size_m": scenario.cell_size_m,
            "platforms": len(scenario.platforms),
            "tasks": len(scenario.tasks),
            "message": dict(scenario.message or {}),
        },
        "inputs": {},
        "outputs": {},
    }
    for key, path in (input_paths or {}).items():
        if path and os.path.exists(path):
            manifest["inputs"][key] = {"path": os.path.abspath(path),
                                       "sha256": sha256_file(path)}
    for key, path in (("plan_json", plan_path),
                      ("assignments_csv", assignments_path),
                      ("commands_csv", commands_path),
                      ("report_md", report_path),
                      ("ros2_commands", ros2_path)):
        manifest["outputs"][key] = {"path": os.path.abspath(path),
                                    "sha256": sha256_file(path),
                                    "bytes": os.path.getsize(path)}
    if extra:
        manifest.update(extra)
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return {
        "plan_json": plan_path,
        "assignments_csv": assignments_path,
        "commands_csv": commands_path,
        "report_md": report_path,
        "ros2_commands": ros2_path,
        "manifest_json": manifest_path,
    }
