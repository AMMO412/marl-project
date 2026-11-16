# -*- coding: utf-8 -*-
"""Large, deterministic planning benchmarks built from delivered scenarios.

The six user-facing workbench scenarios stay unchanged. These bundles combine
the five task types on the existing 50-platform formation so optimization
changes can be measured under resource contention, deadlines, threats and
static chokepoints.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Optional

from .cost import OBJECTIVE_LABELS
from .message import parse_message
from .scheduler import Planner
from .urban_maps import apply_map_to_formation


SCENARIO_ROOT = Path(__file__).resolve().parent / "scenarios"
OBJECTIVES = ("timeliness", "exposure", "energy", "balanced")


@dataclass(frozen=True)
class BenchmarkBundle:
    """A reproducible 4.1 message + formation pair plus its test intent."""

    name: str
    label: str
    description: str
    message: Dict[str, Any]
    formation: Dict[str, Any]

    def write(self, directory: Path) -> Dict[str, str]:
        directory.mkdir(parents=True, exist_ok=True)
        message_path = directory / "message.json"
        formation_path = directory / "formation.json"
        message_path.write_text(
            json.dumps(self.message, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        formation_path.write_text(
            json.dumps(self.formation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "message": str(message_path),
            "formation": str(formation_path),
        }


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _base_task(name: str, task_id: str) -> Dict[str, Any]:
    source = _read_json(SCENARIO_ROOT / name)
    task = deepcopy(source["tasks"][0])
    task["task_id"] = task_id
    return task


def _complex_tasks() -> List[Dict[str, Any]]:
    """Place all five task types across a larger shared operating area."""
    containment = _base_task(
        "area_containment.message.json", "BENCH-SEC"
    )
    containment["priority"] = 5
    containment["target"]["defense_area"] = [
        [-145, -175],
        [-55, -175],
        [-55, -85],
        [-145, -85],
    ]
    containment["params"].update(
        gates=[
            {
                "gate_id": "NORTH",
                # The transformed downtown building footprint covers the
                # original point.  Keep the gate on the same defense edge but
                # shift it to the adjacent roadway so the task tests route
                # planning instead of being rejected as an impossible target.
                "point": [-97, -85],
                "width": 18,
                "direction": [0, -1],
            },
            {
                "gate_id": "EAST",
                "point": [-55, -130],
                "width": 18,
                "direction": [-1, 0],
            },
        ],
        intercept_post=[-100, -130],
        air_altitude_m=70,
        intruders=[
            {
                "target_id": "BENCH-SEC-X1",
                "start": [-100, -55],
                "goal": [-100, -100],
                "speed_mps": 2.5,
                "t_start_s": 45,
                "authorized": False,
                "compliance": False,
            },
            {
                "target_id": "BENCH-SEC-X2",
                "start": [-20, -130],
                "goal": [-65, -130],
                "speed_mps": 2.0,
                "t_start_s": 70,
                "authorized": False,
                "compliance": True,
            },
        ],
    )

    patrol = _base_task("area_patrol.message.json", "BENCH-PTL")
    patrol["priority"] = 3
    patrol["target"]["patrol_area"] = [
        [-220, -20],
        [-100, -20],
        [-100, 70],
        [-220, 70],
    ]
    patrol["params"].update(
        duration_s=180,
        start_units=["U1", "WING-41", "U4", "WING-42"],
        observation_target={
            "target_id": "BENCH-PTL-OBS",
            "start": [-160, -40],
            "goal": [-160, 90],
            "speed_mps": 3,
            "start_after_patrol_s": 2,
        },
    )

    recon = _base_task("crossroad_recon.message.json", "BENCH-RCN")
    recon["priority"] = 4
    recon["target"]["area"] = [
        [20, -160],
        [160, -160],
        [160, -40],
        [20, -40],
    ]
    recon["params"].update(
        # 180 s is the planner's booked work slot.  The absolute search
        # deadline remains far enough out for the dispatch delay caused by
        # resource contention, while keeping the showcase scenario inside
        # the software's 700-step execution budget.
        duration_s=180,
        search_deadline_s=620,
        search_starts={
            "U1": [35, -145],
            "U2": [145, -55],
            "U3": [35, -55],
            "WING-41": [145, -145],
        },
        tracking_target={
            "target_id": "BENCH-RCN-TRK",
            "start": [80, -100],
            "goal": [190, -100],
            "move_after_s": 6,
            "speed_mps": 3,
            "track_outside_s": 25,
        },
    )

    hold = _base_task("key_point_hold.message.json", "BENCH-HLD")
    hold["priority"] = 2
    hold["target"]["key_point"] = [140, 10]
    hold["params"].update(
        air_unit="U6",
        positions=[
            {
                "id": "P1",
                "point": [140, 42],
                "facing_deg": 180,
                "min_units": 1,
            },
            {
                "id": "P2",
                "point": [172, 10],
                "facing_deg": 270,
                "min_units": 1,
            },
            {
                "id": "P3",
                # Kept clear of the transformed residential-map building
                # footprint; the map remains a real hard obstacle.
                "point": [130, -22],
                "facing_deg": 0,
                "min_units": 1,
            },
            {
                "id": "P4",
                "point": [108, 10],
                "facing_deg": 90,
                "min_units": 1,
            },
        ],
    )

    assault = _base_task("asl_junction.message.json", "BENCH-ASL")
    assault["priority"] = 1
    assault["params"]["scout"]["unit"] = "U6"
    assault["params"]["assessor"]["unit"] = "WING-41"
    tasks = [containment, patrol, recon, hold, assault]
    for task in tasks:
        task["window"]["end_s"] = max(700, float(task["window"]["end_s"]))
    return tasks


def _message(name: str, tasks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": "0.3",
        "message_id": "MSG-" + name.upper(),
        "issued_at": "2026-11-11T00:00:00Z",
        "source": "UPPER",
        "tasks": deepcopy(list(tasks)),
    }


def _formation() -> Dict[str, Any]:
    return _read_json(SCENARIO_ROOT / "area_containment.formation.json")


def _add_constraints(
    formation: Dict[str, Any], constraints: Iterable[Dict[str, Any]]
) -> None:
    formation["constraints"].extend(deepcopy(list(constraints)))
    formation["meta"]["benchmark_constraint_count"] = len(
        formation["constraints"]
    )


def _set_windows(
    tasks: Iterable[Dict[str, Any]], windows: Dict[str, tuple]
) -> None:
    for task in tasks:
        start, end = windows[task["task_id"]]
        task["window"] = {"start_s": start, "end_s": end}


def build_suite() -> Dict[str, BenchmarkBundle]:
    """Return four deterministic stress scenarios without changing demos."""
    formation = _formation()
    tasks = _complex_tasks()
    mixed_formation, _ = apply_map_to_formation(formation, "residential")

    mixed = BenchmarkBundle(
        name="interop_bench_multitask",
        label="多任务资源竞争",
        description=(
            "五类任务同时分布在约 360×260 场景单位内；26 个槽位竞争同一套"
            "50 台设备，并使用住宅街区大型地图的建筑和路侧障碍，"
            "覆盖能力闸门、协同到达、时间窗和排程。"
        ),
        message=_message("interop_bench_multitask", tasks),
        formation=mixed_formation,
    )

    deadline_tasks = _complex_tasks()
    _set_windows(
        deadline_tasks,
        {
            "BENCH-SEC": (0, 420),
            # Keep this suite useful as a partial-assignment regression after
            # scenario unit hints became soft preferences.
            "BENCH-PTL": (0, 180),
            "BENCH-RCN": (0, 480),
            "BENCH-HLD": (0, 520),
            "BENCH-ASL": (0, 680),
        },
    )
    deadline_formation, _ = apply_map_to_formation(formation, "downtown")
    deadlines = BenchmarkBundle(
        name="interop_bench_deadlines",
        label="紧迫时间窗",
        description=(
            "保持资源竞争和多区域任务，压缩巡逻、封控、侦察时间窗，"
            "用于验证不可行时间的未分配原因和部分完成报告。地图采用"
            "密集城区，建筑和道路障碍参与地面路径规划。"
        ),
        message=_message("interop_bench_deadlines", deadline_tasks),
        formation=deadline_formation,
    )

    threat_formation, _ = apply_map_to_formation(formation, "mixed")
    _add_constraints(
        threat_formation,
        [
            {
                "constraint_id": "BENCH-THREAT-GROUND-N",
                "type": "threat",
                "applies_to": "ground",
                "intensity": 0.85,
                "area": {
                    "polygon": [
                        [-85, -70],
                        [-25, -70],
                        [-25, -25],
                        [-85, -25],
                    ]
                },
                "source": "complex_benchmark",
            },
            {
                "constraint_id": "BENCH-THREAT-AIR-E",
                "type": "threat",
                "applies_to": "air",
                "intensity": 0.75,
                "area": {
                    "polygon": [
                        [20, -70],
                        [80, -70],
                        [80, -20],
                        [20, -20],
                    ]
                },
                "source": "complex_benchmark",
            },
            {
                "constraint_id": "BENCH-THREAT-ALL-C",
                "type": "threat",
                "applies_to": "all",
                "intensity": 0.95,
                "area": {
                    "polygon": [
                        [-30, -145],
                        [25, -145],
                        [25, -95],
                        [-30, -95],
                    ]
                },
                "source": "complex_benchmark",
            },
        ],
    )
    threats = BenchmarkBundle(
        name="interop_bench_threats",
        label="空地威胁走廊",
        description=(
            "在对地、对空和空地均作用区域布置三段高风险走廊；"
            "时效目标允许穿区，暴露度目标应产生可测量的绕行增益。"
            "底图采用公园与斜街混合片区，地图障碍与威胁区同时生效。"
        ),
        message=_message("interop_bench_threats", tasks),
        formation=threat_formation,
    )

    urban_formation, _ = apply_map_to_formation(formation, "downtown")
    far_tasks = _complex_tasks()
    far_patrol = next(
        task for task in far_tasks if task["task_id"] == "BENCH-PTL"
    )
    far_patrol_area = [
        [290.0, 65.0],
        [410.0, 65.0],
        [410.0, 135.0],
        [290.0, 135.0],
    ]
    far_patrol["target"]["patrol_area"] = deepcopy(far_patrol_area)
    far_patrol["params"]["observation_target"].update(
        start=[350.0, 40.0],
        goal=[350.0, 160.0],
    )
    far_patrol["description"] = (
        "四台平台从出发阵地长距离机动至约360米外的东北远端巡逻区，"
        "在密集城区道路中完成两圈巡逻并跟踪移动目标。"
    )
    units = urban_formation["formation"]["units"]
    origin_x = sum(float(unit["position"]["x"]) for unit in units) / len(units)
    origin_y = sum(float(unit["position"]["y"]) for unit in units) / len(units)
    urban_formation["meta"]["remote_patrol_center"] = [350.0, 100.0]
    urban_formation["meta"]["remote_patrol_center_distance_m"] = round(
        math.hypot(350.0 - origin_x, 100.0 - origin_y), 2
    )
    _add_constraints(
        urban_formation,
        [
            {
                "constraint_id": "BENCH-GROUND-CHOKE-1",
                "type": "no_go",
                "applies_to": "ground",
                "height_m": 4.0,
                "area": {
                    "polygon": [
                        [-90, -75],
                        [-55, -75],
                        [-55, -70],
                        [-90, -70],
                    ]
                },
                "source": "complex_benchmark",
            },
            {
                "constraint_id": "BENCH-GROUND-CHOKE-2",
                "type": "no_go",
                "applies_to": "ground",
                "height_m": 4.0,
                "area": {
                    "polygon": [
                        [-35, -105],
                        [5, -105],
                        [5, -100],
                        [-35, -100],
                    ]
                },
                "source": "complex_benchmark",
            },
            {
                "constraint_id": "BENCH-AIR-NO-FLY",
                "type": "no_go",
                "applies_to": "air",
                "area": {
                    "polygon": [
                        [20, -125],
                        [35, -125],
                        [35, -70],
                        [20, -70],
                    ]
                },
                "source": "complex_benchmark",
            },
        ],
    )
    chokepoints = BenchmarkBundle(
        name="interop_bench_chokepoint",
        label="城市硬障碍与远距巡逻",
        description=(
            "入口通道新增两段地面硬障碍和一条显式对空禁飞带，"
            "并将巡逻区前推至距出发阵地约360米的东北远端；"
            "验证长航程分配、地面绕行、空中独立约束以及道路阻塞下的计划稳定性。"
            "底图采用密集城区，建筑、路侧障碍和追加封锁共同参与规划。"
        ),
        message=_message("interop_bench_chokepoint", far_tasks),
        formation=urban_formation,
    )

    return {
        bundle.name: bundle
        for bundle in (mixed, deadlines, threats, chokepoints)
    }


def _plan_summary(plan) -> Dict[str, Any]:
    metrics = plan.metrics
    objective = plan.objective_metrics or {}
    total_path = sum(float(item.path_length_m) for item in plan.assignments)
    return {
        "tasks_total": metrics.tasks_total,
        "tasks_fully_assigned": metrics.tasks_fully_assigned,
        "assigned_subtasks": metrics.assigned_subtasks,
        "unassigned_subtasks": metrics.unassigned_subtasks,
        "makespan_s": round(metrics.makespan_s, 3),
        "total_energy": round(float(objective.get("total_energy", 0.0)), 3),
        "total_exposure": round(
            float(objective.get("total_exposure", 0.0)), 3
        ),
        "detection_probability": round(
            float(objective.get("detection_probability", 0.0)), 6
        ),
        "total_path_length_m": round(total_path, 3),
        "conflicts_detected": metrics.conflicts_detected,
        "conflicts_resolved": metrics.conflicts_resolved,
        "plan_latency_ms": round(metrics.plan_latency_ms, 3),
        "unassigned": list(plan.unassigned),
    }


def run_suite(
    out_dir: Path,
    objectives: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Plan every scenario under every objective and persist reproducible data."""
    selected = tuple(objectives or OBJECTIVES)
    unknown = [item for item in selected if item not in OBJECTIVES]
    if unknown:
        raise ValueError("未知优化目标：" + ", ".join(unknown))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for bundle in build_suite().values():
        scenario_dir = out_dir / bundle.name
        paths = bundle.write(scenario_dir)
        scenario = parse_message(bundle.message, bundle.formation)
        objective_results = []
        for objective in selected:
            started = time.perf_counter()
            plan = Planner(scenario, objective=objective).plan()
            result = _plan_summary(plan)
            result.update(
                objective=objective,
                objective_label=OBJECTIVE_LABELS.get(objective, objective),
                wall_time_ms=round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
            )
            objective_results.append(result)
            (scenario_dir / ("plan-%s.json" % objective)).write_text(
                json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        results.append(
            {
                "name": bundle.name,
                "label": bundle.label,
                "description": bundle.description,
                "message": paths["message"],
                "formation": paths["formation"],
                "platforms": len(scenario.platforms),
                "tasks": len(scenario.tasks),
                "constraints": len(scenario.constraints),
                "results": objective_results,
            }
        )

    payload = {
        "schema_version": "0.1",
        "basis": "existing five task types and 50-platform formation",
        "objectives": list(selected),
        "scenario_count": len(results),
        "scenarios": results,
        "scope": (
            "planning-only benchmark; does not include UE5, ROS/Gazebo or "
            "external-platform execution"
        ),
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "results.md").write_text(
        _render_markdown(payload), encoding="utf-8"
    )
    return payload


def _render_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# 复杂规划基准结果",
        "",
        "由当前五类任务和 50 台设备编成生成，不改动六个交付演示场景。",
        "",
        "| 场景 | 目标 | 完成 | 槽位 | 未分配 | makespan/s | 能耗 | 暴露量 | 路径长度/m | 规划耗时/ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in payload["scenarios"]:
        for item in scenario["results"]:
            lines.append(
                "| {scenario_label} | {objective_label} | {tasks_fully_assigned}/{tasks_total} | "
                "{assigned_subtasks}/{assigned_subtasks_total} | {unassigned_subtasks} | "
                "{makespan_s:.1f} | {total_energy:.1f} | {total_exposure:.3f} | "
                "{total_path_length_m:.1f} | {plan_latency_ms:.1f} |".format(
                    scenario_label=scenario["label"],
                    assigned_subtasks_total=item["assigned_subtasks"]
                    + item["unassigned_subtasks"],
                    **item,
                )
            )
    lines.extend(
        [
            "",
            "结果仅代表规则规划层，不包含 UE5、ROS/Gazebo 或外部平台执行。",
            "",
        ]
    )
    return "\n".join(lines)
