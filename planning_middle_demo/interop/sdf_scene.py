# -*- coding: utf-8 -*-
"""SDF 场景 → 障碍约束 + 平台出生点（吸收自 M2，独立实现）。

只接纳 SDF 里显式的 ``<box>`` 碰撞体：地面/道路/广场按名字排除，
beacon 作为地标而不是障碍，robot_001..050 作为平台出生点。
mesh / include 没有可提取尺寸时登记为 unresolved，不猜几何。

解析结果用于生成 4.1 编成表；也可以单独当工具跑：

    python -m interop.sdf_scene --sdf ... --robots 1,21,31,41 --out ...
"""

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

FREE_PREFIXES = ("env_road_", "env_city_road_")
FREE_NAMES = ("env_lawn_ground", "env_city_square")
BEACON_PREFIX = "env_beacon"
ROBOT_PREFIX = "robot_"

CLASS_RANGES = (("UGV", 1, 20), ("TANK", 21, 30),
                ("PLANE", 31, 40), ("WING", 41, 50))
CLASS_PARAMS = {
    "UGV": dict(platform_type="ifv",
                capabilities={"RCN": 2, "STK": 1, "PTL": 2, "HLD": 2},
                speed_mps=8.0, endurance_s=21600.0),
    "TANK": dict(platform_type="tank",
                 capabilities={"RCN": 1, "STK": 3, "PTL": 1, "HLD": 3},
                 speed_mps=8.0, endurance_s=28800.0),
    "PLANE": dict(platform_type="uav_recon",
                  capabilities={"RCN": 3, "STK": 0, "PTL": 2, "HLD": 0},
                  speed_mps=30.0, endurance_s=36000.0),
    "WING": dict(platform_type="uav_strike",
                 capabilities={"RCN": 2, "STK": 2, "PTL": 2, "HLD": 0},
                 speed_mps=25.0, endurance_s=21600.0),
}


@dataclass
class RobotSpawn:
    robot_no: int
    name: str
    kind: str
    position: Point
    yaw: float = 0.0
    z: float = 0.0


@dataclass
class SdfScene:
    source: str
    world_name: str
    bounds: Tuple[float, float, float, float]
    obstacles: List[Dict[str, Any]] = field(default_factory=list)
    landmarks: List[Dict[str, Any]] = field(default_factory=list)
    robots: List[RobotSpawn] = field(default_factory=list)
    includes: List[Dict[str, Any]] = field(default_factory=list)


def _text(node, path: str, default: str = "") -> str:
    if node is None:
        return default
    found = node.find(path)
    if found is None or not found.text:
        return default
    return found.text.strip()


def _pose(text: Optional[str]):
    values = [float(v) for v in (text or "0 0 0 0 0 0").split()]
    while len(values) < 6:
        values.append(0.0)
    return tuple(values[:6])


def _combine(parent, child):
    return (parent[0] + child[0], parent[1] + child[1], parent[2] + child[2],
            parent[3] + child[3], parent[4] + child[4], parent[5] + child[5])


def _box_polygon(pose, size) -> List[Point]:
    x, y = pose[0], pose[1]
    sx, sy = float(size[0]), float(size[1])
    yaw = pose[5]
    c, s = math.cos(yaw), math.sin(yaw)
    corners = [(-sx / 2, -sy / 2), (sx / 2, -sy / 2),
               (sx / 2, sy / 2), (-sx / 2, sy / 2)]
    return [(round(x + c * px - s * py, 4), round(y + s * px + c * py, 4))
            for px, py in corners]


def kind_of(robot_no: int) -> str:
    for kind, low, high in CLASS_RANGES:
        if low <= robot_no <= high:
            return kind
    raise ValueError("robot 编号超出 1-50: %d" % robot_no)


