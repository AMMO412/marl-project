# -*- coding: utf-8 -*-
"""生成 interop 的中性样例（4.1 消息 + 编成表）。

场景来自基座工程使用的 container_00 城市 SDF（与 M2 同源，SHA256 已核对
一致），障碍分两部分：
  * SDF 里 28 个显式盒体（花坛/围墙），由 ``interop.sdf_scene`` 解析；
  * 6 栋城市建筑，尺寸取自 M2 的 ``assets/city_buildings.csv``（include
    模型没有可提取尺寸，必须用外部尺寸表，不猜几何）。

任务只覆盖 T-RCN/T-SEC/T-PTL/T-HLD 四类中性任务，不含 T-ASL。
"""

import json
import os
from typing import Any, Dict, List, Tuple

from interop.sdf_scene import build_fleet, parse_sdf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDF_PATH = os.path.join(os.path.dirname(ROOT), "资料", "接口说明",
                        "container_00_combined_scene.sdf")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scenarios")

# M2 assets/city_buildings.csv 的世界坐标范围（x0, y0, x1, y1, 高度）
CITY_BUILDINGS = [
    ("HOUSE-01", -145.6, -191.8, -129.2, -178.9, 7.69),
    ("HOUSE-02", -60.6, -190.7, -47.9, -180.9, 7.23),
    ("HOUSE-03", -144.1, -109.4, -130.9, -100.7, 9.17),
    ("HOUSE-04", -60.9, -111.1, -44.4, -98.2, 7.69),
    ("OFFICE-01", -173.9, -153.9, -156.2, -136.2, 18.66),
    ("OFFICE-02", -33.9, -153.9, -16.2, -136.2, 18.66),
]

DEMO_THREAT = {
    "constraint_id": "THREAT-DEMO",
    "type": "threat",
    "applies_to": "ground",
    "intensity": 0.7,
    "area": {"polygon": [[25, -40], [65, -40], [65, -10], [25, -10]]},
    "note": "演示威胁区；真实威胁数据到位后替换",
}


def _rect_constraint(cid: str, x0: float, y0: float, x1: float, y1: float,
                     height: float) -> Dict[str, Any]:
    return {
        "constraint_id": cid,
        "type": "no_go",
        "applies_to": "ground",
        "area": {"polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]},
        "source": "city_buildings.csv",
        "height_m": height,
    }


def _message(message_id: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": "0.3",
        "message_id": message_id,
        "issued_at": "2026-10-30T08:00:00Z",
        "source": "UPPER",
        "tasks": tasks,
    }


def _task(task_id: str, task_type: str, priority: int, target: Dict[str, Any],
          window: Tuple[int, int], capabilities: Dict[str, int],
          min_units: int, max_units: int, params: Dict[str, Any],
          description: str = "") -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "priority": priority,
        "target": target,
        "window": {"start_s": window[0], "end_s": window[1]},
        "required_capabilities": capabilities,
        "min_units": min_units,
        "max_units": max_units,
        "params": params,
        "description": description,
    }


def build(scene, robot_numbers: List[int], plan_id: str) -> Dict[str, Any]:
    fleet = build_fleet(scene, robot_numbers, plan_id=plan_id,
                        grid_cell_m=2.0, grid_margin_m=1.5)
    constraints = list(fleet["constraints"])
    constraints.extend(_rect_constraint(*item) for item in CITY_BUILDINGS)
    constraints.append(dict(DEMO_THREAT))
    fleet["constraints"] = constraints
    fleet["meta"]["obstacle_sources"] = {
        "sdf_boxes": len(scene.obstacles),
        "city_buildings_csv": len(CITY_BUILDINGS),
        "threat_demo": 1,
    }
    return fleet


