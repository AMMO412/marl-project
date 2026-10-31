# -*- coding: utf-8 -*-
"""interop 的统一数据模型（4.1 输入 → 内部对象 → 4.2 输出）。

分层与 M2 一致：Scenario → Task → Subtask → Assignment → VelocityCommand；
另外补了冲突、未分配与指标对象。所有时间字段单位为秒，坐标为场景单位
（由编成表 meta.cell_size_m 定义，默认 1 单位 = 1 米）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]

TASK_TYPES = ("T-RCN", "T-SEC", "T-PTL", "T-HLD")
TASK_TYPE_LABELS = {
    "T-RCN": "协同侦察",
    "T-SEC": "区域封控",
    "T-PTL": "巡逻警戒",
    "T-HLD": "要点坚守",
}


def robot_topic(robot_id: int) -> str:
    """机器人编号 → 2026-10-30 后的移动话题：/container_00/robot_XXX。

    统一从基座 fleet（可用环境变量覆盖）取名；导入失败时按同一规则兜底，
    保证独立运行 interop 也能生成正确话题。
    """
    try:
        import fleet
        return fleet.topic_of(int(robot_id))
    except ImportError:
        import os
        container = os.environ.get("FLEET_CONTAINER_NAME", "container_00")
        suffix = os.environ.get("FLEET_CMD_SUFFIX", "")
        return "/%s/robot_%03d%s" % (container, int(robot_id), suffix)


@dataclass
class Platform:
    unit_id: str
    robot_id: int
    platform_class: str
    position: Point
    speed_mps: float
    endurance_s: float
    capabilities: Dict[str, int] = field(default_factory=dict)
    status: str = "READY"
    platform_type: str = ""
    heading_rad: float = 0.0
    altitude_m: float = 0.0
    vertical_speed_mps: float = 0.0
    # 基座画像（用于与 planner_v2 对比；缺省按平台类补默认值）
    payload: float = 0.0
    sensor: str = ""
    battery: float = 100.0
    work_rate: float = 1.0
    move_cost: float = 0.0
    work_cost: float = 0.0
    # 运行适配器用：该平台已被在途作业占用到的时刻（秒）；静态规划恒为 0。
    busy_until_s: float = 0.0

    @property
    def topic(self) -> str:
        return robot_topic(self.robot_id)

    @property
    def is_air(self) -> bool:
        return self.platform_class in ("PLANE", "WING")


@dataclass
class Task:
    task_id: str
    task_type: str
    priority: int
    target: Dict[str, Any]
    window_start_s: float
    window_end_s: float
    required_capabilities: Dict[str, int] = field(default_factory=dict)
    min_units: int = 1
    max_units: Optional[int] = None
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    allow_split: bool = True
    description: str = ""


@dataclass
class Subtask:
    subtask_id: str
    parent_task_id: str
    index: int
    task_type: str
    target: Dict[str, Any]
    required_capabilities: Dict[str, int]
    duration_s: float
    window_start_s: float
    window_end_s: float
    priority: int
    depends_on: List[str] = field(default_factory=list)
    coordination: List[str] = field(default_factory=list)
    role: str = ""
    status: str = "UNASSIGNED"


@dataclass
class Assignment:
    unit_id: str
    subtask_id: str
    parent_task_id: str
    task_type: str
    target: Dict[str, Any]
    start_s: float
    end_s: float
    window_start_s: float
    window_end_s: float
    depends_on: List[str]
    coordination: List[str]
    travel_s: float = 0.0
    status: str = "ASSIGNED"
    robot_id: Optional[int] = None
    topic: str = ""
    path: List[Point] = field(default_factory=list)
    path_length_m: float = 0.0
    heading_start: float = 0.0
    heading_end: float = 0.0
    energy: float = 0.0
    risk: float = 0.0
    altitude_m: float = 0.0
    role: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            # 4.2 计划层字段
            "unit_id": self.unit_id,
            "subtask_id": self.subtask_id,
            "task_type": self.task_type,
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "target": self.target,
            # 扩展字段（可追溯到父任务与机器人）
            "parent_task_id": self.parent_task_id,
            "robot_id": self.robot_id,
            "topic": self.topic,
            "window": {"start_s": self.window_start_s,
                       "end_s": self.window_end_s},
            "depends_on": list(self.depends_on),
            "coordination": list(self.coordination),
            "travel_s": round(self.travel_s, 3),
            "path_length_m": round(self.path_length_m, 3),
            "path": [[round(x, 3), round(y, 3)] for x, y in self.path],
            "heading_start": round(self.heading_start, 4),
            "heading_end": round(self.heading_end, 4),
            "energy": round(self.energy, 3),
            "risk": round(self.risk, 3),
            "status": self.status,
            "role": self.role,
            "altitude_m": round(self.altitude_m, 3),
        }


@dataclass
class VelocityCommand:
    robot_id: int
    topic: str
    linear_x: float
    duration_s: float
    at_s: float = 0.0
    linear_y: float = 0.0
    linear_z: float = 0.0
    angular_x: float = 0.0
    angular_y: float = 0.0
    angular_z: float = 0.0
    unit_id: str = ""
    subtask_id: str = ""
    phase: str = "TRANSIT"
    command_id: str = ""
    attempt: int = 1
    action: str = "start"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "topic": self.topic,
            "twist": {
                "linear": {"x": round(self.linear_x, 3),
                           "y": round(self.linear_y, 3),
                           "z": round(self.linear_z, 3)},
                "angular": {"x": round(self.angular_x, 3),
                            "y": round(self.angular_y, 3),
                            "z": round(self.angular_z, 3)},
            },
            "duration_s": round(self.duration_s, 3),
            "unit_id": self.unit_id,
            "subtask_id": self.subtask_id,
            "phase": self.phase,
            "at_s": round(self.at_s, 3),
            "command_id": self.command_id,
            "attempt": self.attempt,
            "action": self.action,
        }


@dataclass
class Conflict:
    conflict_id: str
    type: str
    subtask_ids: List[str]
    detected_at_s: float
    action: str
    resolved: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "type": self.type,
            "subtask_ids": list(self.subtask_ids),
            "detected_at_s": round(self.detected_at_s, 3),
            "action": self.action,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass
class Metrics:
    makespan_s: float = 0.0
    assigned_subtasks: int = 0
    unassigned_subtasks: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    resolution_rate: float = 1.0
    plan_latency_ms: float = 0.0
    tasks_total: int = 0
    tasks_fully_assigned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "makespan_s": round(self.makespan_s, 3),
            "assigned_subtasks": self.assigned_subtasks,
            "unassigned_subtasks": self.unassigned_subtasks,
            "conflicts_detected": self.conflicts_detected,
            "conflicts_resolved": self.conflicts_resolved,
            "resolution_rate": round(self.resolution_rate, 4),
            "plan_latency_ms": round(self.plan_latency_ms, 3),
            "tasks_total": self.tasks_total,
            "tasks_fully_assigned": self.tasks_fully_assigned,
        }


@dataclass
class Plan:
    plan_id: str
    plan_version: int
    generated_at: str
    assignments: List[Assignment]
    commands: List[VelocityCommand]
    conflicts: List[Conflict]
    unassigned: List[Dict[str, Any]]
    metrics: Metrics
    explain: List[str]
    objective: str = "timeliness"
    weights: Dict[str, float] = field(default_factory=dict)
    objective_metrics: Dict[str, Any] = field(default_factory=dict)
    source_message: Optional[Dict[str, Any]] = None
    result_status: str = ""
    evidence_source: str = ""
    backend: str = "unified"

    def to_dict(self) -> Dict[str, Any]:
        data = {
            # 1028 4.2 必需字段在前
            "plan_id": self.plan_id,
            "assignments": [a.to_dict() for a in self.assignments],
            "commands": [c.to_dict() for c in self.commands],
        }
        if self.source_message:
            data["source_message"] = dict(self.source_message)
        data.update({
            "schema_version": "0.3",
            "plan_version": self.plan_version,
            "generated_at": self.generated_at,
            "backend": self.backend,
            "objective": self.objective,
            "objective_weights": dict(self.weights),
            "objective_metrics": dict(self.objective_metrics),
            "result_status": self.result_status,
            "evidence_source": self.evidence_source,
            "execution_scope": "TRANSIT_AND_HOLD",
            "execution_note": (
                "commands 覆盖到达任务点的路径跟随与任务时段的零速度保持；"
                "地面平台原地转向后直行，固定翼按最小转弯半径转向；"
                "任务段动作、20 Hz 续发、超时停车由导航/控制模块负责。"
            ),
            "unassigned": list(self.unassigned),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "metrics": self.metrics.to_dict(),
            "explain": list(self.explain),
        })
        return data


@dataclass
class Scenario:
    formation_id: str
    platforms: List[Platform]
    tasks: List[Task]
    constraints: List[Dict[str, Any]] = field(default_factory=list)
    groups: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    message: Optional[Dict[str, Any]] = None
    cell_size_m: float = 1.0
    plan_id: str = "PLAN-INTEROP-001"
    schema_version: str = "0.3"

    @property
    def platform_map(self) -> Dict[str, Platform]:
        return {p.unit_id: p for p in self.platforms}

    @property
    def task_map(self) -> Dict[str, Task]:
        return {t.task_id: t for t in self.tasks}