def parse_sdf(path: str) -> SdfScene:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    root = ET.parse(path).getroot()
    world = root.find("world")
    if world is None:
        raise ValueError("SDF 里没有 <world>")
    scene = SdfScene(source=path, world_name=world.get("name", ""),
                     bounds=(0.0, 0.0, 0.0, 0.0))

    for model in world.findall("model"):
        name = model.get("name", "")
        pose = _pose(_text(model, "pose", "0 0 0 0 0 0"))
        if name.startswith(ROBOT_PREFIX):
            try:
                number = int(name[len(ROBOT_PREFIX):])
            except ValueError:
                continue
            scene.robots.append(RobotSpawn(
                robot_no=number, name=name, kind=kind_of(number),
                position=(pose[0], pose[1]), yaw=pose[5], z=pose[2]))
            continue
        if name in FREE_NAMES or name.startswith(FREE_PREFIXES):
            if name == "env_lawn_ground":
                size = _text(model, ".//collision/geometry/box/size")
                if size:
                    sx, sy = [float(v) for v in size.split()[:2]]
                    scene.bounds = (pose[0] - sx / 2, pose[1] - sy / 2,
                                    pose[0] + sx / 2, pose[1] + sy / 2)
            continue
        if name.startswith(BEACON_PREFIX):
            scene.landmarks.append(dict(name=name,
                                        position=[pose[0], pose[1]],
                                        kind="beacon"))
            continue
        for link in model.findall("link"):
            link_pose = _pose(_text(link, "pose", "0 0 0 0 0 0"))
            for collision in link.findall("collision"):
                col_pose = _pose(_text(collision, "pose", "0 0 0 0 0 0"))
                size_text = _text(collision, "geometry/box/size")
                if not size_text:
                    continue
                size = [float(v) for v in size_text.split()[:3]]
                full = _combine(_combine(pose, link_pose), col_pose)
                scene.obstacles.append(dict(
                    constraint_id="SDF-%s-%s" % (
                        name, collision.get("name", "collision")),
                    type="no_go",
                    applies_to="ground",
                    area={"polygon": _box_polygon(full, size)},
                    source=name,
                    height_m=size[2] if len(size) > 2 else 0.0,
                ))

    for include in world.findall("include"):
        scene.includes.append(dict(uri=_text(include, "uri"),
                                   name=_text(include, "name"),
                                   pose=_text(include, "pose")))

    if scene.bounds == (0.0, 0.0, 0.0, 0.0):
        xs = [v[0] for o in scene.obstacles for v in o["area"]["polygon"]]
        ys = [v[1] for o in scene.obstacles for v in o["area"]["polygon"]]
        xs.extend(r.position[0] for r in scene.robots)
        ys.extend(r.position[1] for r in scene.robots)
        scene.bounds = (min(xs or [0.0]), min(ys or [0.0]),
                        max(xs or [0.0]), max(ys or [0.0]))
    return scene


def build_fleet(scene: SdfScene, robot_numbers: Sequence[int],
                plan_id: str = "PLAN-INTEROP-001",
                grid_cell_m: float = 5.0,
                grid_margin_m: float = 1.0) -> Dict[str, Any]:
    by_no = {r.robot_no: r for r in scene.robots}
    missing = [no for no in robot_numbers if no not in by_no]
    if missing:
        raise ValueError("SDF 中缺少机器人: %s" % missing)
    units = []
    for index, number in enumerate(robot_numbers, start=1):
        spawn = by_no[number]
        params = CLASS_PARAMS[spawn.kind]
        units.append(dict(
            unit_id="U%d" % index,
            platform_type=params["platform_type"],
            platform_class=spawn.kind,
            robot_id=spawn.robot_no,
            capabilities=dict(params["capabilities"]),
            position={"x": spawn.position[0], "y": spawn.position[1]},
            altitude_m=spawn.z,
            vertical_speed_mps=(3.0 if spawn.kind in ("PLANE", "WING") else 0.0),
            heading_rad=spawn.yaw,
            speed_mps=params["speed_mps"],
            endurance_s=params["endurance_s"],
            status="READY",
        ))
    return dict(
        formation=dict(formation_id="INTEROP-%s" % scene.world_name, units=units),
        constraints=[dict(item) for item in scene.obstacles],
        meta=dict(cell_size_m=1, grid_cell_m=grid_cell_m,
                  grid_margin_m=grid_margin_m, plan_id=plan_id,
                  scene=scene.world_name,
                  scene_bounds=list(scene.bounds),
                  source_sdf=os.path.basename(scene.source)),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="解析 SDF，生成 4.1 编成表骨架")
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--robots", default="1,21,31,41")
    parser.add_argument("--out", default="examples")
    args = parser.parse_args(argv)
    scene = parse_sdf(args.sdf)
    numbers = [int(x) for x in args.robots.split(",") if x.strip()]
    fleet = build_fleet(scene, numbers)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "formation.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fleet, fh, ensure_ascii=False, indent=2)
    print("world=%s bounds=%s boxes=%d beacons=%d robots=%d includes=%d"
          % (scene.world_name, scene.bounds, len(scene.obstacles),
             len(scene.landmarks), len(scene.robots), len(scene.includes)))
    print("formation:", os.path.abspath(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