def scenarios(scene) -> Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]]:
    patrol_fleet = build(scene, [1, 2, 21, 22, 31, 41], "PLAN-INTEROP-PATROL")
    patrol_tasks = [
        _task("T1", "T-PTL", 1,
              {"route": [[-60, 30], [-20, 30], [-20, 70], [-60, 70]]},
              (0, 600), {"PTL": 2}, 1, 1,
              {"duration_s": 90}, "北侧草坪巡逻路线"),
        _task("T2", "T-PTL", 2,
              {"route": [[40, 20], [40, 60], [90, 60]]},
              (0, 600), {"PTL": 2}, 1, 1,
              {"duration_s": 90}, "东侧道路巡逻路线"),
        _task("T3", "T-HLD", 1,
              {"key_point": [112, -86]},
              (120, 900), {"HLD": 2}, 2, 2,
              {"hold_duration_s": 180,
               "defense_positions": [[112, -84], [112, -88]],
               "coordination": ["simultaneous_arrival"]},
              "围墙院内两个坚守阵位"),
    ]

    recon_fleet = build(scene, [1, 31, 41, 42], "PLAN-INTEROP-RECON")
    recon_tasks = [
        _task("T1", "T-RCN", 1,
              {"area": [[-20, 10], [40, 10], [40, 40], [-20, 40]]},
              (0, 300), {"RCN": 2}, 2, 3,
              {"duration_s": 40,
               "coordination": ["simultaneous_arrival"]},
              "草坪北侧区域协同侦察"),
        _task("T2", "T-RCN", 2,
              {"route": [[60, 20], [100, 20], [140, 20]]},
              (0, 400), {"RCN": 2}, 1, 2,
              {"duration_s": 45}, "东西向道路走廊侦察"),
        _task("T3", "T-HLD", 3,
              {"key_point": [70, 10]},
              (0, 500), {"HLD": 2}, 1, 1,
              {"hold_duration_s": 120}, "路口要点坚守"),
    ]

    mixed_fleet = build(scene, [1, 2, 21, 22, 31, 41, 42],
                        "PLAN-INTEROP-MIXED")
    mixed_tasks = [
        _task("T1", "T-SEC", 1,
              {"defense_area": [[95, -95], [130, -95], [130, -65], [95, -65]]},
              (0, 500), {"HLD": 2}, 2, 2,
              {"hold_duration_s": 120,
               "entry_points": [[100, -60], [125, -60]],
               "coordination": ["simultaneous_arrival"]},
              "围墙区域封控，两个入口点"),
        _task("T2", "T-RCN", 2,
              {"target_list": [[-100, -60], [-100, 20], [-40, 60]]},
              (0, 600), {"RCN": 2}, 1, 3,
              {"duration_s": 30}, "西侧三个检查点侦察"),
        _task("T3", "T-HLD", 2,
              {"key_point": [60, 60]},
              (60, 700), {"HLD": 2}, 1, 2,
              {"hold_duration_s": 150,
               "defense_positions": [[56, 60], [64, 60]],
               "coordination": ["simultaneous_arrival"]},
              "东北路口两个坚守阵位"),
        _task("T4", "T-PTL", 3,
              {"route": [[0, 60], [20, 80], [0, 100], [-20, 80]]},
              (0, 700), {"PTL": 2}, 1, 2,
              {"duration_s": 60}, "北侧环形巡逻"),
    ]

    gap_fleet = build(scene, [1, 2, 21, 22, 31, 41], "PLAN-INTEROP-GAP")
    gap_tasks = [
        _task("T1", "T-HLD", 1,
              {"key_point": [0, 40]},
              (0, 300), {"HLD": 3}, 2, 2,
              {"hold_duration_s": 120,
               "defense_positions": [[0, 36], [0, 44]],
               "coordination": ["simultaneous_arrival"]},
              "只有 TANK 满足 HLD3，恰好两台"),
        _task("T2", "T-RCN", 1,
              {"target_list": [[-40, 70]]},
              (0, 400), {"RCN": 3, "HLD": 2}, 1, 1,
              {"duration_s": 30},
              "没有平台同时满足 RCN3 与 HLD2，应报 NO_CAPABILITY"),
        _task("T3", "T-RCN", 2,
              {"target_list": [[-40, 70], [-30, 80], [-50, 90]]},
              (0, 70), {"RCN": 3}, 3, 3,
              {"duration_s": 30},
              "只有一台 PLANE 满足 RCN3，窗口只够一个槽位，应报 WINDOW"),
        _task("T4", "T-PTL", 2,
              {"point": [40, 40]},
              (0, 400), {"PTL": 2}, 1, 1,
              {"duration_s": 60}, "普通巡逻点"),
    ]

    # 区域封控（1028 §2.2）：3 千米级区域在 580×460 米演示场景里等比缩小为
    # 140×90 米；边界 2 台占位、1 台门哨、1 台机动拦截；控制等级"拦阻"、
    # 交战授权"按令"；两条未授权目标 + 一条已授权目标用于核验"拒止进入 /
    # 授权放行 / 警告后撤离"三类事件闭合。
    containment_fleet = build(scene, [1, 2, 3, 21, 22], "PLAN-INTEROP-SEC")
    # 集结待机区：离封控区约 160–200 m，运行链才能完整展示"集结 → 规划路径 →
    # 到达占位点 → 开始封控"。坐标取场景空地上的固定点，不随机。
    assembly_positions = {
        "U1": {"x": 0.0, "y": -45.0},
        "U2": {"x": 10.0, "y": -47.0},
        "U3": {"x": -10.0, "y": -47.0},
        "U4": {"x": 20.0, "y": -45.0},
        "U5": {"x": -20.0, "y": -45.0},
    }
    for unit in containment_fleet["formation"]["units"]:
        if unit["unit_id"] in assembly_positions:
            unit["position"] = dict(assembly_positions[unit["unit_id"]])
    containment_tasks = [
        _task("T1", "T-SEC", 1,
              {"defense_area": [[40, 20], [180, 20], [180, 110], [40, 110]]},
              (0, 600), {"HLD": 1}, 5, 5,
              {"hold_duration_s": 180,
               "control_objective": "deny_entry",
               "control_level": "block",
               "engagement_authority": "on_order",
               "roles": {"boundary": 2, "gate": 2, "intercept": 1,
                         "reserve": 0},
               "gates": [
                   {"gate_id": "G-A", "point": [80, 20], "width": 14,
                    "direction": [0, 1]},
                   {"gate_id": "G-B", "point": [180, 65], "width": 14,
                    "direction": [-1, 0]},
               ],
               "sensor_radius_m": 40,
               "standoff_m": 14,
               "intercept_post": [95, 45],
               "max_leak_rate": 0.0,
               "assembly_point": [0, -46],
               "assembly_radius_m": 30,
               "intruders": [
                   {"target_id": "IN-1", "start": [80, -30], "goal": [80, 60],
                    "speed_mps": 2.5, "t_start_s": 45, "authorized": False,
                    "compliance": False},
                   {"target_id": "IN-2", "start": [220, 65], "goal": [180, 65],
                    "speed_mps": 2.0, "t_start_s": 70, "authorized": False,
                    "compliance": True},
                   {"target_id": "AU-1", "start": [80, -30], "goal": [80, 70],
                    "speed_mps": 2.5, "t_start_s": 100, "authorized": True,
                    "compliance": False},
               ]},
              "140×90 米区域封控：2 段占位 + 门哨 + 机动拦截"),
    ]

    return {
        "patrol_checkpoint": (
            _message("MSG-INTEROP-PATROL-001", patrol_tasks), patrol_fleet),
        "area_recon": (
            _message("MSG-INTEROP-RECON-001", recon_tasks), recon_fleet),
        "mixed_inspection": (
            _message("MSG-INTEROP-MIXED-001", mixed_tasks), mixed_fleet),
        "capability_gap": (
            _message("MSG-INTEROP-GAP-001", gap_tasks), gap_fleet),
        "area_containment": (
            _message("MSG-INTEROP-SEC-001", containment_tasks),
            containment_fleet),
    }


