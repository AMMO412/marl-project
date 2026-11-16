# -*- coding: utf-8 -*-
"""Reusable urban map bridge for benchmark planning and software display.

The generated ``neutral-urban-map/v1`` maps remain the geometry authority.
This module transforms them into the scenario coordinate frame once, emits
planner ``no_go`` constraints, and exposes the same transformed geometry to
the run viewer.  Keeping both paths on one transform prevents the common
failure where a building is visible on the backdrop but ignored by routing.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


MAP_ROOT = Path(__file__).resolve().parent / "urban_maps"
Point = Tuple[float, float]

# Uniform scale is deliberate.  The earlier stretched-map bug came from
# independently scaling X and Y, which turned rectangular footprints and
# square defense areas into misleading shapes.
_MAP_FRAMES = {
    "residential": {
        "scale": 0.7,
        "offset": (-280.0, -260.0),
    },
    "downtown": {
        "scale": 0.59,
        "offset": (-254.0, -225.0),
    },
    "mixed": {
        "scale": 0.43,
        "offset": (-244.0, -358.0),
    },
}

MAP_IDS = tuple(_MAP_FRAMES)


def load_map(map_id: str) -> Dict[str, Any]:
    """Load one packaged map and validate the fields used by the runtime."""
    if map_id not in _MAP_FRAMES:
        raise FileNotFoundError("未知城市地图：%s" % map_id)
    data = json.loads(
        (MAP_ROOT / map_id / "map.json").read_text(encoding="utf-8-sig")
    )
    if (
        data.get("schema") != "neutral-urban-map/v1"
        or data.get("units") != "m"
        or len(data.get("bounds") or []) != 4
    ):
        raise ValueError("地图格式不受支持：%s" % map_id)
    return data


def _frame(map_id: str) -> Dict[str, Any]:
    data = load_map(map_id)
    frame = dict(_MAP_FRAMES[map_id])
    scale = float(frame["scale"])
    offset_x, offset_y = map(float, frame["offset"])
    source = [float(value) for value in data["bounds"]]
    scene_bounds = [
        round(source[0] * scale + offset_x, 3),
        round(source[1] * scale + offset_y, 3),
        round(source[2] * scale + offset_x, 3),
        round(source[3] * scale + offset_y, 3),
    ]
    return dict(
        map_id=map_id,
        doc=data,
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
        source_bounds=source,
        scene_bounds=scene_bounds,
    )


def _point(point: Sequence[float], frame: Dict[str, Any]) -> List[float]:
    return [
        round(float(point[0]) * frame["scale"] + frame["offset_x"], 3),
        round(float(point[1]) * frame["scale"] + frame["offset_y"], 3),
    ]


def _box_polygon(
    box: Sequence[float], frame: Dict[str, Any]
) -> List[List[float]]:
    x, y, width, height = map(float, box)
    half_w, half_h = width / 2.0, height / 2.0
    return [
        _point((x - half_w, y - half_h), frame),
        _point((x + half_w, y - half_h), frame),
        _point((x + half_w, y + half_h), frame),
        _point((x - half_w, y + half_h), frame),
    ]


def _road_polygon(
    road: Dict[str, Any], nodes: Sequence[Sequence[float]],
    frame: Dict[str, Any],
) -> List[List[float]]:
    a = tuple(map(float, nodes[int(road["a"])]))
    b = tuple(map(float, nodes[int(road["b"])]))
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return []
    half = float(road["width_m"]) / 2.0
    nx, ny = -dy / length * half, dx / length * half
    return [
        _point((a[0] + nx, a[1] + ny), frame),
        _point((b[0] + nx, b[1] + ny), frame),
        _point((b[0] - nx, b[1] - ny), frame),
        _point((a[0] - nx, a[1] - ny), frame),
    ]


def _map_items(map_id: str) -> Dict[str, Any]:
    frame = _frame(map_id)
    doc = frame["doc"]
    nodes = doc.get("nodes") or []
    roads = []
    for item in doc.get("roads") or []:
        polygon = _road_polygon(item, nodes, frame)
        if polygon:
            roads.append(
                dict(
                    id=item.get("id"),
                    label=item.get("role") or item.get("id"),
                    polygon=polygon,
                    width_m=round(float(item.get("width_m", 0)) * frame["scale"], 3),
                )
            )
    buildings = [
        dict(
            id=item.get("id"),
            label=item.get("category") or item.get("id"),
            category=item.get("category") or "建筑",
            height_m=float(item.get("height_m", 0.0)),
            polygon=_box_polygon(item["box"], frame),
        )
        for item in doc.get("buildings") or []
    ]
    obstacles = [
        dict(
            id=item.get("id"),
            label=item.get("category") or item.get("id"),
            category=item.get("category") or "路侧障碍",
            height_m=float(item.get("height_m", 0.0)),
            polygon=_box_polygon(item["box"], frame),
        )
        for item in doc.get("obstacles") or []
    ]
    surfaces = [
        dict(
            id=item.get("id"),
            label="公园绿地",
            category="park",
            polygon=_box_polygon(item["box"], frame),
        )
        for item in doc.get("parks") or []
    ]
    landmarks = [
        dict(kind="tree", pose=[*_point(point, frame), 0.0])
        for point in doc.get("trees") or []
    ]
    return dict(
        id=map_id,
        label=doc.get("label") or map_id,
        bounds=frame["scene_bounds"],
        source_bounds=frame["source_bounds"],
        scale=frame["scale"],
        offset=[frame["offset_x"], frame["offset_y"]],
        roads=roads,
        obstacles=buildings + obstacles,
        surfaces=surfaces,
        landmarks=landmarks,
        buildings=buildings,
        roadside_obstacles=obstacles,
        trees=landmarks,
        note=(
            "本底图为真实规划约束：建筑和路侧障碍已写入 no_go，"
            "地面 A* 必须绕行；物高低于空中巡航高度时允许空中越顶。"
        ),
    )


def apply_map_to_formation(
    formation: Dict[str, Any], map_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a copied formation enriched with map constraints and metadata."""
    result = deepcopy(formation)
    geometry = _map_items(map_id)
    frame = _frame(map_id)
    constraints = result.setdefault("constraints", [])
    # A user can change the map in the configuration window. Remove only
    # constraints generated by an earlier urban-map choice; task-authored
    # no-go and threat constraints remain untouched.
    constraints[:] = [
        item for item in constraints
        if not (
            isinstance(item, dict)
            and str(item.get("source") or "").startswith("urban_map:")
        )
    ]
    existing = {
        str(item.get("constraint_id"))
        for item in constraints
        if isinstance(item, dict)
    }
    prefix = "URBAN-%s-" % map_id.upper()
    for index, item in enumerate(geometry["buildings"]):
        constraint_id = "%sBUILDING-%04d" % (prefix, index)
        if constraint_id in existing:
            continue
        constraints.append(
            {
                "constraint_id": constraint_id,
                "type": "no_go",
                "applies_to": "all",
                "height_m": item["height_m"],
                "area": {"polygon": item["polygon"]},
                "source": "urban_map:%s" % map_id,
            }
        )
    for index, item in enumerate(geometry["roadside_obstacles"]):
        constraint_id = "%sROADSIDE-%04d" % (prefix, index)
        if constraint_id in existing:
            continue
        constraints.append(
            {
                "constraint_id": constraint_id,
                "type": "no_go",
                "applies_to": "all",
                "height_m": item["height_m"],
                "area": {"polygon": item["polygon"]},
                "source": "urban_map:%s" % map_id,
            }
        )
    meta = result.setdefault("meta", {})
    map_path = MAP_ROOT / map_id / "map.json"
    source_bytes = map_path.read_bytes()
    meta.update(
        {
            "scene": "urban_%s" % map_id,
            "map_id": map_id,
            "map_label": frame["doc"].get("label") or map_id,
            "map_source": str(map_path.relative_to(MAP_ROOT.parent.parent)),
            "map_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "map_scale": frame["scale"],
            "map_offset": [frame["offset_x"], frame["offset_y"]],
            "map_source_bounds": frame["source_bounds"],
            "map_scene_bounds": frame["scene_bounds"],
            "map_constraint_count": (
                len(geometry["buildings"]) + len(geometry["roadside_obstacles"])
            ),
            "map_geometry_authority": "planning_and_display",
            # The maps add hundreds of static obstacles.  Rebuilding every
            # eight simulated seconds made the native window look frozen.
            # Static geometry does not need that frequency; task hand-offs and
            # explicit failures still trigger an immediate replan.
            "runtime_replan_period_s": 20,
            # No failures or hand-offs means the static city geometry and task
            # set have not changed.  The coordinator can reuse the first plan
            # and refresh each pending job's actual dispatch time.
            "reuse_stable_plan": True,
        }
    )
    return result, geometry