def _check_targets(message: Dict[str, Any], fleet: Dict[str, Any]) -> List[str]:
    """生成后自检：任务目标点不能落在 no_go 里，否则样例本身不合法。"""
    from interop.geometry import point_in_polygon
    from interop.message import target_points

    polygons = []
    for item in fleet.get("constraints", []):
        if item.get("type") != "no_go":
            continue
        area = item.get("area")
        polygon = area.get("polygon") if isinstance(area, dict) else area
        if polygon:
            polygons.append((item.get("constraint_id", "?"),
                             [(float(p[0]), float(p[1])) for p in polygon]))
    problems = []
    for task in message["tasks"]:
        points = list(target_points(task["target"]))
        for key in ("defense_positions", "entry_points"):
            for point in (task.get("params", {}).get(key) or []):
                points.append((float(point[0]), float(point[1])))
        # 区域封控的通道口与目标时间线同样不能落在禁入区里
        for gate in (task.get("params", {}).get("gates") or []):
            if isinstance(gate, dict) and gate.get("point"):
                points.append((float(gate["point"][0]),
                               float(gate["point"][1])))
        for target in (task.get("params", {}).get("intruders") or []):
            if not isinstance(target, dict):
                continue
            for field in ("start", "goal"):
                if target.get(field):
                    points.append((float(target[field][0]),
                                   float(target[field][1])))
        for point in points:
            for name, polygon in polygons:
                if point_in_polygon(point, polygon):
                    problems.append("%s 的目标/阵位点 %s 落在禁入区 %s"
                                    % (task["task_id"], point, name))
    return problems


def main() -> int:
    scene = parse_sdf(SDF_PATH)
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for name, (message, fleet) in scenarios(scene).items():
        problems = _check_targets(message, fleet)
        if problems:
            raise SystemExit("样例 %s 不合法的目标点：\n  %s"
                             % (name, "\n  ".join(problems)))
        message_path = os.path.join(OUT_DIR, "%s.message.json" % name)
        fleet_path = os.path.join(OUT_DIR, "%s.formation.json" % name)
        with open(message_path, "w", encoding="utf-8") as fh:
            json.dump(message, fh, ensure_ascii=False, indent=2)
        with open(fleet_path, "w", encoding="utf-8") as fh:
            json.dump(fleet, fh, ensure_ascii=False, indent=2)
        written.append((name, message_path, fleet_path))
        print("%-20s platforms=%d tasks=%d constraints=%d"
              % (name, len(fleet["formation"]["units"]),
                 len(message["tasks"]), len(fleet["constraints"])))
    print("written:", len(written), "scenario pairs ->", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