def scene_geometry(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return transformed geometry from a run's authoritative formation meta."""
    map_id = str(meta.get("map_id") or "")
    if map_id not in _MAP_FRAMES:
        return {}
    geometry = _map_items(map_id)
    if meta.get("map_scale") is not None:
        expected_scale = float(meta["map_scale"])
        expected_offset = list(meta.get("map_offset") or [])
        if (
            abs(expected_scale - float(geometry["scale"])) > 1e-9
            or len(expected_offset) != 2
            or any(
                abs(float(a) - float(b)) > 1e-9
                for a, b in zip(expected_offset, geometry["offset"])
            )
        ):
            raise ValueError("运行记录中的地图形变与地图资源不一致")
    geometry["sha256"] = meta.get("map_sha256")
    geometry["source"] = meta.get("map_source")
    geometry["map_id"] = map_id
    return geometry


def map_catalog() -> List[Dict[str, Any]]:
    result = []
    for map_id in _MAP_FRAMES:
        doc = load_map(map_id)
        result.append(
            {
                "id": map_id,
                "label": doc.get("label") or map_id,
                "bounds": doc["bounds"],
                "buildings": len(doc.get("buildings") or []),
                "roads": len(doc.get("roads") or []),
                "obstacles": len(doc.get("obstacles") or []),
            }
        )
    return result
